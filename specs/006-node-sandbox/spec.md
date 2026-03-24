# Spec 006: Remote Node Runner and Per-Agent Sandboxing

## Purpose
Separate orchestration from privileged execution by introducing a fail-closed remote node runner that executes only signed, policy-approved, audit-linked requests inside explicit sandbox modes.

## Non-Goals
- Channel delivery logic or media handling
- Human approval UX beyond the governance contracts from Spec 003
- Arbitrary raw shell execution, shell pipelines, or `sh -c` style command strings
- A generic free-form `system_run(command: str)` production capability
- Broad user-wide or workspace-wide sandbox reuse policies
- Auth profile rotation or control-plane fleet management

## Upstream Dependencies
- Specs 001, 002, 003, 004, and 005

## Scope
- A node-runner service boundary separate from gateway and graph orchestration
- Signed gateway-to-node execution requests with bounded freshness and replay protection
- A remote execution capability that extends the typed tool and approval model from Specs 002 and 003
- Sandbox mode resolution for `off`, `shared`, and `agent`
- Container-backed isolation for `shared` and `agent` modes in the initial implementation
- Host-side allowlist enforcement and fail-closed denial behavior
- Durable execution audit records and read-only diagnostics sufficient for operations and tests
- Execution-time policy and approval refresh for queued work from Spec 005

## Data Model Changes
- `node_execution_audits`
  - `id`
  - stable `request_id`
  - optional `execution_run_id`
  - optional `tool_call_id`
  - `execution_attempt_number`
  - optional `message_id`
  - `session_id`
  - `agent_id`
  - `requester_kind` with values `graph_turn` or `resume`
  - `sandbox_mode` with values `off`, `shared`, or `agent`
  - `sandbox_key`
  - `workspace_root`
  - `workspace_mount_mode` with values `read_only` or `read_write`
  - `command_fingerprint`
  - `typed_action_id`
  - optional `approval_id`
  - optional `resource_version_id`
  - `status` with values `received`, `rejected`, `running`, `completed`, `failed`, `timed_out`
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
- `agent_sandbox_profiles`
  - `id`
  - unique `agent_id`
  - `default_mode` with values `off`, `shared`, or `agent`
  - `shared_profile_key`
  - `allow_off_mode`
  - `max_timeout_seconds`
  - `created_at`
  - `updated_at`
- Required indexes
  - unique index on `node_execution_audits(request_id)`
  - lookup index on `node_execution_audits(execution_run_id, created_at)`
  - lookup index on `node_execution_audits(session_id, created_at)`
  - lookup index on `node_execution_audits(agent_id, created_at)`
  - lookup index on `node_execution_audits(status, created_at)`
  - unique index on `agent_sandbox_profiles(agent_id)`

## Contracts
### Capability and Approval Contracts
- Spec 003 is extended with one privileged capability family in this slice: remote node execution through a versioned `resource_kind=node_command_template`.
- A `node_command_template` resource version is immutable and contains the execution artifact to be approved and enforced:
  - a canonical executable template sufficient to derive one final argv vector deterministically at execution time
  - optional `env_allowlist` of environment variable names allowed to flow into the runner
  - optional `working_dir`
  - `workspace_binding_kind` with values `agent`, `session`, or `fixed`
  - optional `fixed_workspace_key` required when `workspace_binding_kind=fixed`
  - `workspace_mount_mode` with values `read_only` or `read_write`
  - `typed_action_id`
  - `sandbox_profile_key`
  - `timeout_seconds`
- Raw shell strings are not supported in this spec:
  - requests must execute with argv semantics only
  - `shell=True`, command concatenation, pipes, redirection, and interpreter wrappers such as `sh -c` or `bash -lc` are denied
- Approval matching continues to use Spec 003 exactness:
  - `resource_version_id`
  - immutable resource payload hash
  - `typed_action_id`
  - deterministic canonical parameter hash for the concrete invocation
  - exact `session_id` and `agent_id` scope
- The concrete invocation parameters in this spec are limited to typed action parameters plus bounded execution overrides:
  - bounded `env` entries whose keys are present in the approved template allowlist
  - optional `working_dir` only when the approved template declares one
  - `timeout_seconds` when less than or equal to the approved template maximum
