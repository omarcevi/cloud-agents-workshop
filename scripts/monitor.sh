#!/usr/bin/env bash
# Lab step 6: create an Online Monitor that scores the deployed agent's live traces.
#
# Online monitors read prompts and answers from Cloud Trace/Logging telemetry events,
# which is why setup.sh writes OTEL_SEMCONV_STABILITY_OPT_IN and
# OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY into .env.
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

existing="$(api GET "${BASE}" | python3 -c 'import json,sys; print(next((e["name"] for e in json.load(sys.stdin).get("onlineEvaluators",[]) if e.get("displayName")=="workplace-quality"), ""))')"
if [[ -n "${existing}" ]]; then
  ok "Online monitor already exists: ${existing##*/}"
else
  # Predefined v1 metrics: safety, overall response quality and tool use. The v1 specs are
  # available in every region that supports monitors; newer versions are not everywhere.
  body="$(python3 - "${RESOURCE}" "${SAMPLING}" <<'PY'
import json, sys
resource, sampling = sys.argv[1], int(sys.argv[2])
metrics = ["safety_v1", "final_response_quality_v1", "tool_use_quality_v1"]
print(json.dumps({
    "displayName": "workplace-quality",
    "agentResource": resource,
    "cloudObservability": {"openTelemetry": {"semconvVersion": "1.39.0"}},
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
echo "  https://console.cloud.google.com/vertex-ai/agents/agent-engines/locations/${LOCATION}/agent-engines/${RESOURCE##*/}?project=${PROJECT_ID}"
