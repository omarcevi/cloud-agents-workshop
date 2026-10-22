#!/usr/bin/env bash
# Lab step 6 fallback, when Online Monitors are not available in your project or region
# (or the evaluation service is unavailable).
#
# 1. Runs the behaviour eval suite locally. Its three metrics are local Python
#    functions, so no evaluation service is needed (Gemini still answers as the agent).
# 2. Shows online monitor results recorded during a rehearsal, so you can see what a
#    monitor reports.
source "$(dirname "$0")/lib/common.sh"
require_project

log "Running the eval set locally (behaviour suite: routing, tool trajectory, no compensation leak)"
"${REPO_ROOT}/scripts/eval.sh" behaviour || warn "The eval gate failed; see the cases listed above."

RECORDED="${REPO_ROOT}/evals/recorded/online-monitor-results.json"
log "Online monitor results recorded during a rehearsal (${RECORDED#"${REPO_ROOT}"/})"
python3 - "${RECORDED}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
print(f"  monitor: {data['monitor']}  ({data['recorded']}, {data['sampled_traces']} traces scored)")
for metric in data["metrics"]:
    print(f"  {metric['name']:<28} mean {metric['mean']:.2f}  lowest {metric['min']:.2f}")
print("\n  Lowest-scoring trace:")
low = data["lowest_trace"]
print(f"    prompt: {low['prompt']}\n    answer: {low['answer']}\n    {low['metric']}: {low['score']} - {low['rationale']}")
PY

mkdir -p "${REPO_ROOT}/artifacts/eval"
echo "fallback_step6.sh ran at $(date -u +%FT%TZ)" > "${REPO_ROOT}/artifacts/eval/online-monitor-fallback.txt"
log "Next: turn the lowest-scoring trace into an eval case (see the step 6 page), then ./scripts/check.sh 6"
