# PR Review Guide: Spec 005 Async Queueing

## Why this file exists
This guide is for developers reviewing the implementation of Spec 005. The goal is to make the async queueing change legible without having to reverse-engineer the whole system from the diff.

Use it to answer five questions:

- what changed in this spec
- where the main logic lives
- how a turn now flows from inbound request to worker completion
- which invariants matter most during review
- what bugs would be most dangerous if we missed them

## What Spec 005 adds
Spec 005 changes the execution model for user-visible turns.

Before this spec, the gateway accepted an inbound message and ran the graph inline on the request path.

After this spec, the system does this:

1. Accept the inbound request at the gateway.
2. Claim or replay dedupe state.
3. Persist the canonical inbound transcript row.
4. Create or reuse a durable `execution_runs` row in `queued`.
5. Finalize dedupe with replayable identifiers.
6. Return `202 Accepted` with `session_id`, `message_id`, `run_id`, and current run `status`.
7. Let a worker claim the run later and execute the graph asynchronously.
8. Persist completion, retry, or failure state on the run row.
9. Preserve Spec 004 after-turn `outbox_jobs` as separate derived-state work.

That is the core mental model to keep in mind while reviewing. The gateway now owns accept-and-enqueue. The worker owns execution.

## What changed in this workspace
The Spec 005 implementation in this workspace includes:

- additive queueing and lease tables in the data model
- a refactored inbound path that commits transcript row, queued run, and dedupe finalization together
- worker-side run claiming and execution
- durable session-lane leases and global concurrency slots
- read-only run diagnostics endpoints
- scheduler fire persistence and scheduler-owned queue submission
- integration tests covering duplicate suppression, stale lease recovery, FIFO lane behavior, scheduler replay, and global cap behavior

This is a large cross-cutting change, so the best review is not file-by-file in git order. Review it as one pipeline.

## Best review order
Read in this order:

1. [`spec.md`](./spec.md)
2. [`plan.md`](./plan.md)
3. [`tasks.md`](./tasks.md)
4. [`apps/gateway/api/inbound.py`](../../apps/gateway/api/inbound.py)
5. [`src/sessions/service.py`](../../src/sessions/service.py)
6. [`src/jobs/repository.py`](../../src/jobs/repository.py)
7. [`src/jobs/service.py`](../../src/jobs/service.py)
8. [`src/sessions/concurrency.py`](../../src/sessions/concurrency.py)
9. [`apps/gateway/api/admin.py`](../../apps/gateway/api/admin.py)
10. [`apps/gateway/deps.py`](../../apps/gateway/deps.py)
11. [`apps/worker/jobs.py`](../../apps/worker/jobs.py)
12. [`apps/worker/scheduler.py`](../../apps/worker/scheduler.py)
13. [`src/db/models.py`](../../src/db/models.py)
14. [`migrations/versions/20260323_005_async_queueing.py`](../../migrations/versions/20260323_005_async_queueing.py)
15. queueing-focused tests in `tests/`

Why this order works:

- start with the public contract change from `201` to `202`
- then read the transactional enqueue logic
- then inspect the queue and lease machinery
- then read the worker execution path
- finish with schema and tests as proof

## Spec-to-code map

| Spec area | Main files |
| --- | --- |
| `202 Accepted` inbound contract | `src/domain/schemas.py`, `apps/gateway/api/inbound.py` |
| Transactional accept-and-enqueue orchestration | `src/sessions/service.py` |
| Duplicate-safe run creation by trigger identity | `src/jobs/repository.py` |
| FIFO claim ordering, retries, and terminal transitions | `src/jobs/repository.py`, `src/jobs/service.py` |
| Session lane and global concurrency enforcement | `src/sessions/concurrency.py`, `src/jobs/repository.py` |
| Worker entrypoint | `apps/worker/jobs.py` |
| Scheduler fire submission and replay safety | `apps/worker/scheduler.py`, `src/jobs/service.py`, `src/sessions/service.py` |
| Read-only run diagnostics | `apps/gateway/api/admin.py`, `src/sessions/service.py` |
| Dependency wiring and worker-safe settings | `apps/gateway/deps.py`, `src/config/settings.py` |
| Schema and migration | `src/db/models.py`, `migrations/versions/20260323_005_async_queueing.py` |
| Proof that behavior works | `tests/test_api.py`, `tests/test_integration.py`, `tests/test_repository.py` |

