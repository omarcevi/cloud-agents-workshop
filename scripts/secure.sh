#!/usr/bin/env bash
# Lab step 4: apply the egress access policy to Agent Gateway.
#
# setup.sh already created the gateway, registered the MCP servers and Google APIs in
# Agent Registry, and made IAP the gateway's authorizer. This script writes the IAM
# access policy: the Workplace Assistant may reach the Google APIs it runs on plus the
# HRIS and ticketing MCP servers, and no agent may reach the compensation server.
# Then bind the agent to the gateway with the agents-cli command it prints.
#
# Usage: ./scripts/secure.sh [--deploy]   (--deploy also runs the agents-cli command)
source "$(dirname "$0")/lib/common.sh"
require_project

DEPLOY=0
[[ "${1:-}" == "--deploy" ]] && DEPLOY=1

GATEWAY="projects/${PROJECT_ID}/locations/${REGION}/agentGateways/${GATEWAY_NAME}"
gcloud network-services agent-gateways describe "${GATEWAY_NAME}" --location "${REGION}" --project "${PROJECT_ID}" \
  >/dev/null 2>&1 || die "Agent Gateway ${GATEWAY_NAME} not found. Is setup still creating it? (tail .setup-gateway.log) Otherwise use ./scripts/fallback_step4.sh"
gcloud network-security authz-policies describe workplace-iap-policy --location "${REGION}" --project "${PROJECT_ID}" \
  >/dev/null 2>&1 || die "The gateway has no IAP authorization policy yet (setup creates it in the background; tail .setup-gateway.log)."

AGENT_PRINCIPAL="${AGENT_PRINCIPAL:-}"
[[ -n "${AGENT_PRINCIPAL}" ]] || die "Unknown agent identity. Run ./scripts/grant_agent_access.sh first (step 2)."

# IAP refers to registry resources by project NUMBER, while `gcloud agent-registry ... list`
# prints the project ID. Policies must use the number form or they never match.
by_number() { sed "s#^projects/${PROJECT_ID}/#projects/${PROJECT_NUMBER}/#"; }

registry_mcp_server() {  # registry_mcp_server CLOUD_RUN_URL
  gcloud agent-registry mcp-servers list --location "${REGION}" --project "${PROJECT_ID}" --format=json \
    | python3 -c 'import json,sys; print(next((m["name"] for m in json.load(sys.stdin) if any(i.get("url","").startswith(sys.argv[1]) for i in m.get("interfaces",[]))), ""))' "$1" \
    | by_number
}

log "Looking up registry names"
HRIS_ID="$(registry_mcp_server "${HRIS_MCP_URL}")"
TICKETING_ID="$(registry_mcp_server "${TICKETING_MCP_URL}")"
COMPENSATION_ID="$(registry_mcp_server "${COMPENSATION_MCP_URL}")"
GOOGLE_APIS_ID="$(gcloud agent-registry endpoints list --location "${REGION}" --project "${PROJECT_ID}" --format=json \
  | python3 -c 'import json,sys; print(next((e["name"] for e in json.load(sys.stdin) if e.get("attributes",{}).get("agentregistry.googleapis.com/system/RuntimeReference",{}).get("uri","").endswith("/services/google-apis")), ""))' \
  | by_number)"
for v in HRIS_ID TICKETING_ID COMPENSATION_ID GOOGLE_APIS_ID; do
  [[ -n "${!v}" ]] || die "${v} not found in Agent Registry. Re-run ./scripts/setup.sh"
  ok "${v} = ${!v##*/}"
done

PROJECT_AGENTS="principalSet://agents.global.proj-${PROJECT_NUMBER}.system.id.goog/attribute.platformContainer/aiplatform/projects/${PROJECT_NUMBER}"
if [[ "${EFFECTIVE_TRUST_DOMAIN:-${AGENT_PRINCIPAL}}" == *".org-"* ]]; then
  org="$(sed -E 's#.*agents\.global\.(org-[0-9]+)\.system.*#\1#' <<< "${AGENT_PRINCIPAL}")"
  PROJECT_AGENTS="principalSet://agents.global.${org}.system.id.goog/attribute.platformContainer/aiplatform/projects/${PROJECT_NUMBER}"
