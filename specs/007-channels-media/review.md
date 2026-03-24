# Review 007: Channels, Streaming, Chunking, and Media Pipeline

## Purpose
Review Spec 007 against the updated project documentation and Specs 001 through 006 so this slice is precise enough to implement without leaking channel logic into orchestration or weakening the existing gateway, policy, durability, and worker boundaries.

## Review Status
- Spec clarified: `yes`
- Plan analyzed: `yes`
- Constitution check passed: `yes`
- Ready for implementation: `yes`

## Resolved Findings
### 1. Resolved: The slice now defines what "streaming" means in this phase
- The earlier spec used "streaming" in the title but never defined whether the implementation should support token-by-token transport streaming or only post-turn chunked delivery.
- The updated spec now makes this explicit: Spec 007 covers chunked outbound dispatch after a completed assistant turn, and true incremental transport streaming is deferred.
- This aligns the implementation target with the current worker-owned execution model from Spec 005 and avoids hidden transport/runtime coupling.

### 2. Resolved: Included channels and adapter boundaries are now explicit
- The earlier spec never said which channels were in scope, even though the plan already named `webchat`, `slack`, and `telegram`.
- The updated spec now names those supported channels, defers others explicitly, and defines a concrete adapter capability contract.
- It also makes thin-adapter boundaries testable by stating what adapters may and may not do.

### 3. Resolved: The attachment model is now concrete and durable
- The earlier spec mentioned normalization and media-safe storage but left the canonical attachment contract and storage/audit model undefined.
- The updated spec adds:
  - the canonical inbound `attachments` contract
  - append-only `message_attachments`
  - normalization responsibilities, failure behavior, and retention requirements
- This brings Spec 007 into line with the transcript-first and append-only patterns established in Specs 001, 002, and 004.

### 4. Resolved: Outbound delivery and directive handling are now explicit enough to build
- The earlier spec said directive parsing and chunking should happen before delivery, but it did not define supported directives, ordering, policy checks, or outbound audit records.
- The updated spec now pins down:
  - supported directives in this phase: `reply`, `media`, and `voice`
  - dispatcher ordering
  - channel-aware chunking rules
  - append-only `outbound_deliveries` records
  - fail-closed behavior when directives are unsupported or denied
- This closes the largest implementation gap between the old placeholder spec and the richer contracts in earlier slices.

### 5. Resolved: Upstream dependencies now reflect the earlier updated specs
- The prior dependency list named only Specs 001, 002, and 005.
- The updated spec now depends explicitly on Specs 003 and 004 as well, because:
  - directive-driven outbound behavior must still respect the capability and policy boundaries from Spec 003
  - attachment and outbound-delivery records must fit the continuity and append-only artifact model from Spec 004

## Architecture Alignment
- The spec remains aligned with the gateway-first architecture in [docs/architecture.md](/Users/scottcornell/src/my-projects/python-claw/docs/architecture.md): channel adapters translate transport details, while the gateway-owned runtime and dispatcher control orchestration.
- The slice matches the architecture's stated Spec 7 requirements for outbound dispatcher abstraction, reply-directive parsing, block chunking, inbound attachment normalization, media-safe handling, and adapter boundary discipline.
- The updated contracts also preserve the project's staged maturity: they add realistic delivery behavior without prematurely introducing live incremental streaming, OCR, transcription, or provider-native rich-layout concerns.

## Constitution Check
- Gateway-first execution is preserved. Adapters do not invoke the graph directly, and outbound dispatch remains a gateway-owned or worker-owned path.
- Transcript-first durability is preserved. Attachments and outbound deliveries are defined as append-only records linked to canonical session/run/message state rather than adapter-only side effects.
- Approval and policy boundaries are preserved. Reply directives request bounded outbound metadata, but they do not authorize capabilities outside the existing runtime policy model.
- Observable, bounded delivery is preserved. The updated spec adds durable delivery records, attachment failure recording, retention bounds, and concrete test expectations.

## Plan Analysis
- The plan's module list still fits the updated spec: shared dispatcher logic, directive parsing, chunking, media processing, and transport-specific adapters are the right implementation seams.
- The migration order is now better grounded because the spec makes both `message_attachments` and `outbound_deliveries` concrete instead of optional hand-waving.
- The remaining implementation risk is normal execution complexity, not contract ambiguity. The plan should continue to implement shared dispatcher/chunking behavior before transport-specific adapter integrations that depend on it.

## Applied Decisions
- Decision: Meaning of "streaming"
  - Selection: chunked post-turn outbound dispatch only in Spec 007
  - Impact: keeps delivery aligned with the existing queued-run model and avoids hidden live-stream transport scope
- Decision: Supported channels
  - Selection: `webchat`, `slack`, and `telegram`
  - Impact: gives adapter work a bounded target and matches the current plan
- Decision: Canonical attachment model
  - Selection: explicit inbound attachment contract plus append-only `message_attachments`
  - Impact: normalization, retention, and context consumption are now testable and auditable
- Decision: Outbound delivery durability
  - Selection: append-only `outbound_deliveries` per chunk or media send
  - Impact: chunk retries, partial failures, and adapter outcomes are inspectable without relying on transport-provider logs
- Decision: Supported reply directives
  - Selection: `reply`, `media`, and `voice`, with fail-closed capability checks
  - Impact: gives the dispatcher a bounded parser contract without letting directives bypass policy or transport rules

## Implementation Gate
- Implementation may begin. The previous blockers were document gaps, not architectural contradictions, and the updated spec resolves them with explicit contracts and bounded scope.

## Sign-Off
- Reviewer: `Codex`
- Date: `2026-03-24`
- Decision: `approved with resolved clarifications`
- Summary: Spec 007 is now consistent with the updated earlier specs and the project architecture. It defines the included channels, the meaning of streaming in this phase, the canonical attachment and outbound-delivery models, and the policy-safe directive/dispatcher contracts needed for a successful implementation.
