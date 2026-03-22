# Spec 004 Review: Context Engine Lifecycle, Continuity, Compaction, and Recovery

## Purpose
Review Spec 004 against the current architecture and upstream specs to identify ambiguities, contract gaps, and cross-spec conflicts before implementation begins.

## Review Status
- Spec clarified: `partially`
- Plan analyzed: `yes`
- Constitution check passed: `yes`
- Ready for implementation: `no`

## Scope Check
- The slice is still bounded around context lifecycle, compaction, continuity, and recovery.
- No obvious later-spec media, node, or auth concerns leaked into the scope.
- The non-goals remain explicit.
- Upstream dependencies on Specs 001, 002, and 003 are correct, but the spec needs tighter alignment with the persistence contracts introduced by Specs 002 and 003.

## Contract Check
- The spec is strong on invariants, but several implementation-shaping contracts remain undefined or conflicting.
- The post-commit job naming mismatch has been resolved in favor of `outbox_jobs`, which now matches the architecture and 004 plan/tasks.
- The canonical continuity record is underspecified for assistant/tool artifacts:
  - Spec 004 says the canonical record is transcript plus transcript-linked governance artifacts.
  - Spec 002 allows assistant/tool persistence through one explicit append-only contract that may be transcript rows or additive event tables.
  - Spec 004 also claims reconstruction for sessions with assistant, tool, and governance artifacts, but does not state which assistant/tool artifacts are canonical for replay.
- The manifest durability gap has been resolved: Spec 004 now requires durable `context_manifests` persistence plus structured-log emission.
- The summary snapshot contract is still incomplete for concurrent turns:
  - the spec requires `snapshot_version`, covered ranges, and source watermark
  - it does not define how versions are allocated under concurrent post-commit workers or what makes a snapshot “latest valid” when multiple jobs race
- The architecture-fit gap is now narrower but still present:
  - the plan must explicitly route lifecycle ownership through `apps/gateway/api/inbound.py`
  - the continuity slice should name a dedicated context-service seam so the graph does not absorb long-term continuity policy

## Security and Policy Check
- The spec preserves the gateway-first boundary and transcript-first durability model.
- Approval-aware continuity is correctly called out as fail-closed.
- The replay source for governance visibility is still ambiguous:
  - Spec 004 says recovery must work from transcript rows and transcript-linked governance artifacts alone.
  - Spec 003 defines dual durability with normalized governance tables required for enforcement.
  - The spec needs to say whether repair rebuilds normalized governance state from governance transcript events, or whether assembly may read normalized tables directly when healthy.

## Operational Check
- Naming is now aligned on `outbox_jobs`.
- Rollback intent is directionally fine, but the runtime behavior under transcript-only fallback is not fully defined for very long sessions.
- Observability requirements are present and manifest storage is now explicit, but the inspection surface for “latest valid summary snapshot” still needs to be implemented through repository/admin contracts.

## Acceptance and Testing Check
- Most acceptance criteria are executable.
- The highest-risk invariants are identified.
- One acceptance area is currently self-conflicting:
  - the spec requires transcript-first invocation when summary/retrieval loading fails
  - the spec also requires bounded overflow retry using additive summaries and older-history elision
  - after deleting all derived artifacts on a long session, transcript-only assembly may still exceed the context window unless the spec explicitly allows synchronous rebuild or a bounded degraded failure mode

## Clarifications Required
- Decision: Define the canonical replay source for assistant and tool continuity.
  - Owner: Spec author
  - Resolution: State explicitly whether assistant/tool proposals, tool outcomes, and outbound intents are reconstructed from `messages` only or whether additive artifact tables from Spec 002 are part of the canonical continuity record. Without that, the “reconstruction algorithm for sessions with assistant, tool, and governance artifacts” is incomplete relative to [spec.md](/Users/scottcornell/src/projects/python-claw/specs/004-context-continuity/spec.md#L20) and [specs/002-runtime-tools/spec.md](/Users/scottcornell/src/projects/python-claw/specs/002-runtime-tools/spec.md#L60).
- Decision: Define what “transcript-first invocation” means when transcript-only assembly still overflows.
  - Owner: Spec author
  - Resolution: Clarify whether the runtime may synchronously rebuild a summary from canonical transcript state before retry, whether it may elide older transcript ranges without any existing derived artifact, or whether a bounded degraded failure is acceptable after transcript-only assembly still exceeds the model window. The current wording in [spec.md](/Users/scottcornell/src/projects/python-claw/specs/004-context-continuity/spec.md#L69) and [spec.md](/Users/scottcornell/src/projects/python-claw/specs/004-context-continuity/spec.md#L70) reads stronger than the system can guarantee on long sessions.
- Decision: Define the governance replay source of truth for approval-aware continuity.
  - Owner: Spec author
  - Resolution: Specify whether continuity assembly and repair read only transcript-linked governance events, rebuild normalized governance tables from them, or may consult normalized governance tables directly when healthy. This needs to be explicit so Spec 004 does not conflict with the dual-durability model in [specs/003-capability-governance/spec.md](/Users/scottcornell/src/projects/python-claw/specs/003-capability-governance/spec.md#L177).
- Decision: Define where the context manifest lives and how it is inspected.
  - Owner: Spec author
  - Resolution: Durable persistence is now explicit; the remaining requirement is to expose retrieval through a defined repository/admin inspection path rather than assuming logs are sufficient.
- Decision: Align the summary snapshot field names and gateway/context ownership seams with the architecture doc.
  - Owner: Spec author
  - Resolution: Keep one summary range naming scheme across Spec 004 and [architecture.md](/Users/scottcornell/src/projects/python-claw/docs/architecture.md), explicitly include `apps/gateway/api/inbound.py` in the lifecycle plan, and name `src/context/service.py` as the continuity-policy seam so implementation follows the documented architecture.

## Plan Analysis Notes
- Risk: Recovery is implemented against transcript plus governance only, but actual runtime behavior still depends on non-canonical assistant/tool artifacts.
  - Impact: Replay succeeds on paper but loses executable continuity in practice.
  - Mitigation: Make the canonical replay inputs explicit and add a recovery test that deletes every declared non-canonical table.
- Risk: Transcript-only fallback is promised more strongly than the model window allows.
  - Impact: The runtime will either violate the spec or silently invent an unapproved truncation rule.
  - Mitigation: Add a bounded fallback contract for long sessions with no usable derived artifacts.
- Risk: Governance replay may read stale normalized state or skip necessary rebuild steps.
  - Impact: Approval visibility and revocation continuity could drift after restart or repair.
  - Mitigation: Specify one deterministic rebuild and read path for governance-aware context assembly.

## Implementation Gate
- Block implementation until the canonical replay inputs for assistant/tool continuity are explicit.
- Block implementation until transcript-only overflow behavior is defined.
- Block implementation until the manifest inspection contract is explicit beyond durable storage.
- Block implementation until the gateway entrypoint and context-service ownership seams are explicit in the plan and accepted as the implementation boundary.

## Sign-Off
- Reviewer: Codex
- Date: 2026-03-22
- Decision: `needs_changes`
- Summary: Spec 004 now has aligned `outbox_jobs` naming and explicit durable manifests, and it remains directionally aligned with the architecture. The remaining blockers are making assistant/tool replay inputs fully explicit, tightening transcript-only overflow behavior, defining the manifest inspection surface, and locking the gateway/context-service ownership seams before implementation starts.
