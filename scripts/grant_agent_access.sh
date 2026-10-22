#!/usr/bin/env bash
# Lab step 2, after `agents-cli deploy`: let the agent's own identity call the MCP servers.
#
# Agent Identity gives the deployed agent its own principal (a SPIFFE-based ID). This
# script reads it from the Agent Runtime resource and grants it roles/run.invoker on the
# three Cloud Run MCP services, then applies the Memory Bank topics.
source "$(dirname "$0")/lib/common.sh"
require_project

RESOURCE="$(agent_resource)" || true
[[ -n "${RESOURCE}" ]] || die "No deployed agent found. Run agents-cli deploy first (see the step 2 page)."
AGENT_LOCATION="$(cut -d/ -f4 <<< "${RESOURCE}")"

log "Reading the agent's identity from ${RESOURCE##*/}"
EFFECTIVE_IDENTITY="$(api GET "https://${AGENT_LOCATION}-aiplatform.googleapis.com/v1beta1/${RESOURCE}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("spec",{}).get("effectiveIdentity",""))')"
[[ "${EFFECTIVE_IDENTITY}" == agents.global.* ]] \
  || die "The agent has no Agent Identity (got '${EFFECTIVE_IDENTITY}'). Redeploy with --agent-identity."
AGENT_PRINCIPAL="principal://${EFFECTIVE_IDENTITY}"
ok "${AGENT_PRINCIPAL}"
save_state AGENT_RESOURCE "${RESOURCE}"
save_state AGENT_PRINCIPAL "${AGENT_PRINCIPAL}"

log "Granting roles/run.invoker on the MCP servers to the agent"
for server in "${MCP_SERVERS[@]}"; do
  gcloud run services add-iam-policy-binding "$(mcp_service_name "${server}")" \
    --region "${REGION}" --project "${PROJECT_ID}" \
    --member "${AGENT_PRINCIPAL}" --role roles/run.invoker --condition None --quiet >/dev/null
  ok "$(mcp_service_name "${server}")"
done

log "Configuring Memory Bank topics (team and office, work preferences)"
(cd "${REPO_ROOT}" && uv run --quiet python scripts/memory_bank.py configure)

log "Done. Chat with: agents-cli run --url \"\$(./scripts/agent_url.sh)\" --mode adk \"Hi\""
