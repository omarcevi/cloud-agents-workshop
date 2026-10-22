#!/usr/bin/env bash
# Lab step 6: run the eval set and fail if any metric is below evals/thresholds.yaml.
#
# The agent runs locally (agents-cli eval run starts it) against fresh local copies of
# the three MCP servers, so eval runs never change the shared Cloud Run data. Gemini and
# the evaluation service are real, so this needs Google Cloud credentials.
#
# Usage: ./scripts/eval.sh [behaviour|handbook|all]   (default: all)
source "$(dirname "$0")/lib/common.sh"
require_project

SUITES=("${1:-all}")
[[ "${SUITES[0]}" == "all" ]] && SUITES=(behaviour handbook)

start_local_mcp_servers

export DEMO_USER_EMAIL GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
status=0
for suite in "${SUITES[@]}"; do
  config="evals/eval_config.yaml"
  [[ "${suite}" == "handbook" ]] && config="evals/eval_config.handbook.yaml"
  out="artifacts/eval/${suite}"
  log "agents-cli eval run (${suite})"
  (cd "${REPO_ROOT}" && agents-cli eval run --dataset "evals/datasets/${suite}.json" \
     --config "${config}" --output "${out}" --project "${PROJECT_ID}") \
    || { fail "agents-cli eval run failed for ${suite}"; status=1; continue; }
  (cd "${REPO_ROOT}" && uv run --quiet python evals/gate.py "${suite}" "${out}") || status=1
done
exit "${status}"