## The most important invariants to review

These are the high-risk rules. If one of these is broken, the system may appear to work but still violate the spec.

### 1. An accepted inbound turn must never exist without a durable queued run
Look at [`src/sessions/service.py`](../../src/sessions/service.py) and [`apps/gateway/api/inbound.py`](../../apps/gateway/api/inbound.py).

Things to confirm:

- the gateway persists the inbound user message before returning success
- the same transaction also creates or reuses the `execution_runs` row
- the same transaction finalizes the dedupe record with replayable identifiers
- if run creation fails, the request fails closed instead of returning success

Why this matters:

- the biggest failure mode in this spec is stranded user-visible work: transcript row committed, but no durable run exists to ever process it

### 2. Duplicate replay must resolve to the same logical run
Look at [`src/sessions/service.py`](../../src/sessions/service.py), [`src/gateway/idempotency.py`](../../src/gateway/idempotency.py), and [`src/jobs/repository.py`](../../src/jobs/repository.py).

Things to confirm:

- inbound dedupe still prevents duplicate transcript rows
- duplicate replay loads the existing run by persisted trigger identity
- run uniqueness is keyed by `(trigger_kind, trigger_ref)`
- replay returns the original `run_id` instead of creating a second queue record

Why this matters:

- this spec layers queue dedupe on top of transcript dedupe
- if either layer is wrong, duplicate upstream delivery can create duplicate logical work

### 3. The request path must not run the graph inline anymore
Look at [`apps/gateway/api/inbound.py`](../../apps/gateway/api/inbound.py), [`src/sessions/service.py`](../../src/sessions/service.py), and [`src/jobs/service.py`](../../src/jobs/service.py).

Things to confirm:

- `SessionService.process_inbound(...)` stops after durable queue submission
- graph invocation happens only from the worker execution path
- the API now returns `202 Accepted`, not a synchronous assistant result

Why this matters:

- the whole reason for this spec is to decouple long-running graph work from HTTP request handling

### 4. Session-lane exclusivity must be durable and restart-safe
Look at [`src/jobs/repository.py`](../../src/jobs/repository.py) and [`src/sessions/concurrency.py`](../../src/sessions/concurrency.py).

Things to confirm:

- lane ownership is represented in `session_run_leases`
- a worker cannot run a second same-session turn while an active lease is valid
- expired leases can be recovered safely
- lease stealing first recovers abandoned work instead of skipping ahead to a later run

Why this matters:

- if two workers can believe they both own the same session lane, transcript order and tool side effects can become nondeterministic

### 5. FIFO ordering within a lane must be preserved
Look at [`src/jobs/repository.py`](../../src/jobs/repository.py).

Things to confirm:

- eligible runs are ordered by `available_at`, then `created_at`, then `id`
- a later run in the same lane does not overtake an earlier eligible run
- blocked lanes do not let later same-lane items slip past the earlier one

Why this matters:

- users expect turns in one session to execute in the order they were accepted

### 6. Global concurrency must be enforced before graph execution
Look at [`src/jobs/repository.py`](../../src/jobs/repository.py), [`src/sessions/concurrency.py`](../../src/sessions/concurrency.py), and [`src/config/settings.py`](../../src/config/settings.py).

Things to confirm:

- claim logic acquires a global slot before treating the run as executable
- the configured cap is enforced from durable state, not just process-local counters
- slots are released on success, failure, and recovery paths

Why this matters:

- a broken cap means production load can exceed the safety envelope the spec intended

### 7. Scheduler submission must stay gateway-first and replay-safe
Look at [`apps/worker/scheduler.py`](../../apps/worker/scheduler.py), [`src/jobs/service.py`](../../src/jobs/service.py), and [`src/sessions/service.py`](../../src/sessions/service.py).

Things to confirm:

- the scheduler persists or reuses a `scheduled_job_fires` row first
- it submits through the gateway-owned queueing service contract
- it creates a canonical `role=user` trigger message when needed
- scheduler replay reuses the same fire and run identities
- scheduler trigger messages use `sender_id = scheduler:<job_key>` and `external_message_id = NULL`

Why this matters:

- the scheduler is allowed to originate work, but it is not allowed to bypass transcript-first durability or duplicate suppression

