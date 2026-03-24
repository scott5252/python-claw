# Plan 006: Remote Node Runner and Per-Agent Sandboxing

## Target Modules
- `apps/gateway/deps.py`
- `apps/node_runner/main.py`
- `apps/node_runner/api/internal.py`
- `apps/node_runner/executor.py`
- `apps/node_runner/policy.py`
- `src/config/settings.py`
- `src/db/models.py` or additive execution-specific models such as `src/db/models_exec.py`
- `src/execution/runtime.py`
- `src/execution/contracts.py`
- `src/execution/audit.py`
- `src/jobs/repository.py`
- `src/sessions/concurrency.py`
- `src/sessions/repository.py`
- `src/sandbox/service.py`
- `src/sandbox/backends/container.py`
- `src/security/signing.py`
- `src/policies/service.py`
- `src/tools/registry.py`
- `src/tools/remote_exec.py`
- `src/capabilities/repository.py`
- `apps/worker/jobs.py`
- `migrations/versions/`
- `tests/`

## Migration Order
1. Add execution persistence for:
   - `node_execution_audits`
   - `agent_sandbox_profiles`
2. Add required enums, replay keys, and lookup indexes after the base tables exist:
   - unique `node_execution_audits(request_id)`
   - lookup `node_execution_audits(execution_run_id, created_at)`
   - lookup `node_execution_audits(session_id, created_at)`
   - lookup `node_execution_audits(agent_id, created_at)`
   - lookup `node_execution_audits(status, created_at)`
   - unique `agent_sandbox_profiles(agent_id)`
3. Extend execution persistence and contracts for retry-safe attempt identity and replay-safe continuity before transport wiring:
   - `tool_call_id`
   - `execution_attempt_number`
   - resolved `workspace_root`
   - resolved `workspace_mount_mode`
   - canonical remote-exec tool outcome persistence keyed by `request_id`
4. Introduce canonical request and signing contracts before wiring transport:
   - canonical JSON serialization
   - request freshness window enforcement
   - key-id based signing and verification
5. Add gateway-owned execution runtime and tool binding changes before enabling worker dispatch:
   - approval and policy refresh at execution time
   - deterministic request construction from approved resource versions
   - deterministic `request_id` derivation from `(execution_run_id, tool_call_id, execution_attempt_number)`
   - single-writer terminal outcome ownership tied to the active Spec 005 run lease
   - fail-closed omission of remote execution tools when approval state is missing
6. Add node-runner request verification, sandbox acquisition, allowlist enforcement, workspace resolution enforcement, and audit state transitions before enabling production dispatch.
7. Finish with integration and failure-mode coverage using `uv run pytest`.

## Implementation Shape
- Preserve the architecture boundary from [docs/architecture.md](/Users/scottcornell/src/projects/python-claw/docs/architecture.md): the gateway and workers decide whether an execution is authorized and construct one canonical request, while the node runner is a separate execution service that only verifies, isolates, executes, and records.
- Keep remote execution as a typed, approved capability extension of Specs 002 and 003 rather than a general subprocess primitive:
  - graph nodes continue to bind tools through `ToolRegistry`
  - the runtime must derive execution only from immutable `node_command_template` resources plus approved typed parameters
  - raw shell strings, `sh -c`, `bash -lc`, pipelines, and runtime-authored ad hoc argv remain denied
- Tie node dispatch identity explicitly to Spec 005 execution ownership:
  - derive `request_id` from `(execution_run_id, tool_call_id, execution_attempt_number)` with stable canonical hashing
  - transport retries for the same attempt reuse the exact same `request_id`
  - only a durably advanced later attempt may produce a new `request_id`
- Enforce a double-check model for privileged execution:
  - gateway or worker checks policy and exact approval match before dispatch
  - node runner re-checks the signed request, template consistency, executable allowlist, timeout ceilings, and sandbox constraints before starting any process
  - disagreement between gateway and node runner fails closed
- Keep terminal tool-outcome writing single-owner and restart-safe:
  - the worker holding the active Spec 005 lease for `execution_run_id` is the only writer of the terminal Spec 002 tool outcome
  - if lease ownership is lost, the worker stops polling or waiting and does not persist a terminal outcome
  - resumed workers reconcile from persisted node audit state keyed by `request_id` and then become the sole writer while they hold the active lease
