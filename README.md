# Deploying your agents on Google Cloud Agent Platform: workshop lab

This repository is the hands-on lab for **Google Cloud Day Türkiye, Builder Connect**
(27 October 2026). You deploy a multi-agent **Workplace Assistant** to **Agent Runtime** with
its own **Agent Identity**. You give it **Memory Bank** and put **Agent Gateway** in front of
its tool calls. Then you follow a request in **Cloud Trace**. You use **evals** as a gate for
changes, and an **Online Monitor** gives scores to live traffic.

**Step-by-step guide (start here):** https://omarcevi.dev/workshops/cloud-agents-workshop/

**You can also do the lab in Cloud Shell, with a tutorial panel that shows each step.** In the dialog, select **Trust repo**, then click **Confirm**. If you do not select **Trust repo**, Cloud Shell runs in ephemeral mode and deletes your files at the end of the session. Click the button only one time, because each click makes one more copy (`cloud-agents-workshop-0`, ...):

[![Open in Cloud Shell](https://gstatic.com/cloudssh/images/open-btn.svg)](https://shell.cloud.google.com/cloudshell/editor?cloudshell_git_repo=https://github.com/omarcevi/cloud-agents-workshop.git&cloudshell_git_branch=main&cloudshell_tutorial=tutorial.md&cloudshell_workspace=.&show=ide%2Cterminal)

All data in this repository is fictional: Kuzey Labs, its employees, the handbook, the
salaries and the tickets.

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

If a preview feature is not available to you, use a fallback script.
`./scripts/fallback_step4.sh` uses Cloud Run IAM instead of Agent Gateway.
`./scripts/fallback_step6.sh` runs the local eval and shows recorded scores for live traffic.
To delete all the resources, run `./scripts/teardown.sh`.

## Quick start (Cloud Shell)

```bash
git clone https://github.com/omarcevi/cloud-agents-workshop.git && cd cloud-agents-workshop
gcloud config set project YOUR_PROJECT_ID
uv tool install --force "google-agents-cli>=1.11"
export PATH="$HOME/.local/bin:$PATH"       # Cloud Shell has an older agents-cli in /usr/local/bin
./scripts/check.sh 0
./scripts/setup.sh && ./scripts/check.sh 1
```

Then do the steps in the guide. Each checkpoint branch (`step-0-start` … `step-6-evaluate`)
contains the repository as it is after that step. It also contains a `.checkpoint` file, so
`./scripts/check.sh` without an argument checks the correct step.

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

If `.env` has no `*_MCP_URL` values, the agent uses local MCP servers on ports 8081–8083
(`PORT=8081 uv run python -m mcp_servers.hris.server`, and so on). If `.env` has the Cloud Run
URLs from `setup.sh`, local runs call Cloud Run with your own identity token.

## Runtime options

| | Agent Runtime | Cloud Run | GKE |
|---|---|---|---|
| What you run | Your agent code; Google runs the container | A container you own | Containers and a cluster you own |
| Sessions and memory | Built in (Sessions, Memory Bank) | Bring your own, or use Agent Platform Sessions/Memory Bank | Bring your own, or use Agent Platform Sessions/Memory Bank |
| Identity | Agent Identity per agent | Service account (Agent Identity in Preview) | Workload Identity |
| Gateway, Registry, Online Monitors | Integrated | Gateway for Cloud Run agents: Preview sign-up | Gateway for GKE agents: Preview sign-up |
| Scaling | Scale to zero, per-request billing | Scale to zero, full control of CPU, concurrency, networking | Anything Kubernetes can do |
| Pick it when | You want the platform to own operations (default) | You need custom serving, sidecars, or VPC egress control | You already run GKE or need GPUs, service mesh, multi-cloud |

**Cloud Run.** The `alt/cloud-run` branch is the same agent after
`agents-cli scaffold enhance . --deployment-target cloud_run`. This command adds the Cloud Run
Dockerfile and the deployment settings. To deploy, run `agents-cli deploy` (it runs
`gcloud run deploy`). Sessions use Agent Platform Sessions through
`SESSION_SERVICE_URI=agentengine://…`.

**GKE.** `agents-cli scaffold enhance . --deployment-target gke` adds Kubernetes manifests
and Terraform for a cluster. Then `agents-cli deploy` builds the image, applies the Terraform
and runs `kubectl apply`. Use Workload Identity for the service account of the pod. Keep
sessions and memory in Agent Platform, so that the pods have no state.

## Retrieval for larger document sets

The handbook is six small markdown files, so `app/tools/handbook.py` uses BM25 in the agent
process. There is no index to build and no cost, and the setup stays fast. For real document
sets, replace the tool with the **Agent Platform RAG Engine** (`VertexAiRagRetrieval` in ADK)
or **Vertex AI Search** (`VertexAiSearchTool`). Keep the same tool name, so that the eval set
still applies.

agents-cli 1.11 gives retrieval as recipes that you clone and study, not as a scaffold flag
(the command `agents-cli data-ingestion` no longer exists). The recipes are `rag-agent-search` (managed
ingestion with Vertex AI Search) and `rag-vector-search` (Vector Search with chunks that you
make). The recipe index of the agents-cli ADK skill lists them.

## Cost

A full run of the lab costs approximately **USD 1 per participant**, mostly for Gemini
tokens. Agent Runtime, Cloud Run, Sessions, Memory Bank and observability stay in the free
tiers, or cost cents at the scale of a workshop. For details and measured numbers, see
[docs/DRY_RUN.md](docs/DRY_RUN.md). All services scale to zero, and `./scripts/teardown.sh`
removes all the resources.

## Security notes

- Git contains no secrets. The setup script makes `.env`, and git ignores it. For secrets,
  use Secret Manager with `agents-cli deploy --secrets ENV=SECRET`. A gitleaks pre-commit
  hook examines each commit (`uv run pre-commit install`).
- The caller of Agent Runtime gives the employee identity (`user_id`). Only callers with IAM
  access can call Agent Runtime, and the MCP servers trust the `X-User-Email` header from the
  agent. For production, see "Take this to a customer" on the guide page for step 4.

The license is Apache 2.0. The scaffold files keep their Google copyright headers.
