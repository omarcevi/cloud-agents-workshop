#!/usr/bin/env bash
# Delete everything the workshop created, then list what is left (should be nothing).
#
# Only touches resources with the workshop's names. It never deletes the project and
# never disables APIs (other things in your project may use them).
#
# Usage: ./scripts/teardown.sh [--yes] [--verify-only]
source "$(dirname "$0")/lib/common.sh"
require_project

YES=0; VERIFY_ONLY=0
for arg in "$@"; do
  case "${arg}" in
    --yes) YES=1 ;;
    --verify-only) VERIFY_ONLY=1 ;;
    *) die "Unknown option ${arg}" ;;
  esac
done

AR_HOST="https://${REGION}-aiplatform.googleapis.com/v1beta1"
REGISTRY_SERVICES=(hris-mcp ticketing-mcp compensation-mcp google-apis)

# Agent Runtime instances named like ours (there can be more than one after re-creates).
agent_resources() {
  api GET "${AR_HOST}/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines" \
    | python3 -c 'import json,sys; [print(e["name"]) for e in json.load(sys.stdin).get("reasoningEngines",[]) if e.get("displayName")=="'"${AGENT_NAME}"'"]'
}

online_evaluators() {
  api GET "${AR_HOST}/projects/${PROJECT_ID}/locations/${REGION}/onlineEvaluators" \
    | python3 -c 'import json,sys; [print(e["name"]) for e in json.load(sys.stdin).get("onlineEvaluators",[]) if e.get("displayName","").startswith("workplace")]' 2>/dev/null || true
}

dashboards() {
  gcloud monitoring dashboards list --project "${PROJECT_ID}" \
    --filter='displayName:"Workplace Assistant"' --format='value(name)' 2>/dev/null || true
}

quiet() { "$@" >/dev/null 2>&1; }

delete_everything() {
  log "Agent Runtime (sessions and memories go with it)"
  for name in $(agent_resources); do
    # Drop the project-level roles agents-cli granted to this agent's identity.
    identity="$(api GET "${AR_HOST}/${name}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("spec",{}).get("effectiveIdentity",""))')"
    api DELETE "${AR_HOST}/${name}?force=true" >/dev/null && ok "deleted ${name##*/}"
    if [[ -n "${identity}" ]]; then
      for role in roles/aiplatform.user roles/serviceusage.serviceUsageConsumer roles/browser \
                  roles/cloudapiregistry.viewer roles/logging.logWriter roles/monitoring.metricWriter; do
        quiet gcloud projects remove-iam-policy-binding "${PROJECT_ID}" \
          --member "principal://${identity}" --role "${role}" --condition None --quiet || true
      done
      ok "removed project roles of principal://${identity}"
    fi
  done

  log "Online monitors"
  for name in $(online_evaluators); do
    api DELETE "${AR_HOST}/${name}" >/dev/null && ok "deleted ${name##*/}"
  done

  log "Agent Gateway policies and gateway"
  quiet gcloud iam policy-bindings delete workplace-egress-binding --project "${PROJECT_ID}" --location global --quiet && ok "policy binding"
  # IAM needs 10-30 s to notice the binding is gone before the policy can be deleted.
  for _ in 1 2 3 4 5 6; do
    if ! gcloud iam access-policies describe workplace-egress --project "${PROJECT_ID}" --location global >/dev/null 2>&1; then break; fi
    if quiet gcloud iam access-policies delete workplace-egress --project "${PROJECT_ID}" --location global --quiet; then
      ok "access policy"; break
    fi
    sleep 10
  done
  quiet gcloud network-security authz-policies delete workplace-iap-policy --location "${REGION}" --project "${PROJECT_ID}" --quiet && ok "authz policy"
  quiet gcloud service-extensions authz-extensions delete workplace-iap --location "${REGION}" --project "${PROJECT_ID}" --quiet && ok "authz extension"
  quiet gcloud network-services agent-gateways delete "${GATEWAY_NAME}" --location "${REGION}" --project "${PROJECT_ID}" --quiet && ok "gateway ${GATEWAY_NAME}"

  log "Agent Registry"
  for service in "${REGISTRY_SERVICES[@]}"; do
    quiet gcloud agent-registry services delete "${service}" --location "${REGION}" --project "${PROJECT_ID}" --quiet && ok "${service}"
  done

  log "Cloud Run MCP servers"
  for server in "${MCP_SERVERS[@]}"; do
    quiet gcloud run services delete "$(mcp_service_name "${server}")" --region "${REGION}" --project "${PROJECT_ID}" --quiet \
      && ok "$(mcp_service_name "${server}")"
  done

  log "Images and build sources"
  quiet gcloud artifacts repositories delete "${AR_REPO}" --location "${REGION}" --project "${PROJECT_ID}" --quiet && ok "Artifact Registry ${AR_REPO}"
  quiet gcloud storage rm -r "gs://${PROJECT_ID}_cloudbuild/workshop-source" && ok "build sources"

  log "Monitoring and logging"
  for metric in workplace_tool_blocked workplace_gateway_denied; do
    quiet gcloud logging metrics delete "${metric}" --project "${PROJECT_ID}" --quiet && ok "${metric}"
  done
  for name in $(dashboards); do
    quiet gcloud monitoring dashboards delete "${name}" --project "${PROJECT_ID}" --quiet && ok "dashboard"
  done

  log "Optional Calendar auth provider"
  quiet gcloud agent-identity auth-providers delete calendar-3lo --location "${REGION}" --project "${PROJECT_ID}" --quiet && ok "calendar-3lo"

  rm -f "${REPO_ROOT}/deployment_metadata.json" "${WORKSHOP_ENV}"
  ok "local state (.workshop.env, deployment_metadata.json)"
}

