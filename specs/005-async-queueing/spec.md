# Spec 005: Async Execution, Scheduler, Queueing, and Concurrency Lanes

## Purpose
Move graph execution out of request-bound handlers into a durable queueing model that preserves gateway-first execution, transcript-first durability, and safe concurrency at both session and system scope.

## Non-Goals
- Remote node sandboxing or privileged execution
- Media handling
- Presence and auth rotation
- Broad control-plane job authoring or approval UX beyond the runtime-facing scheduler contract in this slice
- Replacing Spec 004 `outbox_jobs` for derived-state work; user-visible run queueing is a separate concern

## Upstream Dependencies
- Specs 001, 002, 003, and 004

## Scope
- Accepted-and-queued inbound response pattern for user-visible turns
- Durable execution run records for async graph invocation
- Background worker claim, run, retry, and terminal-state lifecycle
- Session-lane exclusivity with at most one active run per `session_id`
- Global concurrency cap for graph runs
- FIFO ordering within each session lane
- Persistent scheduler definitions and fire records that re-enter through the gateway-owned event path
- Duplicate-work suppression for inbound replays, worker retries, and scheduler fire replays
- Read-only run visibility sufficient for operations and tests

## Data Model Changes
- `execution_runs`
  - `id`
  - `session_id`
  - optional `message_id` for the canonical transcript trigger row when the run is associated with a visible turn or scheduler-authored turn
  - `agent_id`
  - `trigger_kind` with values `inbound_message`, `scheduler_fire`, or `resume`
  - `trigger_ref` as the durable upstream identity for duplicate suppression
  - `lane_key` with the canonical value equal to `session_id` in this spec
  - `status` with values `queued`, `claimed`, `running`, `retry_wait`, `completed`, `failed`, `dead_letter`, `cancelled`
  - `attempt_count`
  - `max_attempts`
  - `available_at`
  - optional `claimed_at`
  - optional `started_at`
  - optional `finished_at`
  - optional `worker_id`
  - optional `last_error`
  - optional `trace_id`
  - `created_at`
  - `updated_at`
- `session_run_leases`
  - `lane_key` with the canonical value equal to `session_id` in this spec
  - `execution_run_id`
  - `worker_id`
  - `lease_expires_at`
  - `created_at`
  - `updated_at`
- `scheduled_jobs`
  - `id`
  - stable `job_key`
  - `agent_id`
  - `target_kind` with values `session` or `routing_tuple`
  - target fields needed to re-enter the gateway deterministically:
    - for `session`: `session_id`
    - for `routing_tuple`: `channel_kind`, `channel_account_id`, exactly one of `peer_id` or `group_id`
  - `cron_expr` or equivalent persisted schedule expression
  - `payload_json`
  - `enabled`
  - optional `last_fired_at`
  - `created_at`
  - `updated_at`
- `scheduled_job_fires`
  - `id`
  - `scheduled_job_id`
  - stable `fire_key`
  - `scheduled_for`
  - `status` with values `queued`, `submitted`, `completed`, `failed`, `cancelled`
  - optional `execution_run_id`
  - optional `last_error`
  - `created_at`
  - `updated_at`
- Required indexes
  - unique index on `execution_runs(trigger_kind, trigger_ref)`
  - lookup index on `execution_runs(status, available_at, created_at, id)`
  - lookup index on `execution_runs(session_id, status, created_at)`
  - lookup index on `execution_runs(lane_key, status, available_at)`
  - lookup index on `execution_runs(worker_id, status)`
  - unique index on `session_run_leases(lane_key)`
  - unique index on `session_run_leases(execution_run_id)`
  - lookup index on `session_run_leases(worker_id, lease_expires_at)`
  - unique index on `scheduled_jobs(job_key)`
  - unique index on `scheduled_job_fires(fire_key)`
  - lookup index on `scheduled_job_fires(scheduled_job_id, scheduled_for)`
  - lookup index on `scheduled_job_fires(status, scheduled_for)`

## Contracts
### Gateway Contracts
- `POST /inbound/message` remains the canonical external entrypoint from Spec 001, but its success path changes in this spec:
  - first persist or replay the inbound transcript event through the Spec 001 idempotent flow
  - then create or look up exactly one `execution_runs` row for the accepted trigger
  - return `202 Accepted` with `session_id`, `message_id`, `run_id`, and current run `status`
  - the request handler must not wait for graph completion before responding
