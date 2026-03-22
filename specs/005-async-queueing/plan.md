# Plan 005: Async Execution, Scheduler, Queueing, and Concurrency Lanes

## Target Modules
- `apps/gateway/api/inbound.py`
- `apps/worker/jobs.py`
- `apps/worker/scheduler.py`
- `src/sessions/concurrency.py`
- `src/jobs/repository.py`
- `src/domain/events.py`
- `tests/`

## Migration Order
1. Add queued-run/job tracking tables if needed
2. Add indexes for run status and session-lane lookup

## Implementation Shape
- Change inbound handling to persist then enqueue.
- Start with background execution only if clearly marked scaffold-only; production path should target a durable worker queue.
- Introduce session-lane lock manager and global concurrency semaphore.
- Make scheduler submit the same inbound contract used by channels.

## Risk Areas
- Lost work between accept and enqueue
- Session starvation under lane locking
- Retry loops creating duplicate downstream work

## Rollback Strategy
- Preserve synchronous debug path only as explicitly non-production fallback.
- Queue failures should fail closed or leave clear retryable state.

## Test Strategy
- Unit: lane manager behavior, retry classification
- Integration: accepted response, queued completion, scheduler re-entry, contention handling
