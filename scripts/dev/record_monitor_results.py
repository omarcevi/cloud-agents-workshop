"""Record a live online monitor's results for scripts/fallback_step6.sh.

Reads the monitor's own log (aiplatform.googleapis.com/online_evaluator) and the agent's
prompt/answer events, and writes evals/recorded/online-monitor-results.json.

Usage: uv run python scripts/dev/record_monitor_results.py [--project P] [--hours 3]
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evals" / "recorded" / "online-monitor-results.json"
SKIPPED_WHY = (
    "The monitor builds one agent configuration per trace and needs the same system "
    "instruction on every call_llm span. A turn where the concierge transfers to a "
    "sub-agent has two, so the whole trace is skipped. Cover those turns with the "
    "offline eval set and the tool error and blocked-call metrics."
)


def read_logs(project: str, log_filter: str, hours: int) -> list[dict[str, Any]]:
    out = subprocess.run(
        [
            "gcloud",
            "logging",
            "read",
            log_filter,
            "--project",
            project,
            "--freshness",
            f"{hours}h",
            "--limit",
            "1000",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out or "[]")


def last_user_text(messages: str) -> str:
    texts = [
        part.get("content", "")
        for message in json.loads(messages)
        if message.get("role") == "user"
        for part in message.get("parts", [])
        if part.get("type") == "text"
    ]
    return texts[-1] if texts else ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default=None)
    parser.add_argument("--hours", type=int, default=3)
    args = parser.parse_args()
    project = (
        args.project
        or subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )

    entries = read_logs(project, 'logName:"online_evaluator"', args.hours)
    scores: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
    skipped: Counter[str] = Counter()
    skipped_traces: set[str] = set()
    scored_traces: set[str] = set()
    monitor = ""
    for entry in entries:
        labels = entry.get("labels", {})
        monitor = monitor or labels.get("online_evaluator", "")
        trace = entry.get("trace", "").rsplit("/", 1)[-1]
        if "gen_ai.evaluation.score.value" in labels:
            explanation = (
                entry.get("jsonPayload", {})
                .get("candidateResult", {})
                .get("explanation", "")
            )
            scores[labels["gen_ai.evaluation.name"]].append(
                (float(labels["gen_ai.evaluation.score.value"]), trace, explanation)
            )
            scored_traces.add(trace)
        elif labels.get("error.type") == "INSUFFICIENT_DATA":
            skipped[labels.get("error.message", "").split(";")[0]] += 1
            skipped_traces.add(trace)
    if not scores:
        raise SystemExit("No scores in the monitor's log yet; send traffic and wait.")

    metrics = [
        {
            "name": name,
            "mean": round(statistics.mean(s for s, _, _ in values), 2),
            "min": min(s for s, _, _ in values),
            "samples": len(values),
        }
        for name, values in sorted(scores.items())
    ]
    metric, (score, trace, explanation) = min(
        ((name, value) for name, values in scores.items() for value in values),
        key=lambda item: item[1][0],
    )
    events = read_logs(
        project,
        f'labels."event.name"="gen_ai.client.inference.operation.details" AND trace:"{trace}"',
        args.hours,
    )
    prompt = answer = ""
    for event in events:
        labels = event.get("labels", {})
        prompt = prompt or last_user_text(labels.get("gen_ai.input.messages", "[]"))
        for message in json.loads(labels.get("gen_ai.output.messages", "[]")):
            for part in message.get("parts", []):
                if part.get("type") == "text":
                    answer = part.get("content", "")
    try:
        rationale = json.loads(explanation)[0]["explanation"]
        rationale = rationale if isinstance(rationale, str) else json.dumps(rationale)
    except (ValueError, KeyError, IndexError, TypeError):
        rationale = explanation
    result: dict[str, Any] = {
        "monitor": monitor.rsplit("/", 1)[-1],
        "recorded": datetime.now(UTC).strftime("%Y-%m-%d"),
        "sampled_traces": len(scored_traces),
        "metrics": metrics,
        "lowest_trace": {
            "prompt": prompt,
            "answer": answer[:400],
            "metric": metric,
            "score": score,
            "rationale": rationale[:400],
        },
    }
    if skipped:
        message, _ = skipped.most_common(1)[0]
        result["skipped"] = {
            "traces": len(skipped_traces),
            "error_type": "INSUFFICIENT_DATA",
            "message": message,
            "why": SKIPPED_WHY,
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
