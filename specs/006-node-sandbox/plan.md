# Plan 006: Remote Node Runner and Per-Agent Sandboxing

## Target Modules
- `apps/node_runner/main.py`
- `apps/node_runner/executor.py`
- `src/tools/remote_exec.py`
- `src/sandbox/service.py`
- `src/policies/service.py`
- `src/security/signing.py`
- `src/db/models_exec.py`
- `tests/`

## Migration Order
1. Add execution audit storage
2. Add per-agent sandbox config persistence if DB-backed

## Implementation Shape
- Keep the node runner small and fail closed.
- Resolve sandbox mode before command dispatch.
- Bind remote-exec exposure only after approval and policy checks.
- Capture request metadata, stdout/stderr preview, duration, and outcome in audit logs.

## Risk Areas
- Signature validation gaps
- Allowlist checks diverging between gateway and node
- Shared sandbox leakage between agents

## Rollback Strategy
- If remote execution is disabled, the graph must continue without exposing the tool.

## Test Strategy
- Unit: signing, allowlist enforcement, sandbox selection
- Integration: signed request acceptance, unsigned rejection, blocked command behavior