fi

RULES="${REPO_ROOT}/.setup-egress-rules.json"
sed -e "s#\"AGENT_PRINCIPAL\"#\"${AGENT_PRINCIPAL}\"#" -e "s#\"PROJECT_AGENTS\"#\"${PROJECT_AGENTS}\"#" \
    -e "s#GOOGLE_APIS_ENDPOINT#${GOOGLE_APIS_ID}#" -e "s#HRIS_MCP_SERVER#${HRIS_ID}#" \
    -e "s#TICKETING_MCP_SERVER#${TICKETING_ID}#" -e "s#COMPENSATION_MCP_SERVER#${COMPENSATION_ID}#" \
    "${REPO_ROOT}/infra/gateway/egress-policy.rules.json" > "${RULES}"
python3 -m json.tool "${RULES}" >/dev/null || die "rendered policy is not valid JSON"

log "IAM access policy workplace-egress (allow HRIS + ticketing, deny compensation)"
if gcloud iam access-policies describe workplace-egress --location global --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam access-policies update workplace-egress --location global --project "${PROJECT_ID}" \
    --details-rules "${RULES}" --quiet >/dev/null
  ok "updated"
else
  gcloud iam access-policies create workplace-egress --location global --project "${PROJECT_ID}" \
    --details-rules "${RULES}" --quiet >/dev/null
  ok "created"
fi
# The binding target must name the project by NUMBER. A binding to the project ID is
# accepted but never applied, and every call through the gateway is then denied.
TARGET="//cloudresourcemanager.googleapis.com/projects/${PROJECT_NUMBER}"
current="$(gcloud iam policy-bindings describe workplace-egress-binding --location global --project "${PROJECT_ID}" \
             --format='value(target.resource)' 2>/dev/null || true)"
if [[ "${current}" != "${TARGET}" ]]; then
  if [[ -n "${current}" ]]; then
    gcloud iam policy-bindings delete workplace-egress-binding --location global --project "${PROJECT_ID}" --quiet >/dev/null
  fi
  gcloud iam policy-bindings create workplace-egress-binding --location global --project "${PROJECT_ID}" \
    --policy "projects/${PROJECT_ID}/locations/global/accessPolicies/workplace-egress" \
    --target-resource "${TARGET}" --quiet >/dev/null
fi
ok "bound to project ${PROJECT_NUMBER}"

# Agents behind the gateway need to read the registry (gateway docs, "required basic roles").
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member "${AGENT_PRINCIPAL}" \
  --role roles/agentregistry.viewer --condition None --quiet >/dev/null
ok "agent may read Agent Registry"

# The gateway inspects TLS, so certificate-bound tokens can't pass through it:
# the agent must use unbound tokens for Google APIs (GOOGLE_API_ENABLE_RUNTIME_BOUND_TOKEN=false).
DEPLOY_CMD=(agents-cli deploy --project "${PROJECT_ID}" --update-only --agent-identity --no-confirm-project
            "--agent-gateway-egress=${GATEWAY}"
            --update-env-vars "GOOGLE_API_ENABLE_RUNTIME_BOUND_TOKEN=false")
save_state GATEWAY_RESOURCE "${GATEWAY}"
if [[ "${DEPLOY}" == 1 ]]; then
  log "Binding the agent to the gateway (redeploy, about 4 minutes)"
  (cd "${REPO_ROOT}" && "${DEPLOY_CMD[@]}")
else
  log "Now bind the agent to the gateway (about 4 minutes):"
  printf '\n  %s \\\n    %s \\\n    %s\n\n' "${DEPLOY_CMD[*]:0:7}" "${DEPLOY_CMD[7]}" "${DEPLOY_CMD[*]:8}"
fi
