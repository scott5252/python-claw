# Plan 002: LangGraph Runtime and Typed Tool Registry

## Target Modules
- `apps/gateway/deps.py`
- `src/db/models.py`
- `src/db/session.py`
- `src/sessions/repository.py`
- `src/sessions/service.py`
- `src/graphs/state.py`
- `src/graphs/prompts.py`
- `src/graphs/nodes.py`
- `src/graphs/assistant_graph.py`
- `src/tools/registry.py`
- `src/tools/messaging.py`
- `src/tools/local_safe.py`
- `src/policies/service.py`
- `src/providers/models.py`
- `src/observability/` or `src/audit/` for tool execution event contracts if a dedicated module is introduced
- `migrations/`
- `tests/`

## Migration Order
1. Extend transcript durability first so one turn can record:
   - assistant output
   - proposed tool calls
   - tool execution outcomes
   - outbound intent or outbound references
2. Add a structured audit sink contract for tool execution attempts and outcomes:
   - prefer additive durable storage if it fits the current schema cleanly
   - otherwise add a defined structured-log event contract that can be upgraded later without changing graph behavior
3. Introduce runtime state and dependency contracts before graph assembly:
   - `AssistantState`
   - `GraphDependencies`
   - `ToolRuntimeContext`
   - `ModelTurnResult`
4. Implement the typed tool registry and policy-aware binding layer before any graph node executes tools.
5. Assemble the single-turn LangGraph runtime behind a gateway-owned entry point:
   - gateway/service code invokes the graph
   - channel adapters still submit work through the gateway path only
6. Add outbound intent handling and the safe local example tool after transcript/audit plumbing exists so outcomes can be recorded from the first executable path.
7. Finish with deterministic tests and one gateway-path integration flow using `uv run pytest`.

## Implementation Shape
- Preserve the architecture boundary from [docs/architecture.md](/Users/scottcornell/src/projects/python-claw/docs/architecture.md): gateway owns routing and invocation, graph owns orchestration, tools expose typed capabilities, and transports remain outside runtime nodes.
- Keep transcript-first durability from the constitution: assistant text, tool proposals, and tool outcomes must be persisted as append-only turn artifacts rather than inferred from logs or mutable in-memory state.
- Define `AssistantState` as the minimal single-turn contract from the spec only:
  - `session_id`
  - `agent_id`
  - `channel_kind`
  - `sender_id`
  - `user_text`
  - `messages`
  - `tool_events`
  - `response_text`
  - `needs_tools`
- Source `agent_id` explicitly at the gateway-owned runtime boundary:
  - use the upstream session value if available
  - otherwise inject a fixed configured default for this slice
- Introduce `ModelTurnResult` as the provider-agnostic inference output consumed by graph nodes:
  - `needs_tools`
  - `tool_requests`
  - `response_text`
- Keep deferred concerns out of this slice:
  - approval execution state
  - scheduler metadata
  - remote node execution metadata
  - compaction, replay, and memory extraction bookkeeping
- Introduce `GraphFactory` and `GraphDependencies` so repositories, policy services, model adapters, transcript writers, and audit sinks are injected instead of constructed inside nodes.
- Bind tools per turn through `ToolRuntimeContext`; do not let graph nodes import concrete tools directly or capture transport/session state ad hoc.
- Decide on `ToolNode` only after verifying it can satisfy all required contracts:
  - explicit policy-filtered tool binding
  - deterministic tests with injected doubles
  - success and failure audit hooks
  - explicit recorded result capture
  - if any of those are awkward, use a custom tool execution node
- Implement the outbound message tool as a runtime-owned intent or persisted assistant-output helper only:
  - no transport client calls
  - no channel adapter formatting logic in graph nodes
- Persist runtime artifacts through one explicit append-only contract:
  - assistant transcript row
  - tool proposal and tool result artifacts
  - outbound intent or outbound reference artifact
  - storage may use typed transcript envelopes or additive linked tables, but must be explicit in the implementation contract
- Choose a deterministic safe local example tool such as `echo_text` or `today_local`:
  - no network
  - no shell execution
  - no filesystem mutation
  - side-effect-bounded and reproducible under tests

## Contracts to Implement
### Runtime Contracts
- `src/graphs/state.py`
  - define `AssistantState` for a single deterministic turn
  - define typed tool-event/result structures used by nodes and persistence
  - define `ModelTurnResult` and typed tool-request records consumed from model adapters
- `src/graphs/assistant_graph.py`
  - expose `GraphFactory`
  - compile the graph from injected `GraphDependencies`
  - keep graph topology stable while allowing different tool sets to bind per runtime policy context
