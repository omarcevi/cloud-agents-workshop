#!/usr/bin/env bash
# Print the deployed agent's query URL, for `agents-cli run --url ... --mode adk`.
source "$(dirname "$0")/lib/common.sh"
RESOURCE="$(agent_resource)" || true
[[ -n "${RESOURCE}" ]] || die "No deployed agent. Run agents-cli deploy first."
printf 'https://%s-aiplatform.googleapis.com/v1/%s\n' "$(cut -d/ -f4 <<< "${RESOURCE}")" "${RESOURCE}"
