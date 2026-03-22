# Plan 003: User-Controlled Capability Governance

## Target Modules
- `apps/gateway/deps.py`
- `src/db/models.py` or additive governance-specific models such as `src/db/models_capabilities.py`
- `src/db/session.py`
- `src/sessions/repository.py`
- `src/sessions/service.py`
- `src/graphs/state.py`
- `src/graphs/nodes.py` or a dedicated approval node/module such as `src/graphs/nodes_approval.py`
- `src/graphs/assistant_graph.py`
- `src/policies/service.py`
- `src/tools/registry.py`
- `src/tools/typed_actions.py`
- `src/capabilities/activation.py`
- `src/capabilities/repository.py`
- `src/observability/` or a dedicated governance audit module if one is introduced
- `migrations/`
- `tests/`

## Migration Order
1. Add normalized governance tables for:
   - `governance_transcript_events`
   - `resource_proposals`
   - `resource_versions`
   - `resource_approvals`
   - `active_resources`
   - approval queue records if kept separately for this slice
2. Add required uniqueness and lookup indexes after the tables exist:
   - proposal state/session lookup
   - latest-version lookup
   - proposal-version uniqueness
   - approval exact-match lookup
   - active-resource lookup
   - queue-state lookup if a queue table exists
3. Extend transcript-linked persistence for governance artifacts before wiring approval execution paths:
   - proposal created
   - approval requested
   - approval decided
   - activation attempted/result
   - revocation applied
4. Introduce repository and policy contracts before graph changes so approval-aware runtime flow depends on explicit interfaces rather than direct table access.
5. Implement approval-aware runtime classification, persisted await-approval exit, resume, activation, and revocation handling behind the gateway-owned path only.
6. Finish with deterministic unit, repository, and integration coverage using `uv run pytest`.

## Implementation Shape
- Preserve the architecture boundary from [docs/architecture.md](/Users/scottcornell/src/projects/python-claw/docs/architecture.md): channel adapters, schedulers, workers, and control-plane code submit through the gateway, but only the gateway-owned runtime path may change approval visibility, activate resources, or apply revocations.
- Preserve transcript-first durability from the constitution by writing governance events into a dedicated append-only `governance_transcript_events` table linked to the canonical transcript while also maintaining normalized lookup tables for enforcement; implementation must treat this as dual durability, not an either-or choice.
- Keep the slice bounded to exact-match approvals only:
  - one artifact version
  - one typed action
  - one canonicalized parameter payload
  - no ambient, family-wide, or reusable approval contracts in this spec
- Classify the user request before model-facing tool binding so denied or unapproved capabilities are omitted before inference/tool exposure.
- Extend Spec 002 runtime contracts rather than replacing them:
  - `AssistantState` may carry approval-gating artifacts for the current turn only
  - `ToolRuntimeContext.policy_context` must expose approval visibility and revocation metadata needed for binding
  - execution-time enforcement must still re-check approvals even when a tool appears bound
- Model proposal and activation as separate persisted state machines with explicit transition ownership and immutable proposal versions. This split state-machine model is the canonical implementation contract for this spec.
- Implement deterministic parameter canonicalization once and reuse the same canonicalizer for approval packet rendering and execution-time enforcement.
- Keep `ActivationController` as the sole activation path and make it idempotent on `(proposal_id, resource_version_id, typed_action_id, canonical_params_hash)`.
- Treat approval waits as persisted runtime state:
  - persist proposal and approval-request artifacts
  - treat transcript-linked governance events as the canonical wait/resume record
  - keep approval queue rows, if present, as derived lookup state rather than the source of truth
  - exit the turn in an awaiting-approval state
  - resume later from a gateway-owned invocation with refreshed policy context and re-bound tools
- Keep raw shell unavailable in this slice. Typed actions are the only normal execution surface, and privileged shell/remote execution remains for a future spec with its own approval contract.

## Contracts to Implement
### Governance Persistence and Repositories
- `src/db/models.py` or additive governance models plus `migrations/`
  - define append-only `governance_transcript_events`, proposal, version, approval, active-resource, and optional approval-queue persistence
  - encode immutable proposal-version semantics, revocation markers, approval expiry, and required indexes
- `src/capabilities/repository.py` or `src/sessions/repository.py`
  - expose explicit repository methods for proposal creation, immutable version writes, approval decision persistence, activation result persistence, revocation persistence, and exact-match approval lookup
  - persist transcript-linked governance artifacts and normalized enforcement rows together at the repository boundary
  - make duplicate approval submissions and duplicate activation attempts safe and deterministic

### Policy, Typed Action, and Activation Contracts
- `src/policies/service.py`
  - classify when a request requires a gated capability before tool binding
  - expose approval visibility and revocation metadata for runtime binding
  - fail closed when approval data is missing, stale, expired, denied, or revoked
  - treat `scope_kind` as session-and-agent scoped only for this slice
