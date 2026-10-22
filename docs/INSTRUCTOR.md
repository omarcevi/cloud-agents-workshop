# Instructor notes

For whoever runs the "Deploying Your Agents on Google Cloud" lab. Participant-facing
instructions live in the guide (omarcevi.dev/workshops/deploy-agents-workshop); this file
covers what happens around it. Timings and rough edges from the rehearsals are in
[DRY_RUN.md](DRY_RUN.md); every command and flag is traced to a doc in
[VERIFIED.md](VERIFIED.md).

## Shape of the session

| Clock | What | Notes |
|---|---|---|
| 0:00 | Slides (5–10 min) | Start participants on step 1 during the intro: `setup.sh` takes about 5 minutes and starts the gateway build in the background. |
| 0:08 | Steps 1–2 | The first deploy is the longest wait (about 5 min). Explain Agent Runtime while it runs. |
| 0:20 | Step 3 | Memories show up 1–2 min after a turn. Fill the gap with Sessions vs Memory Bank. |
| 0:27 | Step 4 | The redeploy that binds the gateway takes about 4–5 min. Demo moment 1. |
| 0:37 | Step 5 | Demo moment 2. |
| 0:44 | Step 6 | The online monitor scores every 10 minutes, so show your own monitor's results. |
| 0:52 | Runtime choice, production checklist, teardown | Remind everyone to run `./scripts/teardown.sh`. |

## Pre-event checklist

**Two weeks before**

- Run the whole lab from an empty project following only the guide (the e2e workflow does
  this too: Actions → E2E → Run workflow). Record step timings in DRY_RUN.md.
- Check the region still offers everything: Agent Runtime, Agent Identity, Memory Bank,
  Agent Gateway, Agent Registry and Cloud Run in `europe-west1`. If a feature moved, the
  fallback region is `us-central1` (set `REGION` before `setup.sh`).
- Check the model: `MODEL` defaults to `gemini-3.5-flash` on the `global` endpoint. During
  rehearsals `gemini-3.8-flash` on `global` ranged from 3 to 130 seconds per call (shared
  capacity), which breaks a live demo. Re-measure before switching.
- Re-read the release notes for Agent Gateway, Agent Identity and Online Monitors. Things
  the lab depends on that changed recently are listed in VERIFIED.md under "Assumptions that
  turned out different".
- Nothing in the core path needs an allowlist. Preview pieces are optional: the semantic
  governance policy (step 4) and Agent Identity on Cloud Run (the `alt/cloud-run` branch).

**One week before**

- Tell participants what to bring: a Google Cloud project with billing where they are
  Owner, and a browser signed in to that account (Cloud Shell). Free-trial credits work.
  Ask them to open Cloud Shell once beforehand; the first start takes a minute.
- Quotas to check in a fresh project (Console → IAM & Admin → Quotas):
  - Cloud Build concurrent builds (setup builds one image; each deploy builds one).
  - Agent Runtime: reasoning engines per region (the lab creates one).
  - Cloud Run: services per region (three).
  - Gemini on `global` uses dynamic shared quota; there is no per-project number to raise.
    A 429 during the event means regional capacity, not your project.
- If participants share one organization: org policies such as
  `iam.allowedPolicyMemberDomains` can block the `principal://` Agent Identity member, and
  `iam.managed.disableAccessPolicyBindings` blocks step 4. Test in a project under that org.

**The day before**

- Deploy your own copy to the end of step 6 in a demo project, and generate a few turns
  so the online monitor has scores to show (it runs every 10 minutes).
- Keep that deployment warm until the session: a request every 30 minutes, or just ask it
  something an hour before you start.
- Open these tabs: the guide, the repo, your agent's Traces tab, the dashboard, the online
  monitor, and the gateway logs query from step 4.
- Charge the laptop. A rehearsal deploy once failed because the machine went to sleep at
  1% battery mid-deploy.

**Wi-Fi fallback**

- Cloud Shell needs only a browser connection, but `git clone` and deploys need the venue
  network. If the network is slow, tell people to keep going in the guide: every step page
  shows the expected output, and checkpoint branches let them catch up.
- Have a phone hotspot for your own demo.
- If the network is down entirely, run the demo from your pre-deployed project and walk
  through the guide's expected output with the room.

## Demo moment 1: step 4, the policy blocks a tool call

Setup: your agent is bound to the gateway. Have the policy file and the logs query ready.

1. "Same code as before. The compensation tool is still wired in. Watch." Ask:
   `What is the salary band for an L5 in Istanbul?`
2. "The agent tried, the gateway said no. Nothing in the agent changed: the security
   team's policy did this." Show `infra/gateway/egress-policy.rules.json`, the deny rule.
3. Run the gateway logs query: "Here is the gateway's own record: who called, which MCP
   server, which method, DENIED. Your customer's security team reads this, not your code."
4. Ask `How many leave days do I have?` "HRIS still works. Allow and deny are per
   destination, and per tool if you want."
5. Line for partners: "When a customer asks how they stop an agent from doing X, the
   answer is a policy their security team owns, not a prompt you wrote."

If the denial doesn't show: the policy takes 1–3 minutes to apply after `secure.sh`. Show
the fallback (`./scripts/fallback_step4.sh`, IAM on the Cloud Run service) and explain the
difference: IAM can only say yes or no per service; the gateway sees MCP methods and tool
names, logs in one place, and covers every destination.

## Demo moment 2: step 5, one turn as a trace

1. Ask `Book next Monday off as a half day.` while the Trace Explorer tab is open.
2. "A minute later, the whole turn is here." Open the newest trace and read it top down:
   `invoke_workflow` → `invoke_agent concierge` → `invoke_agent leave_agent` →
   `generate_content` → `execute_tool get_my_profile` → `execute_tool submit_leave_request`.
3. "Tool calls take milliseconds. Model calls take seconds. That's where latency and
   cost go." Point at the widest bars.
4. Open the dashboard: "Requests, p50/p95 latency, tool errors, and the blocked calls from
   step 4, from a logs-based metric." The blocked-calls tile is the bridge back to step 4.
5. Line for partners: "Ask the customer where their traces should go before you build. If
   they have a SIEM or their own OpenTelemetry collector, that changes the setup, not the
   agent."

## Online monitors in a 60-minute session

The monitor runs about every 10 minutes and scores traces from after its creation, so a
participant who creates it at 0:45 might see the first scores after the session. Show
yours (created the day before). `fallback_step6.sh` prints pre-recorded results from
`evals/recorded/online-monitor-results.json` and marks step 6 as done with the fallback.

What it scores: only turns the concierge answers itself (greetings, refusals,
out-of-scope requests, salary questions). A turn with a hand-over to a sub-agent is skipped
as a whole (`INSUFFICIENT_DATA: system_instruction is not uniform across call_llm spans`),
so the day before, ask your demo agent a few salary and out-of-scope questions as well as
normal ones. Say this out loud in the session; it is the kind of gap partners need to
know about. Refresh the fallback's recording with
`uv run python scripts/dev/record_monitor_results.py`.

Two prerequisites, both handled by the scripts: the monitor needs prompt and answer
content in telemetry (`.env` sets the three variables; without
`ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=true`, kept by the reasoning-engine adapter because
`AdkApp.set_up()` resets it, every trace fails with `INSUFFICIENT_DATA`),
and the Agent Platform service agent needs `roles/observability.viewAccessor`
(`monitor.sh` grants it). Monitor errors are in Cloud Logging under
`logName:"aiplatform.googleapis.com%2Fonline_evaluator"`.

## Resetting between rehearsals

```bash
./scripts/teardown.sh --yes        # deletes everything the lab created, then lists leftovers
./scripts/teardown.sh --verify-only
git checkout main && git clean -fdx -e .venv   # drops .env, .workshop.env, artifacts/
```

`teardown.sh` removes the agent (and the project roles agents-cli granted to its
principal), online monitors, the access policy and binding, the gateway, its IAP
extension and authz policy, Agent Registry services, the three Cloud Run services, the
Artifact Registry repo, build sources, log metrics, the dashboard, and the optional Calendar
auth provider. APIs stay enabled (no cost). The gateway delete takes a few minutes. The
script waits and verifies.

To reset only the demo state without redeploying:

- Memories: `uv run python scripts/memory_bank.py clear` (Memory Bank is keyed by the ADK
  user id, `cli-user` for `agents-cli run`; pass `--user` for others)
- Leave requests and tickets: the MCP servers keep them in memory. A new revision
  (`./scripts/setup.sh --only services`) or a scale-to-zero resets them to the seed data.
- Step 4 fallback: `./scripts/fallback_step4.sh --undo`.

## Checkpoint branches

`step-0-start` … `step-6-evaluate` are generated from `main`, so a fix on main reaches all
of them:

```bash
git checkout main            # clean tree, all fixes committed
./scripts/dev/make_checkpoints.sh          # rebuilds the 7 branches, tags checkpoint/<branch>
git push --force-with-lease origin 'step-*' && git push --force origin 'refs/tags/checkpoint/*'
# or: ./scripts/dev/make_checkpoints.sh --push
```

Each branch is main plus a `.checkpoint` file (a bare `./scripts/check.sh` checks that step)
and, before step 6, without the eval case that step 6 adds (cases with `(lab step 6)` in
their note). CI runs on every `step-*` branch. Commits are unsigned unless
`CHECKPOINT_SIGN=true`.

`alt/cloud-run` is main plus one enhance commit; after changing main:
`git checkout alt/cloud-run && git rebase main` (regenerate `uv.lock` with `uv lock` if
dependencies changed), then push with `--force-with-lease`.

## End-to-end test

Run it locally against a test project (about 45 minutes, a dollar or two):

```bash
RUN_E2E=1 uv run pytest tests/e2e -v -s --maxfail=1    # timings in artifacts/e2e-timings.json
```

`.github/workflows/e2e.yml` runs the same test from GitHub Actions. It is not wired up in
this repository (no Workload Identity Federation is configured). To enable it:

```bash
./scripts/dev/setup_wif.sh TEST_PROJECT_ID omarcevi/cloud-agents-workshop --github
```

This creates a deployer service account with Owner on the test project and a Workload
Identity Federation provider that accepts only the E2E workflow on main, running in the
`e2e` environment. Create that environment with required reviewers (Settings →
Environments). Use a dedicated test project: the job can do anything in it.

## Known rough edges

- First query right after deploy can take 30–60 s (cold start, IAM propagation).
- Policy changes take 1–3 minutes to reach the gateway; mixed allow/deny while it settles.
- Memories appear 1–2 minutes after the turn that produced them.
- At startup the agent logs "Could not list tools on hris/ticketing (HTTP 403)": the A2A
  agent card is built without a user request, so no ID token is attached. Harmless.
- `agents-cli run` always sends user `cli-user`; `DEMO_USER_EMAIL` maps it to the demo
  employee. In Gemini Enterprise the real email arrives instead.
