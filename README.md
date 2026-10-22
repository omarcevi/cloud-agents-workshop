# Deploying Your Agents on Google Cloud: workshop lab

Hands-on lab for **Google Cloud Day Türkiye, Builder Connect** (27 October 2026).
You deploy a multi-agent **Workplace Assistant** to **Agent Runtime** with its own
**Agent Identity**, give it **Memory Bank**, put **Agent Gateway** in front of its tool
calls, follow a request through **Cloud Trace**, and gate changes with **evals** and an
**Online Monitor**.

**Follow-along guide (start here):** https://omarcevi.dev/workshops/deploy-agents-workshop/

**Or follow it step by step inside Cloud Shell** (opens the repo with a guided tutorial panel). In the dialog, tick **Trust repo**, then **Confirm**; otherwise Cloud Shell runs in ephemeral mode and deletes your files when the session ends:

[![Open in Cloud Shell](https://gstatic.com/cloudssh/images/open-btn.svg)](https://shell.cloud.google.com/cloudshell/editor?cloudshell_git_repo=https://github.com/omarcevi/cloud-agents-workshop.git&cloudshell_git_branch=main&cloudshell_tutorial=tutorial.md&show=ide%2Cterminal)

Everything here is fictional: Kuzey Labs, its employees, handbook, salaries and tickets.

```
                         Gemini Enterprise (optional)  /  agents-cli run  /  console playground
                                                   │  query / streamQuery (IAM)
┌──────────────────────── Agent Runtime (europe-west1) ────────────────────────────────────┐
│ concierge ── routes, small talk, refuses out-of-scope                                    │
│ ├── hr_policy_agent → handbook_search (in-process BM25), compensation MCP (salary bands) │
│ ├── leave_agent     → HRIS MCP, Google Calendar (employee's own OAuth, optional)         │
│ └── it_desk_agent   → ticketing MCP                                                      │
│ Sessions · Memory Bank · Agent Identity (principal://agents.global.…) · OpenTelemetry    │
└───────────────┬──────────────────────────────────────────────────────────────────────────┘
                │ every outbound call (step 4)
        Agent Gateway (egress) ── IAP checks the IAM access policy against Agent Registry
                │
   ┌────────────┼─────────────────────┬──────────────────────────┐
   ▼            ▼                     ▼                          ▼
HRIS MCP    Ticketing MCP     Compensation MCP (denied)    Google APIs (Gemini, telemetry…)
Cloud Run, IAM-only ingress (roles/run.invoker for the agent identity)
```

## The lab (35–40 minutes)

| # | Step | You run | Proof (`./scripts/check.sh N`) | Branch |
|---|---|---|---|---|
| 1 | Set up | `./scripts/setup.sh` | APIs on, 3 Cloud Run services healthy | `step-1-setup` |
| 2 | Deploy | `agents-cli deploy --agent-identity …`, `./scripts/grant_agent_access.sh` | agent answers a handbook question | `step-2-deploy` |
| 3 | Remember | chat in two sessions, `scripts/memory_bank.py list` | Memory Bank has team and office | `step-3-remember` |
| 4 | Secure | `./scripts/secure.sh`, `agents-cli deploy --agent-gateway-egress …` | compensation denied and logged, HRIS works | `step-4-secure` |
| 5 | Observe | `./scripts/observe.sh` | trace with a sub-agent span and ≥ 2 tool spans | `step-5-observe` |
| 6 | Evaluate | `./scripts/eval.sh`, `./scripts/score_live.sh`, create an Online Monitor | eval passes thresholds, live traffic scored, monitor exists | `step-6-evaluate` |

Fallbacks when a preview feature is not available to you: `./scripts/fallback_step4.sh`
(Cloud Run IAM instead of Agent Gateway) and `./scripts/fallback_step6.sh` (local eval plus
recorded live-traffic scores). Clean up with `./scripts/teardown.sh`.

## Quick start (Cloud Shell)

```bash
git clone https://github.com/omarcevi/cloud-agents-workshop.git && cd cloud-agents-workshop
gcloud config set project YOUR_PROJECT_ID
uv tool install --force "google-agents-cli>=1.11"
export PATH="$HOME/.local/bin:$PATH"       # Cloud Shell has an older agents-cli in /usr/local/bin
./scripts/check.sh 0
./scripts/setup.sh && ./scripts/check.sh 1
```

Then follow the guide step by step. Each checkpoint branch (`step-0-start` … `step-6-evaluate`)
holds the repo as it should look after that step, plus a `.checkpoint` file so
`./scripts/check.sh` without an argument checks the right step.

## Repository layout

```
app/                  ADK agents (scaffolded with agents-cli 1.11, then customised)
  agent.py            concierge + three specialists
  tools/              handbook retrieval, MCP toolsets (with auth headers), optional calendar
  memory.py audit.py  Memory Bank plugin, audit log for refused tool calls
mcp_servers/          FastMCP servers: hris, ticketing, compensation (one image, three services)
                      (not `mcp/`: that name would shadow the `mcp` Python package)
data/handbook/        Kuzey Labs handbook (markdown)      data/seed/  fictional HR, IT and pay data
evals/                cases.yaml → datasets, metrics, thresholds, gate.py
infra/gateway/        Agent Gateway, IAP authorization, egress access policy, endpoint list, tool specs
infra/monitoring/     dashboard and logs-based metrics      infra/memory/  Memory Bank topics
scripts/              setup, check, teardown, fallbacks, and step helpers
tests/unit            no network: MCP tools, retrieval, routing with a scripted model, configs, shellcheck
tests/integration     real Gemini, local MCP servers (RUN_INTEGRATION=1)
tests/e2e             a real project, full lab plus teardown (RUN_E2E=1)
docs/                 VERIFIED.md (every command checked), DRY_RUN.md, INSTRUCTOR.md
```

## Develop locally

```bash
uv sync                                     # Python 3.12, installs dev tools too
uv run pytest                               # unit tests, no network
uv run ruff check . && uv run mypy          # lint and types
RUN_INTEGRATION=1 uv run pytest tests/integration   # needs gcloud auth application-default login
agents-cli playground                       # ADK web UI on localhost (in-memory sessions and memory)
```

Without `*_MCP_URL` in `.env` the agent expects local MCP servers on ports 8081–8083
(`PORT=8081 uv run python -m mcp_servers.hris.server`, and so on). With the Cloud Run URLs
from `setup.sh`, local runs call Cloud Run with your own identity token.

## Choosing a runtime

| | Agent Runtime | Cloud Run | GKE |
|---|---|---|---|
| What you run | Your agent code; Google runs the container | A container you own | Containers and a cluster you own |
| Sessions and memory | Built in (Sessions, Memory Bank) | Bring your own, or use Agent Platform Sessions/Memory Bank | Bring your own, or use Agent Platform Sessions/Memory Bank |
| Identity | Agent Identity per agent | Service account (Agent Identity in Preview) | Workload Identity |
| Gateway, Registry, Online Monitors | Integrated | Gateway for Cloud Run agents: Preview sign-up | Gateway for GKE agents: Preview sign-up |
| Scaling | Scale to zero, per-request billing | Scale to zero, full control of CPU, concurrency, networking | Anything Kubernetes can do |
| Pick it when | You want the platform to own operations (default) | You need custom serving, sidecars, or VPC egress control | You already run GKE or need GPUs, service mesh, multi-cloud |

**Cloud Run.** The `alt/cloud-run` branch is the same agent re-scaffolded with
`agents-cli scaffold enhance . --deployment-target cloud_run`, which adds the Cloud Run
Dockerfile and deploy settings; deploy with `agents-cli deploy` (it runs `gcloud run deploy`).
Sessions use Agent Platform Sessions through `SESSION_SERVICE_URI=agentengine://…`.

**GKE.** `agents-cli scaffold enhance . --deployment-target gke` adds Kubernetes manifests
and Terraform for a cluster; `agents-cli deploy` builds the image, applies Terraform and runs
`kubectl apply`. Use Workload Identity for the pod's service account and keep sessions and
memory in Agent Platform so the pods stay stateless.

## Upgrading retrieval

The handbook is six small markdown files, so `app/tools/handbook.py` uses in-process BM25:
no index to build, nothing to pay for, setup stays fast. For real document sets, swap the
tool for the **Agent Platform RAG Engine** (`VertexAiRagRetrieval` in ADK) or **Vertex AI
Search** (`VertexAiSearchTool`), and keep the same tool name so the eval set still applies.
agents-cli 1.11 ships retrieval as clone-and-study recipes rather than a scaffold flag
(`agents-cli data-ingestion` is removed): `rag-agent-search` (managed ingestion with
Vertex AI Search) and `rag-vector-search` (Vector Search with your own chunking), listed in
the agents-cli ADK skill's recipe index.

## Cost

A full run-through costs about **USD 0.30–1 per participant**, mostly Gemini tokens; Agent
Runtime, Cloud Run, Sessions, Memory Bank and observability stay inside free tiers or cost
cents at workshop scale. Details and measured numbers: [docs/DRY_RUN.md](docs/DRY_RUN.md).
Everything scales to zero; `./scripts/teardown.sh` removes it all.

## Security notes

- No secrets in git: `.env` is generated and ignored; use Secret Manager with
  `agents-cli deploy --secrets ENV=SECRET`. A gitleaks pre-commit hook guards commits
  (`uv run pre-commit install`).
- The employee identity (`user_id`) is asserted by whoever calls Agent Runtime. Only callers
  with IAM access can call it, and the MCP servers trust the agent's `X-User-Email` header.
  For production, see "Taking this to a customer" on the step 4 guide page.

Licensed under Apache 2.0. Scaffold files keep their Google copyright headers.
