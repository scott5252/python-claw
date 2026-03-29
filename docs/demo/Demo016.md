# Demo Guide: Spec 016 Human Handoff, Collaboration, and Approval UX

This guide shows how to demo Spec 016 in a way that works for:

1. a non-developer who wants to see the assistant safely hand a conversation to a human operator, pause automation, resume automation, and use a clearer approval experience
2. a developer who wants to verify the durable session state, blocked runs, suppression behavior, operator notes, collaboration history, and approval prompt records behind that experience

The demo covers:

1. enabling the collaboration and approval settings needed for a clean local demo
2. creating a normal user-facing primary session
3. showing how a human operator takes over that session
4. proving that new inbound work is still appended to transcript state but is queued as a durable `blocked` run instead of normal automated work
5. showing how resuming the session releases blocked work back into the normal queue
6. demonstrating operator assignment and internal notes
7. demonstrating the race where a run was already queued, but a takeover wins before dispatch, so the assistant reply is suppressed instead of delivered
8. demonstrating the structured approval prompt flow on webchat, including prompt inspection and approval decision handling
9. inspecting the admin and diagnostics surfaces that make the new behavior auditable

The demo uses one simple real-world story:

- a bike shop uses the assistant for customer chat
- most customer messages are handled automatically while the session stays in `assistant_active`
- when a sensitive or complex thread needs manual handling, an operator takes over the conversation
- while takeover is active, new user messages are preserved in the transcript but automation does not continue responding
- once the operator is ready, they resume automation and the queued blocked work is released safely
- when an action requires approval, the system creates a durable approval prompt and records who approved or denied it

Important note about this demo:

- the local demo is intentionally deterministic
- the easiest way to show structured approval prompts in this codebase is through the authenticated webchat flow
- the easiest way to show handoff and blocked-run behavior is through the normal inbound API plus the admin collaboration routes
- this keeps the walkthrough reliable for both mixed audiences and technical reviewers

## 1. What You Will Run

For the main local demo, you will run:

- PostgreSQL with Docker Compose
- database migrations
- the gateway API
- the worker helper
- `curl` commands for user, operator, and diagnostics reads

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

1. a customer starts a conversation with the assistant
2. the assistant is active by default, so normal inbound work queues and runs automatically
3. an operator takes over the session because the thread needs human handling
4. while the session is under takeover, the customer can still send messages, but those messages create `blocked` runs instead of normal queued runs
5. the operator adds notes and assignment metadata so other operators can understand the case
6. the operator resumes automation, which releases the blocked work in deterministic order
7. in a separate approval example, a webchat user triggers an approval-required action
8. the system records a durable approval prompt and exposes structured approval actions for that prompt
9. an approval decision is recorded through a backend-owned path, and the prompt history remains auditable

This is what Spec 016 adds to the application:

- durable `automation_state` on sessions
- durable operator assignment metadata
- append-only operator notes
- append-only collaboration events
- durable `blocked` execution runs with an explicit blocked reason
- best-effort dispatch-time suppression when takeover wins the race after a run is already queued
- durable approval prompt rows with one-time action tokens
- admin write routes for takeover, pause, resume, assignment, notes, and governance decisions
- diagnostics visibility into blocked and suppressed work

## 4. Setup The Application

### Step 1: Prepare `.env`

If `.env` does not exist yet:

```bash
cp .env.example .env
```

For this demo, make sure these values exist in `.env`.

These are the minimum values you should set for a clean Spec 016 demo:

