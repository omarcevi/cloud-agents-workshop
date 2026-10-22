#!/usr/bin/env bash
# Prove that a lab step worked. Usage: ./scripts/check.sh STEP   (0-6; 0 = ready to start)
#   ./scripts/check.sh      checks the step of the checkpoint branch you are on
source "$(dirname "$0")/lib/common.sh"
require_project

STEP="${1:-$(cat "${REPO_ROOT}/.checkpoint" 2>/dev/null || echo 0)}"
FAILED=0
pass() { ok "$*"; }
miss() { fail "$*"; FAILED=1; }

ask_json() {  # ask_json MESSAGE [USER]
  (cd "${REPO_ROOT}" && uv run --quiet python scripts/ask.py --json --user "${2:-check-user@kuzeylabs.example}" "$1" 2>/dev/null)
}
json_get() {  # json_get JSON PYTHON_EXPR  (the parsed JSON is `d`)
  python3 -c "import json,sys; d=json.loads(sys.argv[1]); print($2)" "$1"
}

check_0() {
  log "Step 0: tools, login and project"
  local tool
  for tool in gcloud uv agents-cli python3 curl; do
    if command -v "${tool}" >/dev/null; then pass "${tool} found"; else miss "${tool} not found (see the overview page)"; fi
  done
  local account billing
  account="$(gcloud config get-value account 2>/dev/null || true)"
  if [[ -n "${account}" ]]; then pass "logged in as ${account}"; else miss "not logged in: gcloud auth login"; fi
  billing="$(gcloud billing projects describe "${PROJECT_ID}" --format='value(billingEnabled)' 2>/dev/null || true)"
  if [[ "${billing}" == True ]]; then pass "billing enabled on ${PROJECT_ID}"; else miss "billing not enabled (or not visible) on ${PROJECT_ID}"; fi
  if gcloud auth application-default print-access-token >/dev/null 2>&1; then
    pass "application default credentials"
  else
    miss "no application default credentials: gcloud auth application-default login"
  fi
}

check_1() {
  log "Step 1: APIs enabled and three MCP servers healthy"
  local enabled
  enabled="$(gcloud services list --enabled --project "${PROJECT_ID}" --format='value(config.name)')"
  for api_name in aiplatform.googleapis.com run.googleapis.com agentregistry.googleapis.com \
                  networkservices.googleapis.com iap.googleapis.com agentidentity.googleapis.com \
                  telemetry.googleapis.com cloudtrace.googleapis.com; do
    if grep -qx "${api_name}" <<< "${enabled}"; then pass "${api_name}"; else miss "${api_name} is not enabled"; fi
  done
  local token
  token="$(gcloud auth print-identity-token)"
  for server in "${MCP_SERVERS[@]}"; do
    local name url ready code_anon code_auth
    name="$(mcp_service_name "${server}")"
    url="$(gcloud run services describe "${name}" --region "${REGION}" --project "${PROJECT_ID}" --format='value(status.url)' 2>/dev/null || true)"
    [[ -n "${url}" ]] || { miss "${name} is not deployed"; continue; }
    ready="$(gcloud run services describe "${name}" --region "${REGION}" --project "${PROJECT_ID}" \
               --format='value(status.conditions[0].status)')"
    code_auth="$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${token}" "${url}/health")"
    code_anon="$(curl -s -o /dev/null -w '%{http_code}' "${url}/health")"
    if [[ "${ready}" == "True" && "${code_auth}" == 200 && "${code_anon}" == 403 ]]; then
      pass "${name} ready, /health 200 with a token, 403 without"
    else
      miss "${name}: ready=${ready}, with token=${code_auth}, without=${code_anon} (want True/200/403)"
    fi
  done
}

check_2() {
  log "Step 2: agent deployed with Agent Identity and answers a handbook question"
  local resource identity result
  resource="$(agent_resource)" || true
  [[ -n "${resource}" ]] || { miss "no deployment_metadata.json. Run agents-cli deploy"; return; }
  identity="$(api GET "https://${REGION}-aiplatform.googleapis.com/v1beta1/${resource}" \
                | python3 -c 'import json,sys; print(json.load(sys.stdin).get("spec",{}).get("effectiveIdentity",""))')"
  if [[ "${identity}" == agents.global.* ]]; then pass "Agent Identity: principal://${identity}"; else miss "agent has no Agent Identity (${identity:-none})"; fi
  for server in "${MCP_SERVERS[@]}"; do
    if gcloud run services get-iam-policy "$(mcp_service_name "${server}")" --region "${REGION}" \
         --project "${PROJECT_ID}" --format=json | grep -q "principal://${identity}"; then
      pass "agent may invoke $(mcp_service_name "${server}")"
    else
      miss "agent lacks roles/run.invoker on $(mcp_service_name "${server}"). Run ./scripts/grant_agent_access.sh"
    fi
  done
  result="$(ask_json "How many unused leave days can I carry over into next year?")" || { miss "the agent did not answer"; return; }
  if [[ "$(json_get "${result}" '"handbook_search" in [c["name"] for c in d["tool_calls"]]')" == True \
        && "$(json_get "${result}" '"5" in d["answer"]')" == True ]]; then
    pass "handbook answer: $(json_get "${result}" 'd["answer"][:120].replace(chr(10)," ")')..."
  else
    miss "unexpected answer: $(json_get "${result}" 'd["answer"][:200]')"
  fi
}

