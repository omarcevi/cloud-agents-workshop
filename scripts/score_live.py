"""Score the deployed agent's recent conversations (lab step 6).

The managed Online Monitor skips every turn in which the concierge hands over to a
sub-agent: it expects one system instruction per trace. The evaluation service itself
grades multi-agent turns fine when they arrive in the format `agents-cli eval generate`
writes, with every agent listed in agent_data.agents. So this script:

  build    reads recent conversations from Agent Runtime Sessions and writes one eval case
           per turn to artifacts/live/traces.json, in that format;
  report   summarises the results of `agents-cli eval grade` over those cases and points
           at the lowest-scoring turn, which `session_to_eval_case.py` turns into a test.

scripts/score_live.sh runs build, grade and report in one go.

Usage: uv run python scripts/score_live.py build [--hours 3] [--max-turns 20]
       uv run python scripts/score_live.py report [RESULTS_DIR]
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "artifacts" / "live"
TRACES = OUT_DIR / "traces.json"
API = "https://{location}-aiplatform.googleapis.com/v1beta1"


def engine_name() -> str:
    meta = json.loads((ROOT / "deployment_metadata.json").read_text())
    name = meta.get("remote_agent_runtime_id")
    if not name:
        sys.exit(
            "No deployed agent in deployment_metadata.json. Run `agents-cli deploy` first."
        )
    return str(name)


def forbidden_salary_strings() -> list[str]:
    """Every individual salary in the seed data (as evals/build_datasets.py computes it)."""
    data = json.loads((ROOT / "data" / "seed" / "compensation.json").read_text())
    return sorted(str(v) for v in data["salaries"].values())


def _session() -> Any:
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    http = AuthorizedSession(credentials)
    # Bill the API call to the lab project: Cloud Shell's credentials carry no quota project.
    http.headers["x-goog-user-project"] = engine_name().split("/")[1]
    return http


def recent_sessions(http: Any, engine: str, since: datetime) -> list[dict[str, Any]]:
    """Sessions updated after `since`, newest first."""
    base = API.format(location=engine.split("/")[3])
    sessions: list[dict[str, Any]] = []
    token = ""
    while True:
        params = {"pageSize": 100, "orderBy": "update_time desc", "pageToken": token}
        response = http.get(f"{base}/{engine}/sessions", params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        for session in data.get("sessions", []):
            if (
                datetime.fromisoformat(session["updateTime"].replace("Z", "+00:00"))
                < since
            ):
                return sessions
            sessions.append(session)
        token = data.get("nextPageToken", "")
        if not token:
            return sessions


def session_events(http: Any, session_name: str) -> list[dict[str, Any]]:
    base = API.format(location=session_name.split("/")[3])
    events: list[dict[str, Any]] = []
    token = ""
    while True:
        params = {"pageSize": 100, "pageToken": token}
        response = http.get(f"{base}/{session_name}/events", params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        events.extend(data.get("sessionEvents", []))
        token = data.get("nextPageToken", "")
        if not token:
            return events


def _clean(content: dict[str, Any]) -> dict[str, Any]:
    """Drop thought text and thought signatures, as `agents-cli eval generate` does."""
    parts = [
        {
            k: v
            for k, v in part.items()
            if k not in ("thoughtSignature", "thought_signature")
        }
        for part in content.get("parts") or []
        if not part.get("thought")
    ]
    return {**content, "parts": parts}


def turns(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group session events into turns: one user message and the agents' events after it."""
    result: list[dict[str, Any]] = []
    for event in events:
        content = event.get("content")
        if not content:
            continue
        if event.get("author") == "user":
            if any(p.get("text") for p in content.get("parts") or []):
                result.append(
                    {
                        "invocation_id": event.get("invocationId"),
                        "user": content,
                        "events": [],
                    }
                )
            continue
        cleaned = _clean(content)
        if (
            cleaned["parts"]
            and result
            and event.get("invocationId") == result[-1]["invocation_id"]
        ):
            result[-1]["events"].append(
                {
                    "author": event["author"],
                    "content": cleaned,
                    "event_time": event.get("timestamp"),
                }
            )
    return [t for t in result if t["events"]]


