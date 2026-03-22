# Spec 003: User-Controlled Capability Governance

## Purpose
Ensure agents can propose resources and actions, but cannot activate or execute dangerous capabilities without explicit user approval.

## Non-Goals
- Remote node transport details
- Media handling
- Auth failover
- Scheduler-triggered approvals
- Dispatcher mechanics beyond the gateway-owned runtime path
- Multi-turn continuity, replay, or recovery jobs outside approval gating
- Broad capability-family or user-wide ambient approval models

## Upstream Dependencies
- Specs 001 and 002

## Scope
- Request classification before tool binding
- Proposal, approval, activation, and revocation lifecycle
- Typed action catalog for normal operations
- Approval queue and approval state machine
- Provenance and audit logging
- Approval subgraph or equivalent gated runtime flow

## Data Model Changes
- Governance transcript artifacts use a dedicated append-only table linked to the canonical transcript rather than overloading user-visible message rows.
- `governance_transcript_events`
  - `id`
  - `session_id`
  - `message_id`
  - `event_kind`
  - `proposal_id`
  - optional `resource_version_id`
  - optional `approval_id`
  - optional `active_resource_id`
  - `event_payload`
  - `created_at`
- `resource_proposals`
  - `id`
  - `session_id`
  - `message_id`
  - `agent_id`
  - `resource_kind`
  - `requested_by`
  - `current_state`
  - `latest_version_id`
  - `created_at`
  - immutable transition timestamps needed for audit and queue handling
- `resource_versions`
  - `id`
  - `proposal_id`
  - immutable `version_number`
  - `content_hash`
  - `resource_payload`
  - `created_at`
- `resource_approvals`
  - `id`
  - `proposal_id`
  - `resource_version_id`
  - `approval_packet_hash`
  - `typed_action_id`
  - `canonical_params_json`
  - `canonical_params_hash`
  - `scope_kind` for exact approval scope in this spec
  - `approver_id`
  - `approved_at`
  - optional `expires_at`
  - optional `revoked_at`
  - optional `revoked_by`
- `active_resources`
  - `id`
  - `proposal_id`
  - `resource_version_id`
  - `activation_state`
  - `activated_at`
  - optional `revoked_at`
  - optional `revocation_reason`
- Approval queue records if separate from artifact approval storage
  - `proposal_id`
  - `queue_state`
  - `presented_at`
  - `resolved_at`
- Required indexes
  - lookup indexes on `resource_proposals(session_id, current_state)` and `resource_proposals(latest_version_id)`
  - unique index on `resource_versions(proposal_id, version_number)`
  - unique index on `resource_versions(content_hash)` only if hashes are globally unique by construction
  - approval lookup index on `resource_approvals(resource_version_id, typed_action_id, canonical_params_hash)`
  - active lookup index on `active_resources(resource_version_id, activation_state)`
  - queue lookup index on approval queue `queue_state`

## Contracts
- Agents may create proposals only.
- ActivationController is the sole activation path.
- ExecutionPolicyEnforcer verifies approval hash, action, and parameters before execution.
- Proposal and activation use the explicit split state model in this spec. This split model is canonical for implementation even where older architecture wording refers to a single lifecycle:
  - proposal states: `proposed`, `pending_approval`, `approved`, `denied`, `expired`
  - activation states: `inactive`, `active`, `activation_failed`, `revoked`
- Allowed state transitions are:
  - proposal: `proposed -> pending_approval -> approved`
  - proposal: `proposed -> pending_approval -> denied`
  - proposal: `pending_approval -> expired`
  - approval-backed active resource: `inactive -> active`
  - approval-backed active resource: `inactive -> activation_failed`
  - approval-backed active resource: `active -> revoked`
- Transition ownership is:
  - assistant/runtime may create `proposed`
  - gateway-owned approval flow may move `proposed -> pending_approval`
  - human approver may move `pending_approval -> approved` or `pending_approval -> denied`
  - gateway-owned ActivationController may create `inactive -> active` or `inactive -> activation_failed`
  - gateway-owned revocation flow may move `active -> revoked`
- `ActivationController` must be idempotent by `(proposal_id, resource_version_id, typed_action_id, canonical_params_hash)`.
- `ActivationController` persists activation attempts, success/failure outcome, and any active-resource record updates in the same gateway-owned transaction boundary.
- `ExecutionPolicyEnforcer` must deny at execution time unless all of the following match exactly:
  - `resource_version_id`
  - immutable `content_hash`
  - `typed_action_id`
  - canonicalized parameter payload hash
  - unexpired and unrevoked approval record
- The canonical approval packet is human-readable and contains:
  - `proposal_id`
  - `resource_version_id`
  - `content_hash`
  - `typed_action_id`
  - `canonical_params_json`
  - `canonical_params_hash`
  - `scope_kind`
  - `approver_id`
  - `approved_at`
  - optional `expires_at`
- Parameter canonicalization must be deterministic and stable:
  - object keys are serialized in sorted order
  - no implicit default parameters may be added after approval hashing
  - semantically relevant types must be preserved
  - the same canonicalizer is used both when presenting approval packets and when enforcing execution