# Print anything the workshop created that still exists. Returns 1 if anything is left.
verify() {
  log "Checking for leftovers"
  local left=0 found
  check() {  # check LABEL COMMAND...
    local label="$1"; shift
    found="$("$@" 2>/dev/null || true)"
    if [[ -n "${found}" ]]; then fail "${label}: ${found//$'\n'/, }"; left=1; else ok "no ${label}"; fi
  }
  check "Agent Runtime instances" agent_resources
  check "online monitors" online_evaluators
  check "agent gateways" gcloud network-services agent-gateways list --location "${REGION}" --project "${PROJECT_ID}" --filter="name~/${GATEWAY_NAME}$" --format='value(name)'
  check "authz policies" gcloud network-security authz-policies list --location "${REGION}" --project "${PROJECT_ID}" --filter='name~workplace' --format='value(name)'
  check "authz extensions" gcloud service-extensions authz-extensions list --location "${REGION}" --project "${PROJECT_ID}" --filter='name~workplace' --format='value(name)'
  check "access policies" gcloud iam access-policies list --location global --project "${PROJECT_ID}" --filter='name~workplace' --format='value(name)'
  check "registry services" gcloud agent-registry services list --location "${REGION}" --project "${PROJECT_ID}" \
    --filter="name~/(hris-mcp|ticketing-mcp|compensation-mcp|google-apis)$" --format='value(name)'
  check "Cloud Run services" gcloud run services list --region "${REGION}" --project "${PROJECT_ID}" \
    --filter="metadata.labels.${LABEL_KEY}=${LABEL_VALUE}" --format='value(metadata.name)'
  check "Artifact Registry repositories" gcloud artifacts repositories list --location "${REGION}" --project "${PROJECT_ID}" \
    --filter="name~/${AR_REPO}$" --format='value(name)'
  check "logs-based metrics" gcloud logging metrics list --project "${PROJECT_ID}" --filter='name~^workplace_' --format='value(name)'
  check "dashboards" dashboards
  check "auth providers" gcloud agent-identity auth-providers list --location "${REGION}" --project "${PROJECT_ID}" --filter='name~calendar-3lo' --format='value(name)'
  return "${left}"
}

if [[ "${VERIFY_ONLY}" == 0 ]]; then
  if [[ "${YES}" == 0 ]]; then
    read -r -p "Delete all workshop resources in ${PROJECT_ID} (${REGION})? [y/N] " answer
    [[ "${answer}" == [yY]* ]] || die "Cancelled."
  fi
  delete_everything
fi
if verify; then
  log "Nothing left. APIs stay enabled; they cost nothing while unused."
else
  die "Some resources are still there (deletes can take a minute). Re-run: ./scripts/teardown.sh --verify-only"
fi
