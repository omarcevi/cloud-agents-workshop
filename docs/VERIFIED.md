# Verified commands, versions and docs

Everything the lab runs, and everything the guide tells participants to run, was checked
against the installed tools, their source, the official docs, or a live run in a test
project (`europe-west1`, an org-less project with billing). Verified on **2026-10-22**.

How to read the "Verified how" column:

- **live**: run end to end against a real project; the result was checked.
- **--help**: the command and every flag used appear in the installed tool's help output.
- **source**: read in the installed package's source (agents-cli, ADK, google-auth, SDK).
- **docs**: the official page says so; not exercised here.
- **not re-verified**: written from the docs or an earlier run, and not checked again in
  this pass. Treat it as the first thing to confirm in a rehearsal.

Launch stages change often. Re-check the "Status" column the week of the event.

## 1. Versions

| Component | Version | Notes |
|---|---|---|
| agents-cli (`google-agents-cli`) | 1.11.0 | `uv tool install "google-agents-cli>=1.11"`; 1.7 lacks `--agent-gateway-egress` and `publish gemini` |
| Google Cloud CLI | 590.0.0 (core, alpha, beta 2026.10.16) | 519 lacked `agent-registry`, `iam access-policies`, `agent-gateways`; run `gcloud components update` |
| google-adk | 2.12.0 | extras `gcp, otel-gcp, bigquery-analytics, agent-identity` |
| fastmcp | 4.1.3 | MCP servers; needs uvicorn ≥ 0.35 |
| mcp | 2.3.0 | `mcp.types.ToolAnnotations` |
| google-genai | 2.31.0 | the deployed agent reported the same version in its telemetry |
| google-cloud-agentplatform | 2.5.0 | `agentplatform.Client`, `AdkApp` |
| google-cloud-aiplatform | 2.5.0 (lockfile) | research environment had 2.6.0; nothing used differs |
| google-auth | 2.62.0 | first version with `fetch_id_token(..., bind_id_token=False)` |
| opentelemetry-api / -sdk | 1.42.1 | exporter-gcp-logging 1.12.0a0, exporter-gcp-trace 1.15.0 |
| httpx | 0.28.1 | |
| Python | 3.12 (local 3.12.14; image `python:3.12-slim`) | |
| uv | 0.12.3 locally; 0.8.13 inside the agent image (pinned by the agents-cli template) | |

## 2. Region and model choices

