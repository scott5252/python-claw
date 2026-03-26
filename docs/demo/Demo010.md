# Demo Guide: Spec 010 Typed Tool Schemas and Hybrid Intent Control

This guide shows a junior technical person how to:

1. Set up the application so Spec 010 behavior is active in a realistic workflow
2. Run the application through the normal gateway and worker path
3. Demonstrate a complete provider-backed, end-to-end customer-communication flow
4. Show that governed tool use now depends on backend-owned typed schemas and canonical validation
5. Show that `approve <proposal_id>` still bypasses model interpretation as a deterministic control action
6. Verify that schema identity and canonical validated arguments are persisted as durable evidence

The demo uses a real-world scenario:

- a bicycle repair shop employee asks the assistant to notify customer Maya that her repair order is ready for pickup

This is a good demo because it shows the main Spec 010 behaviors:

- provider-backed natural-language tool suggestion
- typed backend-owned tool schemas instead of loose argument hints
- one shared tool contract across prompt guidance, provider export, and runtime validation
- safe proposal creation for governed actions after schema validation
- deterministic approval handling for `approve` and `revoke`
- durable schema identity for approval and replay

Important note about the current implementation:

- this demo builds on the provider-backed runtime from Spec 009
- the default runtime mode is still `rule_based`, so you must explicitly enable provider mode
- tool execution is still backend-owned
- governed actions still require exact backend approval before execution
- the easiest way to prove the schema-specific behavior is to combine the normal chat flow with one optional developer verification step that reads durable records after the run

## 1. What You Will Run

For a successful local demo, you will run:

- PostgreSQL and Redis with Docker Compose
- database migrations
- the gateway API
- the local one-pass worker helper
- a real provider-backed model call through the gateway and worker path

You do not need the node runner for this demo.

## 2. Before You Start

You need:

- Python 3.11+
- `uv`
- Docker Desktop or another Docker runtime
- a valid OpenAI API key or another compatible endpoint that works with the current provider adapter settings

You should work from the project root:

```bash
cd /Users/scottcornell/src/my-projects/python-claw
```

## 3. Setup The Application

### Step 1: Prepare the environment file

If `.env` does not already exist, create it from `.env.example`:

```bash
cp .env.example .env
```

For this demo, make sure these values exist in `.env`:

```text
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=change-me
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=change-me-internal
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true

PYTHON_CLAW_RUNTIME_MODE=provider
PYTHON_CLAW_LLM_PROVIDER=openai
PYTHON_CLAW_LLM_API_KEY=replace-with-your-real-key
PYTHON_CLAW_LLM_MODEL=gpt-4o-mini
PYTHON_CLAW_LLM_TIMEOUT_SECONDS=30
PYTHON_CLAW_LLM_MAX_RETRIES=1
PYTHON_CLAW_LLM_TEMPERATURE=0.2
PYTHON_CLAW_LLM_MAX_OUTPUT_TOKENS=512
PYTHON_CLAW_LLM_TOOL_CALL_MODE=auto
PYTHON_CLAW_LLM_MAX_TOOL_REQUESTS_PER_TURN=4
PYTHON_CLAW_LLM_DISABLE_TOOLS=false
```

Optional if you use an OpenAI-compatible endpoint instead of the default API URL:

```text
PYTHON_CLAW_LLM_BASE_URL=https://your-compatible-endpoint.example/v1
```

What is happening in the system:

- the app loads configuration from `.env`
- provider mode enables the real provider-backed path instead of the rule-based adapter
- `PYTHON_CLAW_LLM_TOOL_CALL_MODE=auto` allows the backend to expose typed tool definitions to the model
- Spec 010 now ensures those tool definitions are backend-owned schemas, not informal prompt hints
- the diagnostics tokens protect `/health/ready` and `/diagnostics/*`

Important fail-closed behavior:

- if provider mode is selected and `PYTHON_CLAW_LLM_API_KEY` is missing, startup fails clearly
- if a provider tool call later contains malformed arguments, the backend rejects it safely instead of executing it

### Step 2: Install Python dependencies

Run:

```bash
uv sync --group dev
```

What is happening in the system:

- `uv` creates or updates the local virtual environment
- Python packages needed by the gateway, worker, SQLAlchemy, FastAPI, tests, and provider SDK are installed

### Step 3: Start local infrastructure

Run:

```bash
docker compose --env-file .env up -d
```

Optional checks:

```bash
docker compose ps
docker compose logs postgres
docker compose logs redis
```

What is happening in the system:

- PostgreSQL starts and becomes the durable store for sessions, messages, runs, approvals, manifests, artifacts, and schema-aware governance records
- Redis also starts because it is part of the local development stack, even though this demo path does not depend on it directly

### Step 4: Apply the database schema

Run:

```bash
uv run alembic upgrade head
```