- Resolve sandbox mode before any process launch, temp directory preparation, or workspace mount decision. Unsupported or ambiguous sandbox selection is a hard rejection.
- Resolve workspace identity before any process launch or mount preparation:
  - derive one canonical `workspace_root` from approved template data plus exact runtime scope
  - include `workspace_root` and `workspace_mount_mode` in the signed request and audit row
  - in this slice, `shared` mode mounts the resolved workspace as `read_only`
- Keep raw shell execution exceptional and privileged:
  - it is not part of the normal typed tool path
  - any scaffold-only host execution hook must stay disabled by default and require explicit deployment gating plus audit visibility
- Treat durability and idempotency as part of safety:
  - node runner persists or reuses the audit row keyed by `request_id` before acknowledging receipt
  - duplicate delivery returns the current persisted state and never launches a second process
- Keep transport and runtime fail-closed:
  - unsigned, stale, malformed, replayed-with-different-payload, policy-mismatched, sandbox-mismatched, or audit-write-failed requests never execute
  - unavailable node runners surface as execution failure to the worker and do not trigger local fallback execution inside the gateway
- Keep continuity aligned with Specs 002 and 004:
  - remote-exec terminal outcomes must be persisted through the canonical Spec 002 tool outcome path with `request_id`, status, failure category, and bounded diagnostics
  - `node_execution_audits` remain the operational execution-detail table rather than the only replay source for prior remote-exec outcomes

## Service and Module Boundaries
### Gateway and Worker Responsibilities
- `src/tools/registry.py`
  - expose remote execution adapters only when configuration, policy, and approval visibility all allow the capability
- `src/tools/remote_exec.py`
  - adapt a typed tool invocation into the gateway-owned remote execution runtime contract
  - never construct subprocesses directly
- `src/execution/runtime.py`
  - refresh execution-time policy, approval, and continuity state
  - load the approved `node_command_template`
  - derive canonical invocation params and final argv deterministically
  - derive canonical `workspace_root` and `workspace_mount_mode` deterministically
  - resolve sandbox mode and sandbox key from policy plus `agent_sandbox_profiles`
  - derive `request_id` from `(execution_run_id, tool_call_id, execution_attempt_number)`
  - create and sign `NodeExecRequest`
  - send the request to the node runner, reconcile resumed ownership by `request_id`, and translate the result into typed tool outcome state
- `src/policies/service.py`
  - enforce pre-dispatch capability visibility and execution-time approval matching
  - fail closed when approval, revocation, or policy data is stale or unavailable
- `apps/worker/jobs.py`
  - refresh policy and approval state immediately before dispatching queued work from Spec 005
  - never reuse enqueue-time approval decisions
  - release terminal outcome ownership when the active Spec 005 lease is lost
- `src/jobs/repository.py` and `src/sessions/concurrency.py`
  - expose the active execution-run lease state needed to enforce single-writer terminal outcome persistence
- `src/sessions/repository.py`
  - persist the canonical remote-exec tool outcome artifact with `request_id`, bounded diagnostics, and transcript-visible failure category for Spec 004 continuity replay

### Node Runner Responsibilities
- `apps/node_runner/api/internal.py`
  - expose `POST /internal/node/exec`
  - expose `GET /internal/node/exec/{request_id}`
  - keep the HTTP surface internal and execution-only
- `apps/node_runner/policy.py`
  - verify request signatures, freshness, and replay safety
  - enforce host executable allowlists, deny known shell wrappers, and apply timeout ceilings
  - reject anything stricter than or inconsistent with node policy
- `src/sandbox/service.py`
  - resolve backend descriptors from `sandbox_mode` and `sandbox_key`
  - resolve one canonical `workspace_root` and `workspace_mount_mode`
  - acquire or reuse the correct execution environment
  - refuse implicit downgrade from `agent` to `shared` or `off`, or from `shared` to `off`
- `apps/node_runner/executor.py`
  - execute argv-only subprocesses with `shell=False` or equivalent
  - capture bounded stdout and stderr previews
  - update audit state through start and terminal transitions
- `src/execution/audit.py`
  - encapsulate insert-or-get by `request_id`, transition updates, and read-only lookup

