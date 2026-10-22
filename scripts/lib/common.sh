#!/usr/bin/env bash
# Shared settings and helpers for the workshop scripts. Source it; don't run it.
# shellcheck disable=SC2034  # variables here are used by the scripts that source this file

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSHOP_ENV="${REPO_ROOT}/.workshop.env"   # script state written by setup.sh (git-ignored)
AGENT_ENV="${REPO_ROOT}/.env"               # agent config; agents-cli deploy ships it as env vars

# Load state from a previous setup.sh run, if any. Values already set in the
# environment win, so `REGION=europe-west4 ./scripts/setup.sh` works.
if [[ -f "${WORKSHOP_ENV}" ]]; then
  while IFS='=' read -r key value; do
    [[ -z "${key}" || "${key}" == \#* ]] && continue
    if [[ -z "${!key:-}" ]]; then
      export "${key}=${value}"
    fi
  done < "${WORKSHOP_ENV}"
fi

PROJECT_ID="${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${REGION:-europe-west1}"
LABEL_KEY="workshop"
LABEL_VALUE="deploy-agents"
LABELS="${LABEL_KEY}=${LABEL_VALUE}"

AR_REPO="${AR_REPO:-workshop}"
AGENT_NAME="workplace-assistant"                 # Agent Runtime display name = project name in agents-cli-manifest.yaml
MCP_SERVERS=(hris ticketing compensation)
GATEWAY_NAME="${GATEWAY_NAME:-workplace-gw}"
DEMO_USER_EMAIL="${DEMO_USER_EMAIL:-deniz.kaya@kuzeylabs.example}"

if [[ -t 1 ]]; then
  _BOLD=$'\033[1m'; _GREEN=$'\033[32m'; _RED=$'\033[31m'; _YELLOW=$'\033[33m'; _RESET=$'\033[0m'
else
  _BOLD=""; _GREEN=""; _RED=""; _YELLOW=""; _RESET=""
fi

log()  { printf '%s==>%s %s\n' "${_BOLD}" "${_RESET}" "$*"; }
ok()   { printf '%s  ✔%s %s\n' "${_GREEN}" "${_RESET}" "$*"; }
warn() { printf '%s  !%s %s\n' "${_YELLOW}" "${_RESET}" "$*" >&2; }
fail() { printf '%s  ✘%s %s\n' "${_RED}" "${_RESET}" "$*" >&2; }
die()  { fail "$*"; exit 1; }

require_project() {
  [[ -n "${PROJECT_ID}" ]] || die "No project. Run: gcloud config set project YOUR_PROJECT_ID"
  PROJECT_NUMBER="${PROJECT_NUMBER:-$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')}"
  export PROJECT_ID PROJECT_NUMBER REGION
}

mcp_service_name() { printf '%s-mcp' "$1"; }

# Read the deployed agent's resource name from agents-cli's deployment_metadata.json.
agent_resource() {
  local meta="${REPO_ROOT}/deployment_metadata.json"
  [[ -f "${meta}" ]] || return 1
  python3 -c 'import json,sys; v=json.load(open(sys.argv[1])).get("remote_agent_runtime_id"); print(v or "")' "${meta}"
}

# Write KEY=VALUE into an env file, replacing an existing KEY line.
set_env_value() {
  local file="$1" key="$2" value="$3"
  touch "${file}"
  python3 - "${file}" "${key}" "${value}" <<'PY'
import sys
path, key, value = sys.argv[1:]
lines = open(path, encoding="utf-8").read().splitlines()
out, found = [], False
for line in lines:
    if line.split("=", 1)[0] == key:
        out.append(f"{key}={value}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}={value}")
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
}

save_state() { set_env_value "${WORKSHOP_ENV}" "$1" "$2"; export "$1=$2"; }

access_token() { gcloud auth print-access-token; }

# Authenticated REST call: api METHOD URL [JSON_BODY]
api() {
  local method="$1" url="$2" body="${3:-}"
  local args=(-sS -X "${method}" -H "Authorization: Bearer $(access_token)"
              -H "Content-Type: application/json" -H "x-goog-user-project: ${PROJECT_ID}")
  if [[ -n "${body}" ]]; then args+=(-d "${body}"); fi
  curl "${args[@]}" "${url}"
}

# Start fresh local copies of the three MCP servers on 8081-8083 and point the agent at
# them (*_MCP_URL). Eval runs use them so they never change the shared Cloud Run data.
# Stopped by the EXIT trap this sets.
LOCAL_MCP_PIDS=()
# shellcheck disable=SC2329  # called by the EXIT trap
stop_local_mcp_servers() {
  if [[ ${#LOCAL_MCP_PIDS[@]} -gt 0 ]]; then kill "${LOCAL_MCP_PIDS[@]}" 2>/dev/null || true; fi
}
start_local_mcp_servers() {
  trap stop_local_mcp_servers EXIT
  log "Starting local MCP servers"
  local port=8081 server p
  for server in "${MCP_SERVERS[@]}"; do
    (cd "${REPO_ROOT}" && HOST=127.0.0.1 PORT="${port}" uv run --quiet python -m "mcp_servers.${server}.server" \
       > "${REPO_ROOT}/.setup-local-${server}.log" 2>&1) &
    LOCAL_MCP_PIDS+=($!)
    export "$(tr '[:lower:]' '[:upper:]' <<< "${server}")_MCP_URL=http://127.0.0.1:${port}"
    port=$((port + 1))
  done
  for p in 8081 8082 8083; do
    for _ in $(seq 1 50); do curl -sf "http://127.0.0.1:${p}/health" >/dev/null && break; sleep 0.2; done
    curl -sf "http://127.0.0.1:${p}/health" >/dev/null || die "Local MCP server on port ${p} did not start"
  done
  ok "hris :8081, ticketing :8082, compensation :8083"
}

# Fill PROJECT_ID into an eval config template (judge model names need the project) and
# print the path of the filled-in copy, which sits next to the template so relative
# custom_function_file paths still resolve.
render_eval_config() {
  local template="$1" rendered
  rendered="$(dirname "${template}")/.$(basename "${template}" .yaml).${PROJECT_ID}.yaml"
  sed "s#PROJECT_ID#${PROJECT_ID}#g" "${REPO_ROOT}/${template}" > "${REPO_ROOT}/${rendered}"
  printf '%s' "${rendered}"
}
