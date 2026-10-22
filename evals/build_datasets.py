"""Build the agents-cli eval datasets from evals/cases.yaml.

- behaviour.json: routing, tool trajectory and compensation-leak cases.
- handbook.json:  policy questions with the handbook passages as `context`, for the
  built-in grounding metric.
Run after editing cases.yaml:  uv run python evals/build_datasets.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.tools.handbook import get_index  # noqa: E402

OUT = ROOT / "evals" / "datasets"
CASE_FIELDS = (
    "expected_agent",
    "expected_tool_calls",
    "forbidden_tools",
    "must_refuse",
    "note",
)


def forbidden_salary_strings() -> list[str]:
    """Every individual salary in the seed data, as a digit string."""
    data = json.loads((ROOT / "data" / "seed" / "compensation.json").read_text())
    return sorted(str(v) for v in data["salaries"].values())


def handbook_context(anchors: list[str]) -> str:
    """The whole handbook: the metric asks "is every claim supported by the handbook?".

    `anchors` (the sections a good answer cites) are only checked to exist; passing just
    those sections made correct answers that cited a neighbouring section look ungrounded.
    """
    passages = get_index().passages
    known = {p.source for p in passages}
    missing = [a for a in anchors if a not in known]
    if missing:
        raise SystemExit(f"Unknown handbook sections in cases.yaml: {missing}")
    return "\n\n".join(f"[{p.source}] {p.title}\n{p.text}" for p in passages)


def to_eval_case(case: dict[str, Any], salaries: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "eval_case_id": case["id"],
        "prompt": {"role": "user", "parts": [{"text": case["prompt"]}]},
    }
    out.update({k: case[k] for k in CASE_FIELDS if k in case})
    out["forbidden_strings"] = salaries
    if "handbook" in case:
        out["context"] = handbook_context(case["handbook"])
    return out


def build() -> dict[str, dict[str, Any]]:
    cases = yaml.safe_load((ROOT / "evals" / "cases.yaml").read_text())
    salaries = forbidden_salary_strings()
    return {
        name: {"eval_cases": [to_eval_case(c, salaries) for c in cases[name]]}
        for name in ("behaviour", "handbook")
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, dataset in build().items():
        path = OUT / f"{name}.json"
        path.write_text(
            json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"{path.relative_to(ROOT)}: {len(dataset['eval_cases'])} cases")


if __name__ == "__main__":
    main()
