# Spec 001: Gateway, Routing, Sessions, and Transcript Foundation

## Purpose
Establish the canonical entry path, deterministic routing, durable session identity, and append-only transcript model for the system.

## Non-Goals
- Memory extraction or retrieval
- LangGraph orchestration
- Remote execution
- Media processing
- Multi-agent delegation
- Scheduler-driven execution

## Upstream Dependencies
- Project constitution only

## Scope
- FastAPI gateway as the sole inbound execution entrypoint
- Inbound message contract
- Routing service and deterministic session-key strategy
- Direct-message `main` session behavior plus scoped group/channel sessions
- PostgreSQL-backed `sessions` and `messages`
- Idempotent inbound handling using `external_message_id`
- Basic transcript readback and read-only admin/history endpoints

## Data Model Changes
- `sessions`
  - `id`
  - `session_key` unique and deterministic
  - `channel_kind`
  - `channel_account_id`
  - `scope_kind` with values `direct` or `group`
  - `peer_id` nullable and required for `direct`
  - `group_id` nullable and required for `group`
  - `scope_name` where direct sessions use the literal value `main`
  - timestamps needed for creation and last activity tracking
- `messages`
  - `id`
  - `session_id`
  - `role`
  - `content`
  - `external_message_id` nullable for non-inbound rows added by later specs
  - `sender_id`
  - immutable creation timestamp
- `inbound_dedupe` persisted idempotency record
  - `status` with values `claimed` or `completed`
  - `channel_kind`
  - `channel_account_id`
  - `external_message_id`
  - `session_id` nullable while `status=claimed`
  - `message_id` nullable while `status=claimed`
  - `first_seen_at`
  - `expires_at`
- Required indexes
  - unique index on `sessions.session_key`
  - session transcript paging index on `messages(session_id, id)`
  - unique dedupe index on `inbound_dedupe(channel_kind, channel_account_id, external_message_id)`
  - lookup indexes for `sessions(channel_kind, channel_account_id, peer_id, scope_name)` and `sessions(channel_kind, channel_account_id, group_id)`

## Contracts
### Routing Contract
- The routing service accepts normalized inputs:
  - `channel_kind`
  - `channel_account_id`
  - `sender_id`
  - exactly one of `peer_id` or `group_id`
- `peer_id` identifies the other participant in a direct conversation and must not be combined with `group_id`.
- `group_id` identifies the shared room, thread root, or channel-scoped conversation container and must not be combined with `peer_id`.
- A direct conversation resolves to `scope_kind=direct` and `scope_name=main`.
- A group or channel conversation resolves to `scope_kind=group` and `scope_name={group_id}`.
- The canonical session key is:
  - direct: `{channel_kind}:{channel_account_id}:direct:{peer_id}:main`
  - group: `{channel_kind}:{channel_account_id}:group:{group_id}`
- Routing input normalization is gateway-owned and must be deterministic before session-key composition.
- Normalization rules for routing identifiers are:
  - `channel_kind` must be a validated lowercase enum value and is composed exactly as validated.
  - `channel_account_id`, `sender_id`, `peer_id`, and `group_id` must be trimmed for leading and trailing whitespace.
  - If trimming produces an empty value, the request is invalid.
  - After trimming, identifier values are preserved exactly as sent, including case, interior whitespace, punctuation, and Unicode code points.
  - Spec 001 performs no case folding, Unicode normalization, punctuation rewriting, or adapter-specific canonicalization.

### API and Event Contracts
- `POST /inbound/message`
  - Required payload fields: `channel_kind`, `channel_account_id`, `external_message_id`, `sender_id`, `content`
  - Required routing field: exactly one of `peer_id` or `group_id`
  - Behavior:
    - reject invalid routing combinations with `400`
    - on first delivery, create or claim an `inbound_dedupe` row with `status=claimed` before transcript mutation
    - after claim, resolve the canonical session, append one inbound transcript row, and finalize the same `inbound_dedupe` row with `status=completed`, `session_id`, and `message_id`
    - return the resolved `session_id` and created `message_id` only after dedupe finalization succeeds
    - on duplicate delivery with `status=completed`, return the original `session_id` and `message_id` without appending a second transcript row
    - on duplicate delivery with `status=claimed`, the handler must treat the record as in-progress or recoverable state rather than creating a second transcript row
