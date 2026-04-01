# Demo Guide: Spec 014 Agent Profiles and Delegation Foundation

This guide shows how to demo the Spec 014 features in a way that works for:

1. a non-developer who wants to see that one assistant identity now owns a conversation durably
2. a developer who wants to verify the agent, model-profile, and run-binding records that make that possible

The demo covers:

1. bootstrap creation of durable default agent and model profiles
2. durable session ownership through `owner_agent_id`
3. run creation with persisted `model_profile_key`, `policy_profile_key`, and `tool_profile_key`
4. the rule that existing sessions keep their owner even if `default_agent_id` changes later
5. new operator read surfaces for agents, model profiles, and agent-owned sessions
6. the foundation that future delegation specs will build on without yet creating sub-agents

The demo uses one simple real-world story:

- a bike shop runs one customer-support assistant today, but wants the backend ready for future specialist assistants such as a service-desk agent or an inventory-check agent without silently changing who owns an existing customer conversation

Important note about this demo:

- this spec does not implement delegation orchestration yet
- the demo proves the durable ownership and profile foundation needed before delegation is safe
- the current local demo uses the default single-agent bootstrap path
- some steps still use direct HTTP inspection and one manual worker command because Spec 015 and later specs have not automated those higher-level flows yet

## 1. What You Will Run

For the main local demo, you will run:

- PostgreSQL with Docker Compose
- database migrations
- the gateway API
- the worker helper
- `curl` commands for the gateway and admin surfaces

You do not need live provider credentials for this demo.

## 2. Before You Start

You need:

- Python 3.11+
- `uv`
- Docker Desktop or another Docker runtime

Work from the project root:

```bash
cd /Users/scottcornell/src/my-projects/python-claw
```

## 3. Setup The Application

### Step 1: Prepare `.env`

If `.env` does not exist yet:

```bash
cp .env.example .env
```

For this demo, make sure these values exist in `.env`:

```text
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=change-me
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=change-me-internal
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true

PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent
PYTHON_CLAW_RUNTIME_MODE=rule_based

PYTHON_CLAW_POLICY_PROFILES=[{"key":"default","remote_execution_enabled":false,"denied_capability_names":[],"delegation_enabled":false}]
PYTHON_CLAW_TOOL_PROFILES=[{"key":"default","allowed_capability_names":["echo_text","remote_exec","send_message"]}]
PYTHON_CLAW_HISTORICAL_AGENT_PROFILE_OVERRIDES=[]

PYTHON_CLAW_CHANNEL_ACCOUNTS=[
  {"channel_account_id":"acct","channel_kind":"slack","mode":"fake"},
  {"channel_account_id":"acct","channel_kind":"telegram","mode":"fake"},
  {"channel_account_id":"acct","channel_kind":"webchat","mode":"fake"},
  {"channel_account_id":"acct-1","channel_kind":"slack","mode":"fake"},
  {"channel_account_id":"acct-1","channel_kind":"telegram","mode":"fake"},
  {"channel_account_id":"acct-1","channel_kind":"webchat","mode":"fake"}
]
```

Important formatting notes:

- `PYTHON_CLAW_POLICY_PROFILES`, `PYTHON_CLAW_TOOL_PROFILES`, and `PYTHON_CLAW_HISTORICAL_AGENT_PROFILE_OVERRIDES` must be valid JSON
- `PYTHON_CLAW_CHANNEL_ACCOUNTS` must also be valid JSON
- do not wrap the whole JSON value in extra single quotes
- safest option: keep each JSON value on one line exactly as valid JSON

What this means:

- `default-agent` is the bootstrap owner for a brand-new canonical session
- `rule_based` keeps the demo easy to run locally
- the default policy profile allows normal safe behavior and keeps delegation disabled
- the default tool profile defines the explicit capability allowlist for the default agent
- the historical override registry is empty because this demo starts from a clean local environment

### Step 2: Install Python dependencies

Run:

```bash
uv sync --group dev
```

### Step 3: Start local infrastructure

Run:

```bash
docker compose --env-file .env up -d
```

Optional checks:

```bash
docker compose ps
docker compose logs postgres
```

### Step 4: Apply database migrations

Run:

```bash
uv run alembic upgrade head
```

This is important for Spec 014 because the new migration adds:

- `agent_profiles`
- `model_profiles`
- durable ownership fields on `sessions`
- persisted profile-key fields on `execution_runs`

## 4. Run The Application

Use three terminals for the demo.

### Terminal A: Start the gateway

Run:

```bash
uv run uvicorn apps.gateway.main:app --reload
```

The gateway starts on `http://127.0.0.1:8000`.

Expected startup behavior:

- the app starts successfully
- bootstrap creates or validates the default model profile
- bootstrap creates or validates the default agent profile
- startup fails closed if the default agent or linked profiles are invalid

### Terminal B: Keep the worker helper ready

Run this command each time the guide tells you to process queued work:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Why this is still manual:

- today the demo needs a person to trigger the local worker helper
- this manual step becomes less necessary as the platform moves into more complete orchestration and operational flows
- the future spec most directly related to removing this kind of manual “operator glue” for end-to-end specialist workflows is Spec 017 in [docs/features_plan.md](/docs/features_plan.md), which calls for production hardening, smoke-test flows, and stronger operational automation

### Terminal C: Use `curl`

Set these shell variables once:

```bash
BASE=http://127.0.0.1:8000
AUTH='Authorization: Bearer change-me'
INTERNAL='X-Internal-Service-Token: change-me-internal'
```

Verify the service:

```bash
curl $BASE/health/live
curl $BASE/health/ready -H "$AUTH"
```

Expected result:

- `GET /health/live` returns HTTP `200`
- `GET /health/ready` returns HTTP `200` when the bearer token is correct

## 5. Variables You Will Reuse

Write these down as you go:

- `SESSION_ID`
- `RUN_ID`
- `MESSAGE_ID`

## 6. Main Demo A: Non-Developer Walkthrough

This is the easiest demo path for a mixed audience. It shows:

- a customer conversation being bootstrapped to a durable agent owner
- the worker preserving that owner and its profile keys on the run
- a new operator view that can explain which agent owns the session

### Scenario

A customer messages the bike shop asking about a tune-up. The support assistant answers, and the system now records that this conversation is durably owned by the default support agent rather than relying on a global process setting each time.

### Step 1: Inspect the bootstrapped agents

In Terminal C, run:

```bash
curl -s $BASE/agents -H "$AUTH"
```

Expected result:

- HTTP `200`
- JSON array
- one entry should exist for `default-agent`

Expected shape:

```json
[
  {
    "agent_id": "default-agent",
    "display_name": "default-agent",
    "role_kind": "assistant",
    "description": null,
    "default_model_profile_id": 1,
    "policy_profile_key": "default",
    "tool_profile_key": "default",
    "enabled": 1
  }
]
```

What this proves:

- Spec 014 introduced durable agent records
- the app now has a canonical agent registry instead of only one loose `default_agent_id` setting

### Step 2: Inspect the bootstrapped model profile

Run:

```bash
curl -s $BASE/model-profiles -H "$AUTH"
```

Expected result:

- HTTP `200`
- JSON array
- one entry should exist for the default model profile

Expected shape:

```json
[
  {
    "id": 1,
    "profile_key": "default",
    "runtime_mode": "rule_based",
    "provider": null,
    "model_name": null,
    "timeout_seconds": 30,
    "tool_call_mode": "auto",
    "streaming_enabled": 1,
    "enabled": 1
  }
]
```

What this proves:

- Spec 014 introduced durable model-profile records
- the runtime can now pick a model profile per agent rather than assuming one process-wide model configuration is always authoritative

### Step 3: Submit a customer message

Run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct",
    "external_message_id": "demo014-msg-001",
    "sender_id": "customer-riley",
    "content": "Hi, can I bring my commuter bike in after 3 PM today for a tune-up?",
    "peer_id": "customer-riley"
  }'