### 8. Execution-time refresh from Specs 003 and 004 must remain intact
Look at [`apps/gateway/deps.py`](../../apps/gateway/deps.py) and [`src/jobs/service.py`](../../src/jobs/service.py).

Things to confirm:

- the worker rebuilds runtime dependencies at execution time
- the worker does not capture live request-scoped objects from enqueue time
- policy, approvals, and context assembly are refreshed at execution time
- after-turn `outbox_jobs` are still enqueued from the worker completion path

Why this matters:

- Spec 005 must not freeze approval or continuity state at enqueue time
- this is one of the easiest subtle regressions to miss during an async refactor

## End-to-end walkthrough

This is the easiest way to reason about the new design.

### Step 1: inbound request enters the gateway
[`apps/gateway/api/inbound.py`](../../apps/gateway/api/inbound.py)

`POST /inbound/message` opens a DB session, calls `SessionService.process_inbound(...)`, commits once, and returns `202`.

Important review point:

- the success response now means “durably accepted and queued,” not “assistant finished”

### Step 2: the gateway claims or replays dedupe identity
[`src/sessions/service.py`](../../src/sessions/service.py) and [`src/gateway/idempotency.py`](../../src/gateway/idempotency.py)

Possible outcomes:

- first delivery: proceed to create session, message, and queued run
- duplicate completed record: return original `session_id`, `message_id`, and `run_id`
- non-stale claimed record: fail closed
- stale claimed record: recover and proceed

Important review point:

- replay logic now needs to bridge from dedupe identity to the existing queue record

### Step 3: the inbound transcript row and queued run are persisted together
[`src/sessions/service.py`](../../src/sessions/service.py)

For first delivery:

1. normalize routing
2. get or create the canonical session
3. append the user message
4. create or get the initial execution run with `trigger_kind='inbound_message'`
5. finalize the dedupe row with `session_id` and `message_id`
6. return `run_id` and `status`

Important review point:

- the persisted trigger identity for inbound work is the canonical `message_id`, not the raw webhook payload

### Step 4: a worker claims the next eligible run
[`apps/worker/jobs.py`](../../apps/worker/jobs.py), [`src/jobs/service.py`](../../src/jobs/service.py), and [`src/jobs/repository.py`](../../src/jobs/repository.py)

The worker:

1. finds an eligible queued or retryable run
2. acquires the session lease
3. acquires the global slot
4. transitions the run to `claimed`
5. marks it `running`

Important review point:

- claim order and lease ownership are the heart of the concurrency model

### Step 5: the worker reloads dependencies and invokes the graph
[`src/jobs/service.py`](../../src/jobs/service.py) and [`apps/gateway/deps.py`](../../apps/gateway/deps.py)

The worker reloads:

- repository dependencies
- policy service
- tool registry
- activation controller
- context service
- assistant graph

Then it loads the canonical trigger message and invokes the graph for that session and message.

Important review point:

- the worker is reusing the existing runtime contracts from Specs 002 through 004, not inventing a second runtime

### Step 6: completion, retry, or failure is persisted
[`src/jobs/service.py`](../../src/jobs/service.py) and [`src/jobs/repository.py`](../../src/jobs/repository.py)

Possible outcomes:

- success: mark `completed`
- retryable error: increment attempts and move to `retry_wait` or `dead_letter`
- terminal error: mark `failed`

In all paths:

- lane and global leases are released
- scheduler fire state is updated when the run came from a scheduler fire

Important review point:

- retry and lease-loss recovery must be duplicate-safe because abandoned workers are part of the design, not an edge case

## Database review checklist
Check [`src/db/models.py`](../../src/db/models.py) against [`migrations/versions/20260323_005_async_queueing.py`](../../migrations/versions/20260323_005_async_queueing.py).

You want the ORM models and migration to agree on:

- `execution_runs` exists with trigger identity uniqueness
- `session_run_leases` exists with one active lease per lane
- global concurrency storage exists and matches the implementation shape
- `scheduled_jobs` exists with stable `job_key`
- `scheduled_job_fires` exists with stable `fire_key`
- lookup indexes support worker claim order, diagnostics, and lease recovery

Pay extra attention to one implementation detail:

- the current code introduces `global_run_leases` as the durable table for global concurrency tracking, even though the original spec text focused on `session_run_leases` and a cap contract rather than naming a table directly