- `GET /sessions/{session_id}`
  - Read-only session metadata surface for admin/history use in this spec
  - Returns routing metadata and timestamps only; no mutation behavior is allowed
- `GET /sessions/{session_id}/messages`
  - Read-only transcript history surface for admin/history use in this spec
  - Uses count-based cursor pagination with `limit` and `before_message_id`
  - Returns messages in ascending append order within the page
  - Maximum page size must be bounded

### Repository and Service Contracts
- Session repository must support get-or-create by canonical `session_key`.
- Message repository must support append-only insert and paged read by `session_id`.
- Idempotency service must persist the dedupe claim before transcript mutation.
- Idempotency service must support a two-phase lifecycle:
  - `claimed`: first delivery has been accepted but no replayable transcript identifiers are yet guaranteed
  - `completed`: the transcript row is durable and the dedupe record stores replayable `session_id` and `message_id`
- Crash or restart recovery rules are:
  - a persisted `claimed` row must prevent a second first-delivery insert for the same dedupe identity
  - duplicate handling must never create a second transcript row while a matching `claimed` row exists
  - the implementation must provide a bounded recovery path for stale `claimed` rows, such as lock-and-finalize or lock-and-retry logic, before accepting new work for that same dedupe identity
- This spec persists inbound user turns only. Later specs may add assistant or tool rows without changing the append-only rule.

## Runtime Invariants
- Every inbound event enters through the gateway.
- The same routing inputs produce the same session identity.
- Duplicate inbound deliveries do not duplicate transcript turns.
- Duplicate identity is scoped by `channel_kind`, `channel_account_id`, and `external_message_id`.
- Direct chats can resume through a stable `main` session mapping.
- Transcript rows are append-only and are never updated in place to change content or order.
- Direct sessions always use literal scope name `main`.
- Dedupe decisions survive process restarts because the canonical record lives in PostgreSQL.

## Security Constraints
- Gateway-only execution path
- Idempotency before transcript mutation
- Read-only admin/history surfaces in this spec
- Invalid or ambiguous routing inputs fail closed
- No adapter, worker, or later runtime may bypass the gateway to create transcript rows in this spec

## Operational Considerations
- Process restart must not break session resumability.
- Dedupe records use an explicit retention policy of 30 days unless superseded by a stricter platform requirement.
- Once a dedupe record expires, a replayed upstream event may be treated as new work.
- Transcript retrieval must support bounded pagination.
- Structured logs must include `channel_account_id`, `external_message_id`, and `session_id` for accepted and duplicate deliveries.
- Structured logs for dedupe handling must also include `channel_kind` and dedupe `status`.
- Any execution beyond transcript persistence in the request path is scaffold-only and must be marked as such until later specs land.

## Acceptance Criteria
- Duplicate webhook delivery stores one user turn.
- Repeated messages with the same routing tuple reuse the same session.
- Direct-chat `main` mapping remains stable across restarts.
- Transcript history retrieval returns ordered append-only events.
- Requests with both `peer_id` and `group_id`, or with neither, are rejected.
- Duplicate delivery returns the original session/message identifiers rather than creating new ones.
- `GET /sessions/{session_id}/messages` pages history with a bounded `limit` and `before_message_id` cursor.

## Test Expectations
- Unit tests for routing rules and session-key composition
- Unit tests for trim-only normalization and preserved-case identifier handling
- Repository tests for append-only transcript behavior
- API tests for duplicate delivery handling and deterministic session reuse
- Integration test covering restart-safe session lookup
- API tests for invalid routing tuples and read-only history endpoints
- Integration test covering duplicate replay after process restart using persisted dedupe state
- Unit and integration tests covering `claimed` to `completed` dedupe transitions, stale `claimed` recovery, and dedupe identity isolation across channel kinds
