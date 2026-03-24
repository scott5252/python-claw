# Spec Review: 005 Async Execution, Scheduler, Queueing, and Concurrency Lanes

## Review Status
- Spec clarified: `yes`
- Plan analyzed: `yes`
- Constitution check passed: `yes`
- Ready for implementation: `yes`

## Scope Check
- The slice remains bounded around durable async execution, scheduler submission, and concurrency control.
- Later-spec concerns remain excluded: remote node sandboxing, media, broad control-plane UX, and new approval semantics are still non-goals.
- Upstream dependencies on Specs 001 through 004 are correct because this slice extends inbound durability, graph execution, governance refresh, and context continuity.

## Contract Check
- The spec now makes the highest-risk contract explicit: first-delivery inbound transcript persistence, queued run creation, and dedupe completion must commit together before `202 Accepted` is returned.
- Scheduler-triggered work now has explicit transcript rules, including canonical trigger rows with scheduler provenance and duplicate-safe fire reuse.
- Concurrency is now implementable without guesswork through durable lane leases, FIFO claim ordering, and stale-lease recovery rules.
- Read-only diagnostics are now named explicitly so operations and tests have concrete API targets.

## Security and Policy Check
- Gateway-first execution is preserved. Scheduler re-entry must use the gateway-owned service contract and may not call graph nodes directly.
- Transcript-first durability is preserved. Async execution does not replace canonical transcript history, and accepted turns cannot be stranded without a durable run record.
- Execution-time policy and approval refresh remain explicit for queued work.
- Failure paths fail closed on queue creation, lane contention, and global-cap saturation.

## Operational Check
- Migration order is now clear enough to implement safely: storage first, then API/schema changes, then worker behavior.
- Observability and failure handling are sufficient for this slice, including claim latency, queue age, retries, dead-letter outcomes, and scheduler fire replay.
- The spec now calls out PostgreSQL-first durability as the production baseline and constrains any background-task path to scaffold-only behavior.

## Acceptance and Testing Check
- Acceptance criteria are executable and cover the critical crash window, scheduler parity, concurrency, and recovery behavior.
- Test expectations now include the missing transactional integration case and scheduler transcript provenance coverage.
- Cross-boundary integration points are identified where they matter most: inbound acceptance, worker recovery, scheduler replay, and execution-time policy/context refresh.

## Clarifications Required
- Decision:
  - Owner: `resolved in spec`
  - Resolution: Accepted inbound work must atomically commit transcript row, queued run, and dedupe completion.
- Decision:
  - Owner: `resolved in spec`
  - Resolution: Scheduler-triggered turns persist canonical transcript trigger rows with `sender_id=scheduler:{job_key}` and enqueue through gateway-owned contracts.
- Decision:
  - Owner: `resolved in spec`
  - Resolution: Session concurrency uses durable lane leases with stale-lease recovery instead of in-memory locking.
- Decision:
  - Owner: `resolved in spec`
  - Resolution: Workers claim eligible runs in FIFO order within a lane and classify retryable versus terminal failures through one explicit shared classifier.

## Plan Analysis Notes
- Risk:
  - Impact: Accepting a user message without a durable queued run would strand visible work after a crash.
  - Mitigation: Implement the transactional inbound accept-and-enqueue contract first and test rollback behavior before changing the API to `202 Accepted`.
- Risk:
  - Impact: Scheduler replay could create duplicate visible turns and duplicate runs.
  - Mitigation: Use deterministic `fire_key`, create-or-get fire persistence, and create-or-get run creation keyed by the fire identity.
- Risk:
  - Impact: Lease expiry could allow parallel execution in the same session lane.
  - Mitigation: Use durable lease rows with expiry checks, idempotent recovery, and duplicate-safe terminal updates.

## Sign-Off
- Reviewer: `Codex`
- Date: `2026-03-23`
- Decision: `approved`
- Summary: Spec 005 is now concrete enough to implement safely without violating gateway-first execution, transcript-first durability, or approval and continuity refresh guarantees.
