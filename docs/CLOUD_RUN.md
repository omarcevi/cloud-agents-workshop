# Alternative target: Cloud Run

This branch is `main` after:

```bash
agents-cli scaffold enhance . --deployment-target cloud_run --no-agent-gateway -n workplace-assistant
```

- `--no-agent-gateway`: Agent Gateway binding exists only for Agent Runtime (agents-cli
  refuses `cloud_run` together with the gateway flag). Gateways for Cloud Run agents are a
  Preview sign-up.
- The manifest now says `deployment_target: cloud_run`; `agents-cli deploy` runs
  `gcloud run deploy --source .` with the generated settings (`--dry-run` prints it).
- The enhance also generates `deployment/terraform/`. It is removed here: `agents-cli
  deploy` does not use it, and the template grants project-wide roles (for example
  `roles/storage.admin` to the app's service account) that you would narrow to
  bucket-level grants before handing it to a customer.
- Two dependency fixes after the enhance: `google-cloud-agentplatform` is added back
  (Sessions and Memory Bank still come from Agent Platform), and the template's
  `uvicorn~=0.34` pin is relaxed because FastMCP 4.1.3 needs 0.35 or later.

## What changes compared with Agent Runtime

| Concern | Agent Runtime (main) | Cloud Run (this branch) |
|---|---|---|
| Sessions | Built in (`GOOGLE_CLOUD_AGENT_ENGINE_ID` is injected) | Set `SESSION_SERVICE_URI=agentengine://projects/P/locations/L/reasoningEngines/ID` (an Agent Runtime instance used only as the session and memory store), or use Cloud SQL |
| Memory Bank | Built in | Set `MEMORY_BANK_RESOURCE=projects/P/locations/L/reasoningEngines/ID` |
| Identity | Agent Identity | The service's service account (Agent Identity on Cloud Run is Preview) |
| MCP server access | `roles/run.invoker` for the agent principal | `roles/run.invoker` for the service account |
| Who can call the agent | IAM on `:query`/`:streamQuery` | Cloud Run IAM (`--no-allow-unauthenticated`) or IAP (`agents-cli deploy --iap`) |
| Tracing | Telemetry env vars set by agents-cli | Same code; set `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true` |

## Deploy

```bash
./scripts/setup.sh --only apis,repo,image,services,env     # the MCP servers, as in the lab
agents-cli deploy --project $PROJECT_ID --region europe-west1 \
  --update-env-vars SESSION_SERVICE_URI=agentengine://projects/$PROJECT_ID/locations/europe-west1/reasoningEngines/ID
```

Then grant the Cloud Run service's service account `roles/run.invoker` on the three MCP
servers. This branch is checked by CI (lint and unit tests); it is not part of the timed lab.