### Shared Contracts
- `src/execution/contracts.py`
  - define canonical `NodeExecRequest`, node response payloads, and result-state mappings
- `src/security/signing.py`
  - provide canonical serialization, keyed signing, and verification with explicit key ids and freshness validation
- `src/config/settings.py`
  - provide runner URL, signing keys, freshness windows, timeout ceilings, host allowlists, sandbox backend mappings, and explicit enablement flags for any direct-host mode

## Signed Request Design
- `NodeExecRequest` is the only dispatch payload between gateway and node runner. It must include:
  - `request_id`
  - `execution_run_id`
  - `tool_call_id`
  - `execution_attempt_number`
  - `session_id`
  - optional `message_id`
  - `agent_id`
  - `typed_action_id`
  - `approval_id`
  - `resource_version_id`
  - `resource_payload_hash`
  - `canonical_params_json`
  - `canonical_params_hash`
  - derived `argv`
  - resolved `sandbox_mode`
  - resolved `sandbox_key`
  - resolved `workspace_root`
  - resolved `workspace_mount_mode`
  - `issued_at`
  - `expires_at`
  - optional `trace_id`
- The gateway runtime must build the request from:
  - the immutable approved `node_command_template`
  - approved typed action parameters
  - bounded execution overrides allowed by the template
  - canonical workspace resolution rules derived from the template plus exact runtime scope
- Signature design:
  - canonicalize the full JSON body with stable ordering and no post-sign default expansion
  - sign the canonical body plus a signing `key_id`
  - transmit `key_id`, signature, and request body together
  - verify against the configured trusted public or shared keys on the node runner
- Freshness and replay rules:
  - `issued_at` and `expires_at` create a bounded freshness window
  - stale requests are rejected before sandbox selection or execution
  - `request_id` is the idempotency and replay key for one logical execution attempt
  - duplicate delivery with the same body reuses the existing audit row and current status
  - duplicate delivery with the same `request_id` but different signed body is rejected as a replay or tampering event
- Verification rules on the node runner:
  - reject unknown `key_id`
  - reject malformed or missing required fields
  - reject mismatched `resource_payload_hash`, `canonical_params_hash`, or derived `argv`
  - reject requests whose signed payload would require disallowed executable, env, working directory, timeout, or sandbox mode

## Sandbox Selection and Enforcement Path
1. The gateway runtime loads the agent sandbox profile and current policy inputs.
2. The gateway resolves one explicit `sandbox_mode` and `sandbox_key` for the invocation and includes both in the signed request.
3. The node runner verifies the signature and request freshness before touching execution state beyond audit persistence.
4. The node runner revalidates that the requested sandbox mode is allowed by deployment config and host policy.
5. `src/sandbox/service.py` resolves the backend descriptor:
   - `off`: allowed only when deployment config explicitly enables direct host execution and the agent profile allows it
   - `shared`: map `shared_profile_key` to a reusable configured container sandbox
   - `agent`: map `(session_id, agent_id, sandbox_profile_key)` to a dedicated container sandbox identity
6. `src/sandbox/service.py` resolves the canonical workspace:
   - `agent`: agent-scoped workspace root
   - `session`: session-and-agent scoped workspace root
   - `fixed`: deployment-defined workspace root keyed by `fixed_workspace_key`
7. The sandbox backend acquires or creates the target environment before process start and mounts the resolved workspace with the approved `workspace_mount_mode`, except that `shared` mode must mount it as `read_only` in this slice.
8. The executor launches the process only inside the selected environment with argv-only semantics.
9. Any failure in resolution, allocation, mount preparation, env filtering, or backend health returns a rejected or failed audit state without local fallback.

### Initial Container Isolation Contract
- `src/sandbox/backends/container.py`
  - use a configured image or backend descriptor per sandbox profile
  - mount a read-only image filesystem by default
  - allow writes only to the explicit workspace mount and explicit temp-data mount
  - pass only explicitly approved environment variables from the template allowlist
  - disable outbound network by default
  - run as an explicitly configured non-broad user identity
- The backend must make sandbox identity auditable:
  - `shared` is keyed by configured `shared_profile_key`
  - `agent` is keyed by `(session_id, agent_id, sandbox_profile_key)`
  - selection keys must appear in audit state or correlated events