```text
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=change-me
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=change-me-internal
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true

PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent
PYTHON_CLAW_RUNTIME_MODE=rule_based

PYTHON_CLAW_DEFAULT_ASSIGNMENT_QUEUE_KEY=support
PYTHON_CLAW_APPROVAL_ACTION_TOKEN_TTL_SECONDS=3600
PYTHON_CLAW_SLACK_INTERACTIVE_APPROVALS_ENABLED=false
PYTHON_CLAW_TELEGRAM_INTERACTIVE_APPROVALS_ENABLED=false
PYTHON_CLAW_WEBCHAT_INTERACTIVE_APPROVALS_ENABLED=true
PYTHON_CLAW_TAKEOVER_SUPPRESSES_INFLIGHT_DISPATCH=true
PYTHON_CLAW_OPERATOR_NOTE_MAX_CHARS=2000

PYTHON_CLAW_CHANNEL_ACCOUNTS=[{"channel_account_id":"acct","channel_kind":"slack","mode":"fake"},{"channel_account_id":"acct","channel_kind":"telegram","mode":"fake"},{"channel_account_id":"acct","channel_kind":"webchat","mode":"fake"},{"channel_account_id":"acct-1","channel_kind":"slack","mode":"fake"},{"channel_account_id":"acct-1","channel_kind":"telegram","mode":"fake"},{"channel_account_id":"acct-1","channel_kind":"webchat","mode":"fake"}]
```

What each important setting does in this demo:

- `PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent`
  - this is the assistant that owns the primary customer session
- `PYTHON_CLAW_RUNTIME_MODE=rule_based`
  - this keeps the demo local and deterministic
- `PYTHON_CLAW_DEFAULT_ASSIGNMENT_QUEUE_KEY=support`
  - operator assignment calls can use this queue label as the default workbucket
- `PYTHON_CLAW_APPROVAL_ACTION_TOKEN_TTL_SECONDS=3600`
  - structured approval links and actions remain valid for one hour in this demo
- `PYTHON_CLAW_WEBCHAT_INTERACTIVE_APPROVALS_ENABLED=true`
  - the webchat approval example will show a durable prompt row with action tokens
- `PYTHON_CLAW_TAKEOVER_SUPPRESSES_INFLIGHT_DISPATCH=true`
  - this is the setting that lets you show the new suppression behavior when takeover happens before dispatch
- `PYTHON_CLAW_OPERATOR_NOTE_MAX_CHARS=2000`
  - this keeps operator notes bounded and audit-friendly

Important formatting notes:

- `PYTHON_CLAW_CHANNEL_ACCOUNTS` must be valid JSON
- safest option: keep each JSON value on one line exactly as shown above

### Step 2: Install Python dependencies

Run:

```bash
uv sync --group dev
```

What the system is doing:

- `uv` creates or updates the local virtual environment
- the FastAPI app, Alembic, SQLAlchemy, and test helpers are installed
- this step does not change application state yet

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
- the demo uses PostgreSQL so the durable queue and admin reads behave like the normal local operational path

### Step 4: Apply database migrations

Run:

```bash
uv run alembic upgrade head
```

Why this matters for Spec 016:

- the new migration adds the session collaboration fields
- the new migration adds blocked-run fields on `execution_runs`
- the new migration adds `session_operator_notes`
- the new migration adds `session_collaboration_events`
- the new migration adds `approval_action_prompts`

## 5. Run The Application

Use three terminals for the demo.

### Terminal A: Start the gateway

Run:

```bash
uv run uvicorn apps.gateway.main:app --reload
```

The gateway starts on `http://127.0.0.1:8000`.

Expected startup behavior:

- the application loads `.env`
- settings validation confirms the collaboration and approval configuration is valid
- bootstrap creates or validates the default agent records

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
- it processes exactly one run
- it releases the lane and global leases

Why this is manual in the demo:

- it keeps each queue transition easy to explain
- it makes blocked and resumed work visible one step at a time

### Terminal C: Use `curl`

Set these shell variables once:

```bash
BASE=http://127.0.0.1:8000
AUTH='Authorization: Bearer change-me'
INTERNAL='X-Internal-Service-Token: change-me-internal'
OP='X-Operator-Id: operator-alex'
```

Verify the service:

```bash
curl $BASE/health/live
curl $BASE/health/ready -H "$AUTH"
```

Expected result:

- `GET /health/live` returns HTTP `200`
- `GET /health/ready` returns HTTP `200` when the bearer token is correct

What this means:

- the gateway is running
- operator-protected readiness checks are working

## 6. Variables You Will Reuse

Write these down as you go:

