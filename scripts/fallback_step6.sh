#!/usr/bin/env bash
# Lab step 6 fallback, when the evaluation service or Online Monitors are not available
# in your project or region.
#
# 1. Runs the behaviour eval suite locally. Its three metrics are local Python
#    functions, so no evaluation service is needed (Gemini still answers as the agent).
# 2. Shows live-traffic scores recorded during a rehearsal (what ./scripts/score_live.sh
#    prints), so you can see what scoring production traffic looks like.
source "$(dirname "$0")/lib/common.sh"
require_project

log "Running the eval set locally (behaviour suite: routing, tool trajectory, no compensation leak)"
"${REPO_ROOT}/scripts/eval.sh" behaviour || warn "The eval gate failed; see the cases listed above."

log "Live-traffic scores recorded during a rehearsal (evals/recorded/live-scores.json)"
(cd "${REPO_ROOT}" && uv run --quiet python scripts/score_live.py report --recorded evals/recorded/live-scores.json)

mkdir -p "${REPO_ROOT}/artifacts/eval"
echo "fallback_step6.sh ran at $(date -u +%FT%TZ)" > "${REPO_ROOT}/artifacts/eval/online-monitor-fallback.txt"
log "Next: turn the lowest-scoring trace into an eval case (see the step 6 page), then ./scripts/check.sh 6"
