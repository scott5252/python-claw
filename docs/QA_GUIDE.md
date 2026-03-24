# QA Guide

This document is the hands-on QA guide for `python-claw`. It is meant to grow as new specs are implemented.

Right now it covers how to test the behaviors delivered by:

- Spec 001: gateway sessions
- Spec 002: runtime tools
- Spec 003: capability governance
- Spec 004: context continuity
- Spec 005: async queueing, workers, scheduler submission, and run diagnostics
- Spec 006: remote node runner and sandboxing
- Spec 007: channels, chunking, and media normalization

The emphasis is on running the server, interacting with it through HTTP, and verifying both API behavior and database state.

## What The Application Exposes

The current HTTP surface is:

- `GET /health`
- `POST /inbound/message`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/governance/pending`
- `GET /runs/{run_id}`
- `GET /sessions/{session_id}/runs`

The main write path is always `POST /inbound/message`.

As of Spec 005, that write path is accept-and-queue. The gateway returns after the inbound message and queued run are durably stored. Assistant execution happens later when a worker claims the run.

As of Spec 007, that same write path may also accept canonical attachment metadata. The attachment references are stored immediately, but normalization and outbound delivery happen later on the worker side.

## Before You Start

### 1. Start local dependencies

From the project root:

```bash
uv sync --group dev
docker compose --env-file .env up -d
uv run alembic upgrade head
```

### 2. Start the gateway

In another terminal:

```bash
uv run uvicorn apps.gateway.main:app --reload
```

Default local address:

```bash
http://127.0.0.1:8000
```

### 3. Keep a worker command ready

Most specs now need a worker pass after `POST /inbound/message`. The simplest manual command is:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once

print(run_once())
PY
```

Run it once per queued turn, or repeat it until it prints `None`.

### 4. Optional: open a database shell

If you are using the default local PostgreSQL container:

```bash
docker compose exec postgres psql -U openassistant -d openassistant
```

Useful starter query once connected:

```sql
\dt
```

That will show the tables available for inspection.

## Basic Smoke Check

Confirm the app is up:

```bash
curl http://127.0.0.1:8000/health
```

Expected result:

- HTTP `200`
- a small health payload

## Spec 001: Gateway Sessions

Spec 001 is about deterministic routing, session creation and reuse, append-only messages, and duplicate suppression.

### Scenario 1: Create a direct-message session

Send the first inbound message:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-1",
    "external_message_id": "msg-001",
    "sender_id": "sender-1",
    "content": "hello",
    "peer_id": "peer-1"
  }'
```

Expected result:

- HTTP `202`
- JSON with:
  - `session_id`
  - `message_id`
  - `run_id`
  - `status: "queued"`
  - `dedupe_status: "accepted"`

### Scenario 2: Replay the same inbound message

Send the exact same request again:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-1",
    "external_message_id": "msg-001",
    "sender_id": "sender-1",
    "content": "hello",
    "peer_id": "peer-1"
  }'
```

Expected result:

- HTTP `202`
- `dedupe_status: "duplicate"`
- same `session_id` as the first call
- same `message_id` as the first call
- same `run_id` as the first call

### Scenario 3: Reuse the same session with a new inbound message

Send a second message in the same direct conversation:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-1",
    "external_message_id": "msg-002",
    "sender_id": "sender-1",
    "content": "follow-up",
    "peer_id": "peer-1"
  }'
```

Expected result:

- HTTP `202`
- same `session_id` as before
- a new `message_id`
- a new `run_id`

### Scenario 4: Inspect the session and transcript

Get session metadata:

```bash
curl http://127.0.0.1:8000/sessions/<session_id>
```

Get transcript history:

```bash
curl "http://127.0.0.1:8000/sessions/<session_id>/messages?limit=20"
```

Expected result:

- the session shows the normalized routing identity
- before worker execution, transcript only includes inbound user rows
- after running the worker, transcript includes both user and assistant rows

### Scenario 5: Verify invalid routing is rejected

Send both `peer_id` and `group_id`:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-1",
    "external_message_id": "msg-bad",
    "sender_id": "sender-1",
    "content": "bad route",
    "peer_id": "peer-1",
    "group_id": "group-1"
  }'
```

Expected result:

- HTTP `400`

### Tables To Inspect For Spec 001

Look at these tables while testing:

- `sessions`
- `messages`
- `inbound_dedupe`

Useful queries:

```sql
select id, session_key, channel_kind, channel_account_id, scope_kind, peer_id, group_id, scope_name
from sessions
order by created_at desc;
```

```sql
select id, session_id, role, content, external_message_id, sender_id, created_at
from messages
order by id desc;
```

```sql
select id, status, channel_kind, channel_account_id, external_message_id, session_id, message_id, first_seen_at, expires_at
from inbound_dedupe
order by id desc;
```

What to verify:

- one canonical session row per conversation identity
- duplicate deliveries do not create duplicate inbound message rows
- `inbound_dedupe` stores the original `session_id` and `message_id`

## Spec 002: Runtime Tools

Spec 002 adds a gateway-owned single-turn runtime after the inbound user message is stored.

Current default runtime behavior:

- `echo <text>` uses `echo_text`
- `send <text>` is still handled by the runtime, but in Spec 003 it is now governed
- anything else returns `Received: <text>`

### Scenario 1: Plain assistant response

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-2",
    "external_message_id": "msg-plain-001",
    "sender_id": "sender-2",
    "content": "how are you",
    "peer_id": "peer-2"
  }'
```

Expected result:

- HTTP `202`
- response `status` is initially `queued`
- after running the worker once, transcript gets a final assistant message like `Received: how are you`
- no tool artifacts for this turn

### Scenario 2: Safe local tool execution with `echo`

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-2",
    "external_message_id": "msg-echo-001",
    "sender_id": "sender-2",
    "content": "echo runtime hello",
    "peer_id": "peer-2"
  }'
```

Expected result:

- HTTP `202`
- after running the worker once, assistant response content should be `runtime hello`
- runtime artifacts should show tool proposal and tool result
- audit rows should show attempt and result

### Tables To Inspect For Spec 002

Look at these additional tables:

- `session_artifacts`
- `tool_audit_events`

Useful queries:

```sql
select id, session_id, artifact_kind, correlation_id, capability_name, status, payload_json, created_at
from session_artifacts
order by id desc;
```