What is happening in the system:

- Alembic creates all current tables through Spec 010
- after this step, the gateway can persist inbound messages and the worker can process queued runs through the provider-backed, schema-aware runtime path

## 4. Run The Application

Use three terminals for the main demo.

### Terminal A: Start the gateway API

Run:

```bash
uv run uvicorn apps.gateway.main:app --reload
```

What is happening in the system:

- FastAPI starts on `http://127.0.0.1:8000`
- the app builds shared services for sessions, execution runs, health, diagnostics, and the provider-backed model adapter
- the tool registry now exposes typed schemas for `echo_text`, `send_message`, and `remote_exec`

### Terminal B: Keep a worker terminal ready

You will run this command after each user message:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What is happening in the system when you run it:

- the helper opens a database session
- it claims at most one eligible `execution_runs` row
- it assembles transcript context and backend-owned prompt data
- it invokes the provider-backed runtime
- it validates any proposed tool request against the backend-owned schema before approval lookup or execution
- it commits and exits

### Terminal C: Use curl to simulate the user chat

Set these helpful variables:

```bash
BASE=http://127.0.0.1:8000
AUTH='Authorization: Bearer change-me'
```

Verify the gateway is live:

```bash
curl $BASE/health/live
```

Expected result:

- HTTP 200
- JSON with `"status": "ok"`

Verify readiness:

```bash
curl $BASE/health/ready -H "$AUTH"
```

Expected result:

- HTTP 200
- a PostgreSQL check with status `ok`

What is happening in the system:

- `/health/live` only checks that the process is running
- `/health/ready` also checks that the app can talk to PostgreSQL and that the application can finish startup in the selected runtime mode

## Main Demo

This section is the primary end-to-end demo for most audiences. It shows a realistic provider-backed governed action and the Spec 010 safety behavior around typed tool schemas and hybrid intent control.

### Scenario

A shop employee is helping customer Maya and wants the assistant to send a pickup-ready notification.

We will demonstrate one approval cycle across three user messages:

1. The employee asks in normal language for the customer notification.
2. The model suggests a governed outbound action.
3. The backend validates the request against the typed `send_message` schema and creates a proposal instead of executing it.
4. The employee approves the proposal with a deterministic `approve <proposal_id>` command.
5. The employee retries the same request.
6. The approved outbound action executes through the normal backend-owned tool path.

This is a realistic workflow because a production assistant often uses natural language on the front end but still requires exact backend approval for externally impactful actions.

## Part A: Create A Schema-Validated Governed Request

### Step 1: Submit the first natural-language request

In Terminal C, run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "bike-shop-demo",
    "external_message_id": "demo010-msg-1",
    "sender_id": "employee-alex",
    "content": "Please let Maya know that bike repair order BR-1042 is complete and ready for pickup today before 6 PM.",
    "peer_id": "customer-maya"
  }'
```

Expected result:

- HTTP 202
- JSON similar to:

```json
{
  "session_id": "....",
  "message_id": 1,
  "run_id": "....",
  "status": "queued",
  "dedupe_status": "accepted",
  "trace_id": "...."
}
```

Write down:

- `session_id`
- `run_id`
- `trace_id`

What is happening in the system:

1. The gateway validates the inbound message.
2. It checks `inbound_dedupe` to make sure `demo010-msg-1` has not already been processed.
3. It resolves or creates a durable session.
4. It appends the user message to `messages`.
5. It creates one queued `execution_runs` row.
6. It returns quickly with `202 Accepted`.

At this point, the work is queued but not yet executed.

### Step 2: Process the queued run

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What is happening in the system:

1. The worker claims the queued run.
2. The graph assembles transcript context and backend-owned prompt data.
3. The provider-backed model receives prompt-visible tool guidance that came from the same typed tool definitions used by the runtime.
4. The model may suggest `send_message` for this request.
5. The backend validates the raw tool arguments against the fixed-shape `send_message` schema.
6. Because the request is schema-valid but not yet approved, the backend creates a governance proposal instead of executing the tool.
7. The graph appends an assistant message telling the user how to approve the proposal.
8. The worker persists the manifest and completes the run.

Important Spec 010 point:

- the model is not trusted to define argument semantics
- the provider may suggest `send_message`, but the backend still decides whether the arguments are valid and whether the action can execute

### Step 3: Read the transcript

In Terminal C, run:

```bash
curl -s $BASE/sessions/<SESSION_ID>/messages?limit=20
```

Replace `<SESSION_ID>` with the `session_id` from Step 1.

Expected result:

- the transcript now includes an assistant message that says approval is required
- that assistant message includes a `proposal_id` and an `approve <proposal_id>` instruction

### Step 4: Read the pending approval

In Terminal C, run:

```bash
curl -s $BASE/sessions/<SESSION_ID>/governance/pending
```

Expected result:

- one pending proposal
- `capability_name` should be `send_message`
- `typed_action_id` should be `tool.send_message`
- the canonical parameters should contain the final outbound text

Write down the `proposal_id`.

What this proves:

- the request made it through schema validation
- the backend canonicalized the arguments before creating the proposal
- the governed record, not the model output, is now the authoritative requested-action artifact

## Part B: Show Hybrid Intent Control With Deterministic Approval

### Step 5: Submit the approval command

In Terminal C, run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "bike-shop-demo",
    "external_message_id": "demo010-msg-2",
    "sender_id": "employee-alex",
    "content": "approve <PROPOSAL_ID>",
    "peer_id": "customer-maya"
  }'
```

