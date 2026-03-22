# Spec 008: Presence, Observability, Auth Failover, and Operational Hardening

## Purpose
Add the operator-facing surfaces and failure handling needed for a credible multi-user deployment.

## Non-Goals
- New business capabilities
- Channel redesign
- Capability-governance redesign

## Upstream Dependencies
- Specs 001 through 007

## Scope
- Presence endpoint and/or WebSocket presence snapshots
- Structured logging and tracing
- Multi-auth profile rotation and cooldown
- Recovery metrics and alerts
- Admin diagnostics for sessions, jobs, runs, and stuck work

## Data Model Changes
- `auth_profiles`
- Optional presence or health snapshots if persisted
- Metrics or diagnostics views as needed

## Contracts
- Logs, traces, and audits must correlate by session, run, agent, and channel.
- Auth profile selection occurs before provider invocation.
- Operators can inspect job and session health without raw DB queries.

## Runtime Invariants
- Failures are diagnosable without direct database inspection.
- Auth-profile failure can rotate to another active profile where configured.
- Continuity failures emit visible telemetry.

## Security Constraints
- Admin diagnostics are read-only unless explicitly authorized.
- Secrets never appear in logs, traces, or presence payloads.

## Operational Considerations
- Need alert thresholds for failed outbox jobs, compaction failures, and stuck runs.
- Presence payloads should avoid expensive live aggregation per request.

## Acceptance Criteria
- Presence/status can be queried externally.
- Auth failures can put one profile on cooldown and rotate to another.
- Operators can inspect stuck runs, failed jobs, and active sessions through diagnostics surfaces.

## Test Expectations
- Tests for auth rotation, telemetry emission, and diagnostics access control