- `SESSION_ID`
- `FIRST_RUN_ID`
- `BLOCKED_RUN_ID`
- `RACE_SESSION_ID`
- `RACE_RUN_ID`
- `APPROVAL_SESSION_ID`
- `APPROVAL_PROPOSAL_ID`

## 7. Main Demo A: Non-Developer Walkthrough

This path is for a mixed audience. It focuses on the user story first and the durable system behavior second.

### Scenario

A customer begins chatting with the bike shop assistant. The assistant handles the conversation automatically at first. Then an operator takes over the session, adds a note, and pauses automation while the customer sends another message. That new message is preserved, but the assistant does not continue replying until the operator resumes automation.

### Step 1: Start a normal customer conversation

Run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct",
    "external_message_id": "demo016-msg-001",
    "sender_id": "customer-riley",
    "content": "Hi, do you service hydraulic brakes on short notice?",
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
- `status` should be `queued`
- `dedupe_status` should be `accepted`

Write down:

- `SESSION_ID`
- `FIRST_RUN_ID`

What the result means:

1. the gateway created or reused the canonical session for this customer
2. the user message was appended to the durable transcript
3. because the session is still in the default `assistant_active` state, the system created a normal queued execution run
4. nothing about human takeover has happened yet

### Step 2: Show the default collaboration state

Replace `replace-with-session-id` with your real `SESSION_ID`, then run:

```bash
curl -s "$BASE/sessions/replace-with-session-id/automation" -H "$AUTH"
```

Expected result:

- HTTP `200`
- JSON showing:
  - `automation_state: "assistant_active"`
  - `assigned_operator_id: null`
  - `assigned_queue_key: null`
  - `collaboration_version: 1`
  - `blocked_run_count: 0`

What this means:

- every primary session now has explicit automation state
- new sessions start in `assistant_active`
- there is no operator assignment yet
- the optimistic concurrency version starts at `1`

### Step 3: Let the worker process the initial automated run

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Expected result:

- one run id prints
- it should match the first run id or be that same queued run

What the result means:

1. the worker claimed the first queued run
2. the assistant processed the initial message
3. because the session was still `assistant_active`, the run was eligible for normal execution

### Step 4: Show the session transcript

Run:

```bash
curl -s "$BASE/sessions/$SESSION_ID/messages"
```

Expected result:

- HTTP `200`
- a message list containing at least:
  - the original user message
  - one assistant reply

What this means:

- the initial turn behaved like normal pre-handoff automation
- the assistant transcript row was persisted because delivery was not blocked or suppressed

### Step 5: Have a human operator take over the session

Run:

```bash
curl -s "$BASE/sessions/$SESSION_ID/takeover" \
  -H "$AUTH" \
  -H "$OP" \
  -H 'Content-Type: application/json' \
  -d '{
    "expected_collaboration_version": 1,
    "reason": "Customer asked for manual service confirmation",
    "note": "Operator is verifying same-day brake availability with the repair desk."
  }'
```

Expected result:

- HTTP `200`
- JSON showing:
  - `automation_state: "human_takeover"`
  - `collaboration_version: 2`
  - `blocked_run_count: 0`

What the result means:

1. the operator mutation succeeded because the supplied `expected_collaboration_version` matched the stored value
2. the session state changed durably from `assistant_active` to `human_takeover`
3. the system recorded the operator note and collaboration event
4. any new user-visible automation targeting this primary session will now be blocked instead of queued normally

### Step 6: Show the note and collaboration history

Run:

```bash
curl -s "$BASE/sessions/$SESSION_ID/notes" -H "$AUTH"
```

Then run:

```bash
curl -s "$BASE/sessions/$SESSION_ID/collaboration" -H "$AUTH"
```

Expected result:

- notes endpoint returns one internal note written by `operator-alex`
- collaboration endpoint returns events including:
  - `takeover`
  - `note_created` if the note was stored separately in your run order

What this means:

- operator notes are durable and internal-only
- the system keeps append-only collaboration history rather than hiding handoff state in ad hoc transcript text

### Step 7: Add assignment metadata

Run:

```bash
curl -s "$BASE/sessions/$SESSION_ID/assign" \
  -H "$AUTH" \
  -H "$OP" \
  -H 'Content-Type: application/json' \
  -d '{
    "expected_collaboration_version": 2,
    "assigned_operator_id": "operator-alex",
    "assigned_queue_key": "support-escalations",
    "reason": "Alex owns this manual follow-up"
  }'
```

Expected result:

- HTTP `200`
- JSON showing:
  - `automation_state: "human_takeover"`
  - `assigned_operator_id: "operator-alex"`
  - `assigned_queue_key: "support-escalations"`
  - `collaboration_version: 3`

What this means:

- assignment is durable metadata
- assignment does not itself imply automation is active or inactive
- the session can stay in takeover while also carrying queue and operator ownership data

### Step 8: Send another customer message while takeover is active

Run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct",
    "external_message_id": "demo016-msg-002",
    "sender_id": "customer-riley",
    "content": "I also need to know whether I should bring the bike in clean and whether I need to leave it all day.",
    "peer_id": "customer-riley"
  }'
```

Expected result:

- HTTP `202 Accepted`
- JSON containing a new `run_id`
- `status` should now be `blocked`

Write down:

- `BLOCKED_RUN_ID`

What the result means:

1. the new user message was still accepted and appended to the transcript
2. the system did not discard or reject the customer’s message just because takeover is active
3. instead of creating a normal queued run, the system created a durable `blocked` run with an explicit reason tied to the collaboration state

### Step 9: Show the blocked run

Run:

```bash
curl -s "$BASE/runs/$BLOCKED_RUN_ID"
```

Expected result:

- HTTP `200`
- JSON showing:
  - `status: "blocked"`
  - `blocked_reason: "automation_state:human_takeover"`
  - `blocked_at` populated

What this means:

- blocked work is not just an in-memory decision
- it is durable queue state that can be inspected later by operators and diagnostics

### Step 10: Prove that blocked work does not execute

In Terminal B, run the worker helper once:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Expected result:

- the helper prints `None`
- or it processes some unrelated eligible work if other demo activity exists
- it must not process the blocked run for this session

What this means:

- the worker claim path excludes blocked runs
- human takeover is enforced at queue time, not just at the UI layer

### Step 11: Show the transcript while the run is blocked

Run:

```bash
curl -s "$BASE/sessions/$SESSION_ID/messages"
```

Expected result:

- HTTP `200`
- the second user message is present
- there is no assistant reply for that second message yet

What this means:

- transcript truth and automation state are now separated correctly
- the user’s message is preserved
- the assistant has not responded because the system is honoring takeover

### Step 12: Resume automation

Run:

```bash
curl -s "$BASE/sessions/$SESSION_ID/resume" \
  -H "$AUTH" \
  -H "$OP" \
  -H 'Content-Type: application/json' \
  -d '{
    "expected_collaboration_version": 3,
    "reason": "Repair desk answered the operator questions"
  }'
```

Expected result:

- HTTP `200`
- JSON showing:
  - `automation_state: "assistant_active"`
  - `collaboration_version: 4`
  - `blocked_run_count: 0`

What the result means:

1. the session is automating again
2. the resume operation released the blocked run back to normal queue state
3. no duplicate run was created; the same durable run row was transitioned out of `blocked`

### Step 13: Process the released run

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Expected result:

- one run id prints
- it should be the blocked run id that was just released

Then verify it:

```bash
curl -s "$BASE/runs/$BLOCKED_RUN_ID"
```

Expected result:

- `status` should now be `completed`
- `blocked_reason` should be cleared

What this means:

- resume does not create replacement work
- it reuses the blocked run row and returns it to normal queue processing

### Step 14: Show the final transcript

Run:

```bash
curl -s "$BASE/sessions/$SESSION_ID/messages"
```

Expected result:

- the transcript now includes:
  - the first user message
  - the first assistant reply
  - the second user message
  - the follow-up assistant reply after resume

What this means for a non-developer:

- the system paused automation safely
- the customer’s second message was preserved
- once the operator resumed automation, the assistant continued from durable state instead of losing context

## 8. Main Demo B: Dispatch Suppression Race

This path demonstrates a more subtle Spec 016 feature: a run was already created, but takeover happened before outbound dispatch. The system should suppress delivery instead of leaking a user-visible reply.

### Scenario

The customer sends a message. Before the worker processes and dispatches the reply, an operator takes over the session. The assistant may still finish its computation, but the outbound result must not be delivered as a normal assistant transcript message.

### Step 1: Create a fresh session for the race demo

Run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct",
    "external_message_id": "demo016-race-001",
    "sender_id": "customer-jordan",
    "content": "Can you quote me for a brake bleed today?",
    "peer_id": "customer-jordan"
  }'
```

