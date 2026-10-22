# Dry run

## Run 2: Cloud Shell, following only the guide (2026-10-22, 11:08–11:48 UTC)

**Setup.** Real Cloud Shell (driven with `gcloud cloud-shell ssh --authorize-session`, so
every command ran on the Cloud Shell VM with its preinstalled tools), a fresh
`git clone https://github.com/omarcevi/cloud-agents-workshop.git`, project
`cloud-agents-project` in `europe-west1`, every command copied from the guide. The project
was not brand new: its APIs were already enabled by earlier runs (and stay enabled after
teardown), so a new project adds the first-time API enablement, about one to two minutes,
to step 1. Times are wall-clock command time; reading time is not included.

| Step | What ran | Command time | Result |
|---|---|---|---|
| 0–1 Set up | clone, `uv tool install --force "google-agents-cli>=1.11"`, `check.sh 0`, `setup.sh`, `check.sh 1` | 0:36 + 1:51 + 0:22 = **2:49** (gateway ready 6:00 after setup started, in the background) | pass, after fixing check 1 for Cloud Shell (below) |
| 2 Deploy | `agents-cli deploy --agent-identity`, `grant_agent_access.sh`, three `agents-cli run`, `check.sh 2` | 4:31 + 0:54 = **5:25** | pass. The salary question was refused once (IAM grant not applied yet) and answered on retry |
| 3 Remember | tell the agent, `memory_bank.py list`, two questions, `check.sh 3` | 0:43 + 0:20 = **1:03** (+ waiting for memories) | pass. Memories appeared about 30 s after the turn; listing straight away showed none |
| 4 Secure | `secure.sh`, gateway-binding deploy, two questions, logs, `check.sh 4` | 5:44 + 0:56 = **6:40** | pass: `gateway_denied` logged by the agent, `DENIED` in the gateway log, HRIS still answers |
| 4 fallback | `fallback_step4.sh`, salary question, `check.sh 4`, `--undo` | 2:25 (incl. waiting for IAM) | pass with reason `permission_denied`. The IAM removal took 1–3 minutes to apply |
| 5 Observe | leave request, `observe.sh`, `check.sh 5` | **1:18** (incl. a 45 s wait for spans) | pass, after changing the prompt (below). Waterfall: concierge → leave_agent → model → `get_leave_balance`, `submit_leave_request` → MCP |
| 6 Evaluate | `eval.sh`, `score_live.sh`, `monitor.sh`, regression loop, `check.sh 6` | 2:07 + 1:20 + 1:39 + 0:15 = **5:21** | pass. Gate: behaviour 1.0/1.0/1.0, handbook grounding 1.0. Live: 20 turns scored |
| 6 fallback | `fallback_step6.sh` | 0:54 | pass |
| Teardown | `teardown.sh --yes` | about 10 minutes (run 1: 10:06) | nothing left (`--verify-only` lists every resource type) |

**Total command time for steps 1–6: about 23 minutes**, of which about 10 are the two
deploys. With reading and typing, 35–40 minutes for a participant is realistic; the deploys
are where the instructor explains the next concept.

### Problems found and fixed in this run

| Problem | Fix |
|---|---|
| Cloud Shell ships agents-cli 1.3.1 in `/usr/local/bin`; `uv tool install` puts 1.11 in `~/.local/bin`, which is not on `PATH` in that session, so participants would run 1.3.1 | Guide and README: `uv tool install --force "google-agents-cli>=1.11"` and `export PATH="$HOME/.local/bin:$PATH"`. `check.sh 0` now fails on agents-cli older than 1.11 and on a gcloud without Agent Registry/Gateway |
| `gcloud auth print-identity-token` fails in Cloud Shell ("No identity token can be obtained from the current credentials"), so `check.sh 1` stopped | Check 1 skips the authenticated probe when no ID token is available; step 2 proves the agent gets through |
| Cloud Trace answered `429 Too Many Requests` to `trace.py`: Cloud Shell's credentials carry no quota project | The REST scripts send `x-goog-user-project` with the lab project |
| Check 5 found one tool span: with the office already in Memory Bank, the leave agent skipped `get_my_profile` | Step 5's prompt asks for the remaining balance too, so the trace always has two tool calls |
| `memory_bank.py list` said memories take "a few seconds" | Now "about a minute" |

