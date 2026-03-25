# Spec 009: Provider-Backed LLM Runtime

## Purpose
Replace the current rule-based model adapter with a provider-backed LLM runtime that preserves the existing gateway-first, worker-owned, append-only execution model. This slice must make normal natural-language turns possible without moving tool execution, approval creation, audit persistence, outbound intent creation, or context manifest ownership out of the current backend services.

## Non-Goals
- Tool-schema redesign beyond what is needed to preserve the current `ToolRequest` contract
- Retrieval, durable memory extraction, or attachment-content understanding
- Token streaming or partial transcript persistence
- Real transport-provider integrations for Slack, Telegram, or web chat
- Agent-profile or multi-agent model selection beyond the current single default agent path
- Replacing the current policy service with LLM-authored enforcement logic

## Upstream Dependencies
- Spec 001
- Spec 002
- Spec 003
- Spec 004
- Spec 005
- Spec 006
- Spec 007
- Spec 008

## Scope
- Add a real provider-backed implementation behind `src/providers/models.py` that still returns `ModelTurnResult`
- Preserve the existing `ToolRequest`, `ToolEvent`, `ToolResultPayload`, and graph-node contracts from `src/graphs/state.py` and `src/graphs/nodes.py`
- Extend prompt construction so the model sees transcript context, summary context already assembled by the backend, attachment metadata already normalized by the backend, visible tools, and approval-related operating rules
- Add configuration for provider selection, API keys, model names, timeouts, retries, temperature, and tool-call mode
- Keep deterministic policy classification and approval enforcement in backend code even when the provider suggests a tool
- Add failure mapping for provider timeout, invalid credentials, malformed responses, malformed tool requests, unsupported tool names, and provider unavailability
- Keep the worker retry and observability behavior introduced in Specs 005 through 008 accurate when model calls fail
- Add unit and integration coverage for natural-language turns, tool-using turns, approval-gated turns, and provider failure paths

## Data Model Changes
- No new canonical business-state tables are required for this slice.
- No new migration is required if provider metadata remains in existing append-only artifacts, manifests, and observability fields.
- Provider-execution metadata in this slice must be stored only in additive, already-supported payload shapes:
  - `context_manifests` may include bounded model-execution metadata such as provider name, model name, tool-visibility snapshot, and prompt strategy identifier
  - `tool_audit_events` and existing observability events may include bounded provider-failure classification and request metadata that do not expose secrets
- This spec must not introduce a second transcript or inference-history source of truth outside the existing message, artifact, run, and manifest records.

## Contracts
### Provider Adapter Contract
- `src/providers/models.py` remains the runtime seam for model execution.
- The provider-backed adapter must continue to expose:
  - `complete_turn(*, state: AssistantState, available_tools: list[str]) -> ModelTurnResult`
  - `runtime_services() -> ToolRuntimeServices`
- The adapter may add helper classes or provider-specific clients, but callers outside `src/providers/` must continue to depend on the existing `ModelAdapter` abstraction.
- `AssistantState` may grow additively in this slice to carry one backend-owned typed prompt payload prepared before the provider call, so the adapter can preserve its current method signature without re-owning prompt assembly.
- The adapter must translate provider-native responses into the existing backend-owned contracts:
  - plain assistant text becomes `ModelTurnResult(needs_tools=False, tool_requests=[], response_text=...)`
  - provider-requested tools become `ModelTurnResult(needs_tools=True, tool_requests=[...], response_text=...)`
- `ModelTurnResult` may grow additively in this slice with bounded `execution_metadata` needed for manifest persistence and observability, but existing callers must continue to depend on the current `needs_tools`, `tool_requests`, and `response_text` fields.
- Minimum `execution_metadata` fields are:
  - `provider_name`
  - `model_name`
  - `prompt_strategy_id`
  - `tool_call_mode`
  - `provider_attempt_count`
  - `semantic_fallback_kind` nullable
- `ToolRequest.correlation_id` must always be backend-safe, stable for the returned request, and non-empty even if the provider omits a native call identifier.
- Provider-native request or response objects must not leak beyond the provider module boundary.
- The provider module must expose one bounded internal provider-error contract, such as a typed exception family or equivalent structured error object, carrying:
  - provider failure category
  - retryable boolean
  - safe bounded detail suitable for logs or durable failure state
- Worker retry and observability code must consume that bounded provider-error contract rather than parsing provider SDK exception strings ad hoc.

