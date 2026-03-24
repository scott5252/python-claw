# Plan 005: Async Execution, Scheduler, Queueing, and Concurrency Lanes

## Target Modules
- `apps/gateway/api/inbound.py`
- `apps/gateway/api/admin.py`
- `apps/gateway/deps.py`
- `apps/worker/jobs.py`
- `apps/worker/scheduler.py`
- `src/config/settings.py`
- `src/domain/schemas.py`
- `src/domain/events.py`
- `src/db/models.py`
- `src/gateway/idempotency.py`
- `src/jobs/repository.py`
- `src/jobs/service.py`
- `src/routing/service.py`
- `src/sessions/concurrency.py`
- `src/sessions/repository.py`
- `src/sessions/service.py`
- `src/graphs/assistant_graph.py`
- `src/context/outbox.py`
- `migrations/versions/`
- `tests/`

## Migration Order
1. Add durable queueing tables:
   - `execution_runs`
   - `session_run_leases`
   - `scheduled_jobs`
   - `scheduled_job_fires`
2. Add required enums, retry metadata, ownership fields, and indexes only after the base tables exist:
   - unique `execution_runs(trigger_kind, trigger_ref)`
   - lookup `execution_runs(status, available_at, created_at, id)`
   - lookup `execution_runs(session_id, status, created_at)`
   - lookup `execution_runs(lane_key, status, available_at)`
   - lookup `execution_runs(worker_id, status)`
   - unique `session_run_leases(lane_key)`
   - unique `session_run_leases(execution_run_id)`
   - lookup `session_run_leases(worker_id, lease_expires_at)`
   - unique `scheduled_jobs(job_key)`
   - unique `scheduled_job_fires(fire_key)`
   - lookup `scheduled_job_fires(scheduled_job_id, scheduled_for)`
   - lookup `scheduled_job_fires(status, scheduled_for)`
3. Extend repository contracts before changing HTTP behavior:
   - create-or-get by `(trigger_kind, trigger_ref)`
   - FIFO eligible-run selection
   - lane lease acquire, refresh, release, and stale-lease recovery
   - scheduler fire create-or-get and fire-to-run linking
   - bounded read-only run diagnostics by `run_id` and `session_id`
4. Refactor the inbound acceptance path so Spec 001 dedupe completion, transcript persistence, and initial queued run creation commit in one transaction before any `202 Accepted` response is returned.
5. Move graph invocation out of `SessionService.process_inbound` into worker-owned execution services that reload runtime dependencies at execution time and preserve Spec 004 after-turn `outbox_jobs`.
6. Add scheduler submission only after the gateway accept-and-enqueue contract is stable, including deterministic `session` and `routing_tuple` target resolution and scheduler transcript provenance.
7. Finish with integration and recovery coverage using `uv run pytest`.

## Implementation Shape
- Preserve the architecture boundary from [docs/architecture.md](/Users/scottcornell/src/projects/python-claw/docs/architecture.md): the gateway accepts and durably enqueues user-visible work, workers execute graph runs asynchronously, and the scheduler re-enters through a gateway-owned service contract rather than calling graph code directly.
- Replace the current two-session claim/work flow from Spec 001 with one gateway-owned transaction for first delivery:
  - claim or replay the dedupe identity
  - resolve or create the canonical session
  - append the inbound transcript row
  - create or look up the initial `execution_runs` row in `queued`
  - finalize the dedupe row with replayable identifiers
  - commit once before returning `202 Accepted`
- Keep duplicate suppression layered and deterministic:
  - Spec 001 dedupe still prevents duplicate transcript rows
  - `execution_runs(trigger_kind, trigger_ref)` prevents duplicate logical work for the same persisted trigger
  - `scheduled_job_fires(fire_key)` prevents duplicate scheduler fire submission
- Make accepted work durable before the response changes:
  - do not switch the public success contract from `201` to `202 Accepted` until the transactional accept-and-enqueue path is fully in place
  - fail closed if the run row cannot be durably created or reused
