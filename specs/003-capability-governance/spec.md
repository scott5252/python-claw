# Spec 003: User-Controlled Capability Governance

## Purpose
Ensure agents can propose resources and actions, but cannot activate or execute dangerous capabilities without explicit user approval.

## Non-Goals
- Remote node transport details
- Media handling
- Auth failover

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
- `resource_proposals`
- `resource_versions`
- `resource_approvals`
- `active_resources`
- Approval queue records if separate from artifact approval storage

## Contracts
- Agents may create proposals only.
- ActivationController is the sole activation path.
- ExecutionPolicyEnforcer verifies approval hash, action, and parameters before execution.

## Runtime Invariants
- Unapproved tools/resources cannot become active.
- Proposal and activation are distinct states.
- Raw shell is blocked by default.
- Approved capabilities remain versioned and revocable.

## Security Constraints
- Fail closed for missing approvals
- Exact-hash approval binding
- Typed actions preferred over shell

## Operational Considerations
- Approval packets must be human-readable.
- Revocation must take effect immediately for future calls.

## Acceptance Criteria
- An unapproved resource cannot be activated or executed.
- Approval records include artifact version, approver, and action scope.
- Runtime tool exposure changes after approval state changes.

## Test Expectations
- Policy tests for blocked shell and unapproved activation
- Integration tests for proposal -> approval -> activation flow
- Audit/provenance tests
