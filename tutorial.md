<walkthrough-metadata>
  <meta name="title" content="Deploying Your Agents on Google Cloud" />
  <meta name="description" content="Deploy a multi-agent ADK app to Agent Runtime with Agent Identity, Memory Bank, Agent Gateway, traces and evals." />
  <meta name="keywords" content="ADK, Agent Runtime, Agent Identity, Agent Gateway, Memory Bank, evaluation" />
</walkthrough-metadata>

# Deploying Your Agents on Google Cloud

## Welcome

In this lab, you take the **Kuzey Labs Workplace Assistant** from this repository to a
production configuration. The assistant has a concierge and three specialist agents. The
concierge sends HR questions, leave requests and IT problems to the specialist agents. The
specialist agents call MCP servers on Cloud Run.

![Architecture](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/architecture.svg)

| Step | What you do |
|---|---|
| 1 Set up | APIs, three MCP servers, Agent Registry, and Agent Gateway (it builds in the background) |
| 2 Deploy | `agents-cli deploy` to Agent Runtime with Agent Identity |
| 3 Remember | Memory Bank recalls your team and office in a new session |
| 4 Secure | Agent Gateway blocks the compensation system with a policy |
| 5 Observe | One leave request as a trace, and a dashboard |
| 6 Evaluate | Eval gate, scores for live traffic, an Online Monitor |