### Found after the run

| Problem | Fix |
|---|---|
| `teardown.sh` left two IAM bindings: `roles/agentregistry.viewer` on deleted agents' identities (from `secure.sh`) and `roles/observability.viewAccessor` on the Vertex AI service agent (from `monitor.sh`). Not billable, but not "nothing left" | Teardown removes both, sweeps bindings of any agent identity whose instance no longer exists, and `--verify-only` checks for them |
| The guide's Open in Cloud Shell button had no `cloudshell_git_branch` (default `master`) | Button and README link name `main` and open `tutorial.md` with the repo as workspace |
| Two generated files (`.setup-dashboard.json`, `.setup-egress-rules.json`, with the test project's ID and number) were committed | Untracked; `.gitignore` covers `.setup-*` |

### Problems found and fixed before this run (rehearsal on 2026-10-22, run 1)

| Problem | Fix |
|---|---|
| Every cold start after the first failed behind Agent Gateway (`uv run` fetched `hatchling` from PyPI, which the gateway blocks): `:query` returned `400 ... Service Unavailable` once the agent had scaled to zero | `CMD ["uv", "run", "--no-sync", ...]`; unit test guards it |
| `scripts/lib/common.sh` was never committed (the scaffold's `.gitignore` ignored `lib/`) | `.gitignore` anchors `/lib/` |
| The managed Online Monitor scored nothing: ADK request content missing from `call_llm` spans | `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=true` in `.env`, kept by the reasoning-engine adapter because `AdkApp.set_up()` resets it |
| The managed monitor skips multi-agent turns, and its judge was rate-limited on most calls | Step 6 scores live traffic with `score_live.sh` (our judges on Gemini 3.5 Flash); the monitor is created and its limits explained |

### Rough edges left

- **IAM propagation.** New grants take 1–2 minutes (the first salary question in step 2 can
  be refused) and removals 1–3 minutes (`fallback_step4.sh`). The guide says to ask again.
- **Live-scoring judge on blocked tools.** When the gateway blocks the compensation server,
  the agent sees a placeholder tool without parameters and calls it with `{}`; the
  `tool_use` judge scores that turn 0. It makes a good discussion point: check why a turn
  scored low before turning it into a regression case.
- **Gateway log.** The `DENIED` entries for the compensation server had an empty
  `jsonPayload.mcpInfo.method`; the guide's sample shows `tools/list`.
- **`check.sh 4`** reads the agent's audit log for the last 30 minutes, so after the
  fallback it also lists the earlier `permission_denied` entries. It still requires the
  refusal itself.
- **agents-cli noise in Cloud Shell.** `agents-cli run` prints "Could not query installed
  skills via npx" (no Node.js) and sometimes "No project ID could be determined"; both are
  harmless.
- **Managed Online Monitor.** In this project it skipped multi-agent turns and most of its
  grading calls returned `429 Judge model resource exhausted` (shared capacity prioritised
  by organization spend). Do not promise its scores in the session.

### Quotas and limits touched

Cloud Build (one image build in setup, one per deploy), Agent Runtime (one reasoning
engine), Cloud Run (three services, `max-instances 1`), Gemini 3.5 Flash on `global`
(a few hundred calls over the run; the few 429s were absorbed by retries), the evaluation
service (judge calls from `score_live.sh` and `grounding_v1`). No quota increase was needed.

### Cost

The project has no billing export, so this is an estimate from usage: Gemini tokens for
a few hundred agent calls and about a hundred judge calls (roughly USD 0.50–1), Agent Runtime and
Cloud Run for under an hour of mostly idle, scale-to-zero instances (cents), one Cloud
Build image plus two agent builds (free tier), Cloud Trace and Logging (free tier). Expect
**about USD 1 per participant** for one run-through, plus Agent Gateway and IAP request
processing per the Agent Platform pricing page. Run the teardown at the end.
