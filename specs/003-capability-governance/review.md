# Review 003: User-Controlled Capability Governance

## Purpose
Review Spec 003 against the updated project constitution, [docs/architecture.md](/Users/scottcornell/src/projects/python-claw/docs/architecture.md), and the clarified upstream Specs 001 and 002 to determine whether the capability-governance slice is concrete enough to proceed into clarify and later implementation.

## Review Status
- Spec clarified: `yes`
- Plan analyzed: `yes`
- Constitution check passed: `yes`
- Ready for implementation: `yes`

## Scope Check
- The intended slice is still directionally bounded. It focuses on request classification, approval-gated activation, revocation, provenance, and an approval-aware runtime flow rather than trying to absorb remote execution transport or unrelated media/auth work.
- The non-goals now protect the slice boundary more effectively by explicitly excluding scheduler-triggered approvals, dispatcher mechanics outside the gateway-owned path, multi-turn continuity/replay jobs, and broad ambient approval models.
- The upstream dependency relationship is now concrete enough to implement because the spec states how it extends Spec 002 runtime state, policy context, tool binding, and approval-aware resume behavior.

## Contract Check
- The data model is now concrete enough to drive migrations and repository contracts. Required columns, immutable version semantics, revocation markers, and lookup indexes are specified for proposals, versions, approvals, active resources, and optional queue records.
- The service contracts are now materially actionable:
  - `ActivationController` is still the sole activation path and now has explicit idempotency identity and persistence expectations.
  - `ExecutionPolicyEnforcer` now has a concrete exact-match contract over resource version, content hash, typed action, and canonicalized parameters.
  - The approval queue and state machine are explicit enough to support implementation and tests.
- The runtime flow is now aligned with Spec 002:
  - approval visibility and revocation metadata extend `ToolRuntimeContext.policy_context`
  - denied or unapproved tools are omitted before binding
  - execution-time checks still deny stale or mismatched approvals
  - approval waits are modeled as persisted exit/resume behavior on the gateway-owned path rather than in-memory graph suspension
- Transcript and audit durability are now defined with a dual-persistence model:
  - append-only transcript-linked governance artifacts in a dedicated linked event store preserve replayability and provenance
  - normalized governance tables support efficient enforcement and lookup

## Security and Policy Check
- The spec now satisfies the constitution's approval-before-activation principle with explicit fail-closed rules.
- Exact version-and-parameter binding is now concrete:
  - artifact identity and version hash rules are defined through `resource_version_id` and immutable `content_hash`
  - typed action identity is explicit through `typed_action_id`
  - parameter canonicalization rules are deterministic and shared between approval rendering and execution enforcement
  - approval breadth is intentionally limited to exact single-action, single-parameter approvals in this spec
- Fail-closed behavior is now complete enough for implementation:
  - policy denial occurs before tool binding
  - execution-time denial remains mandatory even if binding is stale or incorrect
  - revocation invalidates future turns and future executions without rewriting durable history
- Gateway-first enforcement is now stated clearly. Approval enforcement, activation, revocation, and audit correlation remain on the gateway-owned runtime path.

## Operational Check
- The plan is sensible in shape and the migration order is reasonable: tables first, then indexes, then provenance links.
- The target modules in the plan are now actionable because the spec defines approval states, matching semantics, dual durability, and persisted exit/resume behavior.
- Audit and provenance minimums are now concrete enough to implement structured logging and durable audit storage later without changing the contract surface.
- Failure handling now covers stale approvals, duplicate approval submissions, denied proposals, expired approvals, revoked capabilities, and restart-safe handling for in-flight approval waits.

## Acceptance and Testing Check
- The acceptance criteria are now executable enough to guide implementation and review.
- The test surface now covers the highest-risk behaviors:
  - blocked shell and unapproved activation
  - proposal -> approval -> activation happy path
  - denied, expired, stale, duplicate, and revoked approval cases
  - exact artifact-version and action-parameter matching
  - immutable proposal/version storage
  - tool omission before binding and rejection at execution time
  - persisted approval exit/resume flow on the gateway-owned runtime path
  - audit/provenance and dual-persistence guarantees

## Clarifications Required
- The previously blocking clarifications have been resolved in the spec revision:
  - proposal and activation use a split state-machine model as the canonical implementation contract
  - awaiting-approval is canonically represented by transcript-linked governance events, with queue rows treated as derived lookup state if present
  - governance events use a dedicated append-only linked event store rather than overloading user-visible message rows
  - `scope_kind` is restricted to session-and-agent scope in this slice
- No additional clarification is required before implementation for this slice.

## Plan Analysis Notes
- Risk: Approval scope remains ambiguous.
  - Impact:
    - Future follow-on work could accidentally reintroduce ambient approvals if later specs broaden scope without a new contract.
  - Mitigation:
    - Preserve exact-match approval semantics as the default and require any broader reuse contract to land in a separate spec.
- Risk: Governance artifacts are persisted inconsistently with transcript-first durability.
  - Impact:
    - Dual persistence could drift if transcript artifacts and side tables are not written atomically enough.
  - Mitigation:
    - Implement persistence boundaries carefully and test transcript-linked artifacts and side-table updates together.
- Risk: Approval flow bypasses or weakens gateway-first boundaries.
  - Impact:
    - Workers, control-plane code, or future dispatch layers could activate capabilities without consistent audit and policy enforcement.
  - Mitigation:
    - Keep approval enforcement and activation on the gateway-owned runtime path and reject side-door activation in code review and tests.
- Risk: Runtime rebinding after approval changes is undefined.
  - Impact:
    - Tool exposure may still become stale if resume logic or policy caches are implemented incorrectly.
  - Mitigation:
    - Rebind tools from refreshed policy context on every resumed turn and keep execution-time enforcement as a second barrier.

## Implementation Gate
- Implementation may proceed.
- Review focus during implementation should stay on atomic dual persistence, rebind correctness on resume, and exact-match enforcement.

## Sign-Off
- Reviewer: Codex
- Date: `2026-03-22`
- Decision: `approved_with_followup_risks_noted`
- Summary: Spec 003 now defines the approval state machine, exact approval packet matching, approval-aware runtime binding, dual durability, revocation behavior, and failure-mode coverage needed to align with the architecture, constitution, and upstream Specs 001 and 002. The slice is ready to proceed into implementation, with normal implementation attention on atomic persistence and resume-time rebinding correctness.
