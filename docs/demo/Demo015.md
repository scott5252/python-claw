# Demo Guide: Spec 015 Sub-Agent Delegation and Child Session Orchestration

This guide shows how to demo Spec 015 in a way that works for:

1. a non-developer who wants to see a main assistant hand off bounded work to a specialist assistant and then continue the parent conversation safely
2. a developer who wants to verify the durable records, child sessions, child runs, parent continuation runs, and operator surfaces that make that delegation safe and auditable

The demo covers:

1. enabling bounded delegation through settings-backed policy and tool profiles
2. bootstrapping a parent assistant and a specialist child assistant
3. creating a normal parent session and parent run
4. creating one durable delegation record that points to one child session and one child run
5. processing the child run on the existing worker queue
6. showing how child completion re-enters the parent session through a durable internal continuation message and a normal `delegation_result` run
7. proving that child work is isolated from the parent by session ownership and run binding
8. inspecting the new admin and diagnostics surfaces for delegation lineage

The demo uses one simple real-world story:

- a bike shop has a main customer-support assistant named `default-agent`
- when a customer asks a question that needs specialist research, the main assistant delegates a bounded task to a specialist assistant named `repair-specialist`
- the specialist works in a child session, returns a bounded summary, and the parent conversation resumes from durable transcript state

Important note about this demo:

- Spec 015 implements the durable delegation machinery, but the easiest local demo is still a controlled backend trigger rather than relying on a provider model to choose the tool perfectly every time
- the helper command in this guide calls the same `DelegationService` path that the `delegate_to_agent` typed tool uses in production
- this keeps the walkthrough deterministic and lets both non-developers and developers see the actual durable records created by the spec

## 1. What You Will Run

For the main local demo, you will run:

- PostgreSQL with Docker Compose
- database migrations
- the gateway API
- the worker helper
- `curl` commands for user and admin reads
- one short Python helper command that creates a delegation through the backend service layer

You do not need live LLM provider credentials for this demo.

## 2. Before You Start

You need:

- Python 3.11+
- `uv`
- Docker Desktop or another Docker runtime

Work from the project root:

```bash
cd /Users/scottcornell/src/my-projects/python-claw
```

## 3. Real-World Scenario You Will Demonstrate

You will act out this workflow:

1. a customer asks the bike shop, "Can you confirm whether you do same-day hydraulic brake service and what I should bring with me?"
2. the main support assistant owns the conversation and remains the only assistant that can ultimately respond to the customer
3. the main assistant delegates a bounded research task to a specialist repair assistant
4. the specialist repair assistant receives only a bounded package of parent context, not the full parent transcript and not the parent's approvals
5. the specialist finishes in its own child session
6. the system appends an internal delegation-result message back into the parent session
7. the parent session gets a normal follow-up run on the parent lane
8. the operator can inspect exactly who delegated to whom, when, and with what status

This is what Spec 015 adds to the application:

- durable `delegations` and `delegation_events`
- explicit child sessions with `session_kind=child`
- child runs that use the existing `execution_runs` queue lifecycle
- bounded parent-to-child context packaging
- durable parent continuation through transcript state, not in-memory callbacks
- admin and diagnostics visibility into delegation lineage

## 4. Setup The Application

### Step 1: Prepare `.env`

If `.env` does not exist yet:

```bash
cp .env.example .env
```

For this demo, make sure these values exist in `.env`.

These are the minimum values you should set for a clean Spec 015 demo:

```text
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=change-me
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=change-me-internal
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true

PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent
PYTHON_CLAW_RUNTIME_MODE=rule_based

PYTHON_CLAW_DELEGATION_PACKAGE_TRANSCRIPT_TURNS=6
PYTHON_CLAW_DELEGATION_PACKAGE_RETRIEVAL_ITEMS=4
PYTHON_CLAW_DELEGATION_PACKAGE_ATTACHMENT_ITEMS=2
PYTHON_CLAW_DELEGATION_PACKAGE_MAX_CHARS=4000

PYTHON_CLAW_POLICY_PROFILES=[{"key":"default","remote_execution_enabled":false,"denied_capability_names":[],"delegation_enabled":true,"max_delegation_depth":1,"allowed_child_agent_ids":["repair-specialist"],"max_active_delegations_per_run":1,"max_active_delegations_per_session":2},{"key":"child-safe","remote_execution_enabled":false,"denied_capability_names":[],"delegation_enabled":false,"max_delegation_depth":0,"allowed_child_agent_ids":[],"max_active_delegations_per_run":null,"max_active_delegations_per_session":null}]

PYTHON_CLAW_TOOL_PROFILES=[{"key":"parent-tools","allowed_capability_names":["echo_text","send_message","delegate_to_agent"]},{"key":"child-tools","allowed_capability_names":["echo_text","send_message"]},{"key":"default","allowed_capability_names":["echo_text","send_message","delegate_to_agent"]}]

PYTHON_CLAW_HISTORICAL_AGENT_PROFILE_OVERRIDES=[{"agent_id":"repair-specialist","model_profile_key":"default","policy_profile_key":"child-safe","tool_profile_key":"child-tools"}]

PYTHON_CLAW_CHANNEL_ACCOUNTS=[{"channel_account_id":"acct","channel_kind":"slack","mode":"fake"},{"channel_account_id":"acct","channel_kind":"telegram","mode":"fake"},{"channel_account_id":"acct","channel_kind":"webchat","mode":"fake"},{"channel_account_id":"acct-1","channel_kind":"slack","mode":"fake"},{"channel_account_id":"acct-1","channel_kind":"telegram","mode":"fake"},{"channel_account_id":"acct-1","channel_kind":"webchat","mode":"fake"}]
```