- For a first-delivery inbound message, the gateway must durably commit the inbound transcript row, the initial `execution_runs` row in status `queued`, and the Spec 001 dedupe finalization in one gateway-owned transaction before returning `202 Accepted`.
- Duplicate inbound delivery with an already-completed Spec 001 dedupe record must not enqueue a second logical run for the same transcript trigger.
- If a matching `execution_runs` row already exists for the same trigger identity, the gateway returns the existing `run_id` and status instead of creating a duplicate run.
- Run creation must happen on the gateway-owned path and must be durable before the request returns success.
- If the gateway cannot durably create or look up the `execution_runs` row, the inbound request must fail closed and must not finalize a new dedupe record as completed.
- Read-only diagnostics may expose run metadata and status, but mutation of run state is worker-owned in this spec.
- Read-only operational endpoints in this spec are:
  - `GET /runs/{run_id}` for status, attempts, timestamps, trigger metadata, and latest error
  - `GET /sessions/{session_id}/runs` for bounded recent runs in descending creation order
- These diagnostics are read-only. Replay, cancel, and dead-letter recovery actions remain out of scope for public APIs in this spec.

### Execution Run Contracts
- `execution_runs` is the canonical queue record for user-visible graph execution in this spec.
- `trigger_ref` must be deterministic and replay-safe:
  - inbound-triggered runs use the persisted triggering `message_id`
  - scheduler-triggered runs use the persisted `scheduled_job_fires.fire_key`
  - resume-triggered runs, if used in this slice, must use a persisted gateway-owned resume identity
- `message_id` rules are:
  - inbound-triggered runs must reference the persisted inbound user message row from Spec 001
  - scheduler-triggered runs that contribute to a session transcript must first persist a canonical trigger message row and reference it from `execution_runs.message_id`
  - resume-triggered runs may omit `message_id` only when resuming previously persisted wait state without a new transcript trigger row
- Scheduler-created trigger message rows in this spec must:
  - use `role=user` so they participate in transcript-first continuity like other turn triggers
  - use `external_message_id=NULL`
  - use `sender_id=scheduler:{job_key}`
  - store human-readable content derived from the persisted scheduler payload so replay and audit can reconstruct why the turn was enqueued
- Allowed run state transitions are:
  - `queued -> claimed`
  - `claimed -> running`
  - `claimed -> retry_wait`
  - `running -> completed`
  - `running -> retry_wait`
  - `running -> failed`
  - `retry_wait -> claimed`
  - `failed -> dead_letter`
  - `queued -> cancelled`
  - `retry_wait -> cancelled`
- Transition ownership is:
  - gateway request path creates `queued`
  - worker claim path moves `queued` or eligible `retry_wait` to `claimed`
  - worker execution path moves `claimed -> running`
  - worker completion path moves `running` to `completed`, `retry_wait`, or `failed`
  - worker or operator recovery flow may move `failed -> dead_letter` or pending states to `cancelled` under explicit operational rules
- Claiming a run must be restart-safe and exclusive for that run record.
- Retry scheduling must update `available_at` and `attempt_count` durably before releasing the run back to the queue.
- Terminal states are `completed`, `dead_letter`, and `cancelled`.
- Retry classification in this spec is:
  - retryable: transient dependency failure, worker crash or lease expiry before terminal persistence, temporary lane/global-cap contention, or other explicitly classified transient infrastructure error
  - terminal: deterministic contract violation, missing canonical transcript state for the referenced trigger, non-retryable policy denial, or attempt exhaustion
- Retry backoff must be bounded and deterministic from persisted state:
  - the implementation may use exponential backoff with jitter-free deterministic intervals derived from `attempt_count`
  - `max_attempts` must be configurable and stored on the run row at creation time
- FIFO selection rules are:
  - workers choose eligible runs ordered by `available_at`, then `created_at`, then `id`
  - a later run for the same lane must not overtake an earlier eligible run for that lane