- The final argv presented to the execution host must be derived by the remote execution runtime service from:
  - the immutable approved `node_command_template`
  - the approved typed action parameters for the invocation
  - the allowed bounded execution overrides in this spec
- The resolved workspace presented to the execution host must be derived by the remote execution runtime service from:
  - the immutable approved `node_command_template.workspace_binding_kind`
  - the exact `session_id` and `agent_id` scope already enforced by Spec 003 approvals
  - deployment-defined workspace mapping for any `fixed_workspace_key`
- Callers may not submit an ad hoc runtime-authored workspace path or mount target in this slice.
- Callers may not submit an ad hoc runtime-authored `argv` vector for host execution in this slice.
- The derivation from approved template plus typed parameters to final argv must be deterministic and must participate in the same canonical parameter hashing used for approval enforcement and node request construction.
- No defaulted or expanded execution parameter may be introduced after approval hashing.

### Gateway and Worker Contracts
- The gateway and queue workers remain the only components that may request remote execution for a user-visible turn.
- The remote execution tool is omitted from the bound tool set unless:
  - remote execution is enabled by configuration
  - the current execution-time policy context allows the capability
  - the current turn context includes a matching active approval from Spec 003
- Remote execution capability exposure must remain inside the Spec 002 typed tool factory model:
  - the `ToolRegistry` binds approved remote execution capabilities as typed tools or typed action adapters
  - graph nodes may not special-case remote execution by constructing subprocess requests inline
  - a generic `system_run(command: str)` surface is scaffold-only and must not be the normal production primitive for this spec
- Workers introduced by Spec 005 must refresh policy, approval, and continuity state at execution time before creating a node request.
- The graph runtime never contacts the execution host directly from a tool implementation with ad hoc parameters. It must construct one canonical `NodeExecRequest` through an injected runtime service.
- For one logical remote-execution attempt, the worker path must first durably determine the execution attempt identity before dispatch:
  - transport retries for the same attempt reuse the same `request_id`
  - a new `request_id` may be created only after the worker has durably advanced to a new execution attempt for the same `execution_run_id` and `tool_call_id`
- The worker holding the active Spec 005 lease for the owning `execution_run_id` is the only component allowed to persist the terminal Spec 002 tool outcome for that remote execution attempt.
- If a worker loses lease ownership while waiting on node completion, it must stop polling or waiting, stop writing terminal tool outcomes, and allow a resumed worker to reconcile from persisted node audit state keyed by `request_id`.

### Node Request Contract
- `NodeExecRequest` is the canonical gateway-to-node request body. Required fields are:
  - stable `request_id`
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
- `request_id` must be deterministic for duplicate delivery of the same logical execution attempt and unique across distinct attempts.
- In this spec, one logical execution attempt is scoped by `(execution_run_id, tool_call_id, execution_attempt_number)`.
- The gateway-owned runtime must derive `request_id` from those fields with a stable canonical hash so:
  - transport retries or duplicate submissions for the same attempt reuse the exact same `request_id`
  - worker-level retries that intentionally create a new attempt for the same tool call produce a different `request_id`
- The request signature covers the exact canonical JSON body plus a signing key identifier.
- If a `request_id` already exists in `node_execution_audits`, that existing row is the single authority for the logical execution attempt in any state.
- Duplicate delivery of an existing `request_id` must never start a second process.
- For duplicate delivery, the node runner must return the current persisted state for the existing `request_id` rather than creating a second execution record or re-running the command.
- The node runner must reject the request before execution if any of the following checks fail:
  - signature verification
  - unknown key identifier
  - expired `expires_at`
  - malformed or missing required fields
  - mismatch between request `derived argv`, approved resource payload, and canonical invocation parameters
  - disallowed `sandbox_mode`
  - mismatch between approved payload and concrete invocation parameters

### Node Runner Contracts
- The node runner is an execution service, not an orchestration surface:
  - it does not assemble context
  - it does not bind tools
  - it does not resolve approvals interactively
  - it does not call the graph runtime
- The node runner must independently enforce host safety even for a valid signed request:
  - execute with argv semantics only
  - deny non-allowlisted executables
  - deny known shell interpreters and command wrapper patterns
  - enforce configured timeout ceilings
  - enforce sandbox mode resolution and sandbox-key routing before process start