- No silent downgrade is permitted:
  - failed `agent` allocation does not fall back to `shared` or `off`
  - failed `shared` allocation does not fall back to `off`
  - disabled `off` mode rejects the request even if the signed payload requested it

## Audit Schema and Event Design
### Persistent Audit Row
- `node_execution_audits` remains the primary durable record for each logical execution attempt. Required fields:
  - `id`
  - `request_id`
  - optional `execution_run_id`
  - optional `tool_call_id`
  - `execution_attempt_number`
  - optional `message_id`
  - `session_id`
  - `agent_id`
  - `requester_kind`
  - `sandbox_mode`
  - `sandbox_key`
  - `workspace_root`
  - `workspace_mount_mode`
  - `command_fingerprint`
  - `typed_action_id`
  - optional `approval_id`
  - optional `resource_version_id`
  - `status`
  - optional `deny_reason`
  - optional `exit_code`
  - `stdout_preview`
  - `stderr_preview`
  - `stdout_truncated`
  - `stderr_truncated`
  - `started_at`
  - optional `finished_at`
  - optional `duration_ms`
  - optional `trace_id`
  - `created_at`
  - `updated_at`

### Optional Structured Audit Events
- Add structured audit events through `src/execution/audit.py` or an observability companion if the codebase already prefers event records:
  - `node_exec_received`
  - `node_exec_rejected`
  - `node_exec_sandbox_acquired`
  - `node_exec_started`
  - `node_exec_completed`
  - `node_exec_failed`
  - `node_exec_timed_out`
- Each event should include:
  - `request_id`
  - `execution_run_id`
  - `tool_call_id`
  - `session_id`
  - `agent_id`
  - `typed_action_id`
  - `approval_id`
  - `sandbox_mode`
  - `sandbox_key`
  - `status`
  - optional `deny_reason`
  - optional `exit_code`
  - optional `duration_ms`
  - optional `trace_id`
- Keep previews bounded and sanitized:
  - no full transcript dumps
  - no unrestricted environment capture
  - no secret-bearing payload expansion
- Make `request_id` the correlation key across worker logs, node logs, tool outcomes, and audit persistence.

## Contracts to Implement
### Persistence and Configuration Contracts
- `src/db/models.py` or `src/db/models_exec.py` and `migrations/versions/`
  - define `node_execution_audits` and `agent_sandbox_profiles`
  - encode status enums, timestamps, replay key uniqueness, and lookup indexes
- `src/config/settings.py`
  - define node runner endpoint, signing key ids, key material references, freshness windows, timeout ceilings, executable allowlists, shell denylist, sandbox backend descriptors, and explicit direct-host execution enablement flags
  - define canonical workspace mapping for `agent`, `session`, and `fixed` workspace resolution

### Gateway Runtime Contracts
- `src/execution/runtime.py`
  - implement canonical request derivation, signing, dispatch, polling or sync result handling, and tool outcome translation
  - require refreshed approval and policy checks at dispatch time
  - fail closed if node runner transport is unavailable
- `src/execution/contracts.py`
  - define request, response, and audit-state mapping models with stable canonical serialization
- `src/tools/remote_exec.py`
  - map typed remote execution actions into the runtime service without exposing subprocess details to graph code
- `src/policies/service.py`
  - enforce exact approval and policy matching before tool exposure and again before dispatch
- `src/capabilities/repository.py`
  - provide immutable approved resource version lookup and exact approval lookup for execution-time enforcement

### Node Runner Contracts
- `apps/node_runner/main.py` and `apps/node_runner/api/internal.py`
  - wire internal HTTP endpoints, dependencies, and health-safe startup
- `apps/node_runner/policy.py`
  - implement signature verification, freshness checks, replay-safe duplicate handling, allowlist enforcement, timeout ceilings, and shell-wrapper denial
- `src/sandbox/service.py` and `src/sandbox/backends/container.py`
  - implement sandbox resolution, acquisition, reuse, and fail-closed rejection on unsupported backends or disabled modes
- `apps/node_runner/executor.py`
  - run the approved argv only
  - enforce `shell=False`
  - capture bounded output and duration
  - map process exit or timeout into audit terminal states