What each important setting does in this demo:

- `PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent`
  - this is the main assistant that will own the customer session
- `PYTHON_CLAW_RUNTIME_MODE=rule_based`
  - this keeps the demo local and deterministic without requiring a real provider model
- `PYTHON_CLAW_DELEGATION_PACKAGE_TRANSCRIPT_TURNS=6`
  - the child gets at most six recent parent transcript messages
- `PYTHON_CLAW_DELEGATION_PACKAGE_RETRIEVAL_ITEMS=4`
  - the child can receive up to four retrieval or memory items if they exist
- `PYTHON_CLAW_DELEGATION_PACKAGE_ATTACHMENT_ITEMS=2`
  - the child can receive up to two attachment excerpts if they exist
- `PYTHON_CLAW_DELEGATION_PACKAGE_MAX_CHARS=4000`
  - this is the hard size budget for the packaged child context
- `PYTHON_CLAW_POLICY_PROFILES`
  - `default` enables delegation only to `repair-specialist`
  - `default` limits depth to `1`, so the child cannot create another child in this demo
  - `child-safe` disables delegation for the child assistant, which keeps the demo bounded and easy to explain
- `PYTHON_CLAW_TOOL_PROFILES`
  - `parent-tools` allows `delegate_to_agent`
  - `child-tools` does not allow `delegate_to_agent`, so the specialist can work but cannot fan out further
- `PYTHON_CLAW_HISTORICAL_AGENT_PROFILE_OVERRIDES`
  - this ensures the `repair-specialist` agent is bootstrapped with the child-safe policy and child tool profile

Important formatting notes:

- `PYTHON_CLAW_POLICY_PROFILES`, `PYTHON_CLAW_TOOL_PROFILES`, and `PYTHON_CLAW_HISTORICAL_AGENT_PROFILE_OVERRIDES` must be valid JSON
- `PYTHON_CLAW_CHANNEL_ACCOUNTS` must also be valid JSON
- safest option: keep each JSON value on one line exactly as shown above

### Step 2: Install Python dependencies

Run:

```bash
uv sync --group dev
```

What the system is doing:

- `uv` creates or updates the local virtual environment
- the project dependencies, FastAPI stack, Alembic, and test tools are installed
- this step does not modify application data yet

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

What the system is doing:

- Docker starts the PostgreSQL database declared in `docker-compose.yml`
- the backend is not using SQLite in this demo because we want the normal local operational shape

### Step 4: Apply database migrations

Run:

```bash
uv run alembic upgrade head
```

Why this matters for Spec 015:

- the new migration creates `delegations`
- the new migration creates `delegation_events`
- older Spec 014 migrations create `agent_profiles`, `model_profiles`, and session ownership fields needed for child-session orchestration

## 5. Run The Application

Use three terminals for the demo.

### Terminal A: Start the gateway

Run:

```bash
uv run uvicorn apps.gateway.main:app --reload
```

The gateway starts on `http://127.0.0.1:8000`.

Expected startup behavior:

- bootstrap creates or validates `default-agent`
- bootstrap creates or validates `repair-specialist`
- the linked tool and policy profiles are resolved
- startup fails closed if one of the profile links is invalid

What the system is doing:

- the app reads `.env`
- the settings model validates policy profiles, tool profiles, and delegation package limits
- the bootstrap process seeds durable agent records

### Terminal B: Keep the worker helper ready

Run this command each time the guide tells you to process queued work:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What this worker helper does:

- it claims the next eligible run from the durable queue
- it runs exactly one queued execution
- it releases the queue lease

Why this is still manual in the demo:

- the local demo is focused on proving durable behavior, not background process supervision
- Spec 015 reuses the worker model; it does not add a second orchestration daemon

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

## 6. Variables You Will Reuse

Write these down as you go:

- `SESSION_ID`
- `MESSAGE_ID`
- `PARENT_RUN_ID`
- `DELEGATION_ID`
- `CHILD_SESSION_ID`
- `CHILD_RUN_ID`
- `PARENT_RESULT_RUN_ID`

## 7. Main Demo A: Non-Developer Walkthrough

This path is for a mixed audience. It focuses on the story first and the implementation details second.

### Scenario

A customer asks whether same-day hydraulic brake service is available and what they should bring. The main assistant keeps ownership of the conversation, but asks a repair specialist to do bounded background work. The customer-facing conversation stays with the main assistant.

### Step 1: Show the available agents

Run:

```bash
curl -s $BASE/agents -H "$AUTH"
```

Expected result:

- HTTP `200`
- JSON array containing at least:
  - `default-agent`
  - `repair-specialist`

What this means:

- the system has durable agent identities
- the specialist is not just a hidden prompt trick; it is a real, inspectable agent record

### Step 2: Send the customer’s message

Run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct",
    "external_message_id": "demo015-msg-001",
    "sender_id": "customer-riley",
    "content": "Hi, can you confirm whether you do same-day hydraulic brake service and what I should bring with me?",
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

Write down:

- `SESSION_ID`
- `MESSAGE_ID`
- `PARENT_RUN_ID`

What the system is doing:

1. the gateway resolves or creates the canonical parent session
2. the new customer message is appended as a durable transcript row
3. one parent execution run is queued on the parent session lane
4. no delegation exists yet; this is still just a normal parent conversation

### Step 3: Show the parent session owner

Replace `replace-with-session-id` with your real `SESSION_ID`, then run:

```bash
curl -s "$BASE/sessions/replace-with-session-id"
```

Expected result:

- HTTP `200`
- the session should show:
  - `owner_agent_id: "default-agent"`
  - `session_kind: "primary"`
  - `parent_session_id: null`

What this means:

- the customer conversation belongs to the main assistant
- even after delegation, the parent session remains owned by the parent assistant

### Step 4: Process the initial parent run

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Expected result:

- one run id prints
- it should match the parent run id from Step 2

What the system is doing:

1. the worker claims the parent run
2. the parent run executes on the normal parent session lane
3. because this local demo uses `rule_based`, the parent run itself does not choose delegation automatically
4. the next step will trigger the same backend delegation path directly so the demo stays deterministic

### Step 5: Create the delegation through the real backend service

In Terminal C, run this helper command and replace `replace-with-*` values first:

```bash
uv run python - <<'PY'
from src.config.settings import get_settings
from src.db.session import DatabaseSessionManager
from src.policies.service import PolicyService
from apps.gateway.deps import create_delegation_service

settings = get_settings()
session_manager = DatabaseSessionManager(settings.database_url)
service = create_delegation_service(settings)

PARENT_SESSION_ID = "replace-with-session-id"
PARENT_MESSAGE_ID = int("replace-with-message-id")
PARENT_RUN_ID = "replace-with-parent-run-id"

with session_manager.session() as db:
    result = service.create_delegation(
        db,
        policy_service=PolicyService(
            allowed_capabilities={"echo_text", "send_message", "delegate_to_agent"},
            delegation_enabled=True,
            max_delegation_depth=1,
            allowed_child_agent_ids={"repair-specialist"},
            max_active_delegations_per_run=1,
            max_active_delegations_per_session=2,
        ),
        parent_session_id=PARENT_SESSION_ID,
        parent_message_id=PARENT_MESSAGE_ID,
        parent_run_id=PARENT_RUN_ID,
        parent_agent_id="default-agent",
        parent_policy_profile_key="default",
        parent_tool_profile_key="parent-tools",
        correlation_id="demo015-delegation-001",
        child_agent_id="repair-specialist",
        task_text="Review the customer request and produce a short repair-intake summary explaining whether same-day hydraulic brake service is available and what the customer should bring.",
        delegation_kind="research",
        expected_output="A short summary the parent assistant can use in a follow-up reply.",
        notes="Keep the result concise and suitable for customer support."
    )
    db.commit()
    print("delegation_id=", result.delegation_id)
    print("child_session_id=", result.child_session_id)
    print("child_run_id=", result.child_run_id)
PY
```