Expected result:

- HTTP `202 Accepted`
- JSON with a new session id and run id
- `status: "queued"`

Write down:

- `RACE_SESSION_ID`
- `RACE_RUN_ID`

### Step 2: Take over the session before the worker runs

Run:

```bash
curl -s "$BASE/sessions/$RACE_SESSION_ID/takeover" \
  -H "$AUTH" \
  -H "$OP" \
  -H 'Content-Type: application/json' \
  -d '{
    "expected_collaboration_version": 1,
    "reason": "Operator wants to answer this quote manually"
  }'
```

Expected result:

- HTTP `200`
- `automation_state: "human_takeover"`

### Step 3: Process the queued run anyway

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Expected result:

- the worker still prints one run id
- it should be the race run id

What this means:

- Spec 016 does not try to kill work in the middle of execution
- it allows already-claimed or already-eligible work to finish the graph step, then re-checks collaboration state before dispatch

### Step 4: Inspect the transcript and collaboration history

Run:

```bash
curl -s "$BASE/sessions/$RACE_SESSION_ID/messages"
```

Then run:

```bash
curl -s "$BASE/sessions/$RACE_SESSION_ID/collaboration" -H "$AUTH"
```

Expected result:

- the transcript contains only the user message
- there is no new assistant transcript row for the suppressed reply
- the collaboration events include a `dispatch_suppressed` event

What this means:

- the assistant output was intentionally not persisted as a normal user-visible assistant message
- the system preserved the audit trail without polluting future model context with undelivered content

### Step 5: Inspect diagnostics for the suppressed run

Run:

```bash
curl -s "$BASE/diagnostics/runs/$RACE_RUN_ID" -H "$AUTH"
```

Expected result:

- HTTP `200`
- run details show the execution binding and correlated artifacts
- `correlated_artifacts` should include:
  - a delivery id
  - a collaboration event id

What this means:

- even suppressed work is still diagnosable
- operators can understand why the run completed but did not produce a visible assistant reply

## 9. Main Demo C: Structured Approval Prompt Walkthrough

This path demonstrates the new approval UX in a deterministic way using webchat. In this implementation, webchat is the clearest local surface for showing structured prompts and approval actions.

### Scenario

A webchat user asks the assistant to perform an approval-required action. The assistant creates a durable governance proposal and a durable approval prompt. The prompt can then be inspected and approved through backend-owned approval paths.

### Step 1: Send an approval-required webchat message

Run:

```bash
curl -s "$BASE/providers/webchat/accounts/acct/messages" \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "actor_id": "web-user-1",
    "content": "send hello channel",
    "peer_id": "web-user-1",
    "stream_id": "demo016-webchat-stream"
  }'
```

Expected result:

- HTTP `202 Accepted`
- JSON containing:
  - `session_id`
  - `message_id`
  - `run_id`
  - `status`
  - `external_message_id`

Write down:

- `APPROVAL_SESSION_ID`

### Step 2: Process the webchat run

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Expected result:

- one run id prints

What the system is doing:

1. the assistant classifies `send hello channel` as a governed action
2. because no exact approval exists yet, the backend creates a governance proposal
3. because this is webchat, the backend also creates a structured approval prompt artifact and materializes a durable approval prompt row after the assistant message is known

### Step 3: Inspect pending approvals

Run:

```bash
curl -s "$BASE/sessions/$APPROVAL_SESSION_ID/governance/pending"
```

Expected result:

- HTTP `200`
- one pending proposal entry showing:
  - `proposal_id`
  - `capability_name: "send_message"`
  - `typed_action_id: "tool.send_message"`
  - `canonical_params`
  - `next_action`

