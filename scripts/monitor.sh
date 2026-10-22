#!/usr/bin/env bash
# Lab step 6: create an Online Monitor that scores the deployed agent's live traces.
#
# Online monitors read prompts and answers from Cloud Trace/Logging telemetry events and
# the agent's instructions and tools from the ADK call_llm spans, which is why setup.sh
# writes OTEL_SEMCONV_STABILITY_OPT_IN, OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT
# and ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=true into .env. Without the last one every trace
# fails with INSUFFICIENT_DATA "system_instruction not present in any call_llm span".
# There is no gcloud command for monitors yet, so this calls the REST API (v1beta1).
# The monitor runs about every 10 minutes; first scores appear after that.
#
# Usage: ./scripts/monitor.sh [--sampling PERCENT]   (default 100, capped at 20 traces per run)
source "$(dirname "$0")/lib/common.sh"
require_project

SAMPLING=100
[[ "${1:-}" == "--sampling" ]] && SAMPLING="${2:?percent}"

RESOURCE="$(agent_resource)" || true
[[ -n "${RESOURCE}" ]] || die "No deployed agent. Run agents-cli deploy first."
LOCATION="$(cut -d/ -f4 <<< "${RESOURCE}")"
BASE="https://${LOCATION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_ID}/locations/${LOCATION}/onlineEvaluators"

# Online monitors run as the Vertex AI service agent and read traces through the
# Observability API; without this role a new monitor goes straight to FAILED
# ("Permission 'observability.views.access' denied ... _Trace/.../_AllSpans").
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --condition None --quiet \
  --member "serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com" \
  --role roles/observability.viewAccessor >/dev/null
ok "Vertex AI service agent may read traces (roles/observability.viewAccessor)"

existing="$(api GET "${BASE}" | python3 -c 'import json,sys; print(next((e["name"] for e in json.load(sys.stdin).get("onlineEvaluators",[]) if e.get("displayName")=="workplace-quality" and e.get("state")!="FAILED"), ""))')"
if [[ -n "${existing}" ]]; then
  ok "Online monitor already exists: ${existing##*/}"
else
  # The four metrics the console offers by default (v1 specs, available in every monitor
  # region). Same request body the console sends: note the empty openTelemetry block;
  # setting semconvVersion makes the API answer INVALID_ARGUMENT.
  body="$(python3 - "${RESOURCE}" "${SAMPLING}" <<'PY'
import json, sys
resource, sampling = sys.argv[1], int(sys.argv[2])
metrics = ["final_response_quality_v1", "tool_use_quality_v1", "hallucination_v1", "safety_v1"]
print(json.dumps({
    "displayName": "workplace-quality",
    "agentResource": resource,
    "cloudObservability": {"traceScope": {}, "openTelemetry": {}},
    "metricSources": [{"metric": {"predefinedMetricSpec": {"metricSpecName": m}}} for m in metrics],
    "config": {"randomSampling": {"percentage": sampling}, "maxEvaluatedSamplesPerRun": "20"},
}))
PY
)"
  log "Creating online monitor workplace-quality (sampling ${SAMPLING}%, max 20 traces per run)"
  response="$(api POST "${BASE}" "${body}")"
  if grep -q '"error"' <<< "${response}"; then
    fail "${response}"
    die "Could not create the monitor. Use the console steps on the step 6 page, or ./scripts/fallback_step6.sh"
  fi
  ok "requested: $(python3 -c 'import json,sys; print(json.load(sys.stdin).get("name",""))' <<< "${response}")"
fi
log "Scores appear about 10 minutes after traffic: Agent Platform > Agents > Deployments > ${AGENT_NAME} > Dashboard > Evaluation"
echo "  https://console.cloud.google.com/agent-platform/runtimes/locations/${LOCATION}/agent-engines/${RESOURCE##*/}/dashboard?project=${PROJECT_ID}"
