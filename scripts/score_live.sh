#!/usr/bin/env bash
# Lab step 6: score the deployed agent's recent conversations.
#
# Reads the last few hours of conversations from Agent Runtime Sessions, turns every turn
# (including the ones a sub-agent handled) into an eval case, and grades them with
# `agents-cli eval grade` and evals/eval_config.live.yaml. The managed Online Monitor
# skips multi-agent turns; this covers them. Run it on a schedule in production.
#
# Usage: ./scripts/score_live.sh [--hours 3] [--max-turns 20]
source "$(dirname "$0")/lib/common.sh"
require_project

OUT="artifacts/live"
# The local MCP servers only describe the tools to the judges; the turns come from
# the deployed agent.
start_local_mcp_servers
log "Reading recent conversations from Agent Runtime Sessions"
(cd "${REPO_ROOT}" && uv run --quiet python scripts/score_live.py build "$@" 2>/dev/null) \
  || die "Could not read the conversations (see above)."

config="$(render_eval_config evals/eval_config.live.yaml)"
rm -f "${REPO_ROOT}/${OUT}"/results_*.json
log "Grading them (judge: Gemini 3.5 Flash, about a minute)"
(cd "${REPO_ROOT}" && agents-cli eval grade --traces "${OUT}/traces.json" --config "${config}" \
   --output "${OUT}" --project "${PROJECT_ID}" --qps 2 >/dev/null) \
  || die "agents-cli eval grade failed. Run it without >/dev/null to see why."
(cd "${REPO_ROOT}" && uv run --quiet python scripts/score_live.py report "${OUT}")