```

Expected result:

- HTTP `202 Accepted`
- JSON containing:
  - `session_id`
  - `message_id`
  - `run_id`
  - `status`
  - `dedupe_status`
  - `trace_id`

Expected shape:

```json
{
  "session_id": "replace-with-session-id",
  "message_id": 1,
  "run_id": "replace-with-run-id",
  "status": "queued",
  "dedupe_status": "accepted",
  "trace_id": "replace-with-trace-id"
}
```

Write down:

- `SESSION_ID`
- `MESSAGE_ID`
- `RUN_ID`

What this proves:

- inbound handling still follows the same gateway-first contract
- the new agent/profile behavior is additive, not a second orchestration path

### Step 4: Show the session now has a durable owner

Replace `replace-with-session-id` with your real `SESSION_ID`, then run:

```bash
curl -s "$BASE/sessions/replace-with-session-id"
```

Expected result:

- HTTP `200`
- JSON containing the older session-routing fields plus the new ownership fields

Expected shape:

```json
{
  "id": "replace-with-session-id",
  "session_key": "slack:acct:direct:customer-riley:main",
  "channel_kind": "slack",
  "channel_account_id": "acct",
  "scope_kind": "direct",
  "peer_id": "customer-riley",
  "group_id": null,
  "scope_name": "main",
  "owner_agent_id": "default-agent",
  "session_kind": "primary",
  "parent_session_id": null
}
```

What this proves:

- session ownership is now durable
- `default-agent` was used only to bootstrap this new session
- the session itself now stores the authoritative owner

### Step 5: Process the queued run

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Expected result:

- the command prints a run id
- it should match or include the run id from Step 3

What is happening:

1. the worker claims the run
2. the worker reloads the persisted run
3. the worker validates the run’s agent and persisted profile keys
4. the worker executes using that binding
5. the final assistant transcript row is written

Why this step is still manual:

- local demos still require a human to trigger the worker
- future operational automation is part of the longer-term production hardening work in Spec 017

### Step 6: Show the run stores the execution profile identity

Replace `replace-with-run-id` with your real `RUN_ID`, then run:

```bash
curl -s "$BASE/runs/replace-with-run-id"
```

Expected result:

- HTTP `200`
- JSON containing the older run fields plus the new profile keys

Expected shape:

```json
{
  "id": "replace-with-run-id",
  "session_id": "replace-with-session-id",
  "message_id": 1,
  "agent_id": "default-agent",
  "model_profile_key": "default",
  "policy_profile_key": "default",
  "tool_profile_key": "default",
  "trigger_kind": "inbound_message",
  "status": "completed"
}
```

What this proves:

- the run persists more than just `agent_id`
- worker execution can now replay against the run’s stored profile identity instead of silently switching to whatever the agent points to later

### Step 7: Show which sessions belong to the default agent

Run:

```bash
curl -s "$BASE/agents/default-agent/sessions" -H "$AUTH"
```

Expected result:

- HTTP `200`
- JSON array
- the session from this demo should appear in the list

Expected shape:

```json
[
  {
    "id": "replace-with-session-id",
    "owner_agent_id": "default-agent",
    "session_kind": "primary",
    "parent_session_id": null
  }
]
```

What this proves:

- operators can now inspect the relationship between agents and sessions directly
- this becomes important before future delegation creates child sessions

## 7. Main Demo B: Developer Verification Walkthrough

This section helps a technical audience verify the internal guarantees behind the user-visible demo.

### Step 1: Inspect the detailed agent record

Run:

```bash
curl -s "$BASE/agents/default-agent" -H "$AUTH"
```

Expected result:

- HTTP `200`
- JSON showing the default agent’s linked profile keys

Expected shape:

```json
{
  "agent_id": "default-agent",
  "display_name": "default-agent",
  "role_kind": "assistant",
  "policy_profile_key": "default",
  "tool_profile_key": "default",
  "enabled": 1
}
```

Developer takeaway:

- the agent profile is now the durable identity record
- disabling or changing an agent can be handled through this record instead of by changing only process config

### Step 2: Inspect the detailed model profile record

Run:

```bash
curl -s "$BASE/model-profiles/default" -H "$AUTH"
```

Expected result:

- HTTP `200`
- JSON showing the current bounded model configuration for the default profile

Expected shape:

```json
{
  "profile_key": "default",
  "runtime_mode": "rule_based",
  "provider": null,
  "model_name": null,
  "timeout_seconds": 30,
  "tool_call_mode": "auto",
  "streaming_enabled": 1,
  "enabled": 1
}
```

Developer takeaway:

- model selection is now represented durably through `model_profiles`
- provider credentials are still settings-only and are not copied into this record

### Step 3: Inspect run diagnostics for the persisted binding

Replace `replace-with-run-id` with your real `RUN_ID`, then run:

```bash
curl -s "$BASE/diagnostics/runs/replace-with-run-id" -H "$AUTH"
```

Expected result:

- HTTP `200`
- JSON containing:
  - `run`
  - `execution_binding`
  - `correlated_artifacts`

Expected shape:

```json
{
  "run": {
    "id": "replace-with-run-id",
    "agent_id": "default-agent",
    "model_profile_key": "default",
    "policy_profile_key": "default",
    "tool_profile_key": "default",
    "status": "completed"
  },
  "execution_binding": {
    "agent_id": "default-agent",
    "model_profile_key": "default",
    "policy_profile_key": "default",
    "tool_profile_key": "default"
  }
}
```

Developer takeaway:

- diagnostics can now explain which profile identity the run actually used
- this is the key seam that later specs will reuse for child-agent and delegation inspection

### Step 4: Verify the canonical transcript remains unchanged by the new profile layer

Replace `replace-with-session-id` with your real `SESSION_ID`, then run:

```bash
curl -s "$BASE/sessions/replace-with-session-id/messages"
```

Expected result:

- HTTP `200`
- JSON with one user message and one assistant message
- no extra transcript rows exist just because session ownership or run profile keys were added

Expected shape:

```json
{
  "items": [
    {
      "role": "user",
      "content": "Hi, can I bring my commuter bike in after 3 PM today for a tune-up?"
    },
    {
      "role": "assistant",
      "content": "Received: Hi, can I bring my commuter bike in after 3 PM today for a tune-up?"
    }
  ]
}
```

Developer takeaway:

- Spec 014 is additive to the existing session and run architecture
- it does not replace transcript truth or graph topology

## 8. Optional Demo C: Show Why Existing Session Ownership Matters

This step demonstrates the main behavioral rule from Spec 014:

- existing sessions keep their persisted owner
- changing `PYTHON_CLAW_DEFAULT_AGENT_ID` later does not silently reassign them

### Step 1: Stop the gateway

Stop Terminal A.

### Step 2: Temporarily change the default agent id in `.env`

Change:

```text
PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent
```

to:

```text
PYTHON_CLAW_DEFAULT_AGENT_ID=agent-2
```

Do not change the session id from the earlier demo.

### Step 3: Restart the gateway

Run again in Terminal A:

```bash
uv run uvicorn apps.gateway.main:app --reload
```

Expected startup behavior:

- the app still starts
- bootstrap seeds or validates `agent-2`
- the older `default-agent` session still exists

### Step 4: Send a second message on the same routing tuple

Run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct",
    "external_message_id": "demo014-msg-002",
    "sender_id": "customer-riley",
    "content": "Also, are you open before 9 tomorrow morning?",
    "peer_id": "customer-riley"
  }'
```