### Prompt Construction Contract
- `src/graphs/prompts.py` remains the single prompt-construction entry point used by the graph.
- Prompt rendering in this slice must be explicit rather than implicit string concatenation only.
- This slice must introduce a structured backend-owned prompt payload contract rather than leaving final prompt composition split implicitly between `render_prompt(state)` and the provider adapter.
- The prompt builder must accept enough backend-owned inputs to describe the turn coherently, including `AssistantState`, visible tool metadata, and policy guidance metadata needed for the current provider call.
- The backend-owned prompt payload in this slice must have one canonical typed shape, even if the first provider-backed adapter later serializes it into provider-native message objects or text blocks.
- The canonical prompt payload must be assembled by backend code before `complete_turn(...)` is called and carried through the provider call via `AssistantState`, not reconstructed inside the provider adapter from raw database state or registry lookups.
- Minimum prompt payload sections are:
  - `system_instructions`: backend-authored assistant operating rules and safety posture
  - `conversation`: bounded conversation items selected by `ContextService`
  - `attachments`: normalized attachment metadata already present in `state.context_manifest`
  - `tools`: visible tool metadata and backend-authored usage guidance
  - `approval_guidance`: explicit instructions that backend policy and approvals remain authoritative
  - `response_contract`: instructions describing how plain text and tool requests must map back into `ModelTurnResult`
  - `metadata`: bounded non-secret execution metadata such as prompt strategy identifier and provider-facing tool mode
- The rendered prompt or prompt payload must include, in backend-controlled form:
  - bounded conversation history already selected by `ContextService`
  - any summary text already injected into `AssistantState.messages`
  - normalized attachment metadata already present in `state.context_manifest`
  - visible tool names, human-readable descriptions, argument-shape guidance, and governance hints authored by the backend
  - explicit approval and safety instructions describing that backend policy remains authoritative
  - response-format instructions needed for the provider adapter to map output back into `ModelTurnResult`
- Prompt construction must not query the database directly or bypass `ContextService`.
- The provider adapter may serialize the structured prompt payload into a provider-specific request format, but it must not invent or own the authoritative prompt sections that describe tools, approvals, or transcript context.
- `available_tools` remains the backend-authorized name-only execution surface for final tool validation and must not become the sole source of prompt meaning for tool descriptions or usage guidance.

### Tool-Use Contract
- The model may suggest only tools that are already visible through `available_tools`.
- The provider adapter must fail closed on any returned tool request that:
  - names an unavailable capability
  - omits required arguments
  - returns non-object arguments
  - returns more tool requests than the configured per-turn maximum
- Fail-closed handling for malformed tool requests in this slice is:
  - no unsafe tool executes
  - infrastructure and transport failures remain classified run failures that participate in worker retry behavior
  - malformed semantic provider output from an otherwise successful provider response, such as invalid tool-call payloads or unknown tool names, becomes a bounded assistant-safe fallback or bounded failed tool result and completes the run without unsafe execution
  - existing audit and observability surfaces remain consistent with what happened
- The provider adapter must not execute tools directly. Tool execution continues to happen only in `src/graphs/nodes.py`.
- If the provider suggests a governed capability that is registered but does not have an exact active approval, backend graph logic must create a governance proposal through the existing approval-owned persistence path rather than executing the tool directly or silently dropping the request.
- For an LLM-originated governed tool request without an exact active approval, the governance proposal becomes the only canonical requested-action record for that path in this slice:
  - backend code must not persist a separate `tool_proposal` artifact before proposal creation
  - the governance `proposal_id` is the canonical correlation identifier for proposal audit and approval UX on that path
  - observability may record bounded provider metadata for the attempted governed request, but it must not create a second competing approval target
- The assistant response for an LLM-originated governed request without approval must follow one explicit backend-owned pattern:
  - proposal created
  - proposal packet persisted and audited
  - assistant response instructs the user how to approve the proposal using the existing approval command flow

### Policy and Approval Contract
- `src/policies/service.py` remains authoritative for deterministic command classification, approval lookup, exact-match approval enforcement, and deny rules.
- The LLM path must not weaken any current backend policy boundary:
  - if the user message is a deterministic approval command, backend classification wins without asking the provider to interpret it
  - if a provider suggests a governed tool without an exact active approval, backend code must create a proposal through the existing governance lifecycle and must not execute the tool
  - if a provider suggests a denied or unregistered tool, backend code still rejects it
- Prompt instructions may describe approvals, but prompt wording alone is never sufficient authorization.
- LLM-originated governed tool proposals must use the same canonical argument serialization, typed action identity, approval matching, and audit patterns already used for deterministic governed requests.