```sql
select id, session_id, correlation_id, capability_name, event_kind, status, payload_json, created_at
from tool_audit_events
order by id desc;
```

What to verify:

- `echo` creates a `tool_proposal` artifact
- `echo` creates a `tool_result` artifact
- tool attempts and results are audited separately from transcript rows
- the assistant message is appended after runtime execution finishes

## Spec 003: Capability Governance

Spec 003 adds approval-aware capability governance. In the current implementation, `send_message` is the governed capability used to prove the flow.

Current governance behavior:

- `send <text>` does not execute immediately unless there is an exact active approval
- the first governed request creates a proposal and exits in an awaiting-approval state
- `approve <proposal_id>` approves and activates that exact proposal
- `revoke <proposal_id>` revokes it for future turns

### Scenario 1: Request a governed action without approval

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-3",
    "external_message_id": "msg-send-001",
    "sender_id": "sender-3",
    "content": "send hello channel",
    "peer_id": "peer-3"
  }'
```

Expected result:

- HTTP `202`
- after running the worker once, assistant message says approval is required
- assistant message includes a proposal id
- no outbound intent is created yet
- no governed tool execution happens yet

After this call, fetch transcript history:

```bash
curl "http://127.0.0.1:8000/sessions/<session_id>/messages?limit=20"
```

Important notes:

- use the `session_id` returned by this Spec 003 `send hello channel` request, not a session from an earlier `hello`, `follow-up`, or `echo` test
- you can still read the proposal id from the latest assistant message `content`
- there is now also a structured endpoint for pending approvals:

```bash
curl "http://127.0.0.1:8000/sessions/<session_id>/governance/pending"
```

- that endpoint is the preferred way to fetch the `proposal_id`, typed action, and params for approval testing

In the current implementation, the latest assistant message should look roughly like this:

```text
Approval required for `send_message`. Proposal `<proposal_id>` is waiting for approval. Review packet: ...
```

You can capture the proposal id from either:

- the assistant message text, or
- the structured `GET /sessions/<session_id>/governance/pending` response

Example structured response:

```json
[
  {
    "proposal_id": "8198bb6b-b474-4fb3-8f09-ad29522397f1",
    "message_id": 2,
    "agent_id": "agent-1",
    "requested_by": "sender-3",
    "current_state": "pending_approval",
    "resource_kind": "tool",
    "resource_version_id": "8f6d9a2a-1111-2222-3333-444444444444",
    "capability_name": "send_message",
    "typed_action_id": "tool.send_message",
    "content_hash": "...",
    "canonical_params": {
      "text": "hello channel"
    },
    "canonical_params_json": "{\"text\":\"hello channel\"}",
    "scope_kind": "session_agent",
    "next_action": "approve 8198bb6b-b474-4fb3-8f09-ad29522397f1",
    "proposed_at": "2026-03-22T20:00:00Z",
    "pending_approval_at": "2026-03-22T20:00:00Z"
  }
]
```

### Scenario 2: Approve the proposal

Use the proposal id from the previous step:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-3",
    "external_message_id": "msg-send-002",
    "sender_id": "sender-3",
    "content": "approve <proposal_id>",
    "peer_id": "peer-3"
  }'
```

Expected result:

- HTTP `202`
- after running the worker once, assistant confirms approval
- assistant says the original request can now be retried

### Scenario 3: Retry the original governed request

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-3",
    "external_message_id": "msg-send-003",
    "sender_id": "sender-3",
    "content": "send hello channel",
    "peer_id": "peer-3"
  }'
```

Expected result:

- HTTP `202`
- after running the worker once, governed capability is now allowed
- assistant response should be `Prepared outbound message: hello channel`
- an outbound intent should now exist
- tool artifacts and audit rows should exist for this successful runtime call

### Scenario 4: Revoke the proposal

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-3",
    "external_message_id": "msg-send-004",
    "sender_id": "sender-3",
    "content": "revoke <proposal_id>",
    "peer_id": "peer-3"
  }'
```

Expected result:

- HTTP `202`
- after running the worker once, assistant confirms revocation

### Scenario 5: Retry after revocation

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-3",
    "external_message_id": "msg-send-005",
    "sender_id": "sender-3",
    "content": "send hello channel",
    "peer_id": "peer-3"
  }'
```

Expected result:

- HTTP `202`
- after running the worker once, system should require approval again
- a new approval wait should be visible in the assistant response
- no governed action should execute after revocation

### Tables To Inspect For Spec 003

Look at these additional tables:

- `governance_transcript_events`
- `resource_proposals`
- `resource_versions`
- `resource_approvals`
- `active_resources`

Useful queries:

```sql
select id, session_id, message_id, event_kind, proposal_id, resource_version_id, approval_id, active_resource_id, event_payload, created_at
from governance_transcript_events
order by created_at desc;
```

```sql
select id, session_id, message_id, agent_id, resource_kind, requested_by, current_state, latest_version_id, proposed_at, pending_approval_at, approved_at, denied_at, expired_at
from resource_proposals
order by created_at desc;
```

```sql
select id, proposal_id, version_number, content_hash, resource_payload, created_at
from resource_versions
order by created_at desc;
```

```sql
select id, proposal_id, resource_version_id, typed_action_id, canonical_params_hash, scope_kind, approver_id, approved_at, expires_at, revoked_at, revoked_by
from resource_approvals
order by approved_at desc nulls last;
```

```sql
select id, proposal_id, resource_version_id, typed_action_id, canonical_params_hash, activation_state, activated_at, revoked_at, revocation_reason
from active_resources
order by activated_at desc nulls last;
```

What to verify:

- the first `send` request creates proposal state and governance transcript events
- approval creates an approval row and an active-resource row
- retry after approval executes successfully
- revocation marks approval rows revoked
- revocation moves the active resource to `revoked`
- retry after revocation does not reuse the old approval

## Spec 004: Context Continuity

Spec 004 adds transcript-first context assembly, durable context manifests, additive summary snapshots, post-commit outbox jobs, bounded degraded failure on hard overflow, and replay of approval state from canonical governance artifacts.

Current implementation notes:

- every inbound turn persists one `context_manifests` row
- every inbound turn enqueues `summary_generation` and `retrieval_index` jobs
- degraded turns also enqueue `continuity_repair`
- summary generation currently runs through the in-process `OutboxWorker`
- continuity recovery is verified mainly by inspecting database state and re-sending inbound messages

### Scenario 1: Verify a normal turn persists a manifest and outbox jobs

Send a plain message in a fresh session:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "web",
    "channel_account_id": "acct-4",
    "external_message_id": "msg-ctx-001",
    "sender_id": "sender-4",
    "content": "hello context",
    "peer_id": "peer-4"
  }'
```