Replace `<PROPOSAL_ID>` with the value from the pending approval response.

Expected result:

- HTTP 202
- same `session_id`
- a new `run_id`

### Step 6: Process the approval run

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What is happening in the system:

1. The worker claims the new run.
2. The graph classifies the message as a deterministic approval decision before asking the model to interpret it.
3. The backend creates or updates approval and activation state.
4. The graph appends an assistant confirmation message.
5. The worker persists the manifest and completes the run.

Important Spec 010 point:

- `approve <proposal_id>` does not rely on model interpretation
- this is the hybrid intent-control part of the spec
- high-risk administrative commands remain deterministic even though conversational requests can still use the provider-backed path

## Part C: Retry The Approved Request And Execute It

### Step 7: Retry the same natural-language request

In Terminal C, run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "bike-shop-demo",
    "external_message_id": "demo010-msg-3",
    "sender_id": "employee-alex",
    "content": "Please let Maya know that bike repair order BR-1042 is complete and ready for pickup today before 6 PM.",
    "peer_id": "customer-maya"
  }'
```

Expected result:

- HTTP 202
- same `session_id`
- a new `run_id`

### Step 8: Process the approved send run

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What is happening in the system:

1. The worker claims the run.
2. The provider-backed model again suggests the outbound action.
3. The backend validates the suggested tool arguments against the `send_message` schema again.
4. The backend canonicalizes the validated arguments again.
5. It checks approval using the typed action plus canonical validated arguments plus schema identity.
6. The exact approval match is found.
7. The `send_message` tool executes through the normal backend-owned path.
8. The graph appends tool artifacts and the assistant message.
9. The dispatcher creates outbound delivery rows.
10. The local `webchat` adapter returns a synthetic success result, so the delivery is marked `sent`.

### Step 9: Read the final transcript

In Terminal C, run:

```bash
curl -s $BASE/sessions/<SESSION_ID>/messages?limit=30
```

Expected result:

- the transcript includes:
  - the original natural-language send request
  - the approval-required assistant response
  - the deterministic approval message
  - the final successful send turn
- the newest assistant reply should be similar to:

```text
Prepared outbound message: Hello Maya, your bike repair order BR-1042 is complete and ready for pickup today before 6 PM.
```

## Part D: Show The Durable Evidence

### Step 10: Show all runs for the session

In Terminal C, run:

```bash
curl -s $BASE/sessions/<SESSION_ID>/runs
```

Expected result:

- three completed runs for:
  - the first natural-language request
  - the deterministic approval
  - the retried natural-language request

### Step 11: Show delivery diagnostics

In Terminal C, run:

```bash
curl -s $BASE/diagnostics/deliveries -H "$AUTH"
```

Expected result:

- one delivery row for the successful approved send path
- status `sent`

### Step 12: Show continuity diagnostics

In Terminal C, run:

```bash
curl -s $BASE/diagnostics/sessions/<SESSION_ID>/continuity -H "$AUTH"
```

Expected result:

- recent manifests exist for the session
- the latest manifest reflects the successful turn
- the continuity record proves the turn executed on the normal backend-owned path

## Part E: Optional Developer Verification For Spec 010 Evidence

This section is most useful for developers. Non-developers can skip it.

### Step 13: Read schema-aware governance and artifact data directly

In a terminal, run:

```bash
read "SESSION_ID?Session ID: "
SESSION_ID="$SESSION_ID" uv run python - <<'PY'
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(Path(".env"))
engine = create_engine(os.environ["PYTHON_CLAW_DATABASE_URL"])
session_id = os.environ["SESSION_ID"]

with engine.connect() as conn:
    version_payload = conn.execute(
        text("""
            select rv.resource_payload
            from resource_versions rv
            join resource_proposals rp on rp.latest_version_id = rv.id
            where rp.session_id = :session_id
            order by rp.created_at desc
            limit 1
        """),
        {"session_id": session_id},
    ).scalar_one()

    artifact_rows = conn.execute(
        text("""
            select artifact_kind, capability_name, payload_json
            from session_artifacts
            where session_id = :session_id
            order by id asc
        """),
        {"session_id": session_id},
    ).fetchall()

