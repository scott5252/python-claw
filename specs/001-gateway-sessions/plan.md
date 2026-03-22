# Plan 001: Gateway, Routing, Sessions, and Transcript Foundation

## Target Modules
- `apps/gateway/main.py`
- `apps/gateway/api/inbound.py`
- `apps/gateway/api/admin.py`
- `apps/gateway/api/health.py`
- `apps/gateway/deps.py`
- `src/domain/schemas.py`
- `src/db/base.py`
- `src/db/models.py`
- `src/db/session.py`
- `src/routing/service.py`
- `src/sessions/repository.py`
- `src/sessions/service.py`
- `src/gateway/idempotency.py`
- `migrations/`
- `tests/`

## Migration Order
1. Create `sessions` with:
   - `session_key` unique
   - `channel_kind`
   - `channel_account_id`
   - `scope_kind`
   - nullable `peer_id`
   - nullable `group_id`
   - `scope_name`
   - created and last-activity timestamps
2. Create `messages` with:
   - `session_id` foreign key
   - `role`
   - `content`
   - nullable `external_message_id`
   - `sender_id`
   - immutable creation timestamp
3. Create `inbound_dedupe` with:
   - `status` with values `claimed` or `completed`
   - `channel_kind`
   - `channel_account_id`
   - `external_message_id`
   - nullable `session_id`
   - nullable `message_id`
   - `first_seen_at`
   - `expires_at`
4. Add required indexes:
   - unique `sessions(session_key)`
   - `messages(session_id, id)` for append-order paging
   - unique `inbound_dedupe(channel_kind, channel_account_id, external_message_id)`
   - `sessions(channel_kind, channel_account_id, peer_id, scope_name)`
   - `sessions(channel_kind, channel_account_id, group_id)`
5. Ensure read paths use the base tables directly; no derived read models are required in this spec

## Implementation Shape
- Build the inbound contract first.
- Define request schemas and routing inputs with exactly one of `peer_id` or `group_id`.
- Normalize routing identifiers in the gateway before session-key composition using trim-only, preserve-case rules for external identifiers and validated lowercase `channel_kind`.
- Define stable session-key rules before repository code:
  - direct: `{channel_kind}:{channel_account_id}:direct:{peer_id}:main`
  - group: `{channel_kind}:{channel_account_id}:group:{group_id}`
- Resolve or create the session by canonical `session_key`.
- Persist a `claimed` dedupe record before transcript mutation.
- Persist one inbound user turn only after dedupe claim acceptance.
- Finalize the dedupe row to `completed` with replayable `session_id` and `message_id` after transcript insert succeeds.
- Treat persisted `claimed` rows as in-progress or recoverable state, never as permission to create a second transcript row.
- Keep transcript truth in PostgreSQL even if Redis is used as a fast-path dedupe cache.
- Return the original `session_id` and `message_id` on duplicate delivery.
- Expose read-only admin/history APIs only:
  - `GET /sessions/{session_id}`
  - `GET /sessions/{session_id}/messages?limit=&before_message_id=`
- Use count-based pagination and return messages in ascending append order within each page.
- Mark any inline request-path execution beyond transcript persistence as scaffold-only.

## Contracts to Implement
### API Contracts
- `POST /inbound/message`
  - Validate required payload fields: `channel_kind`, `channel_account_id`, `external_message_id`, `sender_id`, `content`
  - Validate routing shape: exactly one of `peer_id` or `group_id`
  - Return `400` on invalid routing tuples
  - On first delivery, return resolved `session_id` and created `message_id`
  - On duplicate delivery, return original `session_id` and `message_id` without creating a new transcript row
- `GET /sessions/{session_id}`
  - Return read-only session metadata and routing fields
- `GET /sessions/{session_id}/messages`
  - Support bounded `limit`
  - Support `before_message_id` cursor
  - Return rows in ascending append order

### Service and Repository Contracts
- `src/routing/service.py`
  - Normalize routing inputs with trim-only, preserve-case behavior for external identifiers
  - Derive `scope_kind`, `scope_name`, and canonical `session_key`
- `src/sessions/repository.py`
  - Get or create session by canonical key
  - Read session metadata by `session_id`
  - Read messages by `session_id`, `limit`, and optional `before_message_id`
- `src/sessions/service.py`
  - Orchestrate route resolution, session lookup, message append, and history readback
- `src/gateway/idempotency.py`
  - Claim first delivery in PostgreSQL with `status=claimed`
  - Detect duplicate delivery from persisted dedupe state using `(channel_kind, channel_account_id, external_message_id)`
  - Finalize accepted deliveries to `status=completed` with stored `session_id` and `message_id`
  - Recover or safely block on stale `claimed` rows without creating duplicate transcript rows
  - Return stored `session_id` and `message_id` for completed duplicates

## Risk Areas
- Ambiguous DM vs group routing
- Dedupe semantics across retries and restarts
- Recovery behavior for stale `claimed` rows after crash or worker interruption
- Session-key drift if channel identifiers are normalized inconsistently
- Cross-channel dedupe collisions if lookup paths omit `channel_kind`
- Pagination bugs if history is ordered by timestamps instead of append identifiers
- Dedupe retention expiry allowing a late upstream replay to be treated as new work

## Rollback Strategy
- Schema changes are additive.
- Roll back request handlers before dropping any newly introduced read endpoints.
- Inbound handlers must tolerate admin/history routes being absent during partial rollback.
- Do not depend on Redis for correctness during rollback; PostgreSQL remains the source of truth.
- If dedupe retention cleanup is introduced, it must be separately disableable without breaking inbound correctness.

## Test Strategy
- Unit:
  - routing normalization and session-key composition
  - invalid routing tuple rejection
  - idempotency `claimed` vs `completed` behavior
  - stale `claimed` recovery behavior
  - transcript paging order by `before_message_id`
- Repository:
  - get-or-create session behavior
  - append-only transcript inserts
  - ordered paged history reads
  - persisted dedupe lookup by `(channel_kind, channel_account_id, external_message_id)`
- API:
  - inbound message acceptance
  - duplicate delivery returns original identifiers
  - deterministic session reuse for repeated routing tuples
  - invalid routing tuple rejection
  - read-only session metadata retrieval
  - read-only message history retrieval with bounded pagination
- Integration:
  - restart-safe session reuse
  - duplicate replay after process restart using persisted dedupe state
  - duplicate isolation across different `channel_kind` values that share the same `channel_account_id` and `external_message_id`
  - transcript history retrieval remains ordered across page boundaries