- The queue implementation may use PostgreSQL as the durable source of truth and may use Redis only as an acceleration layer for claiming, locks, or semaphores.

### Concurrency Contracts
- Session-lane exclusivity is mandatory:
  - at most one run with status `claimed` or `running` may hold the lane for a given `session_id`
  - a second run for the same `session_id` may remain `queued` or `retry_wait`, but it may not enter `running` until the active run releases the lane
- Session-lane enforcement must be safe across process restart and multi-worker deployment. An in-memory lock alone is insufficient.
- Global concurrency is capped by configuration and applies to graph executions in status `running`.
- If global capacity is unavailable, workers must leave the run queued or move it to `retry_wait`; they must not exceed the configured cap.
- Lane acquisition and global-cap checks must occur before graph invocation and must be released on success, failure, cancellation, or lease-expiry recovery.
- Lane ownership in this spec is a durable lease:
  - lane acquisition creates or refreshes exactly one `session_run_leases` row for the lane
  - a worker may execute only while its lease is valid and points to its `execution_run_id`
  - lease loss or expiry requires the worker to stop claiming ownership and treat completion persistence as best-effort, with duplicate-safe terminal updates
- Stale-lane recovery rules are:
  - expired leases may be stolen only by a new worker that first verifies the associated run is not already terminal
  - lease recovery must be idempotent and must never allow two workers to believe they simultaneously hold the same lane
- Global-cap enforcement must be restart-safe and multi-worker-safe. If Redis is used for acceleration, PostgreSQL-backed run state remains the canonical recovery source.

### Scheduler Contracts
- The scheduler is gateway-owned but may not invoke the graph runtime directly.
- Scheduler execution flow is:
  - load enabled `scheduled_jobs`
  - persist a `scheduled_job_fires` row with deterministic `fire_key`
  - submit a gateway-owned execution request that persists the canonical scheduler trigger message row when required and creates or looks up the corresponding `execution_runs` row
  - allow the normal worker queue to execute the run
- Scheduler-triggered turns must traverse the same runtime path as user-triggered turns after queue submission:
  - policy context is loaded at execution time
  - context assembly is loaded at execution time
  - transcript persistence uses the same canonical contracts as other turns
- Scheduler replay or duplicate fire delivery must resolve to the same `scheduled_job_fires` and `execution_runs` records rather than creating duplicates.
- This spec supports only persisted scheduler definitions owned by the application. Dynamic assistant-authored job creation or approval semantics beyond existing governance rules remain out of scope.
- The scheduler re-entry contract is a gateway-owned service boundary, not necessarily an HTTP loopback:
  - implementations may call an internal gateway service method instead of issuing an HTTP request to themselves
  - implementations may not bypass gateway-owned validation, transcript persistence, duplicate suppression, or run creation rules

### Repository and Service Contracts
- Run repository must support:
  - create-or-get by `(trigger_kind, trigger_ref)`
  - claim-next-eligible run with exclusive ownership and visibility timeout or equivalent recovery protection
  - state transition updates with attempt and error metadata
  - read-only lookup by `run_id`, `session_id`, and status
  - ordered listing for session diagnostics and worker claiming using the FIFO rules above
- Session concurrency service must support:
  - acquire lane for `session_id`
  - release lane for `session_id`
  - recover stale lane ownership after worker loss or timeout
- Scheduler repository must support:
  - persisted job definition reads
  - idempotent fire creation by `fire_key`
  - linking a fire record to the created or reused `execution_runs` row
- Worker execution service must:
  - reload runtime dependencies at execution time rather than capturing live request objects
  - invoke the same graph/runtime contracts introduced by Specs 002 through 004
  - persist explicit failure outcomes for retries and terminal exhaustion
  - classify failures as retryable or terminal using one explicit shared classifier rather than ad hoc exception handling
  - heartbeat or lease-refresh while long runs are executing if lease-based recovery is used

