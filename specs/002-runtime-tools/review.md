# Review 002: LangGraph Runtime and Typed Tool Registry

## Purpose
Review the spec and plan before implementation so the runtime, transcript, and gateway boundaries are concrete enough to build and test without drifting from the architecture in `docs/architecture.md`.

## Review Status
- Spec clarified: `no`
- Plan analyzed: `yes`
- Constitution check passed: `yes`
- Ready for implementation: `no`

## Scope Check
- The spec is still a bounded vertical slice. It stays focused on a single-turn LangGraph runtime, typed tool registration, one safe local tool, one outbound message tool, and tool audit hooks.
- Later-spec concerns are mostly kept out. Approval-gated capability activation, remote execution, scheduling, recovery jobs, and multi-turn background workflows remain explicitly deferred.
- The non-goals are clear and still enforce the intended boundary for this slice.
- Upstream dependencies are not yet sufficient as written. Spec 002 requires runtime identifiers that Spec 001 does not define consistently enough for implementation.

## Contract Check
- The graph/runtime boundary is directionally correct: gateway-owned invocation, injected dependencies, typed tool factories, and policy-aware binding all match the architecture.
- The state and runtime context contracts are not fully implementable yet because the required fields do not align with Spec 001:
  - Spec 002 requires `agent_id`, `channel_type`, and `requester_id`.
  - Spec 001 defines `channel_kind` and `sender_id`, and does not yet establish an `agent_id` source on the session or inbound contract.
- The data model is underspecified for transcript-first durability in this slice. The spec requires persistence of tool-call proposals, tool execution outcomes, and final assistant output, but it does not define whether those artifacts live in append-only `messages`, a new transcript-event structure, or separate additive tables.
- The outbound contract is ambiguous. The spec alternates between persisted assistant output and runtime-owned outbound intent, but does not define a durable runtime artifact that preserves the gateway-first, deliver-later model from the architecture.
- The model output contract is still implicit. `needs_tools`, proposed tool calls, and final assistant text need a provider-agnostic typed result contract so deterministic branching and tests do not depend on ad hoc parsing or provider-specific tool-calling behavior.

## Security and Policy Check
- The spec preserves the gateway-first boundary. Channel adapters remain outside graph invocation and transport logic remains outside runtime nodes.
- The spec preserves transcript-first intent, but not yet transcript-first implementation detail. That gap is in the storage contract, not the goal.
- Approval and privileged capability boundaries are explicit enough for this slice. Approval-gated and remote capabilities are intentionally excluded.
- Policy-denied tools fail closed by omission from the bound tool set, which is correct for this phase.

## Operational Check
- Migration order in the plan is sensible: transcript durability, audit sink contract, runtime contracts, tool registry, graph assembly, outbound intent handling, then tests.
- Rollback strategy is reasonable and consistent with additive schema changes and fail-closed tool exposure.
- Observability and audit behavior are sufficiently addressed for this slice if the event contract is defined up front, even if durable audit storage is deferred.
- Hidden production assumptions still need to be removed from the spec before implementation:
  - whether the gateway invokes the graph synchronously in-process for this slice or queues work behind a runtime service boundary
  - how outbound artifacts are represented before the later dispatcher-focused spec lands

## Acceptance and Testing Check
- Most acceptance criteria are executable, but a few remain too abstract until the missing contracts are defined.
- The tests cover the highest-risk invariants around policy filtering, tool audit capture, transport separation, and no fabricated tool outcomes.
- Integration coverage is correctly focused on the gateway-owned runtime path, policy-denied tools, local-only tooling, and tool failure behavior.
- Missing failure-mode coverage:
  - repository-level proof that append-only transcript/event persistence preserves order and replayability for assistant output plus tool artifacts
  - contract tests for provider-agnostic model outputs that drive `needs_tools`, tool proposals, and final assistant text

