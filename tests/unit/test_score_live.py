"""scripts/score_live.py: production sessions become eval cases in agents-cli's format."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "score_live", ROOT / "scripts" / "score_live.py"
)
assert _spec and _spec.loader
score_live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(score_live)


def event(author: str, invocation: str, *parts: dict[str, Any]) -> dict[str, Any]:
    """A session event as the Agent Runtime Sessions REST API returns it."""
    role = "user" if author == "user" else "model"
    return {
        "author": author,
        "invocationId": invocation,
        "timestamp": "2026-10-22T08:57:54Z",
        "content": {"role": role, "parts": list(parts)},
    }


# One session: a small-talk turn the concierge answers, then a turn handed to it_desk_agent.
EVENTS = [
    event("user", "e-1", {"text": "Hi!"}),
    event("concierge", "e-1", {"text": "thinking...", "thought": True}),
    event(
        "concierge",
        "e-1",
        {"text": "Hello! How can I help?", "thoughtSignature": "AY8"},
    ),
    event("user", "e-2", {"text": "List my IT tickets."}),
    event(
        "concierge",
        "e-2",
        {
            "functionCall": {
                "name": "transfer_to_agent",
                "args": {"agent_name": "it_desk_agent"},
            }
        },
    ),
    event(
        "concierge",
        "e-2",
        {
            "functionResponse": {
                "name": "transfer_to_agent",
                "response": {"result": None},
            }
        },
    ),
    event(
        "it_desk_agent",
        "e-2",
        {"functionCall": {"name": "list_my_tickets", "args": {}}},
    ),
    event(
        "it_desk_agent",
        "e-2",
        {
            "functionResponse": {
                "name": "list_my_tickets",
                "response": {"tickets": ["IT-2201"]},
            }
        },
    ),
    event("it_desk_agent", "e-2", {"text": "You have one ticket: IT-2201."}),
    {
        "author": "it_desk_agent",
        "invocationId": "e-2",
        "actions": {"stateDelta": {"x": 1}},
    },
]


def test_turns_group_events_by_user_message() -> None:
    turns = score_live.turns(EVENTS)
    assert [t["user"]["parts"][0]["text"] for t in turns] == [
        "Hi!",
        "List my IT tickets.",
    ]
    first, second = turns
    # Thought parts are dropped and thought signatures stripped, as eval generate does.
    assert [e["content"]["parts"] for e in first["events"]] == [
        [{"text": "Hello! How can I help?"}]
    ]
    assert [e["author"] for e in second["events"]] == ["concierge"] * 2 + [
        "it_desk_agent"
    ] * 3


def test_eval_case_matches_the_agents_cli_trace_format() -> None:
    turn = score_live.turns(EVENTS)[1]
    agents = {
        "concierge": {"agent_id": "concierge"},
        "it_desk_agent": {"agent_id": "it_desk_agent"},
    }
    case = score_live.eval_case("123", "cli-user", 1, turn, agents, ["1620000"])
    assert case["eval_case_id"] == "123#1"
    assert case["prompt"] == {
        "role": "user",
        "parts": [{"text": "List my IT tickets."}],
    }
    assert case["responses"][0]["response"]["parts"] == [
        {"text": "You have one ticket: IT-2201."}
    ]
    assert case["agent_data"]["agents"] is agents
    assert case["agent_data"]["turns"][0]["turn_id"] == "turn_0"
    assert len(case["agent_data"]["turns"][0]["events"]) == 5
    assert case["forbidden_strings"] == ["1620000"]
    assert case["session_user"] == "cli-user"


@pytest.mark.usefixtures("mcp_servers")
async def test_agents_map_lists_every_agent_with_real_instructions_and_tools() -> None:
    agents = await score_live.agents_map()
    assert set(agents) == {
        "concierge",
        "hr_policy_agent",
        "leave_agent",
        "it_desk_agent",
    }
    assert agents["concierge"]["sub_agents"] == [
        "hr_policy_agent",
        "leave_agent",
        "it_desk_agent",
    ]
    # ADK's /app-info leaves "<InstructionProvider: ...>" here; the judges need the text.
    assert "Today is" in agents["leave_agent"]["instruction"]
    names = {
        d["name"]
        for tool in agents["leave_agent"]["tools"]
        for d in tool.get("function_declarations", [])
    }
    assert {"get_leave_balance", "submit_leave_request", "handbook_search"} <= names


def test_summary_finds_the_lowest_scoring_turn() -> None:
    def case(case_id: str, prompt: str) -> dict[str, Any]:
        return {
            "eval_case_id": case_id,
            "session_user": "cli-user",
            "prompt": {"parts": [{"text": prompt}]},
            "responses": [{"response": {"parts": [{"text": "answer"}]}}],
        }

    results = {
        "evaluation_dataset": [{"eval_cases": [case("s1#0", "a"), case("s2#0", "b")]}],
        "summary_metrics": [
            {"metric_name": "resolved", "mean_score": 0.75, "num_cases_valid": 2},
            {"metric_name": "tool_use", "mean_score": None, "num_cases_error": 2},
        ],
        "eval_case_results": [
            {
                "eval_case_index": 0,
                "response_candidate_results": [
                    {"metric_results": {"resolved": {"score": 1.0}}}
                ],
            },
            {
                "eval_case_index": 1,
                "response_candidate_results": [
                    {
                        "metric_results": {
                            "resolved": {"score": 0.5, "explanation": "partly"}
                        }
                    }
                ],
            },
        ],
    }
    summary = score_live.summarize(results)
    assert summary["metrics"]["resolved"] == {"mean": 0.75, "scored": 2, "errors": 0}
    assert summary["metrics"]["tool_use"]["errors"] == 2
    assert summary["lowest"]["case"] == "s2#0"
    assert summary["lowest"]["prompt"] == "b"
    assert summary["lowest"]["metric"] == "resolved"


def test_live_config_judges_see_the_whole_turn() -> None:
    config = yaml.safe_load((ROOT / "evals" / "eval_config.live.yaml").read_text())
    defined = {m["name"]: m for m in config["custom_metrics"]}
    assert set(config["metrics_to_run"]) == set(defined)
    judges = [m for m in defined.values() if "prompt_template" in m]
    assert {m["name"] for m in judges} == {"grounded", "resolved", "tool_use"}
    for judge in judges:
        # The judge model needs a full resource name; scripts fill in the project.
        assert judge["judge_model"].startswith("projects/PROJECT_ID/locations/global/")
        for placeholder in ("{agent_data}", "{prompt}", "{response}"):
            assert placeholder in judge["prompt_template"], (judge["name"], placeholder)
        assert '"score"' in judge["prompt_template"]
    leak = defined["no_compensation_leak"]["custom_function_file"]
    assert (ROOT / "evals" / leak).is_file()


def test_recorded_live_scores_match_the_report_format() -> None:
    recorded = json.loads(
        (ROOT / "evals" / "recorded" / "live-scores.json").read_text()
    )
    assert recorded["turns"] > 0
    assert {"grounded", "resolved", "tool_use", "no_compensation_leak"} <= set(
        recorded["metrics"]
    )
    assert {"case", "prompt", "answer", "metric", "score", "explanation"} <= set(
        recorded["lowest"]
    )