- Split responsibilities in `src/sessions/service.py` and new job services cleanly:
  - inbound session service owns route resolution, canonical transcript persistence, and queue submission
  - worker execution service owns run claiming, lease refresh, graph invocation, retry classification, and terminal persistence
  - graph/runtime code remains the execution engine introduced by Specs 002 through 004 and is reloaded with fresh dependencies at worker execution time
- Keep session-lane and global concurrency enforcement restart-safe:
  - lane ownership is durable in `session_run_leases`
  - global concurrency is configuration-driven and enforced before graph invocation
  - in-memory locks may assist local coordination but may not be the source of truth
- Keep FIFO and fairness explicit:
  - workers select eligible runs ordered by `available_at`, then `created_at`, then `id`
  - a later run for the same `session_id` must not overtake an earlier eligible run in that lane
- Keep scheduler submission transcript-first and gateway-first:
  - persisted jobs create persisted fire rows first
  - `routing_tuple` targets resolve through the same routing rules as Spec 001
  - scheduler-triggered turns persist a canonical `role=user` trigger message with `sender_id=scheduler:{job_key}` before queue execution
  - scheduler submission uses the same gateway-owned validation and queue creation contract as inbound work, without requiring an HTTP loopback
- Preserve Spec 004 separation between user-visible execution and derived-state work:
  - `execution_runs` are the canonical queue for user-visible graph turns
  - `outbox_jobs` remain post-commit derived-state work for summaries, indexing, and repair
  - worker completion must continue to enqueue or preserve after-turn `outbox_jobs` instead of folding that work into the run queue
- Keep diagnostics read-only in this slice:
  - `GET /runs/{run_id}`
  - `GET /sessions/{session_id}/runs`
  - no replay, cancel, or dead-letter mutation APIs in this spec

## Contracts to Implement
### Gateway and Inbound Contracts
- `apps/gateway/api/inbound.py`
  - return `202 Accepted` with `session_id`, `message_id`, `run_id`, and current run `status`
  - stop invoking the graph inline on the request path
  - preserve Spec 001 routing validation and dedupe replay semantics while extending them to run creation
- `src/domain/schemas.py`
  - extend the inbound response schema for accepted-and-queued semantics
  - define read-only run diagnostics models and bounded session-run listing models
- `src/gateway/idempotency.py`
  - support the single-transaction accept-and-enqueue flow instead of a commit-separated claim/finalize path
  - preserve safe handling of persisted `claimed` rows so duplicate delivery never creates a second transcript row or second logical run

### Queue, Lease, and Worker Contracts
- `src/db/models.py` and `migrations/versions/`
  - define `execution_runs`, `session_run_leases`, `scheduled_jobs`, and `scheduled_job_fires`
  - encode run statuses, retry metadata, worker ownership, lease expiry, scheduler target fields, and required uniqueness and lookup indexes
- `src/jobs/repository.py`
  - create-or-get run rows by trigger identity
  - claim next eligible run with exclusive ownership and FIFO ordering
  - persist run transitions, attempts, `available_at`, timestamps, `worker_id`, and terminal errors
  - read runs by `run_id`, `session_id`, and status for diagnostics and worker operations
  - create-or-get scheduler fires by `fire_key` and link them to reused or new run rows
- `src/sessions/concurrency.py`
  - provide durable session-lane lease acquire, refresh, release, and stale-lease recovery helpers
  - coordinate with global concurrency limits without relying on process-local state for correctness
- `src/jobs/service.py` and `apps/worker/jobs.py`
  - implement claim, lease heartbeat, graph execution, retry classification, deterministic backoff, and terminal-state persistence
  - reload runtime dependencies at execution time rather than capturing request-scoped objects
  - preserve Spec 003 execution-time approval refresh and Spec 004 continuity/context refresh

### Scheduler and Routing Contracts
- `apps/worker/scheduler.py`
  - load enabled jobs, compute deterministic fire identities, and persist create-or-get fire rows
  - submit work through the gateway-owned queueing service contract rather than invoking graph code directly
- `src/routing/service.py`
  - resolve persisted `routing_tuple` scheduler targets with the same normalization and session-key rules used for inbound channel traffic
