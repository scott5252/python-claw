# Tasks 005: Async Execution, Scheduler, Queueing, and Concurrency Lanes

1. Add job/run tracking schema if required by the chosen queue design.
2. Write tests for session-lane locking and global concurrency limits.
3. Refactor inbound endpoint to persist then enqueue work.
4. Implement background worker entrypoint for graph execution.
5. Implement scheduler jobs that re-enter through the gateway contract.
6. Add duplicate-work suppression around queue retries and scheduler replays.
7. Add integration tests for accepted/queued flow, lane contention, and scheduler parity.
