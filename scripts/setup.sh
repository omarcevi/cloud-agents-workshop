#!/usr/bin/env bash
# Lab step 1: enable APIs, build and deploy the three MCP servers, register them, write .env.
# Safe to re-run: every phase checks what already exists.
#
# Usage: ./scripts/setup.sh [--only PHASE[,PHASE...]]
#   phases: apis repo image services registry metrics gateway env
source "$(dirname "$0")/lib/common.sh"

ONLY=""
if [[ "${1:-}" == "--only" ]]; then ONLY="${2:-}"; fi
want() { [[ -z "${ONLY}" || ",${ONLY}," == *",$1,"* ]]; }

APIS=(
  aiplatform.googleapis.com            # Agent Runtime, Sessions, Memory Bank, Gemini
  run.googleapis.com                   # MCP servers
  cloudbuild.googleapis.com            # builds the MCP image
  artifactregistry.googleapis.com
  agentregistry.googleapis.com         # Agent Registry (MCP servers, endpoints)
  apphub.googleapis.com
  networkservices.googleapis.com       # Agent Gateway
  networksecurity.googleapis.com       # authorization policies
  iap.googleapis.com                   # IAP enforces the gateway's egress IAM
  agentidentity.googleapis.com         # Agent Identity, Auth Manager
  agentidentitycredentials.googleapis.com
  telemetry.googleapis.com             # OpenTelemetry ingestion
  cloudtrace.googleapis.com
  logging.googleapis.com
  monitoring.googleapis.com
  cloudresourcemanager.googleapis.com
  iam.googleapis.com
  iamcredentials.googleapis.com
  serviceusage.googleapis.com
  compute.googleapis.com               # required by Agent Gateway
)

phase_apis() {
  log "Enabling APIs (takes a minute the first time)"
  gcloud services enable "${APIS[@]}" --project "${PROJECT_ID}" --quiet
  ok "APIs enabled"
}

phase_repo() {
  log "Artifact Registry repository ${AR_REPO} in ${REGION}"
  if gcloud artifacts repositories describe "${AR_REPO}" --location "${REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    ok "already exists"
  else
    gcloud artifacts repositories create "${AR_REPO}" --repository-format docker \
      --location "${REGION}" --project "${PROJECT_ID}" --labels "${LABELS}" \
      --description "Cloud agents workshop" --quiet
    ok "created"
  fi
}

# The image tag is a hash of everything that goes into the image, so a re-run skips the build.
mcp_image() {
  local hash
  hash="$(cd "${REPO_ROOT}" && find mcp_servers data/seed -type f -not -name '*.pyc' -not -path '*/__pycache__/*' \
            | LC_ALL=C sort | xargs cat | shasum -a 256 | cut -c1-12)"
  printf '%s-docker.pkg.dev/%s/%s/mcp-servers:%s' "${REGION}" "${PROJECT_ID}" "${AR_REPO}" "${hash}"
}

phase_image() {
  MCP_IMAGE="${MCP_IMAGE_OVERRIDE:-$(mcp_image)}"
  log "MCP server image ${MCP_IMAGE##*/}"
  if gcloud artifacts docker images describe "${MCP_IMAGE}" >/dev/null 2>&1; then
    ok "already built"
  else
    (cd "${REPO_ROOT}" && gcloud builds submit . --config mcp_servers/cloudbuild.yaml \
       --substitutions "_IMAGE=${MCP_IMAGE}" --region "${REGION}" --project "${PROJECT_ID}" \
       --gcs-source-staging-dir "gs://${PROJECT_ID}_cloudbuild/workshop-source" --quiet \
       > "${REPO_ROOT}/.setup-build.log" 2>&1) \
      || die "Image build failed. See .setup-build.log"
    ok "built with Cloud Build"
  fi
  save_state MCP_IMAGE "${MCP_IMAGE}"
}

deploy_service() {
  local server="$1" name
  name="$(mcp_service_name "${server}")"
  gcloud run deploy "${name}" --image "${MCP_IMAGE}" --region "${REGION}" --project "${PROJECT_ID}" \
    --no-allow-unauthenticated --set-env-vars "MCP_SERVER=${server}" \
    --cpu 1 --memory 512Mi --min-instances 0 --max-instances 1 --concurrency 40 \
    --labels "${LABELS}" --quiet > "${REPO_ROOT}/.setup-${server}.log" 2>&1
}