Expected result:

- HTTP `202`
- response includes `session_id`, `message_id`, and `run_id`
- after running the worker once, transcript includes the user row and a final assistant row

Inspect the latest manifest and jobs for that session:

```sql
select id, session_id, message_id, degraded, manifest_json, created_at
from context_manifests
where session_id = '<session_id>'
order by id desc;
```

```sql
select id, session_id, message_id, job_kind, job_dedupe_key, status, attempt_count, available_at, last_error, created_at
from outbox_jobs
where session_id = '<session_id>'
order by id desc;
```

What to verify:

- the newest `context_manifests` row has `degraded = false`
- `manifest_json` includes:
  - `assembly_mode: "transcript_full"`
  - `full_transcript_range`
  - `assistant_tool_artifact_ids`
  - `governance_artifact_ids`
- `outbox_jobs` includes one `summary_generation` row and one `retrieval_index` row for the triggering `message_id`

### Scenario 2: Generate and inspect an additive summary snapshot

Build enough transcript for summary generation by sending a few more turns in the same session:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "web",
    "channel_account_id": "acct-4",
    "external_message_id": "msg-ctx-002",
    "sender_id": "sender-4",
    "content": "second turn",
    "peer_id": "peer-4"
  }'
```

Then run the queue worker until it prints `None`, so those queued turns complete before the outbox worker runs.

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "web",
    "channel_account_id": "acct-4",
    "external_message_id": "msg-ctx-003",
    "sender_id": "sender-4",
    "content": "third turn",
    "peer_id": "peer-4"
  }'
```

Run the outbox worker once from the project root:

```bash
uv run python - <<'PY'
from datetime import datetime, timezone

from src.config.settings import Settings
from src.context.outbox import OutboxWorker
from src.db.session import DatabaseSessionManager
from src.sessions.repository import SessionRepository

settings = Settings()
manager = DatabaseSessionManager(settings.database_url)
repository = SessionRepository()

with manager.session() as db:
    completed = OutboxWorker(repository=repository).run_pending(
        db,
        now=datetime.now(timezone.utc),
    )
    print(completed)
    db.commit()
PY
```

Inspect the snapshots:

```sql
select id, session_id, snapshot_version, base_message_id, through_message_id, source_watermark_message_id, summary_text, summary_metadata_json, created_at
from summary_snapshots
where session_id = '<session_id>'
order by snapshot_version asc;
```

What to verify:

- at least one `summary_snapshots` row exists for the session
- snapshot versions increase and older snapshots remain in place
- `base_message_id` and `through_message_id` define an inclusive covered range
- `source_watermark_message_id` matches the turn that triggered the job

### Scenario 3: Force hard overflow and verify bounded degraded failure

Restart the gateway with a tiny transcript context window:

```bash
PYTHON_CLAW_RUNTIME_TRANSCRIPT_CONTEXT_LIMIT=1 uv run uvicorn apps.gateway.main:app --reload
```

Then send two messages in a fresh session:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "web",
    "channel_account_id": "acct-5",
    "external_message_id": "msg-overflow-001",
    "sender_id": "sender-5",
    "content": "hello",
    "peer_id": "peer-5"
  }'
```

Run the queue worker until it prints `None`, then fetch the transcript.

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "web",
    "channel_account_id": "acct-5",
    "external_message_id": "msg-overflow-002",
    "sender_id": "sender-5",
    "content": "follow up",
    "peer_id": "peer-5"
  }'
```

Fetch the transcript:

```bash
curl "http://127.0.0.1:8000/sessions/<session_id>/messages?limit=20"
```

Expected result:

- HTTP `202` for both inbound requests
- the final assistant message for the second turn says:
  - `I could not safely fit the required session context into the model window for this turn. Continuity repair has been queued.`

Inspect the manifest and jobs:

```sql
select id, message_id, degraded, manifest_json, created_at
from context_manifests
where session_id = '<session_id>'
order by id desc;
```

```sql
select id, message_id, job_kind, job_dedupe_key, status, created_at
from outbox_jobs
where session_id = '<session_id>'
order by id asc;
```

What to verify:

- the newest `context_manifests` row has `degraded = true`
- `manifest_json` includes `assembly_mode: "degraded_failure"`
- `manifest_json` includes an `overflow` object with the original transcript count and configured context window
- a `continuity_repair` job was enqueued for the same turn
- no transcript rows were deleted during the retry/failure flow

### Scenario 4: Delete derived artifacts and verify transcript-first continuity still works

Use a normal context window again and create a session with a few ordinary messages. Then remove only derived continuity artifacts:

```sql
delete from summary_snapshots where session_id = '<session_id>';
delete from context_manifests where session_id = '<session_id>';
delete from outbox_jobs where session_id = '<session_id>';
```

Send one more message in the same session:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "web",
    "channel_account_id": "acct-4",
    "external_message_id": "msg-ctx-004",
    "sender_id": "sender-4",
    "content": "after cleanup",
    "peer_id": "peer-4"
  }'
```

What to verify:

- the turn still succeeds with HTTP `202`
- after running the queue worker once, the assistant response appears in transcript history
- transcript history is still intact through `GET /sessions/<session_id>/messages`
- a new `context_manifests` row is created for the latest turn
- new post-commit `outbox_jobs` rows are created again
- continuity still comes from the append-only transcript, not from deleted summaries or manifests

### Scenario 5: Verify approval continuity replay after normalized-state loss

First complete the Spec 003 approval flow through the successful post-approval retry so the session has:

- a proposal
- a governance transcript history
- an approval row
- an active resource row

Before deleting anything, confirm the governed action succeeds once:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-6",
    "external_message_id": "msg-replay-001",
    "sender_id": "sender-6",
    "content": "send hello channel",
    "peer_id": "peer-6"
  }'
```

Then delete only the normalized approval state:

```sql
delete from active_resources where proposal_id = '<proposal_id>';
delete from resource_approvals where proposal_id = '<proposal_id>';
```

