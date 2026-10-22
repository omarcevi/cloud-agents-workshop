#!/usr/bin/env bash
# Lab step 5: create the monitoring dashboard and show the latest leave request trace.
source "$(dirname "$0")/lib/common.sh"
require_project

RESOURCE="$(agent_resource)" || true
[[ -n "${RESOURCE}" ]] || die "No deployed agent. Run agents-cli deploy first."
ENGINE_ID="${RESOURCE##*/}"

log "Logs-based metrics (setup.sh creates them; this makes sure they exist)"
for file in "${REPO_ROOT}"/infra/monitoring/log-metrics/*.json; do
  name="$(basename "${file}" .json)"
  if gcloud logging metrics describe "${name}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    ok "${name}"
  else
    gcloud logging metrics create "${name}" --config-from-file "${file}" --project "${PROJECT_ID}" >/dev/null && ok "${name} created"
  fi
done

log "Dashboard"
existing="$(gcloud monitoring dashboards list --project "${PROJECT_ID}" \
  --filter='displayName:"Workplace Assistant"' --format='value(name)' 2>/dev/null | head -1)"
if [[ -z "${existing}" ]]; then
  config="${REPO_ROOT}/.setup-dashboard.json"
  sed "s/REASONING_ENGINE_ID/${ENGINE_ID}/g" "${REPO_ROOT}/infra/monitoring/dashboard.json" > "${config}"
  gcloud monitoring dashboards create --config-from-file "${config}" --project "${PROJECT_ID}" >/dev/null
  existing="$(gcloud monitoring dashboards list --project "${PROJECT_ID}" \
    --filter='displayName:"Workplace Assistant"' --format='value(name)' | head -1)"
fi
ok "https://console.cloud.google.com/monitoring/dashboards/builder/${existing##*/}?project=${PROJECT_ID}"

log "Latest trace with a leave request"
(cd "${REPO_ROOT}" && uv run --quiet python scripts/trace.py --project "${PROJECT_ID}") \
  || warn "No leave request trace yet. Ask the agent to book a day off, wait a minute, then run: uv run python scripts/trace.py"
