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

Every concept is explained in the guide:
[omarcevi.dev/workshops/deploy-agents-workshop](https://omarcevi.dev/workshops/deploy-agents-workshop/).
This panel has the commands. Click the copy button on a command to paste it into the
terminal. Use the same terminal tab for the whole lab: later steps reuse variables you
set earlier.

<walkthrough-tutorial-duration duration="40"></walkthrough-tutorial-duration>

## Select your project

Pick a project with billing enabled where you are Owner. All data in this lab is fictional.

<walkthrough-project-setup billing="true"></walkthrough-project-setup>

Point Cloud Shell at it:

```bash
gcloud config set project <walkthrough-project-id/>
```

If Cloud Shell asks you to **Authorize** gcloud, click **Authorize**.

## Step 1 · Set up

Cloud Shell has an older agents-cli in `/usr/local/bin`. Install 1.11 or later and put it
first on your `PATH`:

```bash
uv tool install --force "google-agents-cli>=1.11"
export PATH="$HOME/.local/bin:$PATH"
```

Check tools, login and billing:

```bash
./scripts/check.sh 0
```

Enable the APIs, build and deploy the three MCP servers, register them in Agent Registry,
and start building Agent Gateway in the background (about 2 minutes; the gateway keeps
going for about 6 more):

```bash
./scripts/setup.sh
```

While it runs, look at what it does:
<walkthrough-editor-open-file filePath="scripts/setup.sh">scripts/setup.sh</walkthrough-editor-open-file>.

Check the step:

```bash
./scripts/check.sh 1
```

Concepts and troubleshooting: [Step 1 in the guide](https://omarcevi.dev/workshops/deploy-agents-workshop/step-1/).

## Step 2 · Deploy

Read the agents first:
<walkthrough-editor-open-file filePath="app/agent.py">app/agent.py</walkthrough-editor-open-file>.

Deploy to Agent Runtime with its own Agent Identity (about 5 minutes):

```bash
source .workshop.env
agents-cli deploy --project $PROJECT_ID --agent-identity --no-confirm-project
```

Let the agent's identity call the MCP servers, and configure Memory Bank:

```bash
./scripts/grant_agent_access.sh
```

Chat with it. IAM grants take a minute or two to apply: if an answer says a system is
unavailable, ask again.

```bash
AGENT_URL=$(./scripts/agent_url.sh)
agents-cli run --url "$AGENT_URL" --mode adk "How many unused leave days can I carry over?"
agents-cli run --url "$AGENT_URL" --mode adk "What is the salary band for an L5 in Istanbul?"
```

```bash
./scripts/check.sh 2
```

Behind? `git checkout step-1-setup` gives you the state after step 1. Guide:
[Step 2](https://omarcevi.dev/workshops/deploy-agents-workshop/step-2/).

## Step 3 · Remember

Tell the agent something about yourself:

```bash
agents-cli run --url "$AGENT_URL" --mode adk "Hi! I'm on the platform team in the Istanbul office, and I prefer to take Fridays off."
```

Memory Bank extracts facts in the background, usually within a minute or two:

```bash
uv run python scripts/memory_bank.py list
```

Now ask in new sessions. The agent should know your office and remind you about the
platform team's on-call swap:

```bash
agents-cli run --url "$AGENT_URL" --mode adk "How many leave days do I have?"
agents-cli run --url "$AGENT_URL" --mode adk "Book next Friday off."
```

```bash
./scripts/check.sh 3
```

Guide: [Step 3](https://omarcevi.dev/workshops/deploy-agents-workshop/step-3/).

## Step 4 · Secure

The policy in
<walkthrough-editor-open-file filePath="infra/gateway/egress-policy.rules.json">infra/gateway/egress-policy.rules.json</walkthrough-editor-open-file>
allows the HRIS and ticketing servers and denies the compensation system.

Make sure the gateway finished building:

```bash
tail -1 .setup-gateway.log
```

It should say `GATEWAY READY`. Apply the access policy:

```bash
./scripts/secure.sh
```

Bind the agent to the gateway (a redeploy, about 5 minutes):

```bash
agents-cli deploy --project $PROJECT_ID --update-only --agent-identity --no-confirm-project \
  --agent-gateway-egress=projects/$PROJECT_ID/locations/europe-west1/agentGateways/workplace-gw \
  --update-env-vars GOOGLE_API_ENABLE_RUNTIME_BOUND_TOKEN=false
```

Same question as in step 2, and a check that HRIS still works:

```bash
agents-cli run --url "$AGENT_URL" --mode adk "What is the salary band for an L5 in Istanbul?"
agents-cli run --url "$AGENT_URL" --mode adk "How many leave days do I have?"
```

The gateway's own record of the denial:

```bash
gcloud logging read 'resource.type="networkservices.googleapis.com/Gateway" AND jsonPayload.authzPolicyInfo.result="DENIED"' \
  --freshness=15m --limit=3 --format='value(timestamp,httpRequest.requestUrl)'
```

```bash
./scripts/check.sh 4
```

No gateway in your project? `./scripts/fallback_step4.sh` blocks the server with Cloud Run
IAM instead. Guide: [Step 4](https://omarcevi.dev/workshops/deploy-agents-workshop/step-4/).

## Step 5 · Observe

Make one leave request:

```bash
agents-cli run --url "$AGENT_URL" --mode adk "Book next Monday off as a half day and tell me how many leave days I have left."
```

Wait a minute for the spans to arrive, then create the dashboard and print the trace:

```bash
./scripts/observe.sh
```

Open the two links it prints: the trace in Trace Explorer and the dashboard.

```bash
./scripts/check.sh 5
```

Guide: [Step 5](https://omarcevi.dev/workshops/deploy-agents-workshop/step-5/).

## Step 6 · Evaluate

The eval set:
<walkthrough-editor-open-file filePath="evals/cases.yaml">evals/cases.yaml</walkthrough-editor-open-file>.
Run it and gate on the thresholds (about 2 minutes):

```bash
./scripts/eval.sh
```

Score your own conversations from steps 2–5 with LLM judges (about a minute):

```bash
./scripts/score_live.sh
```

Create Google's managed Online Monitor. It scores every 10 minutes; the guide explains what
it can't score yet.

```bash
./scripts/monitor.sh
```

Turn a production conversation into a test case:

```bash
uv run python scripts/ask.py "Book 29 October off for me."
```

Copy the `session:` number it prints, then:

```bash
uv run python scripts/session_to_eval_case.py SESSION_ID --id my_regression
```

In <walkthrough-editor-open-file filePath="evals/cases.yaml">evals/cases.yaml</walkthrough-editor-open-file>,
the new case is at the end of the behaviour list. Set
`forbidden_tools: [submit_leave_request]` (29 October is a public holiday), then:

```bash
uv run python evals/build_datasets.py && ./scripts/eval.sh behaviour
```

```bash
./scripts/check.sh 6
```

Guide: [Step 6](https://omarcevi.dev/workshops/deploy-agents-workshop/step-6/).

## Clean up

Delete everything the lab created (about 10 minutes). It lists anything left over at the end.

```bash
./scripts/teardown.sh
```

## Done

<walkthrough-conclusion-trophy></walkthrough-conclusion-trophy>

You deployed a multi-agent app to Agent Runtime with its own identity, gave it memory, put
a policy in front of every tool call, traced it, and gated it on evals.

Next: the [production readiness checklist](https://omarcevi.dev/workshops/deploy-agents-workshop/production/)
and [Agent Runtime, Cloud Run or GKE](https://omarcevi.dev/workshops/deploy-agents-workshop/runtimes/).