| Choice | Why | Verified how |
|---|---|---|
| Region `europe-west1` | Agent Runtime, Sessions, Memory Bank, Agent Gateway, Agent Registry, Agent Identity and auth providers, Model Armor and semantic governance are all offered there. Closest supported region to Türkiye. | docs ([agent locations](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-locations), [Agent Identity locations](https://docs.cloud.google.com/iam/docs/agent-identity-locations), [Model Armor locations](https://docs.cloud.google.com/model-armor/locations)); live for everything the lab creates |
| Model endpoint `global` (`GOOGLE_CLOUD_LOCATION=global`) | With Agent Identity the SDK calls the mTLS host. For the `eu` multi-region that is `aiplatform.eu.rep.mtls.googleapis.com`, which does not resolve (NXDOMAIN), so model calls behind the gateway failed with 503. `global` works. Agent data (source, sessions, memories) still stays in `europe-west1`. | live |
| Model `gemini-3.5-flash`, `thinking_level=LOW`, 25 s timeout × 3 attempts (`app/config.py`) | `gemini-3.8-flash` on `global` answered in 3 s to 130 s during testing (shared capacity), too slow for a timed lab. 3.5 Flash answered in 3–5 s every time. Override with `MODEL=...`. | live (2026-10-22, 06:00–06:40 UTC) |
| Memory Bank extraction model pinned to `projects/PROJECT_ID/locations/eu/publishers/google/models/gemini-3.8-flash` (`infra/memory/memory-bank.json`) | With the default extraction model, generation timed out (`DEADLINE_EXCEEDED` after about 6 min) under load. With the pinned model, extraction took about 6 s. | live |

## 3. Commands and APIs by lab step

### Step 1: Set up

| Command / API (as the scripts run it) | Status | Verified how | Doc |
|---|---|---|---|
| `gcloud services enable aiplatform run cloudbuild artifactregistry agentregistry apphub networkservices networksecurity iap agentidentity agentidentitycredentials telemetry cloudtrace logging monitoring cloudresourcemanager iam iamcredentials serviceusage compute` (`.googleapis.com` each; `scripts/setup.sh`) | GA | live | [Agent Gateway setup](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/set-up-agent-gateway) |
| `gcloud artifacts repositories create REPO --repository-format docker --location europe-west1 --labels workshop=deploy-agents` | GA | live | — |
| `gcloud builds submit . --config mcp_servers/cloudbuild.yaml --substitutions _IMAGE=... --region europe-west1 --gcs-source-staging-dir gs://PROJECT_cloudbuild/workshop-source` | GA | live | — |
| `gcloud run deploy NAME --image IMAGE --no-allow-unauthenticated --set-env-vars MCP_SERVER=... --cpu 1 --memory 512Mi --min-instances 0 --max-instances 1 --concurrency 40` | GA | live, --help | [gcloud run deploy](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy), [Host MCP servers on Cloud Run](https://docs.cloud.google.com/run/docs/host-mcp-servers) |
| FastMCP streamable HTTP, `stateless_http`, path `/mcp`; health route `/health` (Cloud Run reserves `/healthz`) | GA | live, unit tests | [ADK MCP tools](https://adk.dev/tools-custom/mcp-tools/) |
| `gcloud agent-registry services create NAME --location europe-west1 --display-name ... --mcp-server-spec-type tool-spec --mcp-server-spec-content "$(cat infra/gateway/toolspecs/SERVER.json)" --interfaces url=URL/mcp,protocolBinding=jsonrpc` | GA track in gcloud | live, --help | [Register MCP servers](https://docs.cloud.google.com/agent-registry/register-mcp-servers), [gcloud reference](https://docs.cloud.google.com/sdk/gcloud/reference/agent-registry/services/create) |
| `gcloud agent-registry services create google-apis --endpoint-spec-type no-spec --interfaces protocolBinding=jsonrpc,url=https://HOST ...` (one interface per line of `infra/gateway/platform-endpoints.txt`, max 50) | GA track | live | [Register endpoints](https://docs.cloud.google.com/agent-registry/register-endpoints) |
| `gcloud agent-registry services update NAME --interfaces ...` (re-runs refresh URLs) | GA track | live | same |
| `gcloud logging metrics create NAME --config-from-file infra/monitoring/log-metrics/NAME.json` | GA | live | [Logs-based metrics](https://docs.cloud.google.com/logging/docs/logs-based-metrics) |
| `gcloud network-services agent-gateways import workplace-gw --source gateway.yaml --location europe-west1` (background job, about 3 min) | GA track (no Preview banner for Agent Runtime agents) | live | [Set up Agent Gateway](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/set-up-agent-gateway), [gcloud reference](https://docs.cloud.google.com/sdk/gcloud/reference/network-services/agent-gateways/import) |
| `gcloud service-extensions authz-extensions import workplace-iap --source infra/gateway/iap-authz-extension.yaml --location europe-west1` (`service: iap.googleapis.com`, `failOpen: false`, `metadata.iapPolicyVersion: "V2"`) | GA | live | [gcloud reference](https://docs.cloud.google.com/sdk/gcloud/reference/service-extensions/authz-extensions/import) |
| `gcloud network-security authz-policies import workplace-iap-policy --source ... --location europe-west1` (`REQUEST_AUTHZ`, `CUSTOM`, about 3.5 min) | GA | live | [gcloud reference](https://docs.cloud.google.com/sdk/gcloud/reference/network-security/authz-policies/import) |
| Gateway YAML fields `protocols: [MCP]`, `googleManaged.governedAccessPath: AGENT_TO_ANYWHERE`, `registries: [//agentregistry.googleapis.com/projects/P/locations/R]` | — | source (gcloud schema `networkservices/v1/AgentGateway.yaml`), unit test validates the files against the vendored schemas | — |

### Step 2: Deploy

| Command / API | Status | Verified how | Doc |
|---|---|---|---|
| `agents-cli deploy --project $PROJECT_ID --agent-identity --no-confirm-project` (first create 4:46; updates 2:30–3:20) | Agent Runtime GA; Agent Identity GA (2026-04-22) | live, --help | [agents-cli](https://github.com/google/agents-cli), [Agent Identity on Agent Runtime](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/agent-identity) |
| `.env` values are shipped as environment variables by `agents-cli deploy` | — | live, source (`deploy/agent_runtime.py`) | — |
| `GET https://europe-west1-aiplatform.googleapis.com/v1beta1/projects/P/locations/L/reasoningEngines/ID` → `spec.effectiveIdentity` (`agents.global.proj-NUMBER.system.id.goog/...`) | v1beta1 field | live | [Agent Identity overview](https://docs.cloud.google.com/iam/docs/agent-identity-overview) |
| `gcloud run services add-iam-policy-binding SERVICE --member principal://agents.global.proj-NUMBER.system.id.goog/resources/aiplatform/projects/NUMBER/locations/L/reasoningEngines/ID --role roles/run.invoker --condition None` | GA | live (works in an org-less project; about 2 min to propagate) | [Authenticate as the agent's own identity](https://docs.cloud.google.com/iam/docs/auth-agent-own-identity) |
| `google.oauth2.id_token.fetch_id_token(Request(), audience, bind_id_token=False)` from Agent Runtime, audience = `https://SERVICE-....run.app` | — | live, source (google-auth 2.62.0) | [Authenticate agents (Cloud Run, Preview banner)](https://docs.cloud.google.com/run/docs/ai/authenticate-agents) |
| ADK `McpToolset(connection_params=StreamableHTTPConnectionParams(url, timeout=20), tool_filter=[...], header_provider=...)` | — | live, source | [ADK MCP tools](https://adk.dev/tools-custom/mcp-tools/) |
| `agents-cli run --url "$(./scripts/agent_url.sh)" --mode adk "PROMPT"` (URL `https://L-aiplatform.googleapis.com/v1/projects/NUMBER/locations/L/reasoningEngines/ID`) | — | live, --help | [Use an ADK agent](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-adk-agent) |
| REST `POST .../reasoningEngines/ID:query` `{"class_method":"async_create_session","input":{"user_id":...}}` and `POST ...:streamQuery?alt=sse` `{"class_method":"async_stream_query",...}` (`scripts/ask.py`) | v1 | live | [Use an ADK agent](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-adk-agent), [runtime contract](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/runtime-contract) |
| Console playground: Agent Platform → Agents → Deployments → the runtime → Playground | GA | live | [Use an agent](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-agent) |
| `agents-cli publish gemini [--agent-runtime-id ...] [--gemini-app-id projects/NUM/locations/LOC/collections/COLL/engines/ID] [--registration-type adk\|a2a] [--list]` | GA (needs a Gemini Enterprise app and the Discovery Engine API) | --help only; `--list` returned HTTP 403 because `discoveryengine.googleapis.com` is not enabled in the test project. Not published (no Gemini Enterprise app). | [Register an ADK agent](https://docs.cloud.google.com/gemini/enterprise/docs/register-and-manage-an-adk-agent) |

### Step 3: Remember

| Command / API | Status | Verified how | Doc |
|---|---|---|---|
| Sessions: `VertexAiSessionService` wired by the template when `GOOGLE_CLOUD_AGENT_ENGINE_ID` is set (Agent Runtime sets it) | Launch stage not re-verified; billed since 2026-09-01 | live, source | [Use an ADK agent](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-adk-agent) |
| `google.adk.memory.VertexAiMemoryBankService` registered as the runner's memory service (`app/app_utils/services.py`) | same | live, source | [Memory Bank setup](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/setup) |
| `VertexAiMemoryBankService.add_events_to_memory(..., events=this_invocation_events, custom_metadata={"wait_for_completion": False})` from a `BasePlugin.after_run_callback` (`app/memory.py`) | — | live (memories appear 1–2 min after the turn), source | same |
| `google.adk.tools.preload_memory_tool.PreloadMemoryTool()` on each sub-agent | — | live (recall in a new session) | same |
| `agentplatform.Client(...).runtimes.update(name=..., config={"context_spec": {"memory_bank_config": ...}})` (`scripts/memory_bank.py configure`; topics `team_and_office`, `work_preferences`, managed `EXPLICIT_INSTRUCTIONS`) | — | live (returns in seconds, no rebuild) | same |
| `client.memory_banks.memories.retrieve(name=..., scope={"app_name": "app", "user_id": USER_ID})`; `.delete(name=...)` (`scripts/memory_bank.py list\|clear`) | — | live; the scope must match exactly (`cli-user` for `agents-cli run`) | [Fetch memories](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/fetch-memories) |

### Step 4: Secure

| Command / API | Status | Verified how | Doc |
|---|---|---|---|
| `gcloud agent-registry mcp-servers list --location europe-west1 --format=json` and `gcloud agent-registry endpoints list ...` (to read registry IDs for the policy) | GA track | live, --help | [Register MCP servers](https://docs.cloud.google.com/agent-registry/register-mcp-servers) |
| `gcloud iam access-policies create\|update workplace-egress --location global --details-rules RULES.json` (rules in `infra/gateway/egress-policy.rules.json`) | GA track in gcloud 590; launch stage not re-verified | live, --help | [Configure IAM policies (UAP)](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/configure-iam-policies-uap), [gcloud reference](https://docs.cloud.google.com/sdk/gcloud/reference/iam/access-policies/create) |
| Rule permission `iap.googleapis.com/resources.egressViaIAP`; CEL `destination.agent_registry.resource_type`, `.endpoint.name`, `.mcp_server.name` | — | live | [CEL attributes (UAP)](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/cel-attributes-uap) |
| `gcloud iam policy-bindings create workplace-egress-binding --location global --policy projects/P/locations/global/accessPolicies/workplace-egress --target-resource //cloudresourcemanager.googleapis.com/projects/NUMBER` | GA track | live | [gcloud reference](https://docs.cloud.google.com/sdk/gcloud/reference/iam/policy-bindings/create) |
| `gcloud projects add-iam-policy-binding P --member principal://... --role roles/agentregistry.viewer` (agents behind a gateway read the registry) | GA | live | [Deploy with Agent Gateway](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/agent-gateway-runtime-deploy) |
| `agents-cli deploy --project P --update-only --agent-identity --no-confirm-project --agent-gateway-egress=projects/P/locations/europe-west1/agentGateways/workplace-gw --update-env-vars GOOGLE_API_ENABLE_RUNTIME_BOUND_TOKEN=false` (4:39) | GA track | live, --help | same |
| `agents-cli deploy --agent-gateway-ingress=projects/P/locations/R/agentGateways/G` (ingress mode, described in the guide only) | — | --help only | [Set up Agent Gateway](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/set-up-agent-gateway) |
| Gateway request logs: `resource.type="networkservices.googleapis.com/Gateway"`, `jsonPayload.authzPolicyInfo.result` (`ALLOWED`/`DENIED`), `jsonPayload.enforcedGatewaySecurityPolicy.hostname`, `jsonPayload.agentGatewayInfo.agentRegistryResource`, `jsonPayload.mcpInfo.method` | — | live | [Monitor Agent Gateway](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/monitor-agent-gateway) |
| Denial as the agent sees it: HTTP 403 `Egress request is not authorized.` (498 is also documented) | — | live | [Troubleshoot Agent Gateway](https://docs.cloud.google.com/gemini-enterprise-agent-platform/troubleshooting/troubleshoot-agent-gateway) |
| MCP tool annotations: `ToolAnnotations(read_only_hint=True)` on HRIS read tools; V2 CEL `destination.agent_registry.mcp_server.tool.annotations.read_only_hint`; V1 `api.getAttribute('iap.googleapis.com/mcp.tool.isReadOnly', false)` | — | annotations: unit tests. CEL attributes: docs only; the lab's rules are per server, so whether the gateway reads annotations from a manually registered tool spec is **not verified** | [CEL attributes (UAP)](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/cel-attributes-uap) |
| `scripts/fallback_step4.sh`: `gcloud run services remove-iam-policy-binding compensation-mcp --member principal://... --role roles/run.invoker --condition None` (`--undo` adds it back) | GA | --help; **not re-verified** as a full fallback run | [Cloud Run troubleshooting](https://docs.cloud.google.com/run/docs/troubleshooting) |
| Optional Calendar 3LO: `gcloud agent-identity auth-providers create calendar-3lo --location=europe-west1 --three-legged-oauth-client-id=... --three-legged-oauth-client-secret=... --three-legged-oauth-authorization-url=https://accounts.google.com/o/oauth2/v2/auth --three-legged-oauth-token-url=https://oauth2.googleapis.com/token`; also `describe`, `add-iam-policy-binding`, `delete` | Auth Manager GA (2026-08-22); the ADK page still says Preview | provider lifecycle: live. Redirect URL format `https://agentidentitycredentials.googleapis.com/v1/projects/P/locations/L/authProviders/NAME/oauthcallback`: live. End-to-end consent and event creation: **not verified** (needs an OAuth client and a consenting user). | [Auth Manager](https://docs.cloud.google.com/iam/docs/auth-manager-overview), [3LO](https://docs.cloud.google.com/iam/docs/auth-with-3lo-v2), [manage providers](https://docs.cloud.google.com/iam/docs/manage-auth-providers-v2), [gcloud reference](https://docs.cloud.google.com/sdk/gcloud/reference/agent-identity/auth-providers/create) |
| ADK `AuthenticatedFunctionTool` + `google.adk.integrations.agent_identity.GcpAuthProvider` / `GcpAuthProviderScheme` (`app/tools/calendar.py`, only when `CALENDAR_AUTH_PROVIDER` is set) | ADK marks pluggable auth experimental | source (classes import in ADK 2.12.0) | [ADK Agent Identity](https://adk.dev/integrations/agent-identity/) |
| Optional: `gcloud beta ai semantic-governance-policies create --agent ... --display-name ... --natural-language-constraint ...` | **Preview** | --help only. Not created: it needs a per-region engine and gateway VPC connectivity, and it only gates tool calls the model proposes, not the text answer. | [Semantic governance](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/semantic-governance-overview), [gcloud reference](https://docs.cloud.google.com/sdk/gcloud/reference/beta/ai/semantic-governance-policies/create) |
| Optional: Model Armor templates on the gateway | GA | --help only; not created. EU calls need `CLOUDSDK_API_ENDPOINT_OVERRIDES_MODELARMOR=https://modelarmor.europe-west1.rep.googleapis.com/` (live: without it `templates list` returned PERMISSION_DENIED). On egress it screens MCP `tools/call`, not Gemini `generateContent`. | [Model Armor with Agent Gateway](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/configure-model-armor) |

### Step 5: Observe

| Command / API | Status | Verified how | Doc |
|---|---|---|---|
| Telemetry env set by agents-cli: `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true`; the repo adds `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`, `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY`, `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=true` via `.env` | GA | live (env read back from the deployed engine), source | [Tracing](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/tracing), [ADK Cloud Trace](https://adk.dev/integrations/cloud-trace/) |
| Span names in one turn: `invoke_workflow concierge` → `invoke_agent <agent>` → `call_llm` → `generate_content <model>`, and `execute_tool <tool>` | ADK says the span format is experimental | live | [Traces](https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/observability/traces) |
| Cloud Trace v1 REST `GET https://cloudtrace.googleapis.com/v1/projects/P/traces?filter=...&view=COMPLETE` and `.../traces/TRACE_ID` (`scripts/trace.py`) | GA | live | [projects.traces.list](https://docs.cloud.google.com/trace/docs/reference/v1/rest/v1/projects.traces/list) |
| Structured logs: an OTel `LogRecord` with `event.name=workplace.tool_blocked` (`app/audit.py`) and a `LoggingHandler` bridge for Python warnings (`app/fast_api_app.py`) | — | live | [Logging](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/logging) |
| `gcloud logging read 'labels."event.name"="workplace.tool_blocked"' ...` and the gateway `DENIED` query shown on the step 4 page | GA | live | same |
| `gcloud monitoring dashboards create --config-from-file infra/monitoring/dashboard.json` (PromQL on `gen_ai.invoke_workflow.duration`, logs-based metrics `workplace_tool_blocked`, `workplace_gateway_denied`) | GA | live (created; list and delete also used) | [Monitoring](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/monitoring), [gcloud reference](https://docs.cloud.google.com/sdk/gcloud/reference/monitoring/dashboards/create) |

### Step 6: Evaluate

| Command / API | Status | Verified how | Doc |
|---|---|---|---|
| `agents-cli eval run --dataset evals/datasets/SUITE.json --config evals/eval_config*.yaml --output artifacts/eval/SUITE --project P` (agent runs locally against local MCP servers) | GA (evaluation GA 2026-07-31) | live; behaviour suite 1.0 on every metric; handbook suite grounding 1.0 on 4 of 5 cases at the time | [ADK evaluate](https://adk.dev/evaluate/), [agents-cli](https://github.com/google/agents-cli) |
| Metrics: built-in `grounding_v1` (needs `context` on each case); `custom_function_file` metrics `routed_to_expected_agent`, `tool_trajectory`, `no_compensation_leak` (`evals/metrics/*.py`) | — | live, source (`agentplatform/_genai/_evals_metric_handlers.py`) | same |
| `evals/gate.py SUITE RESULTS_DIR` fails on a below-threshold metric, an errored case, or a missing case (thresholds in `evals/thresholds.yaml`) | — | unit tests, live | — |
| Online monitor: `POST https://europe-west1-aiplatform.googleapis.com/v1beta1/projects/P/locations/europe-west1/onlineEvaluators` with `agentResource`, `cloudObservability: {traceScope: {}, openTelemetry: {}}`, `metricSources[].metric.predefinedMetricSpec.metricSpecName` in `final_response_quality_v1, tool_use_quality_v1, hallucination_v1, safety_v1`, `config.randomSampling.percentage`, `config.maxEvaluatedSamplesPerRun` (`scripts/monitor.sh`) | Feature GA; API v1beta1 | live: created and reached `ACTIVE`; runs about every 10 min | [Evaluate online](https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-online) |
| `gcloud projects add-iam-policy-binding P --member serviceAccount:service-NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com --role roles/observability.viewAccessor` | GA | live (without it the monitor goes to `FAILED`) | same |
| Monitor results: log `aiplatform.googleapis.com/online_evaluator` (resource `aiplatform.googleapis.com/OnlineEvaluator`; scores as `labels."gen_ai.evaluation.name"` / `labels."gen_ai.evaluation.score.value"`, event `gen_ai.evaluation.result`), metric `aiplatform.googleapis.com/online_evaluator/scores`, per-trace Evaluation tab in the console | — | live: single-agent turns scored after the span-capture fix; multi-agent turns skipped (section 4). `scripts/dev/record_monitor_results.py` turns the log into the fallback's recording. | same |
| Console path for monitors: Agent Platform → Optimize → Evaluation → Online monitors → New monitor (3-step wizard) | GA | live | same |
| `scripts/session_to_eval_case.py SESSION_ID --id NAME`: `:query` with `async_get_session`, then appends a case to `evals/cases.yaml` | — | **not re-verified** in this pass (uses the same `:query` API as `scripts/ask.py`) | [Use an ADK agent](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-adk-agent) |
| `scripts/score_live.sh`: Sessions REST `GET .../reasoningEngines/ID/sessions?orderBy=update_time desc` and `.../sessions/SID/events`, one eval case per turn in the `agents-cli eval generate` format (`agent_data.agents` from ADK `get_agents_dict`, instruction providers rendered), then `agents-cli eval grade --traces artifacts/live/traces.json --config <filled-in evals/eval_config.live.yaml> --qps 2` | — | live: 20 of 20 turns graded on all four metrics in about a minute, multi-agent turns included | [Evaluate agents](https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-agents), [Use an ADK agent (sessions)](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-adk-agent) |
| Custom LLM judge in an agents-cli eval config: `custom_metrics[].judge_model` + `prompt_template` with `{agent_data}`, `{prompt}`, `{response}`; the judge answers JSON `{"score", "explanation"}` | — | live. `judge_model` must be a full resource name (`projects/P/locations/global/publishers/google/models/gemini-3.5-flash`); `gemini-3.5-flash` alone, `publishers/...` and `projects/-/...` were rejected. `{agent_data}` gives the judge every agent's instruction and tools and every event of the turn | [Configure a judge model](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/evaluate-judge-model) |
| `scripts/fallback_step6.sh` (local eval plus recorded monitor results) | — | **not re-verified** | — |

### Alternative targets

| Command | Status | Verified how | Doc |
|---|---|---|---|
| `agents-cli scaffold enhance . --deployment-target cloud_run --no-agent-gateway -n workplace-assistant --yes --skip-checks` (produced branch `alt/cloud-run`) | GA | live (generation); the branch passes lint and unit tests. A Cloud Run deploy of that branch was **not run**. | [agents-cli](https://github.com/google/agents-cli) |
| `agents-cli deploy --iap` (Cloud Run only) | — | --help only | — |
| `gcloud beta run deploy --functional-type=mcp-server\|agent --identity-type=agent-identity` | **Preview**, beta track only (GA `gcloud run deploy` has no such flag) | --help | [Agent Platform features on Cloud Run](https://docs.cloud.google.com/run/docs/ai/agent-platform-features) |
| `agents-cli scaffold enhance . --deployment-target gke` | — | --help only | [agents-cli](https://github.com/google/agents-cli) |
| Retrieval upgrade path: ADK `VertexAiRagRetrieval`, `VertexAiSearchTool` | — | source (classes import in ADK 2.12.0); not run | [ADK](https://adk.dev/) |

### Teardown

| Command / API | Verified how |
|---|---|
| `DELETE https://europe-west1-aiplatform.googleapis.com/v1beta1/projects/P/locations/L/reasoningEngines/ID?force=true` (deletes sessions and memories too) | **not re-verified** as part of a full teardown run |
| `DELETE .../onlineEvaluators/ID` | not re-verified |
| `gcloud iam policy-bindings delete`, `gcloud iam access-policies delete` (retried until the binding is gone), `gcloud network-security authz-policies delete`, `gcloud service-extensions authz-extensions delete`, `gcloud network-services agent-gateways delete`, `gcloud agent-registry services delete`, `gcloud run services delete`, `gcloud artifacts repositories delete`, `gcloud storage rm -r gs://P_cloudbuild/workshop-source`, `gcloud logging metrics delete`, `gcloud monitoring dashboards delete`, `gcloud agent-identity auth-providers delete` | --help; auth-provider delete live. Full `scripts/teardown.sh` run **pending** (see `docs/DRY_RUN.md`). |
| `gcloud projects remove-iam-policy-binding` for the project roles agents-cli granted the agent identity on first deploy | --help |
| `scripts/teardown.sh --verify-only` lists every resource type above and fails if any remain | not re-verified |

## 4. Assumptions that turned out different

| Assumed | Reality | Where it matters |
|---|---|---|
| `agents-cli publish gemini-enterprise` | The subcommand is `agents-cli publish gemini`. `gemini-enterprise` still works as a hidden alias and does not appear in `--help`. | Step 2 page, slides |
| `gcloud ai reasoning-engines ...` to inspect an agent | No such group in gcloud 590 (GA, beta or alpha). Use REST `GET .../v1beta1/.../reasoningEngines/ID`. | `scripts/grant_agent_access.sh`, `scripts/check.sh` |
| `identity_type=AGENT_IDENTITY` set by hand | `agents-cli deploy --agent-identity` sets it. The resulting principal is read from `spec.effectiveIdentity`. In an org-less project the trust domain is `agents.global.proj-NUMBER.system.id.goog`, not `org-...`. | Step 2 |
| Agent Identity tokens work for Cloud Run as-is | `fetch_id_token` must be called with `bind_id_token=False` (google-auth ≥ 2.62). | `app/identity.py` |
| `gcloud network-services agent-gateways create` | There is no `create`. Gateways are created with `import --source FILE`. | `scripts/setup.sh` |
| Gateway allows Google APIs by default | Default deny covers platform APIs too. The model, telemetry, logging and Sessions/Memory Bank hosts are registered as one `google-apis` endpoint and allowed by a policy rule. | `infra/gateway/platform-endpoints.txt` |
| Policy binding target by project ID | The binding target must be `//cloudresourcemanager.googleapis.com/projects/NUMBER`. A binding to the project ID is accepted but never applied, and every call is then denied. | `scripts/secure.sh` |
| Registry names in policy conditions match the gateway logs | Gateway logs show `projects/NUMBER/...`, but CEL conditions only matched the `projects/PROJECT_ID/...` form. | `scripts/secure.sh` |
| One rule can combine endpoint and MCP server conditions | A rule mixing `endpoint.name` and `mcp_server.name` never matched. Use one rule per `resource_type`. | `infra/gateway/egress-policy.rules.json` |
| Google API calls pass through the gateway unchanged | The gateway intercepts TLS, so certificate-bound tokens fail with 401. Set `GOOGLE_API_ENABLE_RUNTIME_BOUND_TOKEN=false` (the docs sample uses the older name `GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES`). | Step 4 deploy command |
| A DENY rule on the compensation server stops `initialize` | MCP `initialize` and notifications are base-protocol methods and always pass. `tools/list` and `tools/call` are evaluated. The agent sees the refusal on `tools/list`. | `app/tools/mcp_toolsets.py` |
| The MCP client reports the HTTP status of a refused `tools/list` | It surfaces a generic `MCPError -32603`. The repo repeats `tools/list` with httpx to read the real status and body (`diagnose()`). | `app/tools/mcp_toolsets.py` |
| Policy changes are instant | 1–3 min to propagate; allow and deny can be mixed while settling. | Step 4 timing, `check.sh 4` retries |
| Cold starts behave like the first start | The template's `CMD ["uv", "run", ...]` re-synced the project at every start and fetched `hatchling` from PyPI. The deploy-time start reached PyPI; later cold starts went through the gateway, PyPI was denied, and `:query` returned 400 `FAILED_PRECONDITION ... Service Unavailable`. Fixed with `uv run --no-sync`. The instance had scaled to zero after less than an hour idle. | `Dockerfile`, unit test `test_container_starts_without_network` |
| stdout and Python logging show up in Cloud Logging | On Agent Runtime only OTel log records reached Cloud Logging at runtime (stdout appears during startup only). The repo bridges warnings through an OTel `LoggingHandler`. | `app/fast_api_app.py`, `app/audit.py` |
| agents-cli deploys with content capture on | It sets `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT` and `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false` unless `.env` overrides them. | `.env` written by `scripts/setup.sh` |
| Online monitors only need the two OTel variables from the docs | With only those, every trace failed with `INSUFFICIENT_DATA: system_instruction not present in any call_llm span`. The monitor reads the agent's instructions and tools from the ADK `call_llm` span (`gcp.vertex.agent.llm_request`), which needs `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=true`. Setting it is not enough on Agent Runtime: `agentplatform`'s `AdkApp.set_up()` overwrites it with `false` unless the app was built with `enable_tracing=True`, so `app/app_utils/reasoning_engine_adapter.py` restores the deployed value after `set_up()`. That puts prompts in Cloud Trace: a data-governance decision for a customer. | `scripts/setup.sh`, `app/app_utils/reasoning_engine_adapter.py`, step 6 |
| Online monitors score every trace of a multi-agent app | A trace where the root agent transfers to a sub-agent has a different system instruction per `call_llm` span; the monitor skips the whole trace with `INSUFFICIENT_DATA: system_instruction is not uniform across call_llm spans` (not in the docs as of 2026-10-22). Only single-agent turns get scores, so in this lab the turns that call tools are never scored. | Step 6, `evals/recorded/online-monitor-results.json` |
| Any predefined metric can go on a monitor | Create accepted only `final_response_quality_v1`, `tool_use_quality_v1`, `hallucination_v1` and `safety_v1` (the console's four). `*_v2`, `safety_v3`, `general_quality_v1`, `instruction_following_v1`, `text_quality_v1` and `grounding_v1` each returned a bare `INVALID_ARGUMENT`. `tool_use_quality_v1` reports `EVALUATION_ERROR` on traces without tool calls. | `scripts/monitor.sh` |
| The built-in judges have capacity | The evaluation service's default judge is Gemini 2.5 Flash, and one metric fans out into several judge calls. On shared pay-as-you-go capacity, priority follows the organization's 30-day spend, and the baseline applies to the `global` endpoint only. In this low-spend, org-less test project 60–94% of the monitor's judge calls (regional endpoint) and most built-in-judge calls from `agents-cli eval grade` returned `429 Judge model resource exhausted`; the same error is reported, unanswered, on the Google developer forum (Jan 2026). Our own judges on Gemini 3.5 Flash (`global`) graded every case. | `evals/eval_config.live.yaml`, step 6 ([quotas](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/quotas), [Standard PayGo](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/dynamic-shared-quota)) |
| `us-central1` would grade more reliably | Same test traffic in `us-central1`: same multi-agent skip, and every grading call failed with the same 429. | Region choice |
| Online monitors have a CLI | No gcloud or agents-cli command. REST v1beta1 `onlineEvaluators`. Setting `cloudObservability.openTelemetry.semconvVersion` gave `INVALID_ARGUMENT`; the console's body leaves it empty. The `:activate` route returned 404. The Vertex AI service agent needs `roles/observability.viewAccessor` or the monitor goes to `FAILED`. | `scripts/monitor.sh` |
| `agents-cli eval run` can gate a deploy | No threshold option, and it exits 0 whatever the scores. A failed case can be dropped silently. `evals/gate.py` checks thresholds, errors and the case count. | `scripts/eval.sh` |
| Eval and CLI runs carry a real user | `agents-cli run` always sends user id `cli-user`, `agents-cli eval` sends `eval-cli-user`. The app maps these fixed ids to `DEMO_USER_EMAIL` (opt-in). | `app/identity.py` |
| A production session can be turned into an eval case with agents-cli | No command does that. `scripts/session_to_eval_case.py` fetches the session and appends a case. | Step 6 |
| `scaffold enhance --deployment-target cloud_run` keeps the gateway | It refuses `--agent-gateway` for Cloud Run; use `--no-agent-gateway`. The generated `uvicorn~=0.34` pin also conflicts with FastMCP 4.1.3 (needs 0.35+). | `alt/cloud-run` |
| `agents-cli deploy --project P` runs unattended | It still asks to confirm the project unless `--no-confirm-project` is passed. | Step 2 and 4 commands |
| Model on the `eu` endpoint keeps everything in the EU | The `eu` mTLS host does not resolve, so the model runs on `global`. Data at rest stays in `europe-west1`. | `app/config.py` |
| Memory Bank default extraction model is fine | It timed out under load on the EU endpoint. Pinned to `eu` `gemini-3.8-flash`. | `infra/memory/memory-bank.json` |
| Grounding metric is called `grounding` | The built-in result name is `grounding_v1`; with only the retrieved passage as context it marked correct answers ungrounded, so each case gets the whole handbook as context. | `evals/eval_config.handbook.yaml`, `evals/build_datasets.py` |
| Startup tool listing is authenticated | The A2A agent card build lists MCP tools with no request context, so no ID token is sent and Cloud Run answers 403 at startup. Harmless: per-request listing sends the token. | Logs at startup |
| Cloud Run health path `/healthz` | Cloud Run reserves `/healthz`; the MCP servers use `/health`. | `mcp_servers/common` |

## 5. Preview and allowlist

No allowlist was needed for anything the lab runs. Preview items and what the repo ships
instead:

| Feature | Status | In the lab | Fallback |
|---|---|---|---|
| Semantic governance policies | Preview | Optional, described on the step 4 page | IAM deny rule on the compensation server (the lab's default) |
| Agent Gateway for Cloud Run and GKE agents | Preview sign-up | Not used (Agent Runtime only) | Cloud Run IAM / IAP on the `alt/cloud-run` branch |
| Agent Identity for Cloud Run-hosted agents, `gcloud beta run deploy --functional-type/--identity-type` | Preview, beta track | Not used | Service account identity (`docs/CLOUD_RUN.md` on `alt/cloud-run`) |
| Auth Manager in the ADK docs | GA per IAM release notes (2026-08-22); the ADK page still says Preview, and ADK flags pluggable auth as experimental | Optional Calendar 3LO | The lab works without it |
| Legacy IAM connectors API (`gcloud alpha agent-identity connectors`) | Preview, will not go GA | Not used | `authProviders` |
| Online monitors | GA feature, v1beta1 API, no CLI | `scripts/monitor.sh` | Console steps on the step 6 page; `scripts/fallback_step6.sh` |
| Agent Gateway with egress IAM (step 4) | GA track, can be slow to create (about 7 min total) | `scripts/setup.sh` starts it in the background | `scripts/fallback_step4.sh` (remove `roles/run.invoker` on compensation) |
| Gemini Enterprise publish | GA, but needs a Gemini Enterprise app and license | Optional | Console playground or `agents-cli run` |
