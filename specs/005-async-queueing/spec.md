# Spec 005: Async Execution, Scheduler, Queueing, and Concurrency Lanes

## Purpose
Move graph execution out of request-bound handlers and enforce safe concurrency behavior at both session and system scope.

## Non-Goals
- Remote node sandboxing
- Media handling
- Presence and auth rotation

## Upstream Dependencies
- Specs 001, 002, and 004

## Scope
- Accepted/queued inbound response pattern
- Background graph execution
- Session-lane locking
- Global concurrency cap
- Scheduler re-entry through the gateway
- Retry-policy integration and duplicate-work suppression

## Data Model Changes
- Job/run tracking as needed for queued executions
- Scheduler job definitions if not already present

## Contracts
- Gateway accepts and persists inbound work, then queues execution.
- At most one active run exists per session lane.
- Scheduler creates gateway events rather than bypassing transport.

## Runtime Invariants
- Long runs do not block inbound HTTP workers.
- Duplicate work is prevented or safely ignored.
- Session-lane exclusivity is enforced.

## Security Constraints
- Queue workers follow the same policy path as foreground messages.
- Scheduler events carry trace and provenance metadata.

## Operational Considerations
- Need visibility into queued, running, failed, and retried runs.
- Queue choice must survive process restarts in production.

## Acceptance Criteria
- Inbound HTTP returns acceptance without waiting for long graph completion.
- Two concurrent messages to one session do not run simultaneously.
- Scheduled jobs enter through the same gateway path as user messages.

## Test Expectations
- Integration tests for accepted/queued semantics, lane contention, scheduler re-entry, and duplicate suppression
