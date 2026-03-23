# QA Guide

This document is the hands-on QA guide for `python-claw`. It is meant to grow as new specs are implemented.

Right now it covers how to test the behaviors delivered by:

- Spec 001: gateway sessions
- Spec 002: runtime tools
- Spec 003: capability governance

The emphasis is on running the server, interacting with it through HTTP, and verifying both API behavior and database state.

## What The Application Exposes

The current HTTP surface is:

- `GET /health`
- `POST /inbound/message`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/messages`

The main write path is always `POST /inbound/message`.

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

### 3. Optional: open a database shell

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

- HTTP `201`
- JSON with:
  - `session_id`
  - `message_id`
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

- HTTP `201`
- `dedupe_status: "duplicate"`
- same `session_id` as the first call
- same `message_id` as the first call

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

- HTTP `201`
- same `session_id` as before
- a new `message_id`

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
- messages come back in append order
- transcript includes both user and assistant rows

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

- HTTP `201`
- transcript gets a final assistant message like `Received: how are you`
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

- HTTP `201`
- assistant response content should be `runtime hello`
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

- HTTP `201`
- assistant message says approval is required
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

- HTTP `201`
- assistant confirms approval
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

- HTTP `201`
- governed capability is now allowed
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

- HTTP `201`
- assistant confirms revocation

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

- HTTP `201`
- system should require approval again
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

- HTTP `201`
- response includes `session_id` and `message_id`
- transcript includes the user row and a final assistant row

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

- HTTP `201` for both inbound requests
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

- the turn still succeeds with HTTP `201`
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

- HTTP `201`
- the governed request still succeeds instead of falling back to a new approval wait
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

## Common Failure Signals

These are useful signs that something is wrong:

- duplicate inbound deliveries create multiple inbound `messages` rows
- a governed `send` request executes before approval
- approval succeeds but retry still cannot bind the governed tool
- revocation succeeds but later turns still use the old approval
- transcript rows imply work happened but no matching artifacts or governance records exist
- tool execution succeeds but there are no `tool_audit_events`

## Updating This Guide Later

As future specs are completed, extend this document rather than replacing it.

Recommended pattern:

- keep one section per spec
- add runnable HTTP examples
- list expected API results
- list the database tables and fields QA should inspect
- call out the invariants most likely to regress
