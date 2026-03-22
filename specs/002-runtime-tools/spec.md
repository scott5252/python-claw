# Spec 002: LangGraph Runtime and Typed Tool Registry

## Purpose
Introduce the LangGraph runtime for a single user turn and a typed tool registry without collapsing transport concerns into orchestration or bypassing the gateway-owned execution path.

## Non-Goals
- Capability approvals for tool or resource activation
- Remote node execution
- Context compaction, recovery, or replay jobs
- Scheduler-driven execution
- Multi-turn background workflows

## Upstream Dependencies
- Spec 001

## Scope
- `AssistantState` for one deterministic user turn
- Graph assembly and invocation for one user turn
- Runtime dependency injection for repositories and services
- Typed model result contract for provider-agnostic tool planning
- Tool runtime context injection
- Policy-aware tool registry and factory contract
- Outbound message tool
- One safe local example tool
- Tool audit logging hooks

## Data Model Changes
- Transcript support for persisted assistant messages, tool-call proposals, tool execution outcomes, and outbound intent references using one explicit append-only artifact model
- Optional audit table or structured event sink for tool execution attempts and outcomes
- No transport-adapter data model changes beyond what the gateway already owns

## Contracts
- `GraphFactory` assembles the runtime graph from injected repositories and services rather than constructing infrastructure inline inside nodes.
- `GraphDependencies` is the runtime dependency container used by nodes and is replaceable with test doubles.
- `AssistantState` is a typed state contract for a single turn. Required fields in this spec:
  - `session_id`
  - `agent_id`
  - `channel_kind`
  - `sender_id`
  - `user_text`
  - `messages`
  - `tool_events`
  - `response_text`
  - `needs_tools`
- `agent_id` must be sourced explicitly by the gateway-owned runtime entry point. If upstream session routing does not yet provide multi-agent resolution, this spec uses a fixed configured default agent identifier rather than inferring one inside graph nodes.
- `AssistantState` fields explicitly deferred to later specs include summary snapshot bookkeeping, memory extraction artifacts, approval state, scheduler metadata, and remote execution metadata.
- `ToolRuntimeContext` carries the per-turn binding context for tools. Required fields in this spec:
  - `session_id`
  - `agent_id`
  - `channel_kind`
  - `sender_id`
  - `policy_context`
  - `runtime_services`
- `ModelTurnResult` is the typed provider-agnostic inference contract consumed by graph nodes. Required fields in this spec:
  - `needs_tools`
  - `tool_requests`
  - `response_text`
- `ToolRegistry` exposes typed factories keyed by capability name. Nodes do not import or instantiate concrete tools ad hoc.
- Tool visibility is determined before execution by registry filtering against runtime policy, channel, and agent/session context.
- Assistant output and tool activity must be stored through one explicit append-only persistence contract. This spec may implement that as typed transcript event envelopes in message storage or as additive event tables linked to the canonical transcript, but it may not leave the storage shape implementation-defined.
- The outbound message tool returns or persists an outbound message intent owned by the runtime and gateway contracts; it does not directly invoke channel transports.
- The graph must persist the canonical assistant transcript row and a runtime-owned outbound intent or outbound reference that a later gateway dispatch layer can consume without reinterpreting assistant text.
- Tool execution must produce either a recorded success result or a recorded failure result. Assistant text may only describe a tool outcome that exists in recorded execution state.

## Runtime Invariants
- Transport logic stays outside the graph.
- Tools are exposed through a registry or factory contract, not imported or wired ad hoc inside graph nodes.
- Tool outcomes are never fabricated.
- The graph remains functional without remote execution support.
- Graph compilation and invocation remain deterministic for the same injected dependencies, initial state, and model/tool stubs used in tests.
- The runtime can bind different tool sets for different policies without changing graph topology.
- The gateway owns graph invocation. Channel adapters, transports, and delivery implementations do not call graph nodes directly.

