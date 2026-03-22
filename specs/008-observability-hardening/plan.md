# Plan 008: Presence, Observability, Auth Failover, and Operational Hardening

## Target Modules
- `apps/gateway/api/health.py`
- `apps/gateway/websocket/control.py`
- `src/observability/tracing.py`
- `src/providers/auth_profiles.py`
- `src/domain/presence.py`
- `src/config/settings.py`
- `tests/`

## Migration Order
1. Create `auth_profiles`
2. Add indexes for provider/agent/status lookup
3. Add any diagnostics views or read models if required

## Implementation Shape
- Configure structured logging and tracing first so later work is visible.
- Bind provider auth lookup through an `AuthProfileStore`.
- Expose read-only operational surfaces for presence, runs, jobs, and continuity health.

## Risk Areas
- Logging secrets
- Presence endpoints doing expensive synchronous aggregation
- Cooldown logic leaving the system without a fallback key unexpectedly

## Rollback Strategy
- If tracing backends are unavailable, structured local logs remain mandatory.

## Test Strategy
- Unit: auth-profile selection/cooldown, presence snapshots
- Integration: diagnostics surfaces and failure telemetry