Expected result:

- HTTP `202 Accepted`
- the response should reuse the original `SESSION_ID`

### Step 5: Inspect the session again

Run:

```bash
curl -s "$BASE/sessions/replace-with-session-id"
```

Expected result:

- `owner_agent_id` should still be `default-agent`
- the session owner should not silently change to `agent-2`

What this proves:

- Spec 014 makes existing session ownership durable
- `default_agent_id` is now bootstrap-only for new primary sessions

Why this still requires a manual config edit:

- today this is the clearest way to prove the ownership rule in a local demo
- future specialist-agent flows in Spec 015 will make agent differences visible through explicit delegation behavior instead of a manual config change demo

After this step, put `.env` back to:

```text
PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent
```

and restart the gateway if you want to keep a clean local default.

## 9. What This Demo Proves

By the end of this demo, you have shown that Spec 014 adds:

1. durable `agent_profiles` and `model_profiles`
2. durable session ownership metadata through `owner_agent_id`, `session_kind`, and `parent_session_id`
3. persisted run-level execution profile identity through `model_profile_key`, `policy_profile_key`, and `tool_profile_key`
4. worker-time execution against the stored binding rather than a mutable process-wide default
5. new operator read surfaces for agents, model profiles, and agent-owned sessions
6. the safe foundation needed before future delegation and child-session orchestration

## 10. What Is Still Not In This Spec

This demo intentionally does not show:

- child sessions being created automatically
- one agent delegating work to another
- human handoff or reassignment workflows
- profile editing through a UI or control-plane API

Those belong to later work:

- Spec 015 in [docs/features_plan.md](/docs/features_plan.md) for sub-agent delegation and child-session orchestration
- Spec 016 in [docs/features_plan.md](/docs/features_plan.md) for human handoff and collaboration UX
- Spec 017 in [docs/features_plan.md](/docs/features_plan.md) for stronger production automation and operational hardening

## 11. Troubleshooting

### If `/agents` or `/model-profiles` returns `401`

Make sure you included:

```bash
-H "$AUTH"
```

and that `.env` contains:

```text
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=change-me
```

### If startup fails after changing agent-profile settings

Most likely causes:

- malformed JSON in `PYTHON_CLAW_POLICY_PROFILES`
- malformed JSON in `PYTHON_CLAW_TOOL_PROFILES`
- a missing profile key referenced by an override
- a blank key in one of the profile registries

### If the session owner is not what you expect

Remember the Spec 014 rule:

- new canonical sessions bootstrap from `PYTHON_CLAW_DEFAULT_AGENT_ID`
- existing sessions use their persisted `owner_agent_id`

### If the worker command prints `None`

That usually means:

- there is no queued run waiting to be processed
- you already processed the run
- the inbound request failed before run creation

## 12. Quick Recap For A Live Demo

If you only have a few minutes, do these steps:

1. `GET /agents` to show `default-agent`
2. `GET /model-profiles` to show the default model profile
3. `POST /inbound/message` to create a session and run
4. `GET /sessions/{session_id}` to show `owner_agent_id`
5. run the worker helper once
6. `GET /runs/{run_id}` to show `agent_id` plus the three persisted profile keys
7. `GET /agents/default-agent/sessions` to show the ownership relationship

That sequence gives a non-developer and developer a clear picture of what Spec 014 added and why it matters before delegation is introduced.