### Failure Classification Contract
- Provider failures must map into bounded backend-visible categories that cooperate with existing run retry and diagnostics behavior.
- Minimum provider failure categories in this slice are:
  - `provider_timeout`
  - `provider_unavailable`
  - `provider_auth`
  - `provider_rate_limited`
  - `provider_malformed_response`
  - `provider_tool_schema_error`
  - `provider_unexpected_internal`
- The implementation may map these onto the broader Spec 008 operational categories when persisted to durable run state, but the provider layer must preserve enough detail for debugging.
- Provider failures must never log API keys, bearer tokens, raw authorization headers, or full unbounded prompts or completions.
- Failure handling is split explicitly in this slice:
  - transport, timeout, auth, rate-limit, and provider-unavailable conditions are classified run failures that may participate in bounded retry behavior
  - malformed semantic output from a successfully returned provider payload, including invalid tool-call structure, unknown tool names, or non-object tool arguments, is treated as a non-unsafe completion path with bounded assistant-visible fallback and durable observability
- The retryable or terminal decision for provider-call failures must come from the bounded provider-error contract defined by the provider module, not from substring matching against raw provider SDK error messages in worker code.
- Malformed semantic output from a successfully returned provider payload must persist using one canonical durable pattern:
  - if the payload is tool-shaped enough to identify a stable capability name and correlation identifier, backend code may persist a bounded failed tool result artifact for that attempted request
  - backend code must not execute any tool for malformed semantic output
  - backend code must not invent a `tool_proposal` artifact for payloads that are too malformed to trust as a real request
  - if the payload is too malformed to identify a stable capability name and correlation identifier, backend code must persist a bounded assistant fallback message plus durable observability only
  - this path completes the run safely and is not retried as an infrastructure failure solely because the semantic payload was malformed
- The implementation may add one bounded single-pass repair attempt for malformed semantic output only if it is explicitly documented and tested, but it must not create an unbounded hidden retry loop.

### Configuration Contract
- `src/config/settings.py` and `.env.example` must gain explicit provider-runtime settings.
- Minimum settings in this slice are:
  - `runtime_mode`
  - `llm_provider`
  - `llm_api_key`
  - `llm_base_url` nullable
  - `llm_model`
  - `llm_timeout_seconds`
  - `llm_max_retries`
  - `llm_temperature`
  - `llm_max_output_tokens` nullable
  - `llm_tool_call_mode`
  - `llm_max_tool_requests_per_turn`
  - `llm_disable_tools`
- `llm_tool_call_mode` must be an explicit backend setting rather than adapter-local behavior.
- Minimum supported values in this slice are:
  - `auto`: tools may be offered to the provider subject to backend visibility and policy filtering
  - `none`: the adapter must not expose tool use to the provider for that call
- Additional provider-supported values may be added later only if they preserve the same backend ownership boundaries.
- The default runtime mode after this spec lands must remain safe for local development and CI:
  - default `runtime_mode` is `rule_based`
  - provider-backed behavior is enabled only by explicit configuration
- The settings contract must support a local fail-closed mode:
  - if provider-backed runtime is selected but required credentials are missing, startup or graph construction must fail clearly rather than silently falling back to rule-based behavior
  - if the deployment explicitly selects the rule-based adapter for scaffold mode, that choice must be deliberate in configuration

### Dependency Contract
- Any new provider SDK dependency must be added explicitly in `pyproject.toml`.
- The implementation must preserve a testable abstraction boundary so unit tests can stub provider behavior without requiring live network access.
- The repository must remain runnable in local and CI environments without forcing real provider credentials for the default test suite.

## Runtime Invariants
- All user-visible turns still enter through the gateway, persist canonical state first, and execute on the worker path.
- `ContextService` remains the only component that selects transcript and summary context for a turn.
- `src/graphs/nodes.py` remains the only component that executes tools, writes tool artifacts, persists assistant messages, and persists context manifests.
- Approval-gated capabilities still require exact backend approval matches before execution.
- A provider response can influence `response_text` and `tool_requests`, but it cannot mutate prior transcript rows or directly dispatch outbound traffic.
- The runtime must produce a bounded assistant response or a classified failure; it must not silently swallow provider errors and mark the run successful without a persisted explanation.

