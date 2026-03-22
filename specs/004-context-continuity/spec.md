# Spec 004: Context Engine Lifecycle, Continuity, Compaction, and Recovery

## Purpose
Harden continuity so context-window pressure, partial failures, or loss of derived state do not destroy the assistant's ability to reconstruct conversation state.

## Non-Goals
- Remote node execution
- Media delivery
- Presence and auth failover

## Upstream Dependencies
- Specs 001 and 002

## Scope
- Four-phase context lifecycle: ingest, assemble, compact, after-turn
- Versioned `summary_snapshots`
- Post-commit idempotent `outbox_jobs`
- Continuity reconstruction algorithm
- Recovery and repair services/jobs
- Compaction and retry flow for context overflow

## Data Model Changes
- `summary_snapshots`
- `outbox_jobs`
- Optional transcript chunk index for older-history retrieval

## Contracts
- Transcript remains canonical.
- Summary snapshots cover transcript ranges and are additive.
- After-turn derived-state work is created post-commit only.
- Recovery jobs operate from durable transcript/session state alone.

## Runtime Invariants
- No durable context is destroyed during compaction.
- Context assembly is deterministic and inspectable.
- Retrieval failure does not block transcript-first model invocation.
- Replaying transcript can rebuild continuity after derived-state loss.

## Security Constraints
- Derived-state workers must not mutate canonical transcript history.
- Recovery jobs must be idempotent and traceable.

## Operational Considerations
- Need repair jobs for missing summaries or failed outbox jobs.
- Need metrics for compaction failures, replay latency, and empty-memory retrieval on long sessions.

## Acceptance Criteria
- Graph can compact and retry after context overflow.
- Transcript-only recovery works after deleting derived artifacts.
- Duplicate outbox delivery does not duplicate derived state.
- Latest valid summary snapshot can be retrieved and inspected.

## Test Expectations
- Failure-mode tests for crash points, outbox duplication, concurrent inbound turns, retrieval outage, replay, and compaction/retry
