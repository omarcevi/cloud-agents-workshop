#!/usr/bin/env bash
# Regenerate the checkpoint branches step-0-start … step-6-evaluate from main.
#
# main is the final state. Each branch is main plus a .checkpoint file (so a bare
# ./scripts/check.sh checks that step), minus what later steps add to the repo:
# before step 6 the eval set does not yet contain the production regression case.
# Because every branch is rebuilt from main, a fix on main reaches all of them.
#
# Usage: scripts/dev/make_checkpoints.sh [--push]
#   then, if you didn't pass --push: git push --force-with-lease origin 'step-*'
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${ROOT}"

[[ -z "$(git status --porcelain)" ]] || { echo "Commit or stash your changes first." >&2; exit 1; }
[[ "$(git rev-parse --abbrev-ref HEAD)" == main ]] || { echo "Run this on main." >&2; exit 1; }

BRANCHES=(step-0-start step-1-setup step-2-deploy step-3-remember step-4-secure step-5-observe step-6-evaluate)
MAIN_SHA="$(git rev-parse --short HEAD)"

drop_step6_cases() {
  # Cases added in lab step 6 carry "(lab step 6)" in their note.
  uv run --quiet python - <<'PY'
import re
from pathlib import Path

path = Path("evals/cases.yaml")
text = path.read_text(encoding="utf-8")
blocks = re.split(r"(?m)^(?=  - id: )", text)
kept = [b for b in blocks if "(lab step 6)" not in b]
path.write_text("".join(kept), encoding="utf-8")
PY
  uv run --quiet python evals/build_datasets.py >/dev/null
}

for step in "${!BRANCHES[@]}"; do
  branch="${BRANCHES[$step]}"
  git checkout -q -B "${branch}" main
  echo "${step}" > .checkpoint
  if (( step < 6 )); then drop_step6_cases; fi
  git add -A
  git -c commit.gpgsign="${CHECKPOINT_SIGN:-false}" commit -q --allow-empty -m "Checkpoint: state after step ${step} (${branch})" \
    -m "Generated from main ${MAIN_SHA} by scripts/dev/make_checkpoints.sh."
  git tag -f "checkpoint/${branch}" >/dev/null
  echo "${branch}: $(git rev-parse --short HEAD)"
done
git checkout -q main

if [[ "${1:-}" == "--push" ]]; then
  git push --force-with-lease origin "${BRANCHES[@]}"
  git push --force origin "${BRANCHES[@]/#/refs/tags/checkpoint/}"
fi