- Approval breadth rules are:
  - exact single-action and single-parameter approvals are the default and only supported approval mode in this spec
  - bounded-scope reusable approvals may be introduced only in a later spec with their own explicit contract
- `scope_kind` is restricted in this spec to a session-and-agent scoped approval:
  - the approval is valid only for the exact `session_id`, `agent_id`, `resource_version_id`, `typed_action_id`, and canonical parameter payload represented by the approval record
  - user-wide, workspace-wide, or family-wide approval reuse is out of scope
- Spec 002 is extended as follows:
  - `AssistantState` may include approval-gating artifacts for the current turn only
  - `ToolRuntimeContext.policy_context` must carry approval visibility and revocation metadata needed for pre-binding filtering
  - runtime tool binding must omit approval-gated tools unless the current turn context includes a matching active approval
  - execution-time enforcement must still re-check approval even if a tool appears bound
- The approval-aware runtime flow is:
  - classify the request before binding model-facing tools
  - if the turn requires a gated capability, persist a proposal and approval-request artifacts
  - persist awaiting-approval as append-only governance transcript events linked to the canonical transcript
  - optional approval-queue rows may be maintained as derived lookup state, but they are not the canonical record of the wait
  - exit the turn in a persisted awaiting-approval state rather than pausing the graph only in memory
  - a later gateway-owned invocation resumes from persisted approval state and rebinds tools from refreshed policy context
- Control-plane components, workers, schedulers, and channel adapters may not activate capabilities directly.

## Runtime Invariants
- Unapproved tools/resources cannot become active.
- Proposal and activation are distinct states.
- Raw shell is blocked by default.
- Approved capabilities remain versioned and revocable.
- Denied or unapproved capabilities are omitted during tool binding before model execution.
- Execution-time policy checks still deny mismatched, expired, denied, or revoked approvals even if binding becomes stale.
- Proposal versions are immutable once persisted.
- Gateway-owned runtime invocation is the only path that may approve visibility changes, activation decisions, or revocation effects for future turns.

## Security Constraints
- Fail closed for missing approvals
- Exact-hash approval binding
- Typed actions preferred over shell
- Raw shell remains unavailable unless a future spec introduces an explicit privileged approval contract.
- Revocation invalidates future bindings and future executions immediately after revocation persistence succeeds.
- Approval enforcement, activation, revocation, and audit correlation remain on the gateway-owned runtime path.

## Operational Considerations
- Approval packets must be human-readable.
- Revocation must take effect immediately for future calls.
- Governance persistence uses dual durability:
  - append-only transcript-linked governance artifacts stored in `governance_transcript_events` for proposal, approval request, approval decision, activation result, and revocation result events
  - normalized governance tables for approval lookup, activation status, and revocation enforcement
- Required structured audit/provenance fields include:
  - `session_id`
  - `message_id`
  - `proposal_id`
  - `resource_version_id`
  - `content_hash`
  - `typed_action_id`
  - `canonical_params_hash`
  - `approver_id` when applicable
  - activation or denial outcome
  - event timestamp
- Approval submission and activation handling must be restart-safe and idempotent.
- Failure handling must explicitly cover stale approvals, duplicate approval submissions, denied proposals, expired approvals, revoked capabilities, and restart-safe handling for in-flight approval waits.

## Acceptance Criteria
- An unapproved resource cannot be activated or executed.
- Approval records include artifact version, approver, and action scope.
- Runtime tool exposure changes after approval state changes.
- Proposal, approval, activation, denial, expiry, and revocation states are explicitly persisted with allowed transitions and actor ownership.
- Approval matching requires exact resource version, content hash, typed action, and canonical parameter match.
- Denied or unapproved capabilities are omitted before tool binding and still rejected at execution time if incorrectly presented.
- Revocation prevents future turns and future executions from using the previously approved capability.
- Governance events are durable as append-only transcript-linked artifacts and as normalized lookup records required for enforcement.
- Duplicate approval submissions and duplicate activation attempts do not create conflicting active state.
- Approval waits are represented by persisted state that can survive restart and later gateway-owned resume.

## Test Expectations
- Policy tests for blocked shell and unapproved activation
- Integration tests for proposal -> approval -> activation flow
- Audit/provenance tests
- Unit tests for proposal and activation state transitions, including denial, expiry, activation failure, and revocation
- Unit tests for deterministic parameter canonicalization and exact approval matching
- Unit tests proving proposal versions are immutable once written
- Unit tests proving tool visibility filtering omits denied or unapproved capabilities before binding
- Unit tests proving execution-time enforcement rejects mismatched, expired, stale, or revoked approvals
- Repository or contract tests for dual persistence of transcript-linked governance artifacts and normalized enforcement tables
- Integration tests for duplicate approval submission and duplicate activation idempotency
- Integration tests for approval-request exit and later gateway-owned resume with refreshed tool binding
- Integration tests proving revocation takes effect on later turns and later executions
