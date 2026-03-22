# Spec Review Template

## Purpose
Use this review before implementation begins for the spec. The goal is to force clarification of ambiguities and analysis of the plan before runtime code is written.

## Review Status
- Spec clarified: `yes | no`
- Plan analyzed: `yes | no`
- Constitution check passed: `yes | no`
- Ready for implementation: `yes | no`

## Scope Check
- Is the spec still a bounded vertical slice?
- Did any later-spec concerns leak into this spec?
- Are the non-goals still explicit and enforced?
- Are upstream dependencies correct and sufficient?

## Contract Check
- Are API, event, repository, and service contracts explicit?
- Are any referenced methods, models, or flows still undefined?
- Are data-model changes complete for this slice?
- Are runtime invariants concrete and testable?

## Security and Policy Check
- Does the spec preserve the gateway-first boundary?
- Does it preserve transcript-first durability?
- Are approval and policy boundaries explicit where needed?
- Does any privileged capability fail closed?

## Operational Check
- Are migration order and rollback steps clear?
- Are observability, audit, and failure handling addressed enough for this slice?
- Are there any hidden production assumptions that need to be called out as scaffold-only?

## Acceptance and Testing Check
- Are acceptance criteria executable rather than aspirational?
- Do tests cover the highest-risk invariants?
- Are integration tests identified where cross-boundary behavior matters?
- Is there any missing failure-mode coverage?

## Clarifications Required
- Decision:
  - Owner:
  - Resolution:
- Decision:
  - Owner:
  - Resolution:

## Plan Analysis Notes
- Risk:
  - Impact:
  - Mitigation:
- Risk:
  - Impact:
  - Mitigation:

## Implementation Gate
- Block implementation if any contract remains ambiguous.
- Block implementation if migration order is unclear.
- Block implementation if acceptance criteria cannot be tested.
- Block implementation if the plan violates the constitution.

## Sign-Off
- Reviewer:
- Date:
- Decision: `approved | needs_changes | blocked`
- Summary:
