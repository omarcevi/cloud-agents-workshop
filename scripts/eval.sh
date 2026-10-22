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

PIDS=()
# shellcheck disable=SC2329  # called by the EXIT trap
cleanup() { [[ ${#PIDS[@]} -gt 0 ]] && kill "${PIDS[@]}" 2>/dev/null || true; }
trap cleanup EXIT

log "Starting local MCP servers"
port=8081
for server in "${MCP_SERVERS[@]}"; do
  (cd "${REPO_ROOT}" && HOST=127.0.0.1 PORT="${port}" uv run --quiet python -m "mcp_servers.${server}.server" \
     > "${REPO_ROOT}/.setup-local-${server}.log" 2>&1) &
  PIDS+=($!)
  export "$(tr '[:lower:]' '[:upper:]' <<< "${server}")_MCP_URL=http://127.0.0.1:${port}"
  port=$((port + 1))
done
for p in 8081 8082 8083; do
  for _ in $(seq 1 50); do curl -sf "http://127.0.0.1:${p}/health" >/dev/null && break; sleep 0.2; done
  curl -sf "http://127.0.0.1:${p}/health" >/dev/null || die "Local MCP server on port ${p} did not start"
done
ok "hris :8081, ticketing :8082, compensation :8083"

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