Send the exact same governed request again:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-6",
    "external_message_id": "msg-replay-002",
    "sender_id": "sender-6",
    "content": "send hello channel",
    "peer_id": "peer-6"
  }'
```

Expected result:

- HTTP `202`
- after running the queue worker once, the governed request still succeeds instead of falling back to a new approval wait
- the assistant response should again be `Prepared outbound message: hello channel`

Inspect the rebuilt approval state:

```sql
select id, proposal_id, resource_version_id, typed_action_id, canonical_params_hash, approver_id, approved_at, revoked_at
from resource_approvals
where proposal_id = '<proposal_id>'
order by approved_at desc nulls last;
```

```sql
select id, proposal_id, resource_version_id, typed_action_id, canonical_params_hash, activation_state, activated_at, revoked_at
from active_resources
where proposal_id = '<proposal_id>'
order by activated_at desc nulls last;
```

What to verify:

- approval state was rebuilt from persisted governance artifacts
- the replay does not create conflicting approvals for the same exact approved action
- approval visibility remains fail-closed for anything that was not actually approved

## Spec 005: Async Queueing, Workers, Scheduler Submission, and Run Diagnostics

Spec 005 moves graph execution out of the request thread and into durable `execution_runs` rows processed by a worker.

Current implementation notes:

- `POST /inbound/message` now returns `202 Accepted`
- the response includes `run_id` and the initial run `status`
- assistant output does not appear until a worker claims and executes the queued run
- `GET /runs/{run_id}` and `GET /sessions/{session_id}/runs` are the main read-only diagnostics
- scheduler fires create canonical user-role trigger messages with `sender_id = scheduler:<job_key>`

### Scenario 1: Verify accept-and-queue before worker execution

Send a plain inbound message in a fresh session:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-7",
    "external_message_id": "msg-async-001",
    "sender_id": "sender-7",
    "content": "hello from async qa",
    "peer_id": "peer-7"
  }'
```

Expected result before any worker runs:

- HTTP `202`
- response includes `session_id`, `message_id`, `run_id`, `status`, and `dedupe_status`
- `status` is `queued`
- transcript contains the inbound user row but not the assistant reply yet

Check the run endpoints:

```bash
curl http://127.0.0.1:8000/runs/<run_id>
```

```bash
curl http://127.0.0.1:8000/sessions/<session_id>/runs
```

Expected result:

- `GET /runs/<run_id>` returns the same run in `queued`
- `GET /sessions/<session_id>/runs` includes the run in descending creation order

Inspect the durable queue state:

```sql
select id, session_id, message_id, trigger_kind, trigger_ref, lane_key, status, attempt_count, max_attempts, available_at, claimed_at, started_at, finished_at, worker_id, last_error, created_at
from execution_runs
where id = '<run_id>';
```

```sql
select id, status, channel_kind, channel_account_id, external_message_id, session_id, message_id
from inbound_dedupe
where external_message_id = 'msg-async-001';
```

What to verify:

- the inbound user message and the queued run both exist before execution
- the run uses `trigger_kind = 'inbound_message'`
- `trigger_ref` matches the persisted inbound `message_id`
- the dedupe row is finalized against that same `session_id` and `message_id`

### Scenario 2: Run the worker and verify terminal completion

From the project root, run the worker once:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once

print(run_once())
PY
```

Then fetch the run and transcript again:

```bash
curl http://127.0.0.1:8000/runs/<run_id>
```

```bash
curl "http://127.0.0.1:8000/sessions/<session_id>/messages?limit=20"
```

Expected result:

- the worker prints the processed `run_id`
- the run becomes `completed`
- transcript now includes the assistant response for the turn

Inspect queue side effects:

```sql
select id, status, attempt_count, claimed_at, started_at, finished_at, worker_id, last_error
from execution_runs
where id = '<run_id>';
```

```sql
select lane_key, execution_run_id, worker_id, lease_expires_at
from session_run_leases
where lane_key = '<session_id>';
```

```sql
select slot_key, execution_run_id, worker_id, lease_expires_at
from global_run_leases
order by slot_key asc;
```

What to verify:

- `claimed_at`, `started_at`, and `finished_at` are populated on the run
- `worker_id` is populated on the completed run
- `last_error` remains `NULL` on success
- session and global lease rows were released after completion

### Scenario 3: Verify duplicate replay reuses the same queued run

Replay the exact same inbound request from Scenario 1:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-7",
    "external_message_id": "msg-async-001",
    "sender_id": "sender-7",
    "content": "hello from async qa",
    "peer_id": "peer-7"
  }'
```

Expected result:

- HTTP `202`
- `dedupe_status` is `duplicate`
- `run_id` matches the original run
- no second logical run is created

Verify in SQL:

```sql
select id, trigger_kind, trigger_ref, status
from execution_runs
where trigger_kind = 'inbound_message'
  and trigger_ref = '<message_id>';
```

What to verify:

- exactly one row exists for that trigger identity
- replay resolves to the existing run instead of creating a second row

### Scenario 4: Verify same-session FIFO lane behavior

Send two messages quickly to the same session before running the worker:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-8",
    "external_message_id": "msg-lane-001",
    "sender_id": "sender-8",
    "content": "first",
    "peer_id": "peer-8"
  }'
```

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-8",
    "external_message_id": "msg-lane-002",
    "sender_id": "sender-8",
    "content": "second",
    "peer_id": "peer-8"
  }'
```

Inspect session runs before worker execution:

```bash
curl http://127.0.0.1:8000/sessions/<session_id>/runs
```

Then run the worker once, inspect again, and run it a second time.

What to verify:

- both requests return `202`
- both runs share the same `lane_key`
- after the first worker pass, the earlier run is `completed` and the later run is still `queued`
- after the second worker pass, the second run completes
- transcript order stays `first`, assistant reply to first, `second`, assistant reply to second

Useful query:

```sql
select id, message_id, lane_key, status, available_at, created_at
from execution_runs
where session_id = '<session_id>'
order by created_at asc, id asc;
```

### Scenario 5: Verify global concurrency cap blocks an additional claim

Restart the gateway with a one-slot global cap:

```bash
PYTHON_CLAW_EXECUTION_RUN_GLOBAL_CONCURRENCY=1 uv run uvicorn apps.gateway.main:app --reload
```