## Runtime Invariants
- Long graph runs do not block inbound HTTP workers because request handlers return after durable accept-and-queue work completes.
- Every user-visible turn still enters through the gateway-owned path before reaching the graph runtime.
- At most one active graph run exists per session lane.
- Accepted turns cannot be stranded in transcript history without a corresponding durable `execution_runs` record.
- Duplicate inbound replay, worker retry, or scheduler replay does not create duplicate logical runs for the same trigger identity.
- Queue records survive process restarts and are sufficient to resume eligible work without relying on in-memory request state.
- Policy, approval, and continuity context are evaluated at execution time, not frozen at enqueue time.
- Derived-state `outbox_jobs` from Spec 004 remain post-commit work and are not replaced by `execution_runs`.

## Security Constraints
- Workers must execute under the same policy and approval boundaries as synchronous gateway invocation would have used.
- Scheduler-submitted work must carry provenance metadata sufficient to distinguish job identity, fire identity, session target, and resulting `run_id`.
- Queue workers, schedulers, adapters, and control-plane clients may not bypass the gateway-owned contracts to call graph nodes directly.
- Failure or timeout in lane/global-cap acquisition must fail closed by deferring execution, not by running unsafely in parallel.
- No privileged capability becomes implicitly approved because a run was enqueued earlier; approval and revocation checks remain execution-time responsibilities.
- Scheduler-created transcript rows must preserve provenance and must not impersonate external channel senders.

## Operational Considerations
- Production queueing must be durable across restart; an in-process `BackgroundTask` path may exist only as clearly marked scaffold-only or debug-only behavior.
- Need structured logs, traces, and metrics for:
  - accepted inbound requests and returned `run_id`
  - queue depth and age
  - claim latency and execution latency
  - lane contention and global-cap saturation
  - retry counts, terminal failures, and dead-letter outcomes
  - scheduler fire creation, replay, and completion
- Need stale-run recovery rules for claimed or running work abandoned by worker crash, including lease expiry or equivalent claim timeout behavior.
- Need bounded retry policy with explicit retryable-vs-terminal classification so poison runs do not loop forever.
- Read-only operational diagnostics must make it possible to inspect queued, running, retrying, failed, and dead-letter runs by `session_id` and `run_id`.
- The initial production implementation in this repo should prefer PostgreSQL-backed durability first. Redis acceleration is optional and must remain replaceable without changing the canonical queue and lease contracts.

## Acceptance Criteria
- `POST /inbound/message` returns `202 Accepted` with durable `session_id`, `message_id`, and `run_id` without waiting for graph completion.
- A duplicate inbound delivery that resolves to the same persisted trigger does not create a second `execution_runs` row.
- Two concurrent accepted messages for the same session do not execute graph runs simultaneously; one may wait queued while the other runs.
- Two accepted messages for different sessions may execute concurrently up to the configured global cap.
- A newly accepted inbound turn cannot commit a user transcript row without also committing the initial queued run record that references it.
- A worker crash after claim but before completion leaves the run recoverable and does not require the original live HTTP request to resume execution.
- Scheduler fire replay for the same persisted fire identity does not create duplicate logical work.
- Scheduler-triggered turns persist a canonical transcript trigger row with scheduler provenance before queue execution begins.
- Scheduler-triggered runs traverse the same gateway-owned runtime path as user-triggered runs after submission and preserve policy and continuity behavior.
- Derived-state `outbox_jobs` continue to run only after transcript commit and are not conflated with user-visible execution queue records.

## Test Expectations
- API tests for `202 Accepted` semantics and returned run metadata from `POST /inbound/message`
- Repository tests for create-or-get duplicate suppression on `(trigger_kind, trigger_ref)`
- Repository or integration tests for exclusive run claim behavior and stale-claim recovery
- Unit and integration tests for session-lane exclusivity under concurrent arrivals to the same `session_id`
- Integration tests for global concurrency limits across different sessions
- Transactional integration tests proving first-delivery inbound persistence commits message row, dedupe completion, and queued run together or rolls them all back together
- Failure-mode tests covering worker crash after queue claim, retry scheduling, retry exhaustion, and dead-letter transition
- Integration tests proving scheduler fire replay is idempotent and reuses the same logical run
- Integration tests proving scheduler-created trigger rows use scheduler provenance and appear in continuity assembly as canonical turn triggers
- Integration tests proving scheduler-submitted work re-enters through gateway-owned contracts rather than direct graph invocation
- Integration tests proving approval visibility and continuity assembly are refreshed at execution time for queued work
