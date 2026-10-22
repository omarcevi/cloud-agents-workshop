#!/usr/bin/env bash
# Lab step 4 fallback, when Agent Gateway is not available in your project or region.
#
# Removes the agent identity's roles/run.invoker on the compensation Cloud Run service.
# The agent's code still calls the server; Cloud Run IAM now refuses it, so you still
# see a policy-level block, logged as reason=permission_denied.
#
# Usage: ./scripts/fallback_step4.sh          apply the block
#        ./scripts/fallback_step4.sh --undo   give the permission back
source "$(dirname "$0")/lib/common.sh"
require_project

[[ -n "${AGENT_PRINCIPAL:-}" ]] || die "Unknown agent identity. Run ./scripts/grant_agent_access.sh first (step 2)."
SERVICE="$(mcp_service_name compensation)"

if [[ "${1:-}" == "--undo" ]]; then
  gcloud run services add-iam-policy-binding "${SERVICE}" --region "${REGION}" --project "${PROJECT_ID}" \
    --member "${AGENT_PRINCIPAL}" --role roles/run.invoker --condition None --quiet >/dev/null 2>&1
  ok "The agent may call ${SERVICE} again."
  exit 0
fi

log "Removing roles/run.invoker on ${SERVICE} from the agent's identity"
gcloud run services remove-iam-policy-binding "${SERVICE}" --region "${REGION}" --project "${PROJECT_ID}" \
  --member "${AGENT_PRINCIPAL}" --role roles/run.invoker --condition None --quiet >/dev/null 2>&1 || true
ok "Done. IAM changes take about a minute to apply."

cat <<'EOF'

What you just did, compared with Agent Gateway:

  Cloud Run IAM (this fallback)          Agent Gateway (the main path)
  -----------------------------------    ------------------------------------------------
  One server at a time, set on the       One policy for every agent and every destination,
  server by whoever owns it.             set centrally by the platform or security team.
  All or nothing per service.            Per tool, using registry data (tool name,
                                         readOnlyHint...), with explicit deny rules.
  Only for destinations that check       Also covers Google APIs and external SaaS, and
  Google IAM (Cloud Run, Google APIs).   can add Model Armor and semantic policies.
  Logged by the server you blocked.      Every decision logged in one place.

Now ask the agent for a salary band again, then run: ./scripts/check.sh 4
EOF
