"""Fail the build when eval scores drop below evals/thresholds.yaml.

`agents-cli eval run` exits 0 whatever the scores, so this reads its results file
and decides. It also fails if any case errored, because errored cases are left out
of the mean.

Usage: uv run python evals/gate.py SUITE RESULTS_DIR
  SUITE is a key of thresholds.yaml (behaviour, handbook); RESULTS_DIR holds the
  results_*.json written by `agents-cli eval run --output RESULTS_DIR`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

THRESHOLDS = Path(__file__).with_name("thresholds.yaml")


def latest_results(results_dir: Path) -> dict[str, Any]:
    files = sorted(results_dir.glob("results_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit(f"No results_*.json in {results_dir}. Did `agents-cli eval run` finish?")
    data: dict[str, Any] = json.loads(files[-1].read_text())
    return data


def check(results: dict[str, Any], thresholds: dict[str, float]) -> tuple[bool, list[str]]:
    lines, passed = [], True
    summary = {m["metric_name"]: m for m in results.get("summary_metrics", [])}
    for metric, minimum in thresholds.items():
        m = summary.get(metric)
        if m is None:
            lines.append(f"FAIL {metric}: no score in the results")
            passed = False
            continue
        mean, errors = m.get("mean_score"), m.get("num_cases_error") or 0
        ok = mean is not None and mean >= minimum and errors == 0
        passed &= ok
        lines.append(
            f"{'PASS' if ok else 'FAIL'} {metric}: {mean if mean is None else round(mean, 3)}"
            f" (threshold {minimum}, {m.get('num_cases_valid')} cases, {errors} errors)"
        )
    cases = results.get("evaluation_dataset", [{}])[0].get("eval_cases", [])
    for result in results.get("eval_case_results", []):
        case_id = cases[result["eval_case_index"]].get("eval_case_id", result["eval_case_index"])
        for name, r in result["response_candidate_results"][0]["metric_results"].items():
            if name in thresholds and (r.get("score") is None or r["score"] < thresholds[name]):
                why = r.get("error_message") or r.get("explanation") or ""
                lines.append(f"     {case_id} {name}={r.get('score')}: {str(why)[:160]}")
    return passed, lines


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    suite, results_dir = sys.argv[1], Path(sys.argv[2])
    thresholds = yaml.safe_load(THRESHOLDS.read_text())[suite]
    passed, lines = check(latest_results(results_dir), thresholds)
    print("\n".join(lines))
    print(f"Eval gate ({suite}): {'PASSED' if passed else 'FAILED'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
