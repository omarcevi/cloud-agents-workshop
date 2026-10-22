# Alternative: departments as separate agents (A2A)

Proof of concept, tested on 2026-10-22 in `europe-west1`. The main lab deploys one
multi-agent app. On this branch each department's agent is its own Agent Runtime
deployment, and the concierge finds them in Agent Registry and calls them over A2A. It
shows how separate teams can own separate agents on one platform.

## How it works

- `A2A_TEST_ROLE=it_desk` in `.env`: the deployment serves only `it_desk_agent`.
- `A2A_TEST_ROLE=concierge`: at startup the concierge lists Agent Registry
  (`agentregistry.googleapis.com/v1/projects/P/locations/L/agents`), keeps agents whose
  display name starts with `a2a-`, fetches each one's A2A agent card
  (`https://L-aiplatform.googleapis.com/reasoningEngines/v1/<runtime>/api/a2a/app/.well-known/agent-card.json`)
  and adds a `RemoteA2aAgent` per card as a sub-agent.
- The concierge's own Agent Identity authenticates the A2A calls (an `httpx` client with
  a Google bearer token; deploy it with `GOOGLE_API_ENABLE_RUNTIME_BOUND_TOKEN=false`).
- The employee crosses the hop in A2A request metadata (`kuzey_user_id`). The receiving
  agent (`app/app_utils/a2a.py`, `_run_as_caller_user`) runs as that user. It trusts the
  caller because only identities with IAM permission on the agent can reach it.

Deploy each role from its own copy of the repo (agents-cli keeps one
`deployment_metadata.json` per directory) with the display name set in
`agents-cli-manifest.yaml` (`a2a-it-desk`, `a2a-concierge`). Grant the concierge's
principal `roles/agentregistry.viewer`, and the IT agent's principal `roles/run.invoker`
on `ticketing-mcp`.

## Results

| Test | Result |
|---|---|
| Concierge calls a separately deployed agent over A2A | Works: every IT question was handed over and the IT agent called its own tools |
| Discovery in Agent Registry | Works. Agent Runtime deployments register themselves; the concierge found `it_desk_agent` at startup with no URL configured |
| Employee identity across A2A | Works: two employees each saw only their own tickets; the ticketing server's audit log named the right employee |
| Latency | 51 s for the first turn (both agents cold), then 7–12 s |
| Traces | One per agent: a turn becomes a concierge trace and an IT agent trace (same session) |
| Managed Online Monitor | The multi-agent skip is gone: both monitors accepted their traces, and the IT agent's show its tool calls. Grading still failed with "Judge model resource exhausted" (the judge model's shared capacity, see VERIFIED.md) |
| Agent Gateway rules per agent | Partial: concierge→agent calls pass through the gateway and are logged, but the gateway classifies them as the `google-apis` endpoint (the agent shares the `L-aiplatform.googleapis.com` host), so a rule on `destination.agent_registry.agent.name` does not apply yet |

## Not done on this branch

Discovery happens at startup only (a new department needs a concierge restart), HR and
leave are still in-process sub-agents of the concierge, and evals, scripts and the guide
cover the single-deployment lab only.