That is a valid implementation choice if the migration, ORM model, and claim logic are all consistent, but it is worth reviewing deliberately.

## API and schema review checklist
Look at [`src/domain/schemas.py`](../../src/domain/schemas.py), [`apps/gateway/api/inbound.py`](../../apps/gateway/api/inbound.py), and [`apps/gateway/api/admin.py`](../../apps/gateway/api/admin.py).

Things to confirm:

- inbound response model now includes `run_id` and current run `status`
- `POST /inbound/message` returns HTTP `202`
- `GET /runs/{run_id}` is read-only and returns run metadata
- `GET /sessions/{session_id}/runs` is read-only and bounded
- these diagnostics do not accidentally introduce replay or mutation behavior

## Test review checklist

### API tests
[`tests/test_api.py`](../../tests/test_api.py)

Confirms:

- first inbound request returns `202`
- duplicate inbound request reuses the same `run_id`
- diagnostics endpoints expose queued runs

### Integration tests
[`tests/test_integration.py`](../../tests/test_integration.py)

Confirms:

- restart-safe duplicate replay still works
- stale claimed dedupe state can be recovered
- scheduler replay reuses fire, run, and transcript trigger identities
- expired lane leases recover abandoned work before later same-session runs
- global concurrency cap blocks a second claim until the slot is released
- scheduler routing tuples resolve through canonical session rules

### Repository tests
[`tests/test_repository.py`](../../tests/test_repository.py)

Use these to confirm lower-level queue and persistence behavior, especially if you want proof that uniqueness and ordering hold without going through HTTP.

## Good questions to ask during review
If you want to leave high-value review comments, these are strong questions:

- If run creation fails after the message is appended, do we definitely roll back the entire accept path?
- Are we deduping worker-visible work by persisted trigger identity or by request payload coincidence?
- Can a later same-session run ever leapfrog an earlier eligible run under contention?
- What happens if a worker dies after claim but before completion persistence?
- Are lease recovery paths guaranteed not to produce two workers who both think they own the same run?
- Does global-cap enforcement remain correct across multiple worker processes?
- Does scheduler replay create exactly one fire row, one trigger message, and one logical run?
- Are policy and context reloaded at execution time, or are we accidentally freezing stale enqueue-time state?
- Do worker completion paths preserve Spec 004 `outbox_jobs` instead of folding that work into `execution_runs`?

## Common review traps

### Trap 1: treating `202` like a superficial API tweak
It is not. The status-code change is only correct if the queue row is already durable.

### Trap 2: reading the worker path without reading the enqueue path
The correctness story depends on both halves. The queue is only useful if the gateway writes it transactionally.

### Trap 3: checking only happy-path completion
This spec is mostly about crash windows, recovery, duplicate suppression, and concurrency safety.

### Trap 4: overlooking scheduler provenance
Scheduler work must still look like canonical transcript-first work, not a backdoor around the gateway boundary.

### Trap 5: missing cross-spec regressions
Spec 005 sits on top of Specs 001 through 004. A queueing refactor can easily break:

- dedupe semantics from Spec 001
- governance refresh from Spec 003
- context continuity and `outbox_jobs` from Spec 004

## Practical notes for developers

### What is intentionally simplified in this implementation

- the worker entrypoint is currently a simple `run_once(...)` path, not a full daemon loop
- the scheduler entrypoint is currently `submit_job_once(...)`, not a full recurring scheduler service
- diagnostics are read-only; replay, cancel, and dead-letter recovery APIs are intentionally out of scope
- failure classification is intentionally simple: `RuntimeError` is terminal, most other exceptions retry

Those simplifications are okay for this slice if they preserve the spec invariants above.

### What is worth sanity-checking manually

- `POST /inbound/message` returns `202` with `run_id`
- `GET /runs/{run_id}` shows `queued` before worker execution
- a worker pass moves the run to `completed` and appends the assistant reply
- replay of the same inbound payload returns the same `run_id`
- scheduler replay returns the same `run_id` and does not create duplicate scheduler trigger messages

## Bottom line for review
If you remember only four things, remember these:

1. accepted work must be durable before the request returns
2. duplicate deliveries must resolve to one logical run
3. one session lane may have only one active run at a time
4. the worker must reuse gateway-owned runtime contracts instead of bypassing policy, continuity, or transcript rules

If those four things hold, the rest of the implementation becomes much easier to trust.