Write down:

- `DELEGATION_ID`
- `CHILD_SESSION_ID`
- `CHILD_RUN_ID`

What the system is doing:

1. the backend validates that delegation is enabled in policy
2. the backend validates that `repair-specialist` is allowlisted
3. the backend confirms the requested depth does not exceed the configured maximum
4. the backend creates exactly one durable `delegations` row
5. the backend creates exactly one child session with `session_kind=child`
6. the backend appends exactly one system trigger message in the child session
7. the backend queues exactly one child run with `trigger_kind=delegation_child`
8. the backend records append-only delegation events

This is the core of Spec 015.

### Step 6: Show the new delegation in the admin API

Run:

```bash
curl -s "$BASE/sessions/$SESSION_ID/delegations" -H "$AUTH"
```

Expected result:

- HTTP `200`
- one delegation record appears for the parent session

Then run:

```bash
curl -s "$BASE/delegations/$DELEGATION_ID" -H "$AUTH"
```

Expected result:

- HTTP `200`
- JSON showing:
  - the parent session id
  - the child session id
  - the parent run id
  - the child run id
  - `status: "queued"` or `status: "running"` depending on timing
  - `child_agent_id: "repair-specialist"`

What this means for a non-developer:

- the handoff is tracked explicitly
- the specialist work is not invisible or magical
- the system can show where the work went and what state it is in

### Step 7: Process the child run

In Terminal B, run the worker helper again:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Expected result:

- one run id prints
- it should match the child run id or be the next queued child run

What the system is doing:

1. the worker claims the child run on the child session lane
2. the delegation status changes from `queued` to `running`
3. the child assistant executes in its own session with its own bound policy and tool profile
4. if the child creates outbound intent artifacts, Spec 015 suppresses direct user delivery from that child run
5. on completion, the system builds a bounded child result payload
6. the system appends one internal continuation message back into the parent session
7. the system queues one parent continuation run with `trigger_kind=delegation_result`

### Step 8: Show the child session

Run:

```bash
curl -s "$BASE/sessions/$CHILD_SESSION_ID"
curl -s "$BASE/sessions/$CHILD_SESSION_ID/messages"
curl -s "$BASE/sessions/$CHILD_SESSION_ID/runs"
```

Expected result:

- the child session shows:
  - `session_kind: "child"`
  - `parent_session_id` equal to the original parent session
  - `owner_agent_id: "repair-specialist"`

What this means:

- the specialist had its own durable workspace
- the child work did not overwrite or impersonate the parent session

### Step 9: Process the parent continuation run

In Terminal B, run the worker helper one more time:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Expected result:

- one run id prints
- this is the parent continuation run created from the child result

What the system is doing:

1. the worker claims the `delegation_result` run on the parent session lane
2. the parent session sees the durable system continuation message
3. the parent assistant resumes from parent transcript state instead of from an in-memory callback

### Step 10: Show the parent conversation after delegation

Run:

```bash
curl -s "$BASE/sessions/$SESSION_ID/messages"
curl -s "$BASE/sessions/$SESSION_ID/runs"
```

Expected result:

- the parent session now contains:
  - the original customer message
  - a normal parent assistant message from the initial run
  - an internal system message carrying the delegation result
  - a later parent assistant message after the continuation run

What this proves:

- child completion returns to the parent through durable transcript state
- the parent lane remains the only place where the user-facing conversation is continued

## 8. Main Demo B: Developer Verification Walkthrough

This section helps a technical audience verify the exact internal guarantees from Spec 015.

### Step 1: Inspect the child agent profile

Run:

```bash
curl -s "$BASE/agents/repair-specialist" -H "$AUTH"
```

Expected result:

- HTTP `200`
- the agent should show:
  - `policy_profile_key: "child-safe"`
  - `tool_profile_key: "child-tools"`

Developer takeaway:

- the child agent has its own durable profile binding
- the child does not inherit the parent tool profile or policy profile

### Step 2: Inspect the delegation detail record carefully

Run:

```bash
curl -s "$BASE/delegations/$DELEGATION_ID" -H "$AUTH"
```

Check these fields:

- `parent_session_id`
- `parent_message_id`
- `parent_run_id`
- `parent_tool_call_correlation_id`
- `parent_agent_id`
- `child_session_id`
- `child_message_id`
- `child_run_id`
- `child_agent_id`
- `parent_result_message_id`
- `parent_result_run_id`
- `status`
- `depth`
- `delegation_kind`

Developer takeaway:

- one row ties together the whole lineage from parent tool request to child execution to parent continuation

### Step 3: Inspect the delegation event stream