## Security Constraints
- Only safe local tools are included in this spec
- No privileged or approval-gated capability may be exposed by this spec
- Policy-denied tools fail closed by omission from the bound tool set
- Tool calls and outcomes must be auditable
- Outbound messaging must preserve gateway-first delivery boundaries

## Operational Considerations
- Tool binding must be reproducible in tests from explicit runtime context and policy inputs
- Model inference results must be reproducible in tests from a typed adapter contract rather than provider-native payload parsing in graph nodes
- Failures in tool execution must surface explicit recorded outcomes rather than silent fallbacks
- Audit hooks may write to structured logs first if durable audit storage is not yet implemented, but the event contract must be defined now
- The initial safe local example tool must be side-effect-bounded and runnable without network or remote execution support

## Clarifications
- The graph in this spec covers one user turn only:
  - load or assemble prompt context
  - think
  - optionally execute bound tools
  - persist the assistant result and tool records
- Dependency injection occurs at graph-construction time for repositories and services, and at tool-binding time for per-turn runtime context.
- Identifier naming aligns with Spec 001 in this slice:
  - use `channel_kind`, not `channel_type`
  - use `sender_id`, not `requester_id`
  - use a fixed configured `agent_id` if upstream multi-agent routing is not yet present
- The model adapter consumed by the graph returns a typed `ModelTurnResult` containing final text plus any proposed tool requests needed for deterministic branching.
- Test doubles are provided by injecting fake repositories, fake policy services, fake models, and fake audit sinks into the graph factory or dependency container.
- `ToolNode` may be used only if it supports the required audit hooks, deterministic tests, and explicit tool result capture. If it cannot satisfy those contracts cleanly, this spec requires a custom execution node instead.
- The safe local example tool in this spec should be a deterministic, side-effect-bounded local tool such as `echo_text`, `today_local`, or equivalent file-free utility; it must not require network access, shell access, or privileged resources.
- Outbound replies are represented as a persisted assistant transcript row plus a runtime-owned outbound intent or outbound reference that the gateway dispatch layer can translate later. Channel-specific formatting and transport delivery remain outside orchestration.

## Acceptance Criteria
- The graph can be assembled and invoked for one user turn using injected dependencies only, with no transport adapter logic inside graph nodes.
- `AssistantState` has a defined minimal required shape for this spec, uses Spec 001 identifier names, and excludes deferred continuity, approval, and remote-execution concerns.
- Tool binding is contextual: the same registry can expose different tool sets for different runtime policy or channel contexts without changing node wiring.
- Graph state transitions are deterministic under the same initial state and stubbed dependency/model/tool results.
- Model inference outputs are consumed through a typed provider-agnostic contract rather than provider-native tool-call payloads inside graph nodes.
- Tool execution records requested arguments, execution status, and returned outcome or error in transcript or audit storage.
- The assistant never reports a successful tool outcome unless a corresponding recorded tool result exists.
- The runtime persists assistant output, tool artifacts, and outbound intent or outbound references through one explicit append-only contract.
- The outbound message tool produces runtime-owned outbound intent or outbound references without invoking a channel adapter or transport client directly.
- The graph runs correctly when only local tools are available and no remote execution support is configured.
- Channel adapters still do not invoke the graph directly; the gateway-owned runtime path remains the only orchestration entry point.

## Test Expectations
- Unit tests for `AssistantState` transitions and conditional routing
- Unit tests for graph assembly with injected fake repositories and services
- Unit tests for typed `ModelTurnResult` handling and deterministic branching from tool requests
- Unit tests for registry exposure and policy-aware filtering
- Unit tests proving tool runtime context is injected into factories rather than captured from transport adapters
- Unit tests or contract tests proving outbound message tooling does not call channel transports directly
- Repository or contract tests proving append-only persistence of assistant output, tool proposals, tool outcomes, and outbound intent or outbound references
- Tool execution audit tests covering success and failure paths
- Integration test for a tool-using turn through the gateway-owned runtime path
- Integration test for a policy-denied tool turn proving the denied capability is absent from the bound tool set
- Integration test proving the runtime still functions with only safe local tools and no remote execution support