def final_text(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        texts = [
            p["text"] for p in event["content"].get("parts") or [] if p.get("text")
        ]
        if texts:
            return "".join(texts)
    return ""


def eval_case(
    session_id: str,
    user_id: str,
    index: int,
    turn: dict[str, Any],
    agents: dict[str, Any],
    forbidden: list[str],
) -> dict[str, Any]:
    """One turn in the populated-trace format of `agents-cli eval generate`."""
    return {
        "eval_case_id": f"{session_id}#{index}",
        "prompt": {
            "role": "user",
            "parts": [p for p in turn["user"]["parts"] if p.get("text")],
        },
        "responses": [
            {
                "response": {
                    "role": "model",
                    "parts": [{"text": final_text(turn["events"])}],
                }
            }
        ],
        "agent_data": {
            "agents": agents,
            "turns": [{"turn_index": 0, "turn_id": "turn_0", "events": turn["events"]}],
        },
        "forbidden_strings": forbidden,
        "session_user": user_id,
    }


async def agents_map() -> dict[str, Any]:
    """The agents as ADK's /app-info describes them, with instruction providers rendered."""
    from google.adk.agents import LlmAgent
    from google.adk.utils.agent_info import get_agents_dict

    from app.agent import root_agent

    infos = await get_agents_dict(root_agent)
    by_name: dict[str, LlmAgent] = {}
    stack = [root_agent]
    while stack:
        agent = stack.pop()
        by_name[agent.name] = agent
        stack.extend(a for a in agent.sub_agents if isinstance(a, LlmAgent))
    result = {}
    for name, info in infos.items():
        instruction: Any = info.instruction
        provider = by_name[name].instruction
        if callable(provider):  # ours only read today's date, not the context
            try:
                instruction = provider(None)  # type: ignore[arg-type]
                if inspect.isawaitable(instruction):
                    instruction = await instruction
            except Exception:  # keep ADK's placeholder
                instruction = info.instruction
        result[name] = {
            "agent_id": name,
            "agent_type": "LlmAgent",
            "description": info.description,
            "instruction": instruction,
            "tools": [t.model_dump(mode="json", exclude_none=True) for t in info.tools],
            "sub_agents": info.sub_agents,
        }
    return result


def build(hours: float, max_turns: int) -> None:
    engine = engine_name()
    http = _session()
    since = datetime.now(UTC) - timedelta(hours=hours)
    agents = asyncio.run(agents_map())
    forbidden = forbidden_salary_strings()
    cases: list[dict[str, Any]] = []
    sessions = recent_sessions(http, engine, since)
    used = 0
    for session in sessions:
        used += 1
        session_id = session["name"].rsplit("/", 1)[-1]
        for index, turn in enumerate(turns(session_events(http, session["name"]))):
            cases.append(
                eval_case(
                    session_id,
                    session.get("userId", ""),
                    index,
                    turn,
                    agents,
                    forbidden,
                )
            )
        if len(cases) >= max_turns:
            break
    cases = cases[:max_turns]
    if not cases:
        sys.exit(
            f"No conversations in the last {hours:g} h. Ask the agent something first."
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TRACES.write_text(json.dumps({"eval_cases": cases}, indent=1, ensure_ascii=False))
    print(f"{len(cases)} turns from {used} conversations -> {TRACES.relative_to(ROOT)}")


def _results(results_dir: Path) -> dict[str, Any]:
    files = sorted(results_dir.glob("results_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        sys.exit(
            f"No results_*.json in {results_dir}. Did `agents-cli eval grade` finish?"
        )
    data: dict[str, Any] = json.loads(files[-1].read_text())
    return data


def summarize(results: dict[str, Any]) -> dict[str, Any]:
    """Per-metric means and the lowest-scoring turn, from an `agents-cli eval grade` result."""
    cases = results.get("evaluation_dataset", [{}])[0].get("eval_cases", [])
    metrics = {
        m["metric_name"]: {
            "mean": m.get("mean_score"),
            "scored": m.get("num_cases_valid") or 0,
            "errors": m.get("num_cases_error") or 0,
        }
        for m in results.get("summary_metrics", [])
    }
    lowest: dict[str, Any] | None = None
    for result in results.get("eval_case_results", []):
        case = cases[result["eval_case_index"]]
        for name, r in result["response_candidate_results"][0][
            "metric_results"
        ].items():
            score = r.get("score")
            if score is not None and (lowest is None or score < lowest["score"]):
                lowest = {
                    "case": case.get("eval_case_id", ""),
                    "user": case.get("session_user", ""),
                    "prompt": "".join(
                        p.get("text", "") for p in case["prompt"]["parts"]
                    ),
                    "answer": "".join(
                        p.get("text", "")
                        for p in case["responses"][0]["response"]["parts"]
                    ),
                    "metric": name,
                    "score": score,
                    "explanation": str(r.get("explanation") or "")[:300],
                }
    return {"turns": len(cases), "metrics": metrics, "lowest": lowest}


def print_summary(summary: dict[str, Any], heading: str) -> None:
    print(heading)
    for name, m in sorted(summary["metrics"].items()):
        mean = "  n/a" if m["mean"] is None else f"{m['mean']:.2f}"
        note = f", {m['errors']} not applicable or failed" if m["errors"] else ""
        print(f"  {name:<28} mean {mean}  ({m['scored']} scored{note})")
    low = summary["lowest"]
    if not low or low["score"] >= 1:
        print("\nEvery scored turn got full marks on every metric.")
        return
    session_id = low["case"].split("#")[0]
    user = "" if low.get("user") in (None, "", "cli-user") else f" --user {low['user']}"
    print("\nLowest-scoring turn:")
    print(f"  prompt: {low['prompt']}")
    print(f"  answer: {low['answer'][:200]}")
    print(f"  {low['metric']} = {low['score']}: {low['explanation'][:200]}")
    print("\nTurn it into a test case:")
    print(
        f"  uv run python scripts/session_to_eval_case.py {session_id}{user} --id my_regression"
    )


def report(results_dir: Path) -> None:
    summary = summarize(_results(results_dir))
    print_summary(
        summary, f"Scored {summary['turns']} recent turns of the deployed agent:"
    )
    (results_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )


def show_recorded(path: Path) -> None:
    summary = json.loads(path.read_text())
    print_summary(
        summary,
        f"Scores recorded during a rehearsal ({summary.get('recorded', '?')}, {summary['turns']} turns):",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score the deployed agent's recent conversations."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser(
        "build", help="write artifacts/live/traces.json from recent sessions"
    )
    b.add_argument(
        "--hours", type=float, default=3, help="look back this far (default 3)"
    )
    b.add_argument(
        "--max-turns", type=int, default=20, help="at most this many turns (default 20)"
    )
    r = sub.add_parser("report", help="summarise the grade results")
    r.add_argument("results_dir", nargs="?", default=str(OUT_DIR))
    r.add_argument(
        "--recorded", type=Path, help="print a saved summary instead (fallback)"
    )
    args = parser.parse_args()
    if args.command == "build":
        build(args.hours, args.max_turns)
    else:
        if args.recorded:
            show_recorded(args.recorded)
        else:
            report(Path(args.results_dir))


if __name__ == "__main__":
    main()