print("Latest governed resource payload:")
print(json.dumps(json.loads(version_payload), indent=2, sort_keys=True))
print()
print("Session artifacts:")
for artifact_kind, capability_name, payload_json in artifact_rows:
    print(f"{artifact_kind} | {capability_name}")
    print(json.dumps(json.loads(payload_json), indent=2, sort_keys=True))
    print()
PY
```

What you should see:

- the latest governed `resource_payload` includes:
  - `capability_name`
  - `typed_action_id`
  - `tool_schema_name`
  - `tool_schema_version`
  - `arguments`
- the successful `tool_proposal` or `tool_result` artifact payloads should include canonical argument metadata for the executed turn

Why this matters:

- it proves the governed durable record now carries schema identity
- it shows the approval and replay path no longer depends only on raw arguments
- it demonstrates that schema identity is not just prompt metadata

### Step 14: Run the focused Spec 010 tests

Run:

```bash
uv run pytest tests/test_typed_tool_schemas.py -q
```

What this proves:

- fixed-shape schemas reject unknown fields
- `remote_exec` only accepts flat scalar JSON values
- schema version changes alter approval identity without changing `typed_action_id`
- provider tool export and graph-time validation share the same backend-owned schema source
- schema-invalid governed requests do not create proposals

## 5. Why This Demo Matters

This demo proves the most important Spec 010 outcomes:

- natural-language requests can still use the provider-backed assistant path
- provider-suggested tool use is now constrained by backend-owned typed schemas
- approval creation only happens after schema validation succeeds
- exact approval identity now depends on canonical validated arguments plus schema identity
- deterministic `approve` commands still bypass model interpretation
- execution, persistence, delivery, and diagnostics remain backend-owned

## 6. Common Mistakes And Fixes

### Mistake: the gateway fails to start in provider mode

Most likely causes:

- `PYTHON_CLAW_RUNTIME_MODE=provider` is set but `PYTHON_CLAW_LLM_API_KEY` is missing
- `PYTHON_CLAW_LLM_MODEL` is empty or invalid
- dependencies were not installed after the provider SDK was added

Fix:

```bash
uv sync --group dev
```

Then confirm `.env` includes:

```text
PYTHON_CLAW_RUNTIME_MODE=provider
PYTHON_CLAW_LLM_API_KEY=your-real-key
PYTHON_CLAW_LLM_MODEL=gpt-4o-mini
```

### Mistake: posting to `/inbound/message` returns 202 but no assistant reply appears

Cause:

- the gateway only queued the work
- the worker pass has not been run yet

Fix:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

### Mistake: the governed send request does not create a proposal

Possible cause:

- the model produced plain text instead of a tool suggestion on that turn

What to do:

- retry with slightly more explicit wording such as:

```text
Please send Maya a message saying bike repair order BR-1042 is complete and ready for pickup today before 6 PM.
```

- keep `PYTHON_CLAW_LLM_TOOL_CALL_MODE=auto`
- keep `PYTHON_CLAW_LLM_DISABLE_TOOLS=false`

### Mistake: the approval message does not behave deterministically

Expected behavior:

- `approve <proposal_id>` should bypass provider interpretation and directly activate the proposal

If it does not:

- verify you copied the exact `proposal_id`
- verify the proposal is still pending in `/sessions/<SESSION_ID>/governance/pending`

### Mistake: the optional developer verification does not show `tool_schema_name`

Possible causes:

- you queried the wrong session
- you inspected an older proposal from before the Spec 010 change
- the demo request never reached proposal creation

Fix:

- use the current `session_id`
- rerun the governed send path from the start of this demo
- confirm `/sessions/<SESSION_ID>/governance/pending` shows the expected proposal first

## 7. Success Checklist

By the end of the demo, you should be able to confirm:

```text
[ ] .env is present and includes provider and diagnostics settings
[ ] uv sync --group dev completed successfully
[ ] docker compose --env-file .env up -d completed successfully
[ ] uv run alembic upgrade head completed successfully
[ ] the gateway starts successfully in provider mode
[ ] /health/live returns 200
[ ] /health/ready returns 200 with Authorization header
[ ] the first natural-language send request creates a pending governed proposal
[ ] the pending proposal shows canonical parameters for the outbound message
[ ] approve <proposal_id> activates the governed action without relying on model interpretation
[ ] retrying the same request produces Prepared outbound message: ...
[ ] diagnostics/deliveries shows a sent delivery
[ ] optional: the resource payload shows tool_schema_name and tool_schema_version
[ ] optional: tests/test_typed_tool_schemas.py passes
```

If all of those are true, you have successfully demonstrated Spec 010 in a realistic end-to-end workflow.
