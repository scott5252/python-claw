# Plan 003: User-Controlled Capability Governance

## Target Modules
- `src/policies/service.py`
- `src/policies/approval_models.py`
- `src/graphs/nodes_approval.py`
- `src/tools/registry.py`
- `src/tools/typed_actions.py`
- `src/capabilities/activation.py`
- `src/capabilities/repository.py`
- `src/db/models_capabilities.py`
- `tests/`

## Migration Order
1. Create proposal/version/approval/active-resource tables
2. Add indexes for proposal state and approval lookup
3. Add any transcript or audit references needed for provenance

## Implementation Shape
- Classify request intent before binding model-facing tools.
- Split tool exposure into read-only, proposal-only, approved-action, and privileged-action classes.
- Keep control-plane registry mutation out of model-facing tools.
- Block raw shell at the policy layer unless an exact privileged approval exists.

## Risk Areas
- Ambient approvals accidentally broadening scope
- Proposal records that are mutable in place
- Activation bypasses around the graph boundary

## Rollback Strategy
- Approval tables are additive.
- Execution defaults to deny if approval data is unavailable.

## Test Strategy
- Unit: request classification, approval matching, revocation enforcement
- Integration: approval pause/resume flow and typed-action execution after approval
