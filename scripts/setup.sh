#!/usr/bin/env bash
# Lab step 1: enable APIs, build and deploy the three MCP servers, register them, write .env.
# Safe to re-run: every phase checks what already exists.
#
# Usage: ./scripts/setup.sh [--only PHASE[,PHASE...]]
#   phases: apis repo image services env
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
      --description "Deploying Your Agents workshop" --quiet
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
       --substitutions "_IMAGE=${MCP_IMAGE}" --region "${REGION}" --project "${PROJECT_ID}" --quiet \
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
  # Online monitors read prompts and answers from these telemetry events (lab step 6).
  set_env_value "${AGENT_ENV}" OTEL_SEMCONV_STABILITY_OPT_IN gen_ai_latest_experimental
  set_env_value "${AGENT_ENV}" OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT EVENT_ONLY
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
  want env && phase_env
  log "Setup finished in $((SECONDS - start))s. Next: ./scripts/check.sh 1"
}

main "$@"