Write down:

- `APPROVAL_PROPOSAL_ID`

What this means:

- the canonical approval contract from earlier governance specs still exists
- Spec 016 adds a richer prompt layer on top of that contract rather than replacing it

### Step 4: Inspect the structured approval prompt

Run:

```bash
curl -s "$BASE/sessions/$APPROVAL_SESSION_ID/approval-prompts" -H "$AUTH"
```

Expected result:

- HTTP `200`
- one prompt row showing:
  - `proposal_id`
  - `message_id`
  - `channel_kind: "webchat"`
  - `status: "pending"`
  - `expires_at`
  - `presentation_payload_json`

What the result means:

- the approval prompt is durable
- it is tied to a real session and a real assistant message
- the backend stores prompt lifecycle state, not just a text instruction in the transcript

### Step 5: Inspect the prompt payload presented to webchat

Look at the `presentation_payload_json` field from the previous command.

Expected content:

- `proposal_id`
- `capability_name`
- `typed_action_id`
- `canonical_params_json`
- `supported_decisions`
- `fallback_instructions`
- `actions.approve.token`
- `actions.deny.token`

What this means:

- the backend generated a structured approval payload
- approval actions are token-based and backend-owned
- the payload is more explicit than a plain “reply approve …” instruction, while still preserving fallback guidance

### Step 6: Approve the prompt through the admin API

Run:

```bash
curl -s "$BASE/sessions/$APPROVAL_SESSION_ID/governance/$APPROVAL_PROPOSAL_ID/decision" \
  -H "$AUTH" \
  -H "$OP" \
  -H 'Content-Type: application/json' \
  -d '{
    "decision": "approve"
  }'
```

Expected result:

- HTTP `200`
- JSON showing:
  - `proposal_id`
  - `decision: "approve"`
  - `outcome: "approved"`
  - `approval_id`

What this means:

1. the decision flowed through one backend-owned approval decision path
2. the proposal was approved
3. the approval record and prompt state were updated together

### Step 7: Confirm the prompt lifecycle changed

Run:

```bash
curl -s "$BASE/sessions/$APPROVAL_SESSION_ID/approval-prompts" -H "$AUTH"
```

Expected result:

- the same prompt row now shows `status: "approved"`

What this means:

- prompt rows are not write-only artifacts
- they hold a durable lifecycle state that operators can inspect later

### Step 8: Optional webchat approval-action replay demo

If you want to show the user-facing decision path instead of the admin path, do this before the admin approval step or use a fresh webchat approval prompt.

Important note:

- do not manually guess or retype the token from an escaped JSON blob if you can avoid it
- safest option: extract the token with a helper command so the exact raw token string is submitted back to the backend

First, fetch the token cleanly and store it in a shell variable:

```bash
APPROVE_TOKEN=$(curl -s "$BASE/providers/webchat/accounts/acct/approval-prompts?stream_id=demo016-webchat-stream" \
  -H 'X-Webchat-Client-Token: fake-webchat-token' | \
python3 - <<'PY'
import json, sys
items = json.load(sys.stdin)
payload = json.loads(items[0]["presentation_payload_json"])
print(payload["actions"]["approve"]["token"])
PY
)

echo "$APPROVE_TOKEN"
```

Expected result:

- one token string prints
- it should look like a compact URL-safe token rather than a long JSON document

What this means:

- you are now holding the exact backend-issued approval token for that prompt
- this avoids copy and paste mistakes caused by escaped JSON output

Now submit the approval action:

```bash
curl -s "$BASE/providers/webchat/accounts/acct/approval-actions" \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d "{
    \"decision\": \"approve\",
    \"token\": \"$APPROVE_TOKEN\"
  }"
```

Expected result:

- HTTP `200`
- if the prompt is still pending, the result becomes `approved`
- if the prompt was already approved earlier, the endpoint should return the already-recorded durable outcome instead of creating a second approval

If you receive an error:

- check that you are using the token from the current prompt row
- check that the prompt has not already expired
- check that you extracted just the token value, not the surrounding JSON structure