## Security Constraints
- Secrets remain settings-only inputs and must not be persisted in messages, manifests, artifacts, logs, or diagnostics payloads.
- The provider adapter must sanitize prompt and completion previews according to the observability settings from Spec 008.
- Tool visibility presented to the model must already reflect policy filtering from the backend.
- Provider-generated tool arguments are untrusted input and must pass the same backend validation and approval checks as deterministic requests.
- This slice must not introduce direct browser, webhook, or channel-callback communication from the provider module.

## Operational Considerations
- The provider path must have explicit timeout and retry settings so worker retry behavior composes with provider retry behavior instead of multiplying indefinitely.
- Local development must support a deliberate scaffold mode that keeps the current rule-based adapter available when the provider runtime is disabled.
- Diagnostics and structured logs should expose provider name, model name, bounded failure detail, retry count, and degraded status without exposing secrets or full prompt bodies.
- The implementation should record enough model-execution metadata in manifests or observability events to explain which provider path produced a given assistant turn.
- The canonical path for that metadata in this slice is:
  - backend-authored prompt metadata enters the call through the typed prompt payload on `AssistantState`
  - provider-produced execution metadata returns through additive `ModelTurnResult.execution_metadata`
  - graph code persists the bounded subset needed by manifests and observability
- This slice must document whether provider retries are handled inside the adapter, by the worker, or both, and must cap the combined retry budget.
- The combined retry budget in this slice is explicit:
  - worker retries remain the outer execution retry mechanism
  - the provider adapter may perform at most `llm_max_retries` additional attempts within one worker attempt for retryable transport-class failures only
  - total provider call attempts for one accepted run must be bounded by `worker_attempt_count * (1 + llm_max_retries)`, where `worker_attempt_count` is the number of worker execution attempts allowed for that run
  - malformed semantic output from a successfully returned provider payload does not consume additional worker retries solely because the payload was semantically invalid

## Acceptance Criteria
- A normal inbound user message can produce a natural-language assistant reply through a real provider-backed adapter while preserving the existing gateway, worker, graph, and persistence boundaries.
- A provider-generated allowed tool request is translated into `ToolRequest`, executed only by existing graph-node logic, audited, and reflected in the assistant response.
- A provider-generated governed tool request without an active exact approval does not execute and instead creates a governance proposal through the existing backend approval flow, with no separate `tool_proposal` artifact for that path and with the resulting assistant response telling the user how to approve it.
- A malformed provider tool-call response does not execute any unsafe behavior; transport-class failures remain classified retryable run failures, while malformed semantic output becomes a bounded safe completion path with one canonical durable pattern: failed tool result only when the payload is stably identifiable as a tool attempt, otherwise assistant fallback plus observability only.
- A provider timeout or transient provider outage results in accurate run failure classification and retry behavior without corrupting transcript or artifact state.
- Prompt construction uses one backend-owned structured prompt payload contract with required sections for system instructions, conversation, attachments, tools, approval guidance, response contract, and metadata, and that payload is serialized by the provider adapter rather than split ambiguously across graph and adapter code.
- Combined retry behavior is explicit and bounded so total provider call attempts for one accepted run cannot exceed `worker_attempt_count * (1 + llm_max_retries)`.
- The repository test suite can exercise the provider-backed runtime through stubs or fakes without requiring live provider access.

## Test Expectations
- Unit tests for provider response translation into `ModelTurnResult`, including plain-text replies, single-tool replies, multiple-tool replies up to the configured cap, and malformed tool-call payloads
- Unit tests for prompt rendering so visible tools, approval instructions, bounded context inputs, and the required prompt payload sections are present in the backend-authored prompt structure
- Unit tests for configuration validation covering default `rule_based` runtime mode, explicit provider-backed mode, missing credentials, invalid retry or timeout settings, supported `llm_tool_call_mode` values, and deliberate scaffold-mode fallback
- Runtime tests proving backend policy still blocks denied or unknown tools, and creates proposals rather than executing approval-gated tools when the provider suggests them without an exact active approval
- Runtime tests proving LLM-originated governed tool requests without approval create governance proposals without persisting a separate `tool_proposal` artifact
- Integration-style tests proving one accepted run keeps append-only transcript, tool audit, artifact, and manifest behavior unchanged under the provider-backed path
- Failure-path tests proving timeout, auth failure, and provider-unavailable scenarios remain observable and classify correctly
- Failure-path tests proving malformed semantic output persists the canonical safe-completion pattern and does not trigger infrastructure retry behavior by itself
- Retry-behavior tests proving total provider call attempts remain bounded by `worker_attempt_count * (1 + llm_max_retries)`
