# PR Review Guide: Spec 001 Gateway Sessions

## Why this file exists
This guide is for a developer reviewing the implementation of Spec 001. The goal is not just to check that code exists, but to understand:

- what the spec promises
- which files implement each promise
- how an inbound message moves through the system
- what bugs would be most dangerous if we missed them in review

## What Spec 001 is trying to add
Spec 001 creates the first durable gateway path for inbound messages.

At a high level, the system should now do this:

1. Accept an inbound message through FastAPI.
2. Validate and normalize routing inputs.
3. Turn those routing inputs into a deterministic `session_key`.
4. Reuse or create a `sessions` row for that key.
5. Store one append-only `messages` row for the inbound message.
6. Prevent duplicate webhook deliveries from creating duplicate transcript rows.
7. Expose read-only endpoints for session metadata and transcript history.

If you keep those 7 goals in mind, the code is much easier to review.

## Current status in this workspace
The Spec 001 implementation is already committed as `spec:001` on `main`.

Relevant note while reviewing the current workspace:

- there are local uncommitted edits in `README.md`, `alembic.ini`, `migrations/env.py`, and `src/config/settings.py`
- those edits are setup/default-database changes, not the core session-routing behavior from Spec 001

So when you review this spec, focus mainly on the gateway, routing, persistence, idempotency, and tests.

## Best review order
Read in this order:

1. [`spec.md`](./spec.md)
2. [`plan.md`](./plan.md)
3. [`tasks.md`](./tasks.md)
4. [`src/routing/service.py`](../../src/routing/service.py)
5. [`src/gateway/idempotency.py`](../../src/gateway/idempotency.py)
6. [`src/sessions/repository.py`](../../src/sessions/repository.py)
7. [`src/sessions/service.py`](../../src/sessions/service.py)
8. [`apps/gateway/api/inbound.py`](../../apps/gateway/api/inbound.py)
9. [`apps/gateway/api/admin.py`](../../apps/gateway/api/admin.py)
10. [`src/db/models.py`](../../src/db/models.py)
11. [`migrations/versions/20260322_001_gateway_sessions.py`](../../migrations/versions/20260322_001_gateway_sessions.py)
12. tests in `tests/`

Why this order works:

- start with the contract
- then read pure business rules
- then read persistence
- then read the HTTP layer
- finish by checking whether tests cover the promises

## Spec-to-code map
Use this when you want to connect a requirement to an implementation file.

| Spec area | Main files |
| --- | --- |
| Request/response contracts | `src/domain/schemas.py`, `apps/gateway/api/inbound.py`, `apps/gateway/api/admin.py` |
| Routing validation and canonical session key | `src/routing/service.py` |
| Session lookup/creation and transcript paging | `src/sessions/repository.py` |
| End-to-end inbound orchestration | `src/sessions/service.py` |
| Duplicate suppression | `src/gateway/idempotency.py` |
| Database schema | `src/db/models.py`, `migrations/versions/20260322_001_gateway_sessions.py` |
| Dependency wiring | `apps/gateway/deps.py`, `apps/gateway/main.py` |
| Proof that behavior works | `tests/test_routing.py`, `tests/test_idempotency.py`, `tests/test_repository.py`, `tests/test_api.py`, `tests/test_integration.py` |

## The most important invariants to review
These are the high-risk rules. If one is wrong, the whole feature is wrong even if the app “seems to work.”

### 1. Routing must be deterministic
Look at [`src/routing/service.py`](../../src/routing/service.py).

Things to confirm:

- `channel_kind` must be lowercase
- `channel_account_id`, `sender_id`, `peer_id`, and `group_id` are trimmed
- exactly one of `peer_id` or `group_id` is allowed
- direct messages always map to `scope_kind="direct"` and `scope_name="main"`
- group messages always map to `scope_kind="group"` and `scope_name=group_id`
- the `session_key` format matches the spec exactly

Why this matters:

- if normalization changes, the same conversation could create multiple sessions
- if direct chats do not always use `main`, continuity breaks

### 2. Dedupe must happen before transcript mutation
Look at [`src/sessions/service.py`](../../src/sessions/service.py) and [`src/gateway/idempotency.py`](../../src/gateway/idempotency.py).

The intended flow is:

1. claim dedupe identity
2. commit the claim
3. create/reuse session
4. append message
5. finalize dedupe record
6. commit work

Things to confirm:

- the dedupe key includes `channel_kind`, `channel_account_id`, and `external_message_id`
- a duplicate completed record returns the original `session_id` and `message_id`
- a non-stale claimed record blocks duplicate work
- a stale claimed record can be recovered

Why this matters:

- the main correctness risk in this spec is storing the same upstream message twice

### 3. Messages must be append-only and page in stable order
Look at [`src/sessions/repository.py`](../../src/sessions/repository.py).

Things to confirm:

- messages are inserted, not updated in place
- paging is based on `id`
- query uses descending order for fetch efficiency, then reverses rows so the API returns ascending append order
- `before_message_id` means “older than this message”

Why this matters:

- transcript history should read like a timeline
- paging bugs are subtle and easy to miss without reading both query order and response order carefully

### 4. Read endpoints must stay read-only
Look at [`apps/gateway/api/admin.py`](../../apps/gateway/api/admin.py).

Things to confirm:

