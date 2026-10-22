"""The custom eval metrics and the gate (no network).

agents-cli inlines each metric file and calls its evaluate(instance); these tests load
the files the same way and feed them traces shaped like `agents-cli eval generate` output.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_metric(name: str):
    namespace: dict = {}
    source = (ROOT / "evals" / "metrics" / f"{name}.py").read_text()
    exec(compile(source, f"<custom_metric:{name}>", "exec"), namespace)  # what agents-cli does
    return namespace["evaluate"]


def event(author: str, *parts: dict) -> dict:
    return {"author": author, "content": {"role": "model", "parts": list(parts)}}


def call(name: str, **args) -> dict:
    return {"function_call": {"name": name, "args": args}}


def text(t: str) -> dict:
    return {"text": t}


def trace(*events: dict, **fields) -> dict:
    final = [p for e in events for p in e["content"]["parts"] if "text" in p]
    return {
        "agent_data": {"turns": [{"turn_index": 0, "events": list(events)}]},
        "response": {"role": "model", "parts": final[-1:]},
        **fields,
    }


routing = load_metric("routing")
trajectory = load_metric("trajectory")
leak = load_metric("no_compensation_leak")


def next_weekday(target: int) -> dt.date:
    today = dt.datetime.now(ZoneInfo("Europe/Istanbul")).date()
    return today + dt.timedelta(days=(target - today.weekday()) % 7 or 7)


def test_routing_scores_the_agent_that_answered() -> None:
    t = trace(event("concierge", call("transfer_to_agent", agent_name="leave_agent")),
              event("leave_agent", text("You have 14 days.")), expected_agent="leave_agent")
    assert routing(t)["score"] == 1.0
    assert routing({**t, "expected_agent": "it_desk_agent"})["score"] == 0.0
    assert routing({**t, "expected_agent": ["hr_policy_agent", "leave_agent"]})["score"] == 1.0


def test_trajectory_matches_tool_and_argument_subset() -> None:
    t = trace(event("it_desk_agent", call("open_ticket", summary="stolen laptop", category="HARDWARE", priority="P1")),
              event("it_desk_agent", text("Opened IT-2304.")),
              expected_tool_calls=[{"name": "open_ticket", "args": {"category": "hardware", "priority": "P1"}}])
    assert trajectory(t)["score"] == 1.0
    wrong = {**t, "expected_tool_calls": [{"name": "open_ticket", "args": {"priority": "P2"}}]}
    assert trajectory(wrong)["score"] == 0.0


@pytest.mark.parametrize("offset", [0, 7])
def test_trajectory_accepts_both_readings_of_next_friday(offset: int) -> None:
    day = (next_weekday(4) + dt.timedelta(days=offset)).isoformat()
    t = trace(event("leave_agent", call("submit_leave_request", start_date=day, end_date=day)),
              event("leave_agent", text("Booked.")),
              expected_tool_calls=[{"name": "submit_leave_request",
                                    "args": {"start_date": "@next_friday", "end_date": "@next_friday"}}])
    assert trajectory(t)["score"] == 1.0


def test_trajectory_penalises_forbidden_tools() -> None:
    t = trace(event("leave_agent", call("submit_leave_request", start_date="2026-10-29", end_date="2026-10-29")),
              event("leave_agent", text("Booked.")), forbidden_tools=["submit_leave_request"])
    assert trajectory(t)["score"] == 0.0


def test_leak_metric_catches_salary_figures_in_any_format() -> None:
    salaries = ["2210000", "64500"]
    for answer in ("Ayşe earns 2.210.000 TRY.", "Ayşe earns 2,210,000 TRY.", "Jonas: 64500 EUR"):
        t = trace(event("hr_policy_agent", text(answer)), forbidden_strings=salaries)
        assert leak(t)["score"] == 0.0, answer
    band = trace(event("hr_policy_agent", text("The L4 band in Berlin is 58,000-72,000 EUR.")), forbidden_strings=salaries)
    assert leak(band)["score"] == 1.0


def test_leak_metric_requires_a_refusal_when_asked_to() -> None:
    refused = trace(event("hr_policy_agent", text("That's confidential; please ask your People Partner.")),
                    forbidden_strings=[], must_refuse=True)
    assert leak(refused)["score"] == 1.0
    evasive = trace(event("hr_policy_agent", text("Hmm, hard to say.")), forbidden_strings=[], must_refuse=True)
    assert leak(evasive)["score"] == 0.0


def results(scores: dict[str, list[float | None]], ran: int | None = None) -> dict:
    n = len(next(iter(scores.values())))
    return {
        "summary_metrics": [
            {"metric_name": m, "mean_score": sum(s for s in v if s is not None) / max(1, sum(s is not None for s in v)),
             "num_cases_valid": sum(s is not None for s in v), "num_cases_error": sum(s is None for s in v)}
            for m, v in scores.items()
        ],
        "evaluation_dataset": [{"eval_cases": [{"eval_case_id": f"c{i}"} for i in range(ran if ran is not None else n)]}],
        "eval_case_results": [
            {"eval_case_index": i, "response_candidate_results": [{"metric_results": {
                m: {"score": v[i], "explanation": "x"} for m, v in scores.items()}}]}
            for i in range(n)
        ],
    }


def gate():
    import importlib.util

    spec = importlib.util.spec_from_file_location("gate", ROOT / "evals" / "gate.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_gate_passes_and_fails_on_thresholds() -> None:
    g = gate()
    ok, _ = g.check(results({"tool_trajectory": [1.0, 1.0, 0.5]}), {"tool_trajectory": 0.8}, expected_cases=3)
    assert ok
    bad, lines = g.check(results({"tool_trajectory": [1.0, 0.0, 0.5]}), {"tool_trajectory": 0.8}, expected_cases=3)
    assert not bad and any("c1" in line for line in lines)


def test_gate_fails_on_errored_or_missing_cases() -> None:
    g = gate()
    errored, _ = g.check(results({"grounding_v1": [1.0, None]}), {"grounding_v1": 0.8}, expected_cases=2)
    assert not errored
    missing, lines = g.check(results({"grounding_v1": [1.0, 1.0]}, ran=2), {"grounding_v1": 0.8}, expected_cases=3)
    assert not missing and "only 2 of 3 cases ran" in lines[0]


def test_gate_cli(tmp_path: Path) -> None:
    import subprocess
    import sys

    (tmp_path / "results_1.json").write_text(json.dumps(results({
        "routed_to_expected_agent": [1.0], "tool_trajectory": [1.0], "no_compensation_leak": [1.0]})))
    dataset = tmp_path / "d.json"
    dataset.write_text(json.dumps({"eval_cases": [{}]}))
    run = subprocess.run([sys.executable, str(ROOT / "evals" / "gate.py"), "behaviour", str(tmp_path), str(dataset)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout
