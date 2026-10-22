<walkthrough-metadata>
  <meta name="title" content="Deploying Your Agents on Google Cloud" />
  <meta name="description" content="Deploy a multi-agent ADK app to Agent Runtime with Agent Identity, Memory Bank, Agent Gateway, tracing and evals." />
  <meta name="keywords" content="ADK, Agent Runtime, Agent Identity, Agent Gateway, Memory Bank, evaluation" />
</walkthrough-metadata>

# Deploying Your Agents on Google Cloud

## Welcome

You take the **Kuzey Labs Workplace Assistant** from this repo to production shape: a concierge
agent that hands HR questions, leave requests and IT problems to three specialist agents,
which call MCP tool servers on Cloud Run.

![Architecture](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/architecture.svg)

| Step | What you do |
|---|---|
| 1 Set up | APIs, three MCP servers, Agent Registry, the gateway building in the background |
| 2 Deploy | `agents-cli deploy` to Agent Runtime with Agent Identity |
| 3 Remember | Memory Bank recalls your team and office in a new session |
| 4 Secure | Agent Gateway blocks the compensation system by policy |
| 5 Observe | One leave request as a trace, and a dashboard |
| 6 Evaluate | Eval gate, scoring live traffic, an Online Monitor |

Each step explains what happens, gives the commands (click the copy button to paste one into
the terminal) and links to the console pages where you can see the result. The full
explanations, diagrams and troubleshooting are in the guide:
[omarcevi.dev/workshops/deploy-agents-workshop](https://omarcevi.dev/workshops/deploy-agents-workshop/).

Use the same terminal tab for the whole lab: later steps reuse variables you set earlier.

<walkthrough-tutorial-duration duration="40"></walkthrough-tutorial-duration>

## Select your project

Pick a project with billing enabled where you are Owner. All data in this lab is fictional.

<walkthrough-project-setup billing="true"></walkthrough-project-setup>

Point Cloud Shell at it:

```bash
gcloud config set project <walkthrough-project-id/>
```

&nbsp;

If Cloud Shell asks you to **Authorize** gcloud, click **Authorize**. The console links in
this tutorial open the project you selected here.

## Step 1 · Set up

### What's happening

`setup.sh` prepares everything the agent depends on:

- **Three MCP tool servers on Cloud Run:** the HRIS (leave balances, requests), ticketing and
  compensation systems of the fictional company. One container image is built with Cloud
  Build. The services accept only callers with IAM permission and scale to zero.
- **Agent Registry:** the servers, and the Google APIs the agent itself calls, are
  registered. Later the gateway refuses any destination that is not in the registry.
- **Agent Gateway:** it starts building in the background now and takes about 6 minutes;
  you use it in step 4.

![What setup.sh creates](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-1-setup.svg)

[Open the diagram full size](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-1-setup.svg)

### Run it

Cloud Shell has an older agents-cli in `/usr/local/bin`. Install 1.11 or later and put it
first on your `PATH`:

```bash
uv tool install --force "google-agents-cli>=1.11"
export PATH="$HOME/.local/bin:$PATH"
```

&nbsp;

Check tools, login and billing:

```bash
./scripts/check.sh 0
```

&nbsp;

Set up (about 2 minutes):

```bash
./scripts/setup.sh
```

&nbsp;

While it runs, read what it does:
<walkthrough-editor-open-file filePath="scripts/setup.sh">scripts/setup.sh</walkthrough-editor-open-file>.

### See it in the console

- [Cloud Run](https://console.cloud.google.com/run?project=<walkthrough-project-id/>):
  `hris-mcp`, `ticketing-mcp`, `compensation-mcp`, each marked *Require authentication*.
- [Agent Registry](https://console.cloud.google.com/agent-platform/agent-registry?project=<walkthrough-project-id/>):
  the three MCP servers and the Google APIs endpoint.
- [Cloud Build history](https://console.cloud.google.com/cloud-build/builds?project=<walkthrough-project-id/>):
  the MCP server image build.

### Check

```bash
./scripts/check.sh 1
```

&nbsp;

Troubleshooting: [Step 1 in the guide](https://omarcevi.dev/workshops/deploy-agents-workshop/step-1/).

## Step 2 · Deploy

### What's happening

`agents-cli deploy` packages the agent code
(<walkthrough-editor-open-file filePath="app/agent.py">app/agent.py</walkthrough-editor-open-file>
and the `Dockerfile`), builds a container and creates an **Agent Runtime** instance:

- **Serving:** it serves the agent's query and stream-query API, scales with traffic down
  to zero, keeps **Sessions** (each conversation's history) and exports traces.
- **Identity:** `--agent-identity` gives the agent its own **Agent Identity**, a principal
  of its own rather than a shared service account.
- **Access:** `grant_agent_access.sh` gives that identity *Cloud Run Invoker* on each MCP
  server. The agent calls the HRIS as itself, and Cloud Run checks the permission on every
  request.

![What agents-cli deploy does](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-2-deploy.svg)

[Open the diagram full size](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-2-deploy.svg)

### Run it

Deploy (about 5 minutes):

```bash
source .workshop.env
agents-cli deploy --project $PROJECT_ID --agent-identity --no-confirm-project
```

&nbsp;

Grant the agent's identity access to the MCP servers, and configure Memory Bank:

```bash
./scripts/grant_agent_access.sh
```

&nbsp;

Chat with it. IAM grants take a minute or two to apply: if an answer says a system is
unavailable, ask again.

```bash
AGENT_URL=$(./scripts/agent_url.sh)
agents-cli run --url "$AGENT_URL" --mode adk "How many unused leave days can I carry over?"
agents-cli run --url "$AGENT_URL" --mode adk "What is the salary band for an L5 in Istanbul?"
```

### See it in the console

- [Agent Runtime deployments](https://console.cloud.google.com/agent-platform/runtimes?project=<walkthrough-project-id/>):
  open **workplace-assistant**. The **Identity** tab shows its principal, the
  **Playground** tab lets you chat in the browser, and **Sessions** lists the
  conversations you just had.
- [Cloud Run](https://console.cloud.google.com/run?project=<walkthrough-project-id/>):
  select **hris-mcp** and open **Permissions**: the agent's principal has *Cloud Run Invoker*.

### Check

```bash
./scripts/check.sh 2
```

&nbsp;

Behind? `git checkout step-1-setup` gives you the state after step 1. Troubleshooting:
[Step 2 in the guide](https://omarcevi.dev/workshops/deploy-agents-workshop/step-2/).

## Step 3 · Remember

### What's happening

**Sessions** remember one conversation. **Memory Bank** remembers the person across
conversations:

- **Extraction:** after every turn the agent sends the conversation to Memory Bank, which
  extracts facts in the background. It keeps only the topics configured in
  <walkthrough-editor-open-file filePath="infra/memory/memory-bank.json">infra/memory/memory-bank.json</walkthrough-editor-open-file>:
  team and office, and work preferences.
- **Recall:** at the start of each turn, `PreloadMemoryTool` adds what Memory Bank knows
  about this user to the prompt.

Tell it something on Monday and it still knows on Friday.

![Sessions and Memory Bank across a week](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-3-remember.svg)

[Open the diagram full size](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-3-remember.svg)

### Run it

Tell the agent something about yourself:

```bash
agents-cli run --url "$AGENT_URL" --mode adk "Hi! I'm on the platform team in the Istanbul office, and I prefer to take Fridays off."
```

&nbsp;

Memory Bank extracts facts in the background, usually within a minute or two:

```bash
uv run python scripts/memory_bank.py list
```

&nbsp;

Now ask in new sessions. The agent should know your office and remind you about the
platform team's on-call swap:

```bash
agents-cli run --url "$AGENT_URL" --mode adk "How many leave days do I have?"
agents-cli run --url "$AGENT_URL" --mode adk "Book next Friday off."
```

### See it in the console

- [Agent Runtime deployments](https://console.cloud.google.com/agent-platform/runtimes?project=<walkthrough-project-id/>):
  **workplace-assistant**, then the **Memories** tab (facts per user) and the **Sessions**
  tab (each conversation).
- [Memory Bank](https://console.cloud.google.com/agent-platform/memory-bank?project=<walkthrough-project-id/>)
  and [Sessions](https://console.cloud.google.com/agent-platform/sessions?project=<walkthrough-project-id/>):
  the same data across all agents in the project.

### Check

```bash
./scripts/check.sh 3
```

&nbsp;

Troubleshooting: [Step 3 in the guide](https://omarcevi.dev/workshops/deploy-agents-workshop/step-3/).

## Step 4 · Secure

### What's happening

**Agent Gateway** sits between the agent and everything it calls. On every outbound call it
checks, in order:

1. **Agent Registry:** is the destination registered? Unregistered destinations are refused.
2. **IAM access policy:** may this agent's identity reach this MCP server? Deny rules win
   over allow rules.
3. **Content checks (optional):** Model Armor and semantic governance policies inspect the
   tool call.

The policy in
<walkthrough-editor-open-file filePath="infra/gateway/egress-policy.rules.json">infra/gateway/egress-policy.rules.json</walkthrough-editor-open-file>
allows the HRIS and ticketing servers and denies the compensation system. The agent's code
still calls the compensation tool; the policy stops it. In a company, the security team
owns this policy and agent teams register their tools.

![Agent Identity and the checks Agent Gateway runs](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-4-secure.svg)

[Open the diagram full size](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-4-secure.svg)

### Run it

Make sure the gateway finished building:

```bash
tail -1 .setup-gateway.log
```

&nbsp;

It should say `GATEWAY READY`. Apply the access policy:

```bash
./scripts/secure.sh
```

&nbsp;

Bind the agent to the gateway (a redeploy, about 5 minutes):

```bash
agents-cli deploy --project $PROJECT_ID --update-only --agent-identity --no-confirm-project \
  --agent-gateway-egress=projects/$PROJECT_ID/locations/europe-west1/agentGateways/workplace-gw \
  --update-env-vars GOOGLE_API_ENABLE_RUNTIME_BOUND_TOKEN=false
```

&nbsp;

Same question as in step 2, and a check that HRIS still works:

```bash
agents-cli run --url "$AGENT_URL" --mode adk "What is the salary band for an L5 in Istanbul?"
agents-cli run --url "$AGENT_URL" --mode adk "How many leave days do I have?"
```

&nbsp;

The gateway's own record of the denial:

```bash
gcloud logging read 'resource.type="networkservices.googleapis.com/Gateway" AND jsonPayload.authzPolicyInfo.result="DENIED"' \
  --freshness=15m --limit=3 --format='value(timestamp,httpRequest.requestUrl)'
```

### See it in the console

- [Gateways](https://console.cloud.google.com/agent-platform/gateways?project=<walkthrough-project-id/>):
  **workplace-gw**.
- [Agent Runtime deployments](https://console.cloud.google.com/agent-platform/runtimes?project=<walkthrough-project-id/>):
  **workplace-assistant**, then the **Security** and **Topology** tabs.
- [Policies](https://console.cloud.google.com/agent-platform/policies?project=<walkthrough-project-id/>)
  and [Topology](https://console.cloud.google.com/agent-platform/topology?project=<walkthrough-project-id/>):
  the governance views across all agents.
- [Logs Explorer](https://console.cloud.google.com/logs/query;query=resource.type%3D%22networkservices.googleapis.com%2FGateway%22?project=<walkthrough-project-id/>):
  every gateway decision, `ALLOWED` or `DENIED`.

### Check

```bash
./scripts/check.sh 4
```

&nbsp;

No gateway in your project? `./scripts/fallback_step4.sh` blocks the server with Cloud Run
IAM instead. Troubleshooting: [Step 4 in the guide](https://omarcevi.dev/workshops/deploy-agents-workshop/step-4/).

## Step 5 · Observe

### What's happening

Agent Runtime exports **OpenTelemetry** data without extra code:

- **Traces:** one per turn, nested: the workflow, then each agent, then each model call and
  each tool call, down to the MCP request.
- **Logs:** the agent's audit events (such as the blocked salary lookup) and the prompt and
  answer events go to Cloud Logging.
- **Metrics:** Agent Runtime reports request counts and latency. Two logs-based metrics
  count blocked calls.

`observe.sh` puts these on one dashboard.

![One leave request as a trace, and where telemetry lands](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-5-observe.svg)

[Open the diagram full size](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-5-observe.svg)

### Run it

Make one leave request:

```bash
agents-cli run --url "$AGENT_URL" --mode adk "Book next Monday off as a half day and tell me how many leave days I have left."
```

&nbsp;

Wait a minute for the spans to arrive, then create the dashboard and print the trace as a
waterfall:

```bash
./scripts/observe.sh
```

&nbsp;

Read it like a profile: tool calls take milliseconds, model calls take seconds.

### See it in the console

- [Trace Explorer](https://console.cloud.google.com/traces/explorer?project=<walkthrough-project-id/>):
  open the newest trace (or the link `observe.sh` printed).
- [Agent Runtime deployments](https://console.cloud.google.com/agent-platform/runtimes?project=<walkthrough-project-id/>):
  **workplace-assistant**, then the **Traces** tab: the same traces grouped by session.
- [Dashboards](https://console.cloud.google.com/monitoring/dashboards?project=<walkthrough-project-id/>):
  **Workplace Assistant (workshop)**, with requests, latency p50 and p95, tool errors and
  blocked calls.
- [Logs Explorer](https://console.cloud.google.com/logs/query;query=labels.%22event.name%22%3D%22workplace.tool_blocked%22?project=<walkthrough-project-id/>):
  the agent's audit events for blocked tools.

### Check

```bash
./scripts/check.sh 5
```

&nbsp;

Troubleshooting: [Step 5 in the guide](https://omarcevi.dev/workshops/deploy-agents-workshop/step-5/).

## Step 6 · Evaluate

### What's happening

Three ways to tell whether the agent is good:

- **Offline eval set (the deploy gate):**
  <walkthrough-editor-open-file filePath="evals/cases.yaml">evals/cases.yaml</walkthrough-editor-open-file>
  holds prompts and what should happen. `eval.sh` runs the agent on each one and scores
  routing, tool calls and arguments, grounding in the handbook, and that no salary leaks.
  It then fails if a score is below
  <walkthrough-editor-open-file filePath="evals/thresholds.yaml">evals/thresholds.yaml</walkthrough-editor-open-file>.
- **Live traffic:** `score_live.sh` grades your real conversations from steps 2–5 with LLM
  judges.
- **Managed Online Monitor:** Google's monitor scores live traces every 10 minutes. Today it
  skips turns where the concierge hands over to a sub-agent, and its judge model has
  limited capacity in low-spend projects.

Every production failure becomes a new eval case.

![The evaluation loop](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-6-evaluate.svg)

[Open the diagram full size](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-6-evaluate.svg)

### Run it

The eval gate (about 2 minutes):

```bash
./scripts/eval.sh
```

&nbsp;

Score your own conversations (about a minute):

```bash
./scripts/score_live.sh
```

&nbsp;

Create the managed Online Monitor:

```bash
./scripts/monitor.sh
```

&nbsp;

Turn a production conversation into a test case:

```bash
uv run python scripts/ask.py "Book 29 October off for me."
```

&nbsp;

Copy the `session:` number it prints, then:

```bash
uv run python scripts/session_to_eval_case.py SESSION_ID --id my_regression
```

&nbsp;

In <walkthrough-editor-open-file filePath="evals/cases.yaml">evals/cases.yaml</walkthrough-editor-open-file>,
the new case is at the end of the behaviour list. Set
`forbidden_tools: [submit_leave_request]` (29 October is a public holiday), then:

```bash
uv run python evals/build_datasets.py && ./scripts/eval.sh behaviour
```

### See it in the console

- [Evaluation](https://console.cloud.google.com/agent-platform/agent-evaluation?project=<walkthrough-project-id/>):
  the **Online monitors** tab shows **workplace-quality**.
- [Agent Runtime deployments](https://console.cloud.google.com/agent-platform/runtimes?project=<walkthrough-project-id/>):
  **workplace-assistant**, then **Dashboard**: the monitor's scores, about 10 minutes after
  traffic.

### Check

```bash
./scripts/check.sh 6
```

&nbsp;

Troubleshooting: [Step 6 in the guide](https://omarcevi.dev/workshops/deploy-agents-workshop/step-6/).

## Clean up

Delete everything the lab created (about 10 minutes). It lists anything left over at the end.

```bash
./scripts/teardown.sh
```

&nbsp;

Then confirm in the console: no instance under
[Agent Runtime deployments](https://console.cloud.google.com/agent-platform/runtimes?project=<walkthrough-project-id/>),
and no lab services in [Cloud Run](https://console.cloud.google.com/run?project=<walkthrough-project-id/>).

## Done

<walkthrough-conclusion-trophy></walkthrough-conclusion-trophy>

You deployed a multi-agent app to Agent Runtime with its own identity, gave it memory, put
a policy in front of every tool call, traced it, and gated it on evals.

Next: the [production readiness checklist](https://omarcevi.dev/workshops/deploy-agents-workshop/production/)
and [Agent Runtime, Cloud Run or GKE](https://omarcevi.dev/workshops/deploy-agents-workshop/runtimes/).
