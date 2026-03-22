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