- Host allowlists are a second line of defense and may be stricter than gateway policy. If gateway and node policy disagree, execution fails closed.
- The node runner must persist or update a `node_execution_audits` row before acknowledging receipt and must use the same row to record terminal outcome.
- The node runner may expose an internal HTTP surface in this spec:
  - `POST /internal/node/exec`
  - `GET /internal/node/exec/{request_id}`
- These endpoints are internal service contracts only. They are not user-facing APIs.

### Sandbox Contracts
- Sandbox mode is resolved per execution from `agent_sandbox_profiles` plus runtime policy inputs.
- Modes in this spec are:
  - `off`: execute without an isolation container. This mode is allowed only when `allow_off_mode=true` for the agent profile and the deployment configuration explicitly enables it. Otherwise requests selecting `off` are rejected.
  - `shared`: execute inside a reusable sandbox identified by `shared_profile_key`. Different agents may share the same sandbox only when they intentionally map to the same configured key.
  - `agent`: execute inside a dedicated sandbox identified by `(session_id, agent_id, sandbox_profile_key)` for this spec.
- Workspace resolution is explicit and deterministic in this slice:
  - `workspace_binding_kind=agent` resolves the canonical workspace for the approved `agent_id`
  - `workspace_binding_kind=session` resolves the canonical workspace for the exact `(session_id, agent_id)` pair
  - `workspace_binding_kind=fixed` resolves a deployment-defined workspace from `fixed_workspace_key`
  - the resolved `workspace_root` must be included in the signed `NodeExecRequest` and in the audit row
- The initial implementation for `shared` and `agent` should be container-backed so the isolation boundary is explicit and operationally inspectable. Another backend may substitute later only if it preserves the same mode semantics, auditability, and fail-closed behavior.
- The initial implementation for container-backed `shared` and `agent` sandboxes must satisfy this minimum isolation contract:
  - the container image root filesystem is read-only by default, except for explicitly configured writable mounts
  - writable filesystem access is limited to an explicit workspace mount and an explicit temporary-data mount
  - environment variables visible inside the sandbox are limited to values explicitly derived from the approved request and the template `env_allowlist`
  - outbound network access is disabled by default unless a later spec extends the policy model to permit and audit it
  - the execution user identity inside the sandbox must be explicitly configured and may not default implicitly to broad host-equivalent privileges
- Workspace mount rules are:
  - `shared` mode must mount the resolved workspace as `read_only` in this spec
  - `agent` mode may use the approved `workspace_mount_mode`, but only for the single resolved workspace root included in the signed request
  - `off` mode may use the resolved workspace only when direct-host execution is explicitly enabled and the same workspace resolution rules succeed
- Sandbox selection must occur before any process launch or filesystem preparation.
- A request may not silently downgrade from `agent` to `shared` or `off`, or from `shared` to `off`. Unsupported sandbox allocation fails closed.
- Sandbox teardown and reuse may be implementation-defined in this slice, but the selection key and isolation boundary must remain deterministic and auditable.

### Repository and Service Contracts
- The application configuration surface must support:
  - canonical local configuration through the project-root `.env` and Settings model for runner URL, signing key identifiers, timeout ceilings, and sandbox backend defaults
  - deployment-defined sandbox profile mapping for `shared` and `agent` container images or equivalent backend descriptors
- The signing service must support:
  - canonical JSON serialization
  - keyed signing by key identifier
  - verification with freshness-window enforcement
- The sandbox service must support:
  - resolve sandbox mode and sandbox key for a request
  - resolve one canonical `workspace_root` and `workspace_mount_mode` for a request from approved template data plus runtime scope
  - acquire or create the execution environment for `shared` and `agent`
  - reject unsupported direct-host execution when `off` is disabled
- The remote execution runtime service must support:
  - construct `NodeExecRequest` from refreshed runtime state
  - compute `canonical_params_hash` with the same canonicalizer used by Spec 003 approval enforcement
  - send the signed request to the node runner
  - translate node-runner result back into recorded tool outcome state for Spec 002 persistence
  - reconcile resumed or recovered worker ownership from persisted node audit state keyed by `request_id`
- The audit repository must support:
  - insert-or-get by `request_id`
  - state transition updates for `received`, `rejected`, `running`, and terminal outcome
  - read-only lookup by `request_id`, `execution_run_id`, and `session_id`