- `src/sessions/repository.py` and `src/sessions/service.py`
  - expose deterministic session lookup needed for `target_kind=session`
  - persist scheduler trigger transcript rows with scheduler provenance before creating or reusing the associated run row

### Runtime and After-Turn Contracts
- `apps/gateway/deps.py` and `src/config/settings.py`
  - provide worker-safe dependency construction plus queue, lease, retry, and global-concurrency configuration
- `src/graphs/assistant_graph.py`
  - remain the reusable runtime entry for a single turn, now invoked from the worker path instead of the inbound request path
- `src/context/outbox.py`
  - remain dedicated to Spec 004 derived-state processing and stay separate from user-visible run queueing

## Risk Areas
- Stranded visible work if a user message commits without its initial queued run or if dedupe completion commits before run creation.
- Duplicate logical runs if replay handling keys off raw inbound payloads instead of persisted trigger identities like `message_id` or `fire_key`.
- Parallel execution in one session if lease expiry, lease stealing, or completion persistence is not duplicate-safe.
- FIFO drift within a session lane if worker selection ignores earlier eligible runs for the same lane.
- Scheduler target drift if persisted `routing_tuple` targets do not reuse Spec 001 normalization and session-key rules.
- Governance or continuity staleness if queued runs execute with enqueue-time policy or context state instead of execution-time refresh from Specs 003 and 004.
- Spec 004 regression if after-turn summary, repair, or indexing work is accidentally merged into `execution_runs` instead of remaining `outbox_jobs`.

## Rollback Strategy
- Keep schema changes additive and leave the existing canonical transcript path intact.
- Do not change the public inbound success code to `202 Accepted` until transactional run creation is live and tested.
- Preserve a clearly marked scaffold-only synchronous or background-task fallback only if needed for local debugging; production behavior must remain durable-queue first.
- If worker or scheduler components are disabled, accepted turns must fail closed rather than pretending to complete synchronously or bypassing queue contracts.
- Keep `outbox_jobs` independently disableable from the user-visible run queue so Spec 004 derived-state recovery remains isolated.

## Test Strategy
- Unit:
  - retry classification and deterministic backoff
  - lane lease acquisition, refresh, expiry, and stale-lease recovery
  - global concurrency gate behavior
  - deterministic scheduler target resolution for both `session` and `routing_tuple`
- Repository:
  - create-or-get duplicate suppression on `(trigger_kind, trigger_ref)`
  - FIFO eligible-run ordering by `available_at`, `created_at`, and `id`
  - duplicate-safe terminal transitions after lease loss or worker retry
  - scheduler fire reuse and fire-to-run linking
  - bounded recent run listing in descending creation order for diagnostics
- API:
  - `POST /inbound/message` returns `202 Accepted` with `run_id` and status
  - duplicate delivery returns the same logical run instead of creating another
  - `GET /runs/{run_id}` and `GET /sessions/{session_id}/runs` remain read-only and bounded
- Integration:
  - transactional accept-and-enqueue behavior so a user turn cannot commit without its queued run
  - long-running graph execution no longer blocks inbound request handlers
  - same-session contention keeps one run queued while another runs
  - different-session runs execute concurrently up to the configured global cap
  - worker crash or lease expiry leaves work recoverable without the original HTTP request context
  - scheduler replay reuses the same fire and run identities
  - scheduler-triggered turns persist canonical transcript trigger rows with scheduler provenance
  - execution-time refresh of policy, approval visibility, and continuity state for queued runs
- Implementation notes:
  - use `uv sync` for environment setup
  - run targeted checks with `uv run pytest tests`

## Constitution Check
- Gateway-first execution preserved: inbound traffic and scheduler work both enter through gateway-owned validation, transcript persistence, and queue submission contracts.
- Transcript-first durability preserved: no accepted visible turn can exist without a canonical trigger transcript row and a durable queued run.
- Approval and continuity refresh preserved: queued runs load policy and context at execution time, not from stale enqueue-time state.
- Observable, bounded delivery preserved: run diagnostics, retry metadata, scheduler provenance, and explicit failure modes are part of the implementation contract.