Create two different sessions by sending one message to each:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-9",
    "external_message_id": "msg-cap-001",
    "sender_id": "sender-9a",
    "content": "first session",
    "peer_id": "peer-9a"
  }'
```

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-9",
    "external_message_id": "msg-cap-002",
    "sender_id": "sender-9b",
    "content": "second session",
    "peer_id": "peer-9b"
  }'
```

Run the worker once and inspect:

```sql
select slot_key, execution_run_id, worker_id, lease_expires_at
from global_run_leases
order by slot_key asc;
```

```sql
select id, session_id, status, worker_id, created_at
from execution_runs
where session_id in ('<session_id_1>', '<session_id_2>')
order by created_at asc;
```

What to verify:

- only one global lease slot exists while one run is active
- only one of the two runs advances on the first worker pass
- after another worker pass, the remaining queued run can execute

### Scenario 6: Verify scheduler fire submission and replay safety

Create a scheduled job for an existing session:

```sql
insert into scheduled_jobs (
  id,
  job_key,
  agent_id,
  target_kind,
  session_id,
  cron_expr,
  payload_json,
  enabled,
  created_at,
  updated_at
)
values (
  gen_random_uuid()::text,
  'job-qa-1',
  'default-agent',
  'session',
  '<session_id>',
  '0 * * * *',
  '{"prompt":"scheduled ping"}',
  1,
  now(),
  now()
);
```

Submit the same fire twice:

```bash
uv run python - <<'PY'
from datetime import datetime, timezone

from apps.worker.scheduler import submit_job_once

scheduled_for = datetime(2026, 3, 23, 18, 0, tzinfo=timezone.utc)
print(submit_job_once(job_key="job-qa-1", scheduled_for=scheduled_for))
print(submit_job_once(job_key="job-qa-1", scheduled_for=scheduled_for))
PY
```

Expected result:

- both submissions print the same `run_id`
- exactly one scheduler trigger message is created
- exactly one fire row exists for that `fire_key`

Inspect the scheduler state:

```sql
select id, job_key, target_kind, session_id, payload_json, enabled, last_fired_at
from scheduled_jobs
where job_key = 'job-qa-1';
```

```sql
select id, scheduled_job_id, fire_key, scheduled_for, status, execution_run_id, last_error
from scheduled_job_fires
where fire_key = 'job-qa-1:2026-03-23T18:00:00+00:00';
```

```sql
select id, role, content, external_message_id, sender_id, created_at
from messages
where session_id = '<session_id>'
  and sender_id = 'scheduler:job-qa-1'
order by id asc;
```

What to verify:

- scheduler trigger message has `role = 'user'`
- scheduler trigger message has `external_message_id IS NULL`
- `sender_id` is `scheduler:job-qa-1`
- the fire row links to the created run and remains replay-safe

### Tables To Inspect For Spec 005

Look at these additional tables:

- `execution_runs`
- `session_run_leases`
- `global_run_leases`
- `scheduled_jobs`
- `scheduled_job_fires`
- `messages`
- `inbound_dedupe`

## Common Failure Signals For Spec 005

- `POST /inbound/message` returns success but no `execution_runs` row exists
- duplicate replay creates a second run for the same `trigger_kind` and `trigger_ref`
- assistant output appears before any worker executes the queued run
- a later run in the same session completes before an earlier queued run
- lease rows remain stuck after the run is terminal
- global concurrency exceeds the configured cap
- scheduler replay creates multiple trigger messages or multiple fire rows for one `fire_key`
- run diagnostics disagree with database state

## Spec 006: Remote Node Runner and Per-Agent Sandboxing

Spec 006 adds a separate node-runner execution boundary, signed internal execution requests, per-agent sandbox profile resolution, and durable node execution audit rows.

Current implementation notes:

- the node runner is available as a separate FastAPI app at `apps.node_runner.main:app`
- the gateway runtime can construct signed remote-exec requests, but this workspace does not yet expose a normal end-user prompt flow that proposes and approves `remote_exec`
- manual QA for this spec is therefore internal-service and database driven
- the signed-request, duplicate-delivery, allowlist, timeout, and audit contracts are implemented now
- the container backend is only scaffolded in this workspace, so manual QA should focus on request verification, auditability, workspace resolution, and fail-closed behavior rather than real container isolation

### Scenario 1: Start the gateway and node-runner with remote execution enabled

Start the gateway in one terminal:

```bash
PYTHON_CLAW_REMOTE_EXECUTION_ENABLED=true \
PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID=qa-key \
PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET=qa-secret \
PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES=/bin/echo \
uv run uvicorn apps.gateway.main:app --reload
```

Start the node runner in a second terminal:

```bash
PYTHON_CLAW_REMOTE_EXECUTION_ENABLED=true \
PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID=qa-key \
PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET=qa-secret \
PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES=/bin/echo \
uv run uvicorn apps.node_runner.main:app --reload --port 8010
```

Expected result:

- both services start cleanly
- the gateway still serves `GET /health`
- the node runner accepts internal requests on port `8010`

What to verify:

- the same signing key id and secret are configured on both services
- the allowed executable list is explicit and narrow
- remote execution stays disabled unless `PYTHON_CLAW_REMOTE_EXECUTION_ENABLED=true`

### Scenario 2: Seed one approved remote-exec capability and sandbox profile

Create a session, one user message, one sandbox profile, and one approved `node_command_template`:

```bash
uv run python - <<'PY'
from datetime import datetime, timezone

from src.capabilities.repository import CapabilitiesRepository
from src.db.base import Base
from src.db.session import DatabaseSessionManager
from src.routing.service import RoutingInput, normalize_routing_input
from src.sessions.repository import SessionRepository
from src.config.settings import get_settings

settings = get_settings()
manager = DatabaseSessionManager(settings.database_url)
Base.metadata.create_all(manager.engine)

session_repo = SessionRepository()
cap_repo = CapabilitiesRepository()

with manager.session() as db:
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="web",
            channel_account_id="acct-qa-006",
            sender_id="sender-qa-006",
            peer_id="peer-qa-006",
        )
    )
    session = session_repo.get_or_create_session(db, routing)
    message = session_repo.append_message(
        db,
        session,
        role="user",
        content="remote exec qa seed",
        external_message_id="msg-qa-006-seed",
        sender_id="sender-qa-006",
        last_activity_at=datetime.now(timezone.utc),
    )
    cap_repo.upsert_agent_sandbox_profile(
        db,
        agent_id="agent-qa-006",
        default_mode="agent",
        shared_profile_key="shared-default",
        allow_off_mode=False,
        max_timeout_seconds=5,
    )
    proposal, version, approval, active = cap_repo.create_remote_exec_capability(
        db,
        session_id=session.id,
        message_id=message.id,
        agent_id="agent-qa-006",
        requested_by="sender-qa-006",
        approver_id="sender-qa-006",
        template_payload={
            "capability_name": "remote_exec",
            "executable": "/bin/echo",
            "argv_template": ["{text}"],
            "env_allowlist": [],
            "working_dir": None,
            "workspace_binding_kind": "session",
            "fixed_workspace_key": None,
            "workspace_mount_mode": "read_write",
            "typed_action_id": "tool.remote_exec",
            "sandbox_profile_key": "default",
            "timeout_seconds": 5,
        },
        invocation_arguments={"text": "hello from qa"},
    )
    db.commit()
    print("session_id=", session.id)
    print("message_id=", message.id)
    print("proposal_id=", proposal.id)
    print("resource_version_id=", version.id)
    print("approval_id=", approval.id)
    print("active_resource_id=", active.id)
PY
```

Expected result:

- one session and one transcript message are created
- one `agent_sandbox_profiles` row exists for `agent-qa-006`
- one approved and active `node_command_template` capability exists for the exact parameter payload `{"text":"hello from qa"}`

Inspect the seeded approval state:

```sql
select id, agent_id, default_mode, shared_profile_key, allow_off_mode, max_timeout_seconds
from agent_sandbox_profiles
where agent_id = 'agent-qa-006';
```

```sql
select id, session_id, agent_id, resource_kind, current_state, latest_version_id
from resource_proposals
where agent_id = 'agent-qa-006'
order by created_at desc;
```

```sql
select id, proposal_id, content_hash, resource_payload
from resource_versions
where id = '<resource_version_id>';
```

```sql
select id, proposal_id, resource_version_id, typed_action_id, canonical_params_hash, revoked_at
from resource_approvals
where id = '<approval_id>';
```

```sql
select id, proposal_id, resource_version_id, typed_action_id, canonical_params_hash, activation_state
from active_resources
where id = '<active_resource_id>';
```

What to verify:

- `resource_kind = 'node_command_template'`
- the version payload includes `/bin/echo`, `workspace_binding_kind = 'session'`, and `typed_action_id = 'tool.remote_exec'`
- the approval is exact-match scoped to the approved invocation parameters
- the active resource is in `activation_state = 'active'`

### Scenario 3: Send one valid signed request to the node runner

Construct and submit a signed internal request:

```bash
uv run python - <<'PY'
import json
import urllib.request

from src.capabilities.repository import CapabilitiesRepository
from src.config.settings import get_settings
from src.db.session import DatabaseSessionManager
from src.execution.contracts import NodeCommandTemplate, RemoteInvocation, build_exec_request, derive_argv
from src.sandbox.service import SandboxService
from src.security.signing import SigningService

settings = get_settings()
manager = DatabaseSessionManager(settings.database_url)
cap_repo = CapabilitiesRepository()

resource_version_id = "<resource_version_id>"
approval_id = "<approval_id>"
session_id = "<session_id>"
message_id = <message_id>
agent_id = "agent-qa-006"

with manager.session() as db:
    version = cap_repo.get_resource_version(db, resource_version_id=resource_version_id)
    template = NodeCommandTemplate.from_payload(__import__("json").loads(version.resource_payload))
    sandbox = SandboxService(settings=settings, capabilities_repository=cap_repo).resolve(
        db,
        agent_id=agent_id,
        session_id=session_id,
        template=template,
    )
    invocation = RemoteInvocation(
        arguments={"text": "hello from qa"},
        env={},
        working_dir=None,
        timeout_seconds=5,
    )
    request = build_exec_request(
        execution_run_id="run-qa-006-1",
        tool_call_id="tool-qa-006-1",
        execution_attempt_number=1,
        session_id=session_id,
        message_id=message_id,
        agent_id=agent_id,
        approval_id=approval_id,
        resource_version_id=version.id,
        resource_payload_hash=version.content_hash,
        invocation=invocation,
        argv=derive_argv(template=template, arguments={"text": "hello from qa"}),
        sandbox_mode=sandbox.sandbox_mode,
        sandbox_key=sandbox.sandbox_key,
        workspace_root=sandbox.workspace_root,
        workspace_mount_mode=sandbox.workspace_mount_mode,
        typed_action_id="tool.remote_exec",
        ttl_seconds=30,
    )
    signed = SigningService({settings.node_runner_signing_key_id: settings.node_runner_signing_secret}).build_signed_request(
        key_id=settings.node_runner_signing_key_id,
        request_payload=request.to_payload(),
    )

request = urllib.request.Request(
    "http://127.0.0.1:8010/internal/node/exec",
    data=json.dumps(signed.signed_payload()).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=10) as response:
    print(response.status)
    print(json.loads(response.read().decode("utf-8")))
PY
```

Expected result:

- HTTP `200`
- response includes `request_id`
- `status` is `completed`
- `stdout_preview` contains `hello from qa`

Inspect the audit row:

```sql
select request_id, execution_run_id, tool_call_id, execution_attempt_number, session_id, agent_id, sandbox_mode, sandbox_key, workspace_root, workspace_mount_mode, typed_action_id, status, deny_reason, exit_code, stdout_preview, stderr_preview
from node_execution_audits
where request_id = '<request_id>';
```

What to verify:

- the runner persisted one audit row before returning the terminal state
- `status = 'completed'`
- `typed_action_id = 'tool.remote_exec'`
- `sandbox_mode`, `sandbox_key`, `workspace_root`, and `workspace_mount_mode` are populated deterministically
- `stdout_preview` is bounded and inspectable from the database

### Scenario 4: Replay the exact same signed request and verify duplicate safety

Submit the exact same signed payload again.

Expected result:

- HTTP `200`
- the same `request_id` is returned
- the current persisted status is returned
- no second process is started

Verify in SQL:

```sql
select request_id, count(*)
from node_execution_audits
where request_id = '<request_id>'
group by request_id;
```

What to verify:

- the count remains `1`
- duplicate delivery reused the persisted row instead of creating a second execution attempt

### Scenario 5: Tamper with the request and verify fail-closed rejection

Resend the same signed payload, but change one field after signing, for example change `argv` from `["/bin/echo", "hello from qa"]` to `["/bin/echo", "tampered"]`.

You can do that by taking the previous Python snippet and mutating `signed.signed_payload()["request"]["argv"]` before the `POST`.

Expected result:

- HTTP `200`
- the returned audit status is `rejected`
- `deny_reason` indicates signature verification failure or replay payload mismatch

Inspect the audit row:

```sql
select request_id, status, deny_reason, exit_code, stdout_preview, stderr_preview
from node_execution_audits
where request_id = '<request_id>';
```

What to verify:

- the node runner rejects the request before execution
- no successful stdout is recorded for the tampered request
- request verification is fail-closed even when the original request id was known

### Tables To Inspect For Spec 006

Look at these additional tables:

- `agent_sandbox_profiles`
- `node_execution_audits`
- `resource_proposals`
- `resource_versions`
- `resource_approvals`
- `active_resources`
- `messages`

## Common Failure Signals For Spec 006

- the node runner accepts a request with a modified payload after signing
- duplicate delivery creates a second `node_execution_audits` row for the same `request_id`
- `request_id` changes for the same logical `(execution_run_id, tool_call_id, execution_attempt_number)` attempt
- the runner executes a non-allowlisted executable
- sandbox metadata is missing or changes nondeterministically between identical requests
- an unapproved or revoked `node_command_template` can still be executed
- the audit row is missing even though the runner returned a result
- `stdout_preview` or `stderr_preview` is unbounded or empty when terminal diagnostics should exist

## Spec 007: Channels, Chunking, and Media Normalization

Spec 007 adds three important local QA areas:

- canonical inbound attachments on `POST /inbound/message`
- worker-owned attachment normalization into durable media records
- shared outbound dispatch with chunking and delivery auditing for `webchat`, `slack`, and `telegram`

Current implementation notes:

- the gateway still returns `202 Accepted` quickly even when attachments are present
- accepted attachment inputs are stored first and normalized later by the worker
- only normalized `stored` attachments are eligible for turn context or outbound media sends
- large outbound responses are chunked after the assistant turn completes
- outbound sends are recorded in `outbound_deliveries` and `outbound_delivery_attempts`

### Scenario 1: Accept an inbound message with a canonical attachment

Create a local test file from the project root:

```bash
mkdir -p /tmp/python-claw-qa
printf 'qa attachment for spec 007\n' > /tmp/python-claw-qa/spec-007-note.txt
```

Send an inbound message with one attachment:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "telegram",
    "channel_account_id": "acct-8",
    "external_message_id": "msg-media-001",
    "sender_id": "sender-8",
    "content": "please inspect this attachment",
    "peer_id": "peer-8",
    "attachments": [
      {
        "source_url": "file:///tmp/python-claw-qa/spec-007-note.txt",
        "mime_type": "text/plain",
        "filename": "spec-007-note.txt",
        "provider_metadata": {
          "provider": "manual-qa"
        }
      }
    ]
  }'
```

Expected result before any worker runs:

- HTTP `202`
- response includes `session_id`, `message_id`, and `run_id`
- the inbound user message exists immediately
- the attachment input is stored immediately
- no normalized attachment row exists yet until the worker runs

Inspect the accepted attachment input:

```sql
select id, message_id, session_id, ordinal, external_attachment_id, source_url, mime_type, filename, byte_size, provider_metadata_json, created_at
from inbound_message_attachments
where message_id = <message_id>
order by ordinal asc;
```

What to verify:

- one `inbound_message_attachments` row exists for the inbound `message_id`
- `source_url`, `mime_type`, and `filename` match the request
- provider metadata was preserved in bounded JSON form
- the gateway accepted the message without waiting on file download or storage

### Scenario 2: Run the worker and verify normalization plus context manifest linkage

Run the queue worker until it prints `None`.

Then inspect normalized attachments:

```sql
select id, inbound_message_attachment_id, message_id, session_id, ordinal, storage_key, storage_bucket, mime_type, media_kind, filename, byte_size, sha256, normalization_status, retention_expires_at, error_detail, created_at
from message_attachments
where message_id = <message_id>
order by id asc;
```

Inspect the newest manifest for the session:

```sql
select id, session_id, message_id, degraded, manifest_json, created_at
from context_manifests
where session_id = '<session_id>'
order by id desc
limit 1;
```

What to verify:

- the attachment now has one terminal `message_attachments` row
- `normalization_status` is `stored`
- `storage_key`, `storage_bucket`, `media_kind`, and `sha256` are populated
- the newest `context_manifests.manifest_json` contains `attachment_ids`
- the manifest attachment list only references normalized attachments, not raw inbound attachment inputs

### Scenario 3: Verify deterministic rejection for unsupported media

Send an inbound request with a MIME type that is outside the allowed list:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "telegram",
    "channel_account_id": "acct-8",
    "external_message_id": "msg-media-002",
    "sender_id": "sender-8",
    "content": "this should be rejected as media",
    "peer_id": "peer-8",
    "attachments": [
      {
        "source_url": "file:///tmp/python-claw-qa/spec-007-note.txt",
        "mime_type": "video/mp4",
        "filename": "unsupported.mp4",
        "provider_metadata": {
          "provider": "manual-qa"
        }
      }
    ]
  }'
```

Run the worker once, then inspect:

```sql
select id, inbound_message_attachment_id, normalization_status, mime_type, media_kind, error_detail, created_at
from message_attachments
where message_id = <message_id>
order by id asc;
```

What to verify:

- the inbound request still returns HTTP `202`
- normalization does not delete the canonical inbound message
- the terminal `message_attachments` row is `rejected`
- `error_detail` explains the validation failure
- rejected attachments do not break the turn or silently become usable media

### Scenario 4: Verify governed send now creates durable outbound delivery rows

Use the Spec 003 approval flow for a fresh `slack` session until `send hello channel` is approved. Then retry the original governed request so it succeeds.

Expected result after the worker runs:

- the assistant transcript still ends with `Prepared outbound message: hello channel`
- one outbound intent artifact exists
- one logical outbound delivery row exists for the text send
- one delivery-attempt row exists and is terminal `sent`