- The Spec 002 canonical tool outcome artifact for remote execution must persist enough continuity data to support Spec 004 replay without treating the audit table as the only replay source. At minimum, the canonical tool outcome record must include:
  - `request_id`
  - `tool_call_id`
  - terminal tool outcome status
  - transcript-visible failure category when non-successful
  - bounded stdout and stderr previews or a bounded diagnostic summary derived from the audit row
  - optional `exit_code`
- `node_execution_audits` remains the operational and host-execution detail table, but it is not the only continuity-facing record for prior remote execution outcomes.
- The node execution and tool outcome lifecycle contract in this slice is:
  - transport between worker and node runner may be synchronous or asynchronous
  - if transport is asynchronous, `POST /internal/node/exec` returns the accepted `request_id` and the worker is responsible for polling `GET /internal/node/exec/{request_id}` until a terminal state
  - async polling and terminal-outcome persistence must remain single-writer:
    - only the worker that currently holds the active Spec 005 lease for `execution_run_id` may persist the terminal Spec 002 tool outcome
    - a resumed worker may adopt an existing `request_id` by reading persisted node audit state and then become the sole terminal-outcome writer for that run while it holds the active lease
  - regardless of transport style, exactly one recorded tool outcome is produced per logical execution attempt
  - node audit states map to tool outcome states as follows:
    - `received` -> no terminal tool outcome yet; worker continues waiting or polling
    - `running` -> no terminal tool outcome yet; worker continues waiting or polling
    - `completed` with exit code `0` -> successful tool outcome
    - `completed` with non-zero exit code -> failed tool outcome with bounded diagnostics
    - `failed` -> failed tool outcome with bounded diagnostics
    - `timed_out` -> timed-out tool outcome
    - `rejected` -> denied or failed-closed tool outcome with explicit denial metadata
  - transcript-visible failure categorization must distinguish at minimum:
    - approval or policy denial
    - host safety denial
    - execution failure with non-zero exit
    - timeout
    - transport or runner availability failure

## Runtime Invariants
- Queue workers, schedulers, adapters, and control-plane clients still may not bypass the gateway-owned runtime contracts to invoke graph nodes directly.
- Remote execution approvals are checked at execution time, not at enqueue time.
- Unsigned, expired, malformed, duplicate, or policy-mismatched requests never start a process.
- Raw shell execution remains unavailable in this spec.
- The node runner cannot widen authority granted by the gateway; it may only reject more strictly.
- Every execution attempt is traceable through a durable audit row linked to session, agent, run, and approval context.
- Every execution attempt is also traceable through a canonical Spec 002 tool outcome artifact linked by `request_id`, so Spec 004 continuity replay does not depend on operational audit reads alone.
- `agent` sandbox mode never reuses a sandbox across different `(session_id, agent_id, sandbox_profile_key)` identities in this spec.
- A logical execution attempt identified by `request_id` may produce at most one process launch and at most one terminal tool outcome.

## Security Constraints
- Signed requests are mandatory for every node-runner execution attempt.
- Approval before privileged execution remains mandatory and exact-hash bound under Spec 003.
- The execution host must invoke subprocesses with `shell=False` or equivalent argv-only semantics.
- Command allowlist enforcement happens on the execution host even when the gateway already filtered the request.
- Failure to resolve sandbox mode, create sandbox state, verify signature, or persist audit state must fail closed before execution.
- Captured stdout and stderr must be bounded; sensitive full-output retention is out of scope for this slice.

## Operational Considerations
- The initial implementation should keep the node runner small and stateless apart from audit persistence and sandbox lifecycle state.
- Sandbox backend configuration should flow through application settings derived from the project-root `.env`, not an ad hoc workspace-authored runtime file.
- Structured logs, traces, and metrics are required for:
  - request signing and verification failures
  - allowlist denials and policy mismatches
  - sandbox acquisition latency and reuse outcomes
  - execution latency, exit code, timeout, and denial reason
  - duplicate `request_id` replay handling
- `stdout_preview` and `stderr_preview` must be truncated to a bounded size with explicit truncation flags so audit rows remain operationally safe.
- Timeouts must be enforced both by the node runner and by the worker-side client waiting for node completion.
- `off` mode must be treated as an explicitly enabled local-development or tightly controlled deployment option rather than an implicit production default.
- Read-only operational inspection must make it possible to retrieve the latest execution attempt for a `request_id` and bounded recent attempts for a `session_id` or `execution_run_id`.