## Clarifications Required
- Decision: Normalize runtime identifier naming and source-of-truth contracts.
  - Owner: Spec author
  - Resolution:
    - Update Spec 002 to align with Spec 001 naming by using `channel_kind` and `sender_id`, or explicitly declare them as canonical aliases.
    - Resolve `agent_id` by either adding it to the upstream session contract in Spec 001 or deferring it from the required state for this slice and sourcing it from a fixed gateway/runtime default.
    - Recommended path: keep `channel_kind` and `sender_id` as the canonical names in Spec 002 and define a temporary fixed/default `agent_id` source if multi-agent routing is not yet introduced upstream.
- Decision: Define one append-only transcript artifact model for assistant/tool persistence.
  - Owner: Spec author
  - Resolution:
    - Add an explicit persistence contract for assistant messages, tool-call proposals, tool execution outcomes, and outbound references.
    - Recommended path: keep transcript durability append-only by introducing a typed event envelope in transcript storage or an additive `message_artifacts`/`tool_events` table linked to the canonical message stream.
    - Do not leave storage shape implementation-defined.
- Decision: Choose a single runtime-owned outbound artifact for this slice.
  - Owner: Spec author
  - Resolution:
    - Define whether the graph persists an assistant message only, an outbound intent only, or both.
    - Recommended path: persist the canonical assistant transcript row and also persist a runtime-owned outbound intent/reference that the gateway can translate later, without calling transports directly.
    - Keep dispatcher behavior out of this spec; define only the durable contract the later dispatcher will consume.
- Decision: Define a provider-agnostic model result contract.
  - Owner: Spec author
  - Resolution:
    - Add a typed inference result shape that explicitly contains `needs_tools`, `tool_requests`, and `response_text` or equivalent final text field.
    - Recommended path: make nodes consume a typed model adapter result rather than provider-native tool-call payloads so deterministic tests remain stable across providers.

## Plan Analysis Notes
- Risk: Identity and naming mismatches between Specs 001 and 002 cause implementation drift across routing, state assembly, policy checks, and tests.
  - Impact: Runtime wiring becomes ambiguous and implementers will introduce ad hoc mappings in code, making future specs harder to layer cleanly.
  - Mitigation: Apply a single clarification pass now to normalize names and define the source of `agent_id` before runtime code is written.
- Risk: Tool and assistant persistence is not concrete enough for append-only replayability.
  - Impact: The runtime may store tool data in mutable fields, logs only, or inconsistent tables, weakening transcript-first durability and making later continuity specs harder to implement.
  - Mitigation: Define one additive, append-only persistence contract now for assistant output, tool proposals, tool results, and outbound references.
- Risk: Outbound behavior may leak transport concerns into graph code because the runtime artifact is not defined.
  - Impact: The gateway-first boundary erodes and later dispatcher/channel work will require refactoring core orchestration code.
  - Mitigation: Lock in a runtime-owned outbound artifact now and explicitly defer transport dispatch mechanics to the later delivery spec.
- Risk: `needs_tools` and tool request branching become provider-specific.
  - Impact: Deterministic testing weakens, LangGraph nodes couple to one provider, and tool behavior becomes harder to reason about.
  - Mitigation: Define a provider-agnostic model adapter contract before implementing graph nodes.

## Recommended Resolution Set
- Use the minimal correction path for this spec package rather than reopening the entire roadmap:
  - normalize identifier names to the Spec 001 contract
  - define a temporary or upstream-backed `agent_id` source explicitly
  - define one append-only transcript/event persistence shape
  - define one runtime-owned outbound artifact
  - define one typed provider-agnostic model result contract
- This is the recommended option because it preserves the current spec scope, aligns with `docs/architecture.md`, and removes the major implementation ambiguities without spilling into later specs.

## Implementation Gate
- Block implementation until the identifier contract is normalized and the `agent_id` source is defined.
- Block implementation until the append-only persistence shape for assistant and tool artifacts is explicit.
- Block implementation until the outbound runtime artifact is explicit.
- Block implementation until the model result contract is typed and testable.

## Sign-Off
- Reviewer: Codex
- Date: `2026-03-22`
- Decision: `needs_changes`
- Summary: The spec is well-scoped and aligned with the architecture, but it still needs one clarification pass to resolve identifier mismatches, transcript persistence shape, outbound artifact semantics, and the provider-agnostic model result contract before implementation should begin.