Inspect the outbound delivery tables:

```sql
select id, session_id, execution_run_id, outbound_intent_id, channel_kind, channel_account_id, delivery_kind, chunk_index, chunk_count, reply_to_external_id, attachment_id, provider_message_id, status, error_code, error_detail, created_at
from outbound_deliveries
where session_id = '<session_id>'
order by id asc;
```

```sql
select id, outbound_delivery_id, attempt_number, provider_idempotency_key, status, provider_message_id, error_code, error_detail, created_at
from outbound_delivery_attempts
where outbound_delivery_id = <delivery_id>
order by attempt_number asc;
```

What to verify:

- `delivery_kind` is `text_chunk`
- `chunk_index` starts at `0`
- `chunk_count` matches the number of logical sends for that outbound intent
- `status` is `sent`
- the attempt row is append-only and linked to the logical delivery row

### Scenario 5: Verify channel-aware chunking with a long outbound message

For a clean manual QA pass, use `telegram` because it supports reply and media in this slice and has a larger text limit than `slack`. Create a long message that will still exceed a single-chunk limit by using the governed `send` flow with a very long body.

From a shell, build a long command body:

```bash
LONG_TEXT="$(python - <<'PY'
print('send ' + ('paragraph-one ' * 260) + '\n\n' + ('paragraph-two ' * 260))
PY
)"
```

Then submit it:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d "{
    \"channel_kind\": \"telegram\",
    \"channel_account_id\": \"acct-9\",
    \"external_message_id\": \"msg-chunk-001\",
    \"sender_id\": \"sender-9\",
    \"content\": \"$LONG_TEXT\",
    \"peer_id\": \"peer-9\"
  }"
```

If this session has not already approved `send_message`, first complete the approval flow from Spec 003, then resend the same long `send ...` content and run the worker again.

Inspect deliveries for that session:

```sql
select id, outbound_intent_id, delivery_kind, chunk_index, chunk_count, status, provider_message_id, created_at
from outbound_deliveries
where session_id = '<session_id>'
order by chunk_index asc, id asc;
```

What to verify:

- more than one `outbound_deliveries` row exists for the same outbound intent
- all rows for that intent have `delivery_kind = 'text_chunk'`
- `chunk_index` values are ordered and contiguous
- every row for the logical send shares the same `chunk_count`
- each chunk is independently auditable

### Scenario 6: Verify malformed attachment payloads are rejected at the gateway boundary

Send an attachment with a missing required field:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-10",
    "external_message_id": "msg-bad-attachment-001",
    "sender_id": "sender-10",
    "content": "bad attachment payload",
    "peer_id": "peer-10",
    "attachments": [
      {
        "source_url": "",
        "mime_type": "text/plain"
      }
    ]
  }'
```

Expected result:

- HTTP `422`
- no inbound message row is created
- no attachment rows are created

### Tables To Inspect For Spec 007

Look at these additional tables:

- `inbound_message_attachments`
- `message_attachments`
- `outbound_deliveries`
- `outbound_delivery_attempts`
- `context_manifests`
- `session_artifacts`

## Common Failure Signals For Spec 007

- `POST /inbound/message` blocks on attachment fetching instead of returning `202 Accepted`
- inbound attachments are accepted but no `inbound_message_attachments` row is stored
- the worker normalizes the same attachment repeatedly instead of reusing terminal state
- a rejected attachment silently appears in turn context or outbound media sends
- large outbound messages create no `outbound_deliveries` rows even though an outbound intent exists
- chunk ordering is unstable or `chunk_count` differs across rows for the same logical send
- a failed delivery attempt overwrites the original delivery record instead of appending a new attempt
- raw directives leak through as visible adapter text instead of being stripped before send

### Tables To Inspect For Spec 004

Look at these additional tables:

- `summary_snapshots`
- `outbox_jobs`
- `context_manifests`
- `messages`
- `session_artifacts`
- `governance_transcript_events`

## Common Failure Signals For Spec 004

- a turn succeeds but no `context_manifests` row is persisted
- manifest JSON does not match the actual transcript range or summary used
- summary generation overwrites old snapshots instead of appending a new version
- overflow handling silently drops history without a degraded manifest and repair job
- deleting summaries or manifests breaks a later turn even though transcript rows still exist
- deleting normalized approval state forces a new approval even though governance transcript history still proves a valid approval
- duplicate outbox delivery creates duplicate or conflicting derived state

## Suggested QA Pass Order

If you want a clean end-to-end manual QA flow, use this order:

1. smoke test `GET /health`
2. verify Spec 001 direct-session creation and duplicate replay
3. verify transcript inspection with `GET /sessions/{session_id}` and `GET /sessions/{session_id}/messages`
4. verify Spec 002 plain response and `echo` tool path
5. verify Spec 003 governed `send` proposal flow
6. verify Spec 003 approval flow
7. verify Spec 003 post-approval retry flow
8. verify Spec 003 revocation and post-revocation retry flow
9. verify Spec 004 continuity manifests and outbox jobs
10. verify Spec 005 accept-and-queue, worker completion, and run diagnostics
11. verify Spec 005 same-session FIFO and global-cap behavior
12. verify Spec 005 scheduler fire replay and transcript provenance
13. verify Spec 006 signed node-runner execution, duplicate replay safety, and fail-closed tamper rejection
14. verify Spec 007 attachment acceptance, worker normalization, and outbound delivery auditing

## Common Failure Signals

These are useful signs that something is wrong:

- duplicate inbound deliveries create multiple inbound `messages` rows
- inbound requests return `202` but no queued run exists
- a governed `send` request executes before approval
- approval succeeds but retry still cannot bind the governed tool
- revocation succeeds but later turns still use the old approval
- transcript rows imply work happened but no matching artifacts or governance records exist
- tool execution succeeds but there are no `tool_audit_events`
- signed internal execution succeeds but no `node_execution_audits` row exists
- duplicate node-runner delivery creates a second logical execution attempt
- attachment payloads are accepted but never appear in attachment tables
- outbound intent creation succeeds but there are no outbound delivery audit rows after worker execution

## Updating This Guide Later

As future specs are completed, extend this document rather than replacing it.

Recommended pattern:

- keep one section per spec
- add runnable HTTP examples
- list expected API results
- list the database tables and fields QA should inspect
- call out the invariants most likely to regress