## Acceptance Criteria
- A valid approved remote execution request produces one signed `NodeExecRequest`, one durable audit row, and one bounded recorded tool outcome.
- A request with an invalid or expired signature is rejected before process launch and records a rejected audit outcome.
- A request whose concrete invocation does not exactly match the approved `resource_version_id`, `typed_action_id`, and `canonical_params_hash` is rejected before process launch.
- A request for a non-allowlisted executable is rejected on the node host even if the gateway attempted to send it.
- Duplicate delivery of the same `request_id` does not create conflicting execution records or run the command twice.
- Duplicate delivery of an in-flight `request_id` returns the existing execution state for that request rather than creating a second execution attempt.
- Transport retries for the same `(execution_run_id, tool_call_id, execution_attempt_number)` reuse the same `request_id`, while a durable worker retry for a later execution attempt produces a different `request_id`.
- `agent` sandbox mode does not reuse sandbox state across different `(session_id, agent_id, sandbox_profile_key)` identities.
- `shared` and `agent` modes execute through the configured container-backed sandbox path rather than silently falling back to direct-host execution.
- Container-backed `shared` and `agent` execution use the minimum isolation contract in this spec for filesystem mounts, environment propagation, execution identity, and default-disabled network access.
- Workspace resolution is deterministic and auditable, and `shared` mode mounts the resolved workspace as read-only in this slice.
- If remote execution is disabled or no matching approval exists, the tool is absent from the bound tool set and the graph still runs with remaining allowed tools.
- A queued run from Spec 005 reevaluates approval and policy state at execution time before creating a node request.
- The runtime service derives the final host `argv` from the approved template plus typed invocation parameters; callers do not submit ad hoc command vectors.
- Spec 002 persistence records the terminal remote-exec tool outcome with `request_id` and bounded diagnostics so Spec 004 replay can reconstruct prior outcomes without depending only on `node_execution_audits`.
- The worker-to-runner integration produces the same terminal tool outcome mapping regardless of whether transport is implemented synchronously or asynchronously.

## Test Expectations
- Unit tests for canonical request signing and verification, including freshness-window rejection
- Unit tests for deterministic `canonical_params_hash` reuse across approval enforcement and node request construction
- Unit tests proving final host `argv` derivation is deterministic from approved template plus typed invocation parameters
- Unit tests proving `request_id` derivation is stable for transport retries of the same attempt and changes only when `execution_attempt_number` advances durably
- Unit tests for host allowlist enforcement and explicit denial of shell interpreters or wrapper patterns
- Unit tests for sandbox-mode resolution from `agent_sandbox_profiles` and runtime policy inputs
- Unit tests for deterministic workspace resolution and `shared`-mode read-only workspace mount enforcement
- Unit tests for duplicate `request_id` handling while an execution is still `received` or `running`
- Unit tests for node audit state to tool outcome state mapping
- Unit tests for lease-loss behavior proving a worker that no longer holds the active Spec 005 lease cannot persist the terminal tool outcome
- Unit tests proving typed remote execution capability binding uses injected tool factories or runtime services rather than inline graph-node subprocess construction
- Repository or contract tests for `node_execution_audits` idempotency on `request_id`
- Repository or contract tests for canonical remote-exec tool outcome persistence keyed by `request_id`
- Integration tests for signed success, invalid-signature rejection, expired-request rejection, and allowlist denial
- Integration tests proving duplicate `request_id` replay does not re-execute the command
- Integration tests proving duplicate delivery returns the existing execution state for in-flight requests
- Integration tests proving the remote execution tool is omitted when approval is missing, revoked, expired, or remote execution is disabled
- Integration tests proving queued execution refreshes approval state before node request creation
- Integration tests proving a resumed worker can reconcile an existing `request_id` after worker loss without producing a second terminal tool outcome
- Integration tests proving `agent` mode allocates distinct sandbox identities for different session-agent pairs
- Integration tests proving `shared` and `agent` modes use the configured container-backed execution path instead of host execution
- Integration tests proving container-backed execution enforces the minimum isolation contract defined by this spec