phase_services() {
  log "Deploying ${#MCP_SERVERS[@]} MCP servers to Cloud Run (IAM-only, scale to zero)"
  local pids=() server failed=0
  for server in "${MCP_SERVERS[@]}"; do
    deploy_service "${server}" & pids+=($!)
  done
  for i in "${!pids[@]}"; do
    if wait "${pids[$i]}"; then
      ok "$(mcp_service_name "${MCP_SERVERS[$i]}")"
    else
      fail "$(mcp_service_name "${MCP_SERVERS[$i]}") failed. See .setup-${MCP_SERVERS[$i]}.log"; failed=1
    fi
  done
  [[ "${failed}" == 0 ]] || exit 1
  for server in "${MCP_SERVERS[@]}"; do
    local url key
    url="$(gcloud run services describe "$(mcp_service_name "${server}")" --region "${REGION}" \
            --project "${PROJECT_ID}" --format 'value(status.url)')"
    key="$(printf '%s_MCP_URL' "${server}" | tr '[:lower:]' '[:upper:]')"
    save_state "${key}" "${url}"
  done
}

# Agent Registry: the three MCP servers (with their tool specs) and one composite
# endpoint for the Google APIs the agent itself calls. Agent Gateway only lets agents
# reach registered destinations that a policy allows.
register() {  # register NAME DISPLAY ARGS...   (re-runs refresh the interface URLs only)
  local name="$1" display="$2"; shift 2
  if gcloud agent-registry services describe "${name}" --location "${REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    local interfaces=() args=("$@") i
    for ((i = 0; i < ${#args[@]}; i++)); do
      if [[ "${args[$i]}" == --interfaces ]]; then interfaces+=(--interfaces "${args[$((i + 1))]}"); fi
    done
    gcloud agent-registry services update "${name}" --location "${REGION}" --project "${PROJECT_ID}" \
      --quiet "${interfaces[@]}" >/dev/null 2>&1
    ok "${display} (refreshed)"
  else
    gcloud agent-registry services create "${name}" --location "${REGION}" --project "${PROJECT_ID}" \
      --display-name "${display}" --quiet "$@" >/dev/null 2>&1
    ok "${display}"
  fi
}

phase_registry() {
  log "Registering MCP servers and Google APIs in Agent Registry"
  local server url
  for server in "${MCP_SERVERS[@]}"; do
    url="$(gcloud run services describe "$(mcp_service_name "${server}")" --region "${REGION}" \
            --project "${PROJECT_ID}" --format 'value(status.url)')"
    register "$(mcp_service_name "${server}")" "Kuzey ${server} MCP" \
      --mcp-server-spec-type tool-spec \
      --mcp-server-spec-content "$(cat "${REPO_ROOT}/infra/gateway/toolspecs/${server}.json")" \
      --interfaces "url=${url}/mcp,protocolBinding=jsonrpc"
  done
  local args=() line
  while read -r line; do
    [[ -z "${line}" || "${line}" == \#* ]] && continue
    args+=(--interfaces "protocolBinding=jsonrpc,url=${line//REGION/${REGION}}")
  done < "${REPO_ROOT}/infra/gateway/platform-endpoints.txt"
  register google-apis "Google APIs used by the agent" --endpoint-spec-type no-spec "${args[@]}"
}

phase_metrics() {
  log "Logs-based metrics (they only count entries written after they exist)"
  local file name
  for file in "${REPO_ROOT}"/infra/monitoring/log-metrics/*.json; do
    name="$(basename "${file}" .json)"
    if gcloud logging metrics describe "${name}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
      ok "${name} (exists)"
    else
      gcloud logging metrics create "${name}" --config-from-file "${file}" --project "${PROJECT_ID}" >/dev/null
      ok "${name}"
    fi
  done
}

# Creating the gateway and its IAP authorization policy takes about 6 minutes, so it runs in
# the background (log: .setup-gateway.log) and is ready long before step 4.
gateway_job() {
  set -euo pipefail
  local gw_file="${REPO_ROOT}/.setup-gateway.yaml" pol_file="${REPO_ROOT}/.setup-iap-policy.yaml"
  sed -e "s/PROJECT_ID/${PROJECT_ID}/g" -e "s/REGION/${REGION}/g" "${REPO_ROOT}/infra/gateway/gateway.yaml" > "${gw_file}"
  sed -e "s/PROJECT_ID/${PROJECT_ID}/g" -e "s/REGION/${REGION}/g" -e "s/GATEWAY/${GATEWAY_NAME}/g" \
    "${REPO_ROOT}/infra/gateway/iap-authz-policy.yaml" > "${pol_file}"
  echo "$(date -u +%T) creating gateway ${GATEWAY_NAME}"
  gcloud network-services agent-gateways describe "${GATEWAY_NAME}" --location "${REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1 \
    || gcloud network-services agent-gateways import "${GATEWAY_NAME}" --source "${gw_file}" \
         --location "${REGION}" --project "${PROJECT_ID}" --quiet
  echo "$(date -u +%T) IAP authorization extension"
  gcloud service-extensions authz-extensions import workplace-iap --source "${REPO_ROOT}/infra/gateway/iap-authz-extension.yaml" \
    --location "${REGION}" --project "${PROJECT_ID}" --quiet
  echo "$(date -u +%T) IAP authorization policy on the gateway"
  gcloud network-security authz-policies describe workplace-iap-policy --location "${REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1 \
    || gcloud network-security authz-policies import workplace-iap-policy --source "${pol_file}" \
         --location "${REGION}" --project "${PROJECT_ID}" --quiet
  echo "$(date -u +%T) GATEWAY READY"
}

phase_gateway() {
  log "Agent Gateway ${GATEWAY_NAME} (background, about 6 minutes)"
  if gcloud network-security authz-policies describe workplace-iap-policy --location "${REGION}" \
       --project "${PROJECT_ID}" >/dev/null 2>&1; then
    ok "already set up"
    return
  fi
  (gateway_job > "${REPO_ROOT}/.setup-gateway.log" 2>&1 || echo "$(date -u +%T) GATEWAY FAILED" >> "${REPO_ROOT}/.setup-gateway.log") &
  disown
  ok "started; follow it with: tail -f .setup-gateway.log"
}

# .env is read by the agent locally and shipped by `agents-cli deploy` as env vars.
phase_env() {
  log "Writing .env for the agent"
  set_env_value "${AGENT_ENV}" GOOGLE_GENAI_USE_ENTERPRISE true
  set_env_value "${AGENT_ENV}" GOOGLE_CLOUD_PROJECT "${PROJECT_ID}"
  set_env_value "${AGENT_ENV}" GOOGLE_CLOUD_LOCATION global
  set_env_value "${AGENT_ENV}" HRIS_MCP_URL "${HRIS_MCP_URL}"
  set_env_value "${AGENT_ENV}" TICKETING_MCP_URL "${TICKETING_MCP_URL}"
  set_env_value "${AGENT_ENV}" COMPENSATION_MCP_URL "${COMPENSATION_MCP_URL}"
  set_env_value "${AGENT_ENV}" DEMO_USER_EMAIL "${DEMO_USER_EMAIL}"
  # Online monitors read prompts and answers from these telemetry events, and the agent's
  # instructions and tools from the ADK call_llm spans (lab step 6). agents-cli deploys
  # with ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false unless .env says otherwise.
  set_env_value "${AGENT_ENV}" OTEL_SEMCONV_STABILITY_OPT_IN gen_ai_latest_experimental
  set_env_value "${AGENT_ENV}" OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT EVENT_ONLY
  set_env_value "${AGENT_ENV}" ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS true
  ok ".env written"
}

main() {
  require_project
  log "Project ${PROJECT_ID} (${PROJECT_NUMBER}), region ${REGION}"
  save_state PROJECT_ID "${PROJECT_ID}"
  save_state PROJECT_NUMBER "${PROJECT_NUMBER}"
  save_state REGION "${REGION}"
  local start=${SECONDS}
  want apis && phase_apis
  want repo && phase_repo
  want image && phase_image
  want services && phase_services
  want registry && phase_registry
  want metrics && phase_metrics
  want gateway && phase_gateway
  want env && phase_env
  log "Setup finished in $((SECONDS - start))s. Next: ./scripts/check.sh 1"
}

main "$@"