- `src/tools/typed_actions.py`
  - define the typed action catalog used by approval packets and enforcement
  - keep normal approved automation on typed actions rather than shell-shaped execution
- `src/capabilities/activation.py`
  - implement `ActivationController`
  - persist activation attempts, success/failure outcome, and active-resource state updates in the same gateway-owned transaction boundary
  - enforce idempotency on the exact approval identity tuple
- `src/policies/service.py` or a dedicated enforcement module
  - implement `ExecutionPolicyEnforcer`
  - require exact match on `resource_version_id`, `content_hash`, `typed_action_id`, canonical parameter hash, and unexpired/unrevoked approval state at execution time

### Runtime and Graph Contracts
- `src/graphs/state.py`
  - extend runtime state with approval-gating artifacts needed only for the current turn
  - keep approval wait/resume markers explicit rather than inferred from missing tool outcomes
- `src/graphs/nodes.py` or `src/graphs/nodes_approval.py`
  - classify intent before model-facing tool binding
  - persist proposals and approval-request artifacts when a gated capability is needed
  - exit in persisted awaiting-approval state instead of pausing approval only in memory
  - resume through refreshed policy context and tool rebinding after approval changes
- `src/graphs/assistant_graph.py`
  - keep the approval-aware runtime flow on the gateway-owned execution path
  - ensure resumed turns use refreshed policy context rather than stale bound tool state
- `src/tools/registry.py`
  - omit denied or unapproved capabilities during tool binding
  - re-bind visible tools from current policy context per turn
- `src/sessions/service.py` and `apps/gateway/deps.py`
  - wire repository, policy, activation, and runtime dependencies without allowing adapters or workers to call activation directly

## Risk Areas
- Dual durability drift between transcript-linked governance artifacts and normalized enforcement tables if persistence boundaries are not implemented atomically enough.
- Lifecycle terminology drifting back toward a single combined state machine during implementation, which would blur proposal state and activation state.
- Approval breadth silently expanding beyond exact-match semantics during implementation, which would violate the spec and constitution.
- Resume-time tool visibility becoming stale if approval state changes are not reflected through refreshed `policy_context` and per-turn rebinding.
- Activation or revocation being callable outside the gateway-owned runtime path, weakening audit correlation and policy enforcement.
- Canonicalization mismatches between approval rendering and execution checks causing approved actions to fail or mismatched actions to pass.
- Mutable proposal/version updates breaking the required immutable artifact history.
- Duplicate approval submission or duplicate activation creating conflicting active state.

## Rollback Strategy
- Keep schema changes additive and preserve existing transcript/session read paths during rollout.
- Default to deny and omit tools if governance lookup, canonicalization, or approval state resolution is unavailable.
- Keep transcript-linked artifact writing as the stable audit record even if normalized lookup usage must be partially rolled back.
- Gate approval-aware runtime changes behind gateway-owned dependency wiring so adapters, schedulers, and workers do not gain direct activation paths during partial rollback.

## Test Strategy
- Unit:
  - proposal and activation state transitions, including denial, expiry, activation failure, and revocation
  - deterministic parameter canonicalization with stable key ordering and type preservation
  - exact approval matching on version, content hash, typed action, and canonical params
  - tool visibility filtering that omits denied or unapproved capabilities before binding
  - execution-time enforcement rejecting missing, mismatched, expired, stale, denied, or revoked approvals
  - `ActivationController` idempotency on duplicate activation attempts
  - immutable proposal/version storage once persisted
- Repository or persistence:
  - dual persistence of transcript-linked governance artifacts and normalized governance lookup rows
  - duplicate approval submission handling without conflicting approval state
  - revocation persistence immediately affecting future visibility and execution checks
- Integration:
  - proposal -> approval -> activation happy path through the gateway-owned runtime path
  - blocked raw shell and blocked unapproved activation
  - persisted approval-request exit and later gateway-owned resume with refreshed tool binding
  - later-turn and later-execution denial after revocation
  - failure handling for stale approvals, denied proposals, expired approvals, and restart-safe in-flight approval waits
- Implementation notes:
  - use `uv sync` for environment setup
  - run targeted checks with `uv run pytest tests`

## Constitution Check
- Gateway-first execution preserved: approval enforcement, activation, resume handling, and revocation stay on the gateway-owned runtime path; adapters, schedulers, workers, and control-plane code do not activate capabilities directly.
- Transcript-first durability preserved: governance events are append-only transcript-linked artifacts, while normalized governance tables remain derived enforcement structures that must stay consistent with durable history.
- Approval-before-activation preserved: agents only propose, exact-match approval is required before visibility/activation/execution, and privileged shell remains fail-closed and out of scope for this spec.
- Observable, bounded delivery preserved: the slice remains limited to governance for typed capabilities, includes explicit invariants and failure-mode coverage, and requires structured audit/provenance fields and deterministic tests.
