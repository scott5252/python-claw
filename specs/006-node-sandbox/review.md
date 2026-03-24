# Spec Review: 006 Remote Node Runner and Per-Agent Sandboxing

## Review Status
- Spec clarified: `yes`
- Plan analyzed: `yes`
- Constitution check passed: `partial`
- Ready for implementation: `not yet`

## Constitution Alignment
- The spec satisfies the constitution's required sections for a `spec.md`: purpose, non-goals, dependencies, data-model changes, contracts, invariants, security constraints, operational considerations, acceptance criteria, and test expectations.
- Gateway-first execution is preserved: the graph runtime still routes privileged execution through a gateway-owned runtime seam rather than invoking node execution directly.
- Approval-before-activation is preserved at a high level: remote execution remains typed, policy-gated, approval-gated, signed, and audited.
- Observable, bounded delivery is mostly preserved: the slice stays bounded and defines audit, log, metric, and test expectations.
- The remaining issues are not constitutional violations of structure; they are implementation-critical ambiguities that keep the spec from being safely "ready for implementation."

## What Is Solid
- The slice is appropriately bounded around remote privileged execution, signed transport, sandbox selection, and execution auditability.
- Raw shell execution remains explicitly out of scope.
- `node_command_template`, `NodeExecRequest`, and `node_execution_audits` give the implementation a concrete backbone.
- The spec correctly keeps host allowlists as a second fail-closed control rather than relying only on gateway-side approval.

## Remaining Issues

### 1. Duplicate `request_id` handling is internally ambiguous
- Why this matters:
  - [spec.md](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md#L129) requires deterministic duplicate delivery semantics.
  - [spec.md](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md#L136) only rejects duplicates already in a terminal state.
  - [spec.md](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md#L228) says duplicate delivery must not re-execute the command.
  - That leaves in-flight duplicates underspecified.
- Risk:
  - Two workers could race on the same `request_id`, or a retry could arrive while the first attempt is still `received` or `running`, and different implementations could either re-run, poll, reject, or block.
- Solutions:
  1. Treat any existing `request_id` row, in any state, as the single authority. New duplicate deliveries never start execution; they return the existing row's current status.
  2. Reject only terminal duplicates, but allow a duplicate to attach as a watcher when the row is `received` or `running`.
  3. Introduce a runner-side lease or lock table so only one executor may transition a request into `running`; duplicates receive `202 Accepted` plus polling guidance.
  4. Split idempotency into `request_id` and `attempt_id`, where only `attempt_id` may execute and `request_id` is a grouping key.
- Recommendation:
  - Choose solution 1. It is the simplest fail-closed rule, easiest to test, and best aligned with the existing unique audit row model.

### 2. Sandbox isolation semantics are too loose for a safe first implementation
- Why this matters:
  - [spec.md](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md#L163) and [spec.md](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md#L168) define identity and downgrade behavior, but not the minimum isolation contract inside the sandbox.
  - [spec.md](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md#L173) refers to backend descriptors, but not which host resources may be mounted, persisted, or network-accessible.
  - The current review overstates this as "concrete enough to build and test."
- Risk:
  - Different implementations could make materially different security choices around filesystem mounts, writable directories, environment inheritance, network egress, and cleanup, while all claiming compliance.
- Solutions:
  1. Define a minimum container contract in the spec: read-only image root, explicit writable workspace mount, explicit temp mount, default network disabled, explicit env pass-through only from `env_allowlist`.
  2. Keep backend-agnostic wording, but add a required "sandbox profile schema" with fields for mounts, writable paths, network policy, user identity, and cleanup policy.
  3. Limit Spec 006 to `off` and `agent` only, deferring `shared` until backend semantics are fully specified.
  4. Require a single blessed backend for this slice, such as Docker-based execution with a fixed profile template matrix.
- Recommendation:
  - Choose solution 1. It keeps the spec implementable now, preserves the current backend flexibility later, and gives reviewers and implementers a crisp baseline.

### 3. The approved artifact and invocation parameter model is not precise enough
- Why this matters:
  - [spec.md](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md#L75) says the approved template contains `argv`.
  - [spec.md](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md#L91) also says concrete invocation parameters include `argv`.
  - [spec.md](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md#L138) rejects mismatches between approved payload and concrete invocation parameters.
  - The spec never says whether runtime `argv` must be identical to the approved template, whether placeholders are allowed, or whether only suffix arguments may vary.
- Risk:
  - Implementers may build incompatible approval models: some may approve an exact command line, while others may treat the template as a parameterized command family.
- Solutions:
  1. Exact-only model: approved `argv` must match runtime `argv` byte-for-byte; no substitution is allowed in Spec 006.
  2. Placeholder model: approved template may contain named placeholders, and the canonical approval hash includes both the template and the resolved parameter object.
  3. Prefix-locked model: executable and fixed prefix are immutable, but a bounded typed `args` suffix may vary according to schema.
  4. Typed-parameter model: remove runtime `argv` from the external contract and require the runtime service to derive final `argv` from typed action parameters plus the approved template.
- Recommendation:
  - Choose solution 4. It best matches the constitution's typed-action preference, reduces approval drift, and avoids turning the runner contract into a semi-generic command composer.

### 4. Tool outcome and execution lifecycle mapping is underspecified
- Why this matters:
  - [spec.md](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md#L153) requires the runner to persist before acknowledging receipt.
  - [spec.md](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md#L186) requires translation back into Spec 002 tool outcome state.
  - [spec.md](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md#L224) requires one bounded recorded tool outcome.
  - The spec does not define whether node execution is synchronous from the worker's perspective, whether `GET` polling is normative, or how `received`, `running`, `failed`, `timed_out`, and `rejected` map into tool outcomes.
- Risk:
  - Teams could ship incompatible behavior for retries, user-visible tool messages, timeout propagation, and partial diagnostics.
- Solutions:
  1. Make Spec 006 strictly synchronous: `POST /internal/node/exec` returns only after terminal completion, and `GET` is diagnostics-only.
  2. Make Spec 006 explicitly async: `POST` returns accepted plus `request_id`; the worker polls `GET` until terminal state and then writes the tool outcome.
  3. Allow either sync or async transport, but require a normative state-mapping table from node audit status to tool outcome status and transcript-visible failure category.
  4. Collapse node audit status into the existing tool outcome state machine and forbid runner-specific intermediate states from leaking upward.
- Recommendation:
  - Choose solution 3. It preserves implementation flexibility while still making cross-service behavior testable and consistent.

## Review of `review.md`
- The prior review conclusion was too optimistic in four areas:
  - it treated the constitution check as fully passed rather than structurally passed with implementation-critical ambiguities remaining
  - it treated sandbox semantics as concrete enough to implement, even though minimum isolation rules are still unspecified
  - it treated duplicate handling as explicit, even though in-flight duplicate behavior is still ambiguous
  - it marked the spec ready for implementation before the execution lifecycle and approval parameter model were fully pinned down

## Recommended Next Step
- Update `spec.md` to resolve the four issues above.
- After that, rerun the review and only restore `Ready for implementation: yes` once the spec contains:
  - one explicit duplicate-delivery rule
  - one minimum sandbox isolation contract
  - one unambiguous approval-to-invocation parameter model
  - one normative lifecycle mapping from node execution state to tool outcome state

## Sign-Off
- Reviewer: `Codex`
- Date: `2026-03-24`
- Decision: `changes requested`
- Summary: Spec 006 is structurally aligned with the constitution and much stronger than a generic remote-exec proposal, but it still contains four implementation-critical ambiguities. Resolve those in the spec before treating the slice as ready to build.