What this means:

- callback replay is idempotent at the backend decision layer
- the visible proposal id alone is not the approval authority; the token-backed prompt state is

## 10. Developer Verification Walkthrough

This path is for developers and operators who want to inspect the durable records directly through existing endpoints.

### Step 1: Inspect session state after takeover and assignment

Run:

```bash
curl -s "$BASE/sessions/$SESSION_ID" 
```

Then:

```bash
curl -s "$BASE/sessions/$SESSION_ID/automation" -H "$AUTH"
```

Expected result:

- the base session read includes the collaboration fields
- the automation read summarizes:
  - current automation state
  - assignment metadata
  - collaboration version
  - blocked run count

Developer meaning:

- collaboration state lives on `sessions`
- immutable history lives in separate note and event tables

### Step 2: Inspect run history for the blocked-run transition

Run:

```bash
curl -s "$BASE/sessions/$SESSION_ID/runs"
```

Expected result:

- the session run list includes both the original completed run and the later blocked-then-completed run

Developer meaning:

- the blocked run was not replaced by a new run row
- the same durable execution-run identity moved through the state machine

### Step 3: Inspect diagnostics for blocked or suppressed work

Run:

```bash
curl -s "$BASE/diagnostics/runs?session_id=$SESSION_ID" -H "$AUTH"
```

Then:

```bash
curl -s "$BASE/diagnostics/runs/$RACE_RUN_ID" -H "$AUTH"
```

Expected result:

- diagnostics pages list run statuses and ids
- the suppressed run detail shows correlated delivery and collaboration artifacts

Developer meaning:

- Spec 016 extended the existing diagnostics seam instead of creating a parallel operator subsystem

### Step 4: Inspect collaboration events as an append-only audit trail

Run:

```bash
curl -s "$BASE/sessions/$SESSION_ID/collaboration" -H "$AUTH"
```

Expected result:

- you should see a timeline including events such as:
  - `takeover`
  - `assignment_changed`
  - `resume`
  - `dispatch_suppressed` on the race demo session when applicable

Developer meaning:

- the collaboration timeline is durable and append-only
- operators and diagnostics can reconstruct what happened without scraping transcript text

### Step 5: Inspect approval prompt history

Run:

```bash
curl -s "$BASE/sessions/$APPROVAL_SESSION_ID/approval-prompts" -H "$AUTH"
```

Expected result:

- one or more prompt rows with stable ids
- status transitions such as `pending` then `approved`

Developer meaning:

- prompt creation is split from proposal creation
- approval prompt rows are materialized only when the rendered assistant message is known

## 11. What To Say During The Demo

If you are presenting this to a mixed audience, these short explanations work well:

- “This session starts in assistant-active mode, so normal work queues and runs automatically.”
- “When the operator takes over, the customer can keep messaging, but the assistant stops replying automatically.”
- “Notice that the customer message is still saved. We are blocking automation, not losing data.”
- “When the operator resumes automation, the blocked work is released safely in queue order.”
- “In the race example, the assistant had already started work, but takeover won before dispatch, so the reply was suppressed instead of leaking into the user-visible transcript.”
- “For approvals, the system still uses the same exact backend approval contract, but now it also records a durable prompt row that the UI can render safely.”

## 12. Expected Audience Takeaways

By the end of this demo, a non-developer should understand:

- a human can safely take control of a conversation
- customer messages are not lost during handoff
- automation can be paused and resumed in a controlled way
- approval requests are now more structured and easier to present in a UI

By the end of this demo, a developer should understand:

- collaboration state is durable on `sessions`
- notes and collaboration history are append-only
- blocked runs use the existing `execution_runs` queue rather than a parallel queue
- dispatch suppression prevents undelivered assistant content from becoming a normal transcript message
- approval prompts are durable, message-linked presentation artifacts layered on top of the existing proposal and approval semantics

## 13. Cleanup

When you are done, stop the gateway and shut down Docker:

```bash
docker compose --env-file .env down
```

If you want to reset the local database volume too:

```bash
docker compose --env-file .env down -v
```

Use the volume-removal form only if you are comfortable deleting local demo data.