Run:

```bash
curl -s "$BASE/delegations/$DELEGATION_ID/events" -H "$AUTH"
```

Expected event progression:

- `queued`
- `started`
- `completed`

What this proves:

- lifecycle visibility is append-only
- the operator can reconstruct what happened without reading logs only

### Step 4: Inspect the child run

Run:

```bash
curl -s "$BASE/runs/$CHILD_RUN_ID"
curl -s "$BASE/diagnostics/runs/$CHILD_RUN_ID" -H "$AUTH"
```

Check for:

- `trigger_kind: "delegation_child"`
- `trigger_ref` equal to the delegation id
- `lane_key` equal to the child session id
- execution binding fields tied to `repair-specialist`

Developer takeaway:

- child execution is not a side channel
- it uses the same durable `execution_runs` lifecycle as every other queued turn

### Step 5: Inspect the parent continuation run

First get the `parent_result_run_id` from the delegation detail.

Then run:

```bash
curl -s "$BASE/runs/$PARENT_RESULT_RUN_ID"
curl -s "$BASE/diagnostics/runs/$PARENT_RESULT_RUN_ID" -H "$AUTH"
```

Check for:

- `trigger_kind: "delegation_result"`
- `trigger_ref` equal to the delegation id
- `lane_key` equal to the parent session id

Developer takeaway:

- parent continuation is a normal queued run
- it preserves parent lane ordering rather than bypassing the queue

### Step 6: Inspect the child trigger message

Run:

```bash
curl -s "$BASE/sessions/$CHILD_SESSION_ID/messages"
```

Look at the first child message.

You should see:

- `role: "system"`
- `external_message_id: null`
- a `sender_id` in the reserved internal namespace

Developer takeaway:

- the child run starts from one durable transcript row
- the child trigger is explicitly internal and auditable

### Step 7: Inspect the parent continuation message

Run:

```bash
curl -s "$BASE/sessions/$SESSION_ID/messages"
```

Look for the system message added after child completion.

You should see:

- `role: "system"`
- `external_message_id: null`
- `sender_id` using the `system:delegation_result:*` namespace

Developer takeaway:

- parent re-entry happens through transcript truth
- there is no hidden in-memory callback path

### Step 8: Verify child isolation

Use the child agent record and child run record to confirm:

- the child agent is `repair-specialist`
- the child policy profile is `child-safe`
- the child tool profile is `child-tools`
- the child session owner is not `default-agent`

What this proves:

- child policy, tool visibility, and sandbox identity remain isolated from the parent

### Step 9: Verify what Spec 015 intentionally does not do

During the walkthrough, note these boundaries:

- the child does not directly deliver user-visible outbound messages
- the child does not reuse the parent session id
- the child does not inherit the parent’s active approvals automatically
- the child result is summarized back into the parent; the full child transcript is not auto-promoted into the parent context window by default

These boundaries are just as important as the happy path because they are what keep delegation safe.

## 9. Quick Troubleshooting

### Problem: `repair-specialist` does not appear in `/agents`

Check:

- `PYTHON_CLAW_HISTORICAL_AGENT_PROFILE_OVERRIDES` includes `repair-specialist`
- `policy_profile_key` points to `child-safe`
- `tool_profile_key` points to `child-tools`
- you restarted the gateway after editing `.env`

### Problem: delegation creation fails with a policy error

Check:

- `delegation_enabled` is `true` in the parent policy profile
- `allowed_child_agent_ids` includes `repair-specialist`
- `max_delegation_depth` is at least `1`
- the helper command uses `parent_tool_profile_key="parent-tools"`

### Problem: the child run is never created

Check:

- the helper command committed successfully
- `/sessions/$SESSION_ID/delegations` returns a row
- `/delegations/$DELEGATION_ID` shows a `child_run_id`

### Problem: the parent continuation never appears

Check:

- you processed the child run with the worker helper
- the delegation detail now shows `parent_result_message_id` and `parent_result_run_id`
- you then processed the parent continuation run with the worker helper

## 10. What This Demo Proves

By the end of this walkthrough, you will have shown:

1. the system can create a durable child session for a specialist assistant
2. the child work uses the existing worker-owned run queue rather than a hidden parallel orchestrator
3. the parent and child agents remain isolated by session ownership and profile binding
4. child completion returns through one durable parent continuation message and one normal parent continuation run
5. operators can inspect who delegated to whom, when it started, and how it completed

That is the practical value of Spec 015:

- the application can now support bounded specialist delegation in a way that is durable, queue-safe, inspectable, and compatible with the existing transcript-first architecture