- `src/graphs/nodes.py`
  - load or assemble prompt context for the current turn
  - run model inference using injected model services
  - consume typed `ModelTurnResult` values from model services
  - branch deterministically on `needs_tools`
  - execute tools through registry-bound instances only
  - persist final assistant output and recorded tool outcomes before returning

### Tool and Policy Contracts
- `src/tools/registry.py`
  - expose typed tool factories keyed by capability name
  - filter visible tools using runtime policy, channel, agent, and session context before execution
  - fail closed by omission for denied capabilities
- `src/tools/messaging.py`
  - create runtime-owned outbound intents or outbound references owned by runtime/gateway contracts
  - never dispatch transport messages directly
- `src/tools/local_safe.py`
  - provide one deterministic, side-effect-bounded example tool for this spec
- `src/policies/service.py`
  - provide the policy query surface needed for pre-execution tool visibility decisions
  - keep approval-gated and privileged capabilities outside this spec's exposed tool set

### Persistence and Gateway Contracts
- `src/db/models.py` and `migrations/`
  - extend transcript storage for assistant output, tool proposals, tool outcomes, and outbound references if not already present
  - add any structured audit storage introduced by this spec
- `src/sessions/repository.py`
  - persist assistant turn artifacts and recorded tool execution results without breaking append-only transcript expectations
  - expose one explicit append-only persistence contract for assistant output, tool artifacts, and outbound artifacts
- `src/sessions/service.py` or gateway-owned runtime service
  - invoke the graph from the gateway-owned execution path only
  - provide the explicit `agent_id` source used for this slice
  - do not allow channel adapters to call graph nodes directly
- `apps/gateway/deps.py`
  - wire injected repositories and services into the graph factory without collapsing service boundaries

## Risk Areas
- Transport leakage into graph nodes or tool factories, which would violate the gateway-first boundary and make later channel growth brittle.
- Transcript gaps where assistant text claims a tool succeeded but no persisted tool result or audit record exists.
- Identifier mismatches between Spec 001 and runtime state assembly, which would force ad hoc mappings and weaken test clarity.
- Registry drift where tools are imported ad hoc in nodes, preventing policy-aware filtering and per-turn binding.
- Using a generic LangGraph tool executor that cannot capture denied, failed, and successful outcomes with the explicit audit semantics this spec requires.
- Provider-native model outputs leaking into graph nodes instead of a typed provider-agnostic result contract.
- Introducing later-spec concerns such as approvals, scheduler re-entry, remote nodes, or context compaction into this bounded slice.
- Schema changes that store tool data in mutable overwrite fields instead of append-only, replayable transcript artifacts.

## Rollback Strategy
- Keep schema changes additive and preserve existing session/message read paths during rollout.
- If dedicated audit persistence proves too disruptive, retain the event contract and fall back to structured logs without changing graph or tool interfaces.
- Gate the new LangGraph runtime behind the existing gateway-owned service boundary so request acceptance and transcript persistence can remain stable during partial rollback.
- Default to no bound tools rather than permissive behavior if registry, policy, or audit dependencies are unavailable.

## Test Strategy
- Unit:
  - `AssistantState` transitions for one turn
  - deterministic branch selection on `needs_tools`
  - typed `ModelTurnResult` parsing and graph branching without provider-native payload handling inside nodes
  - graph assembly from injected fake repositories, fake models, fake policy services, and fake audit sinks
  - registry exposure and policy-aware filtering
  - `ToolRuntimeContext` injection into factories instead of transport-captured globals
  - outbound message tool proving no channel transport is called
  - tool execution result capture for both success and failure paths
- Repository or persistence:
  - append-only persistence of assistant output, tool proposals, tool outcomes, and outbound intent or outbound references
  - append-only assistant result recording
  - audit event persistence or structured event emission contract coverage
- Integration:
  - one tool-using turn through the gateway-owned runtime path
  - one policy-denied turn proving the denied capability is absent from the bound tool set
  - one runtime turn using only local safe tools and no remote execution support
  - one failure-path turn proving the assistant cannot report success without a recorded tool result
- Implementation notes:
  - use `uv sync` for environment setup
  - run targeted checks with `uv run pytest tests`

## Constitution Check
- Gateway-first execution preserved: graph invocation remains behind gateway/service wiring, never in adapters.
- Transcript-first durability preserved: tool proposals, outcomes, and assistant output are persisted as turn records.
- Runtime identifier alignment preserved: this slice uses Spec 001 naming and an explicit gateway-owned `agent_id` source.
- Approval-before-activation preserved: privileged and approval-gated capabilities stay out of this spec and denied tools fail closed.
- Observable, bounded delivery preserved: audit hooks and deterministic tests are part of the slice, and service boundaries match the architecture document.