- `GET /sessions/{session_id}` only reads metadata
- `GET /sessions/{session_id}/messages` only reads transcript data
- not-found cases return `404`
- paging limit is bounded in the service layer

## End-to-end walkthrough
This is the simplest way to understand the code.

### Step 1: HTTP request enters the gateway
[`apps/gateway/api/inbound.py`](../../apps/gateway/api/inbound.py)

`POST /inbound/message` receives `InboundMessageRequest`, opens two database sessions, and calls `SessionService.process_inbound(...)`.

Important detail:

- there is a separate claim DB session and work DB session
- that helps persist the dedupe claim before transcript writes happen

### Step 2: Routing is normalized
[`src/sessions/service.py`](../../src/sessions/service.py) calls [`src/routing/service.py`](../../src/routing/service.py)

This converts raw request values into a canonical routing result. After this point, the rest of the code should only use normalized values.

### Step 3: Dedupe is claimed
[`src/gateway/idempotency.py`](../../src/gateway/idempotency.py)

The code checks `inbound_dedupe` using:

- `channel_kind`
- `channel_account_id`
- `external_message_id`

Possible outcomes:

- no record: create `claimed`
- completed record: return duplicate replay info
- recent claimed record: raise conflict
- stale claimed record: recover and reuse it

### Step 4: Session is found or created
[`src/sessions/repository.py`](../../src/sessions/repository.py)

`get_or_create_session(...)` looks up by canonical `session_key`. If no row exists, it inserts one. If a race happens, the unique constraint plus retry lookup keeps the key stable.

### Step 5: Message is appended
[`src/sessions/repository.py`](../../src/sessions/repository.py)

`append_message(...)` inserts a `messages` row and updates `session.last_activity_at`.

### Step 6: Dedupe is finalized
[`src/gateway/idempotency.py`](../../src/gateway/idempotency.py)

The claim is updated from `claimed` to `completed`, and the dedupe row stores the final `session_id` and `message_id`. That is what makes duplicate replay safe after restart.

## Database review checklist
Check [`src/db/models.py`](../../src/db/models.py) against [`migrations/versions/20260322_001_gateway_sessions.py`](../../migrations/versions/20260322_001_gateway_sessions.py).

You want the ORM model and migration to agree on:

- `sessions`, `messages`, and `inbound_dedupe` all exist
- `sessions.session_key` is unique
- message paging index is on `(session_id, id)`
- dedupe unique key is `(channel_kind, channel_account_id, external_message_id)`
- direct and group lookup indexes exist on `sessions`
- `session_id` and `message_id` in `inbound_dedupe` are nullable during the `claimed` phase

If the model and migration drift apart, tests may still pass in SQLite fixtures while production migrations fail later.

## Test review checklist
Use the tests as evidence, not just as a checkbox.

### Routing tests
[`tests/test_routing.py`](../../tests/test_routing.py)

Confirms:

- trim-only normalization
- preserved case
- exact-one-of routing validation
- direct and group key composition

### Idempotency tests
[`tests/test_idempotency.py`](../../tests/test_idempotency.py)

Confirms:

- first claim and finalize
- duplicate replay after completion
- non-stale claimed row blocks work
- stale claimed row can be recovered

### Repository tests
[`tests/test_repository.py`](../../tests/test_repository.py)

Confirms:

- same canonical key reuses the same session
- transcript paging is returned in append order

### API tests
[`tests/test_api.py`](../../tests/test_api.py)

Confirms:

- first inbound request is accepted
- duplicate inbound request replays original IDs
- invalid routing returns `400`
- session reuse works
- read endpoints work
- dedupe identity is isolated across channel kinds

### Integration tests
[`tests/test_integration.py`](../../tests/test_integration.py)

Confirms:

- session reuse survives app restart
- duplicate replay survives restart
- stale claimed recovery works
- history paging still works end to end

## Good questions to ask during review
If you are reviewing this PR and want to leave useful comments, these are strong questions:

- Does every path from inbound request to message insert go through dedupe claim first?
- Are we ever using unnormalized routing values after normalization is complete?
- Could any duplicate path create a second transcript row?
- Do model definitions and migration definitions match exactly?
- Does pagination return the oldest-to-newest order within each page as the spec requires?
- Are admin/history endpoints truly read-only?

## Things that are easy to miss
- `channel_kind` is part of dedupe identity. That is important for cross-channel isolation.
- `scope_name="main"` for direct messages is not just a nice label; it is part of stable DM session continuity.
- the service commits the dedupe claim before it starts the transcript write path.
- the API returns `201` even for duplicates, but the payload marks them as `dedupe_status="duplicate"`.
- the stale-claim recovery path is intentionally bounded by `dedupe_stale_after_seconds`.

## Suggested hands-on verification
From the project root, this is the focused test command for this spec:

```bash
.venv/bin/pytest tests/test_routing.py tests/test_idempotency.py tests/test_repository.py tests/test_api.py tests/test_integration.py
```

Current result in this workspace:

- `18 passed in 0.13s`

## Final review summary
If you need a one-paragraph mental model:

This spec builds a small but important foundation. The gateway accepts inbound messages, normalizes routing into a deterministic session identity, stores transcript rows in append-only order, and uses a persisted dedupe table to make duplicate deliveries replay-safe across restarts. Most of your review effort should go into routing determinism, dedupe lifecycle correctness, and transcript paging order, because those are the parts that define whether the system is trustworthy.