Each step tells you what happens, gives the commands, and links to the console pages that
show the result. To paste a command into the terminal, click the copy button. The guide has
the full explanations, the diagrams and the solutions to problems:
[omarcevi.dev/workshops/deploy-agents-workshop](https://omarcevi.dev/workshops/deploy-agents-workshop/).

Use the same terminal tab for the full lab. Later steps use variables that you set in earlier
steps.

<walkthrough-tutorial-duration duration="40"></walkthrough-tutorial-duration>

## Select your project

Select a project that has billing enabled and where you have the Owner role. All data in this
lab is fictional.

<walkthrough-project-setup billing="true"></walkthrough-project-setup>

Set this project in Cloud Shell:

```bash
gcloud config set project <walkthrough-project-id/>
```

&nbsp;

If Cloud Shell asks you to authorize gcloud, click **Authorize**. The console links in this
tutorial open the project that you selected here.

## Step 1 · Set up

### What happens

`setup.sh` prepares all the resources that the agent needs:

- **Three MCP servers on Cloud Run:** the HRIS (leave balances and requests), the ticketing
  system and the compensation system of the fictional company. Cloud Build builds one
  container image for the three servers. The servers accept only callers that have IAM
  permission, and they scale to zero.
- **Agent Registry:** `setup.sh` registers the servers and the Google APIs that the agent
  calls. Later, Agent Gateway refuses all destinations that are not in the registry.
- **Agent Gateway:** `setup.sh` starts to build Agent Gateway in the background. This takes
  approximately 6 minutes. You use the gateway in step 4.

![What setup.sh creates](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-1-setup.svg)

[Open the diagram full size](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-1-setup.svg)

### Run it

1. Install agents-cli 1.11 or later. The second command puts it first in your `PATH`, because Cloud Shell has an older agents-cli in `/usr/local/bin`:
   ```bash
   uv tool install --force "google-agents-cli>=1.11"
   export PATH="$HOME/.local/bin:$PATH"
   ```
2. Check the tools, the login and the billing:
   ```bash
   ./scripts/check.sh 0
   ```
3. Run the setup script (approximately 2 minutes). While the script runs, read <walkthrough-editor-open-file filePath="scripts/setup.sh">scripts/setup.sh</walkthrough-editor-open-file>.
   ```bash
   ./scripts/setup.sh
   ```

### See it in the console

- [Cloud Run](https://console.cloud.google.com/run?project=<walkthrough-project-id/>):
  `hris-mcp`, `ticketing-mcp` and `compensation-mcp`. Each service shows *Require
  authentication*.
- [Agent Registry](https://console.cloud.google.com/agent-platform/agent-registry?project=<walkthrough-project-id/>):
  the three MCP servers and the endpoint for the Google APIs.
- [Cloud Build history](https://console.cloud.google.com/cloud-build/builds?project=<walkthrough-project-id/>):
  the build of the MCP server image.

### Check

```bash
./scripts/check.sh 1
```

&nbsp;

If this check fails, see [Step 1 in the guide](https://omarcevi.dev/workshops/deploy-agents-workshop/step-1/).

## Step 2 · Deploy

### What happens

`agents-cli deploy` packages the agent code
(<walkthrough-editor-open-file filePath="app/agent.py">app/agent.py</walkthrough-editor-open-file>
and the `Dockerfile`), builds a container and creates an **Agent Runtime** instance:

- **Runtime:** Agent Runtime serves the query API and the stream-query API of the agent. It
  scales with the traffic, also to zero. It keeps **sessions** (the history of each
  conversation) and exports traces.
- **Identity:** `--agent-identity` gives the agent its own **Agent Identity**. This identity
  is a principal for this agent only, not a shared service account.
- **Access:** `grant_agent_access.sh` gives this identity the *Cloud Run Invoker* role on each
  MCP server. The agent calls the HRIS as itself. Cloud Run checks the permission on each
  request.

![What agents-cli deploy does](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-2-deploy.svg)

[Open the diagram full size](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-2-deploy.svg)

### Run it

1. Deploy the agent (approximately 5 minutes):
   ```bash
   source .workshop.env
   agents-cli deploy --project $PROJECT_ID --agent-identity --no-confirm-project
   ```
2. Give the identity of the agent access to the MCP servers. The script also configures Memory Bank:
   ```bash
   ./scripts/grant_agent_access.sh
   ```
3. Send two questions to the agent. If an answer says that a system is not available, wait one or two minutes and ask again. IAM grants need this time to apply.
   ```bash
   AGENT_URL=$(./scripts/agent_url.sh)
   agents-cli run --url "$AGENT_URL" --mode adk "How many unused leave days can I carry over?"
   agents-cli run --url "$AGENT_URL" --mode adk "What is the salary band for an L5 in Istanbul?"
   ```

### See it in the console

- [Agent Runtime deployments](https://console.cloud.google.com/agent-platform/runtimes?project=<walkthrough-project-id/>):
  open **workplace-assistant**. The **Identity** tab shows its principal. On the
  **Playground** tab, you can send messages to the agent in the browser. The **Sessions** tab
  shows the conversations that you had.
- [Cloud Run](https://console.cloud.google.com/run?project=<walkthrough-project-id/>):
  select **hris-mcp**. Then open **Permissions**: the principal of the agent has the *Cloud
  Run Invoker* role.

### Check

```bash
./scripts/check.sh 2
```

&nbsp;

To start from the state after step 1, run `git checkout step-1-setup`. If this check fails,
see [Step 2 in the guide](https://omarcevi.dev/workshops/deploy-agents-workshop/step-2/).

## Step 3 · Remember

### What happens

A **session** keeps one conversation. **Memory Bank** keeps facts about the person across
conversations:

- **Extraction:** after each turn, the agent sends the conversation to Memory Bank. Memory
  Bank extracts facts in the background. It keeps only the topics in
  <walkthrough-editor-open-file filePath="infra/memory/memory-bank.json">infra/memory/memory-bank.json</walkthrough-editor-open-file>:
  team and office, and work preferences.
- **Recall:** at the start of each turn, `PreloadMemoryTool` adds the facts about this user
  to the prompt.

If you tell the agent a fact on Monday, the agent still knows it on Friday.

![Sessions and Memory Bank across a week](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-3-remember.svg)

[Open the diagram full size](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-3-remember.svg)

### Run it

1. Tell the agent some facts about yourself:
   ```bash
   agents-cli run --url "$AGENT_URL" --mode adk "Hi! I'm on the platform team in the Istanbul office, and I prefer to take Fridays off."
   ```
2. Show the facts that Memory Bank stored. Memory Bank usually needs one or two minutes to extract them:
   ```bash
   uv run python scripts/memory_bank.py list
   ```
3. Ask two questions in new sessions. The agent knows your office and tells you about the on-call swap for the platform team:
   ```bash
   agents-cli run --url "$AGENT_URL" --mode adk "How many leave days do I have?"
   agents-cli run --url "$AGENT_URL" --mode adk "Book next Friday off."
   ```

### See it in the console

- [Agent Runtime deployments](https://console.cloud.google.com/agent-platform/runtimes?project=<walkthrough-project-id/>):
  **workplace-assistant**, then the **Memories** tab (the facts for each user) and the
  **Sessions** tab (each conversation).
- [Memory Bank](https://console.cloud.google.com/agent-platform/memory-bank?project=<walkthrough-project-id/>)
  and [Sessions](https://console.cloud.google.com/agent-platform/sessions?project=<walkthrough-project-id/>):
  the same data for all the agents in the project.

### Check

```bash
./scripts/check.sh 3
```

&nbsp;

If this check fails, see [Step 3 in the guide](https://omarcevi.dev/workshops/deploy-agents-workshop/step-3/).

## Step 4 · Secure

### What happens

**Agent Gateway** is between the agent and all the destinations that the agent calls. For
each outbound call, the gateway does these checks in this sequence:

1. **Agent Registry:** Is the destination registered? The gateway refuses destinations that
   are not in the registry.
2. **IAM access policy:** Can the identity of this agent get access to this MCP server? Deny
   rules have priority over allow rules.
3. **Content checks (optional):** Model Armor and semantic governance policies examine the
   tool call.

The policy in
<walkthrough-editor-open-file filePath="infra/gateway/egress-policy.rules.json">infra/gateway/egress-policy.rules.json</walkthrough-editor-open-file>
allows the HRIS and the ticketing server, and denies the compensation system. The code of the
agent still calls the compensation tool, but the policy stops the call. In a company, the
security team owns this policy. The agent teams register their tools.

![Agent Identity and the checks Agent Gateway runs](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-4-secure.svg)

[Open the diagram full size](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-4-secure.svg)

### Run it

1. Make sure that the gateway is ready. The command shows `GATEWAY READY`:
   ```bash
   tail -1 .setup-gateway.log
   ```
2. Apply the access policy:
   ```bash
   ./scripts/secure.sh
   ```
3. Connect the agent to the gateway (a new deployment, approximately 5 minutes):
   ```bash
   agents-cli deploy --project $PROJECT_ID --update-only --agent-identity --no-confirm-project \
     --agent-gateway-egress=projects/$PROJECT_ID/locations/europe-west1/agentGateways/workplace-gw \
     --update-env-vars GOOGLE_API_ENABLE_RUNTIME_BOUND_TOKEN=false
   ```
4. Ask the question from step 2 again. The second command makes sure that the HRIS still works:
   ```bash
   agents-cli run --url "$AGENT_URL" --mode adk "What is the salary band for an L5 in Istanbul?"
   agents-cli run --url "$AGENT_URL" --mode adk "How many leave days do I have?"
   ```
5. Read the record of the denial in the gateway log:
   ```bash
   gcloud logging read 'resource.type="networkservices.googleapis.com/Gateway" AND jsonPayload.authzPolicyInfo.result="DENIED"' \
     --freshness=15m --limit=3 --format='value(timestamp,httpRequest.requestUrl)'
   ```

### See it in the console

- [Gateways](https://console.cloud.google.com/agent-platform/gateways?project=<walkthrough-project-id/>):
  **workplace-gw**.
- [Agent Runtime deployments](https://console.cloud.google.com/agent-platform/runtimes?project=<walkthrough-project-id/>):
  **workplace-assistant**, then the **Security** tab and the **Topology** tab.
- [Policies](https://console.cloud.google.com/agent-platform/policies?project=<walkthrough-project-id/>)
  and [Topology](https://console.cloud.google.com/agent-platform/topology?project=<walkthrough-project-id/>):
  the governance views for all agents.
- [Logs Explorer](https://console.cloud.google.com/logs/query;query=resource.type%3D%22networkservices.googleapis.com%2FGateway%22?project=<walkthrough-project-id/>):
  each decision of the gateway, `ALLOWED` or `DENIED`.

### Check

```bash
./scripts/check.sh 4
```

&nbsp;

If your project has no Agent Gateway, use `./scripts/fallback_step4.sh`. This script blocks
the server with Cloud Run IAM. If this check fails, see
[Step 4 in the guide](https://omarcevi.dev/workshops/deploy-agents-workshop/step-4/).

## Step 5 · Observe

### What happens

Agent Runtime exports **OpenTelemetry** data. You do not have to add code:

- **Traces:** one trace for each turn. The trace contains the workflow, then each agent, then
  each model call and tool call, down to the MCP request.
- **Logs:** the audit events of the agent (for example, the blocked salary lookup) and the
  prompt and answer events go to Cloud Logging.
- **Metrics:** Agent Runtime reports the number of requests and the latency. Two logs-based
  metrics count the blocked calls.

`observe.sh` shows these data on one dashboard.

![One leave request as a trace, and where telemetry lands](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-5-observe.svg)

[Open the diagram full size](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-5-observe.svg)

### Run it

1. Send one leave request:
   ```bash
   agents-cli run --url "$AGENT_URL" --mode adk "Book next Monday off as a half day and tell me how many leave days I have left."
   ```
2. Wait one minute for the spans. Then run this script. It creates the dashboard and shows the trace as a waterfall. Tool calls take milliseconds, and model calls take seconds:
   ```bash
   ./scripts/observe.sh
   ```

### See it in the console

- [Trace Explorer](https://console.cloud.google.com/traces/explorer?project=<walkthrough-project-id/>):
  open the newest trace (or the link that `observe.sh` showed).
- [Agent Runtime deployments](https://console.cloud.google.com/agent-platform/runtimes?project=<walkthrough-project-id/>):
  **workplace-assistant**, then the **Traces** tab: the same traces, in groups for each
  session.
- [Dashboards](https://console.cloud.google.com/monitoring/dashboards?project=<walkthrough-project-id/>):
  **Workplace Assistant (workshop)**, with requests, latency p50 and p95, tool errors and
  blocked calls.
- [Logs Explorer](https://console.cloud.google.com/logs/query;query=labels.%22event.name%22%3D%22workplace.tool_blocked%22?project=<walkthrough-project-id/>):
  the audit events of the agent for blocked tools.

### Check

```bash
./scripts/check.sh 5
```

&nbsp;

If this check fails, see [Step 5 in the guide](https://omarcevi.dev/workshops/deploy-agents-workshop/step-5/).

## Step 6 · Evaluate

### What happens

You can find the quality of the agent in three ways:

- **Offline eval set (the deploy gate):**
  <walkthrough-editor-open-file filePath="evals/cases.yaml">evals/cases.yaml</walkthrough-editor-open-file>
  contains prompts and the correct result for each prompt. `eval.sh` runs the agent on each
  prompt. It gives scores for routing, tool calls and arguments, grounding in the handbook,
  and salary leaks. If a score is below
  <walkthrough-editor-open-file filePath="evals/thresholds.yaml">evals/thresholds.yaml</walkthrough-editor-open-file>,
  the gate fails.
- **Live traffic:** `score_live.sh` uses LLM judges to give scores to your real conversations
  from steps 2–5.
- **Managed Online Monitor:** the monitor from Google gives scores to live traces every 10
  minutes. At this time, it does not score turns where the concierge sends the request to a
  specialist agent. Also, its judge model has a small capacity in projects with a low spend.

Each failure in production becomes a new eval case.

![The evaluation loop](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-6-evaluate.svg)

[Open the diagram full size](https://omarcevi.dev/workshops/deploy-agents-workshop/diagrams/step-6-evaluate.svg)

### Run it

1. Run the eval gate (approximately 2 minutes):
   ```bash
   ./scripts/eval.sh
   ```
2. Give scores to your own conversations from steps 2–5 (approximately 1 minute):
   ```bash
   ./scripts/score_live.sh
   ```
3. Create the managed Online Monitor:
   ```bash
   ./scripts/monitor.sh
   ```
4. Make a test case from a conversation in production. First, ask this question:
   ```bash
   uv run python scripts/ask.py "Book 29 October off for me."
   ```
5. Copy the `session:` number from the result. Then run this command:
   ```bash
   uv run python scripts/session_to_eval_case.py SESSION_ID --id my_regression
   ```
6. Open <walkthrough-editor-open-file filePath="evals/cases.yaml">evals/cases.yaml</walkthrough-editor-open-file>. The new case is at the end of the behaviour list. Set `forbidden_tools: [submit_leave_request]`, because 29 October is a public holiday. Then run the gate again:
   ```bash
   uv run python evals/build_datasets.py && ./scripts/eval.sh behaviour
   ```

### See it in the console

- [Evaluation](https://console.cloud.google.com/agent-platform/agent-evaluation?project=<walkthrough-project-id/>):
  the **Online monitors** tab shows **workplace-quality**.
- [Agent Runtime deployments](https://console.cloud.google.com/agent-platform/runtimes?project=<walkthrough-project-id/>):
  **workplace-assistant**, then **Dashboard**: the scores of the monitor, approximately 10
  minutes after the traffic.

### Check

```bash
./scripts/check.sh 6
```

&nbsp;

If this check fails, see [Step 6 in the guide](https://omarcevi.dev/workshops/deploy-agents-workshop/step-6/).

## Teardown

Delete all the resources that the lab created (approximately 10 minutes). At the end, the
script shows the resources that are still there.

```bash
./scripts/teardown.sh
```

&nbsp;

Then make sure that the console shows no instance in
[Agent Runtime deployments](https://console.cloud.google.com/agent-platform/runtimes?project=<walkthrough-project-id/>)
and no lab services in [Cloud Run](https://console.cloud.google.com/run?project=<walkthrough-project-id/>).

## Done

<walkthrough-conclusion-trophy></walkthrough-conclusion-trophy>

You deployed a multi-agent app to Agent Runtime with its own identity. You gave it memory and
put a policy in front of each tool call. You also examined its traces and used evals as a
gate before each deployment.

Next, read the [production readiness checklist](https://omarcevi.dev/workshops/deploy-agents-workshop/production/)
and [Agent Runtime, Cloud Run or GKE](https://omarcevi.dev/workshops/deploy-agents-workshop/runtimes/).