check_3() {
  log "Step 3: Memory Bank holds the user's team and office"
  local facts
  facts="$(cd "${REPO_ROOT}" && uv run --quiet python scripts/memory_bank.py list --user "${CHECK_USER:-cli-user}" 2>/dev/null || true)"
  printf '%s\n' "${facts}" | sed 's/^/     /'
  if grep -qi "platform" <<< "${facts}"; then pass "remembers the team"; else miss "no memory about the platform team yet"; fi
  if grep -qi "istanbul" <<< "${facts}"; then pass "remembers the office"; else miss "no memory about the Istanbul office yet"; fi
}

check_4() {
  log "Step 4: compensation is blocked and logged; HRIS still works"
  local blocked leave since
  since="$(date -u -v-30M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%SZ)"
  blocked="$(ask_json "What is the salary band for an L5 in the Istanbul office?")" || { miss "the agent did not answer"; return; }
  if [[ "$(json_get "${blocked}" 'any(r["name"]=="get_salary_band" and ("error" in str(r["response"]) or "unavailable" in str(r["response"])) for r in d["tool_results"])')" == True ]]; then
    pass "get_salary_band was refused: $(json_get "${blocked}" 'd["answer"][:110].replace(chr(10)," ")')..."
  else
    miss "get_salary_band was not refused: $(json_get "${blocked}" 'd["answer"][:160]')"
  fi
  leave="$(ask_json "How many leave days do I have left?" "deniz.kaya@kuzeylabs.example")" || true
  if [[ "$(json_get "${leave:-{\}}" 'any(r["name"]=="get_leave_balance" and "structuredContent" in str(r["response"]) for r in d.get("tool_results",[]))')" == True ]]; then pass "HRIS still answers (get_leave_balance)"; else miss "HRIS call failed after securing"; fi
  log "Waiting for the audit log entry (up to 2 minutes)"
  local entries=""
  for _ in $(seq 1 12); do
    entries="$(gcloud logging read "labels.\"event.name\"=\"workplace.tool_blocked\" AND timestamp>=\"${since}\"" \
                 --project "${PROJECT_ID}" --limit 5 --format='value(jsonPayload.tool,jsonPayload.reason)' 2>/dev/null || true)"
    [[ -n "${entries}" ]] && break
    sleep 10
  done
  if [[ -n "${entries}" ]]; then pass "logged in Cloud Logging: ${entries//$'\n'/; }"; else miss "no workplace.tool_blocked log entry in the last 30 minutes"; fi
}

check_5() {
  log "Step 5: a trace with a sub-agent and tool calls exists"
  local summary
  summary="$(cd "${REPO_ROOT}" && uv run --quiet python scripts/trace.py --project "${PROJECT_ID}" --json --minutes 180 2>/dev/null)" \
    || { miss "no trace with a leave request in the last 3 hours. Book leave, wait a minute, retry"; return; }
  local subs tools
  subs="$(json_get "${summary}" 'len(d["sub_agent_spans"])')"
  tools="$(json_get "${summary}" 'len(d["tool_spans"])')"
  if [[ "${subs}" -ge 1 ]]; then pass "sub-agent spans: $(json_get "${summary}" 'd["sub_agent_spans"]')"; else miss "no sub-agent span"; fi
  if [[ "${tools}" -ge 2 ]]; then pass "tool spans: $(json_get "${summary}" 'd["tool_spans"]')"; else miss "fewer than 2 tool spans"; fi
  if gcloud monitoring dashboards list --project "${PROJECT_ID}" --filter='displayName:"Workplace Assistant"' --format='value(name)' | grep -q .; then pass "dashboard exists"; else miss "no dashboard. Run ./scripts/observe.sh"; fi
  if gcloud logging metrics describe workplace_tool_blocked --project "${PROJECT_ID}" >/dev/null 2>&1; then pass "logs-based metric workplace_tool_blocked exists"; else miss "missing logs-based metric workplace_tool_blocked"; fi
}

check_6() {
  log "Step 6: eval report passes the thresholds and an online monitor exists"
  local suite
  for suite in behaviour handbook; do
    if [[ -d "${REPO_ROOT}/artifacts/eval/${suite}" ]]; then
      if (cd "${REPO_ROOT}" && uv run --quiet python evals/gate.py "${suite}" "artifacts/eval/${suite}" >/dev/null 2>&1); then pass "eval ${suite} passes the thresholds"; else miss "eval ${suite} is below the thresholds (uv run python evals/gate.py ${suite} artifacts/eval/${suite})"; fi
    else
      miss "no ${suite} eval results. Run ./scripts/eval.sh"
    fi
  done
  local monitors
  monitors="$(api GET "https://${REGION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_ID}/locations/${REGION}/onlineEvaluators" \
                | python3 -c 'import json,sys; print(" ".join(e.get("displayName","") for e in json.load(sys.stdin).get("onlineEvaluators",[])))' 2>/dev/null || true)"
  if [[ -n "${monitors}" ]]; then
    pass "online monitor: ${monitors}"
  elif [[ -f "${REPO_ROOT}/artifacts/eval/online-monitor-fallback.txt" ]]; then
    pass "online monitor fallback used (scripts/fallback_step6.sh)"
  else
    miss "no online monitor. Run ./scripts/monitor.sh, or ./scripts/fallback_step6.sh"
  fi
}

case "${STEP}" in
  0|1|2|3|4|5|6) "check_${STEP}" ;;
  *) die "Usage: ./scripts/check.sh STEP   (0-6)" ;;
esac
if [[ "${FAILED}" == 0 ]]; then log "Step ${STEP} checks passed."; else die "Step ${STEP} is not done yet (see above)."; fi