- `src/execution/audit.py`
  - implement insert-or-get by `request_id`, transition updates, and read-only status retrieval for polling workers

## Risk Areas
- Canonicalization drift between Spec 003 approval hashing, gateway request signing, and node-side verification causing false denials or unsafe acceptance.
- `request_id` derivation drifting from Spec 005 retry and lease ownership semantics, causing retries to be mistaken for duplicate deliveries or duplicate deliveries to be mistaken for new attempts.
- Gateway and node policy divergence around executable allowlists, shell deny patterns, env overrides, or timeout ceilings.
- Sandbox reuse leaking workspace or temporary state across agents if `shared` and `agent` keys are not enforced exactly, or if workspace resolution is not deterministic.
- Hidden fallback behavior that executes locally in the gateway when node dispatch, sandbox acquisition, or audit persistence fails.
- Replay handling that treats duplicate delivery as safe but fails to detect different payloads under the same `request_id`.
- Lease loss or worker crash causing more than one component to believe it may persist the terminal Spec 002 remote-exec outcome.
- Overly broad direct-host execution enablement turning the exceptional `off` mode into the default path.

## Rollback Strategy
- Keep schema and service changes additive so existing typed tool paths continue to function without remote execution enabled.
- Leave remote execution tool binding disabled unless all of the following are configured and healthy:
  - signing keys
  - node runner URL
  - sandbox backend mappings
  - audit persistence
- If the node runner or sandbox backend becomes unavailable, the runtime must omit or fail the remote execution tool rather than silently running commands in-process on the gateway.
- Keep `off` mode explicitly disabled by default so partial rollback cannot widen privilege.

## Test Strategy
- Unit:
  - canonical JSON serialization and stable request hashing
  - stable `request_id` derivation from `(execution_run_id, tool_call_id, execution_attempt_number)`
  - signature verification with correct `key_id`
  - stale signature rejection based on `expires_at`
  - derived argv verification against approved template and canonical params
  - shell-wrapper and raw-command denial
  - sandbox mode resolution for `off`, `shared`, and `agent`
  - deterministic workspace resolution and read-only workspace enforcement for `shared` mode
  - lease-loss behavior that prevents non-owner workers from persisting terminal tool outcomes
  - fail-closed behavior when sandbox config, approval data, or audit persistence is missing
- Repository:
  - `insert-or-get` idempotency on `request_id`
  - duplicate delivery with same payload returns existing state
  - duplicate delivery with different payload under same `request_id` is rejected and never executes
  - audit transition persistence for `received`, `rejected`, `running`, `completed`, `failed`, and `timed_out`
  - canonical remote-exec tool outcome persistence keyed by `request_id` for continuity replay
- Integration:
  - signed approved request executes successfully through gateway -> node runner -> audit completion
  - unsigned request is rejected before execution and records a denial
  - stale signature is rejected before sandbox acquisition or process start
  - denied command or disallowed executable is rejected even if the gateway attempted dispatch
  - queued work whose approval or policy is revoked before execution is denied at dispatch time
  - transport retry for the same attempt reuses the same `request_id`, while a durable worker retry creates a new one only after attempt advancement
  - node runner unavailability produces a transport failure outcome and does not fall back to local execution
  - unavailable sandbox backend rejects the request without downgrade
  - duplicate request delivery does not create a second process
  - worker crash or lease loss allows a resumed worker to reconcile the same `request_id` without producing a second terminal tool outcome
  - unavailable node during worker polling returns a non-success tool outcome that remains auditable
- Implementation notes:
  - use `uv sync` for environment setup
  - run targeted checks with `uv run pytest tests`

## Constitution Check
- Gateway-first execution preserved: only the gateway and workers construct canonical execution requests, and the node runner stays execution-only rather than becoming an orchestration path.
- Approval-before-privilege preserved: typed remote execution remains hidden unless policy and approval allow it, and execution-time refresh is required before dispatch.
- Fail-closed behavior preserved: signature, approval, policy, sandbox, allowlist, audit, or transport failures deny execution instead of falling back.
- Observable, bounded execution preserved: every logical attempt is keyed by `request_id`, recorded durably, and test-covered for the main denial and failure modes.
