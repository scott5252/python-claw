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
- The adapter must translate provider-native responses into the existing backend-owned contracts:
  - plain assistant text becomes `ModelTurnResult(needs_tools=False, tool_requests=[], response_text=...)`
  - provider-requested tools become `ModelTurnResult(needs_tools=True, tool_requests=[...], response_text=...)`
- `ToolRequest.correlation_id` must always be backend-safe, stable for the returned request, and non-empty even if the provider omits a native call identifier.
- Provider-native request or response objects must not leak beyond the provider module boundary.

### Prompt Construction Contract
- `src/graphs/prompts.py` remains the single prompt-construction entry point used by the graph.
- Prompt rendering in this slice must be explicit rather than implicit string concatenation only.
- The rendered prompt or prompt payload must include, in backend-controlled form:
  - bounded conversation history already selected by `ContextService`
  - any summary text already injected into `AssistantState.messages`
  - normalized attachment metadata already present in `state.context_manifest`
  - visible tool names and backend-authored usage guidance
  - explicit approval and safety instructions describing that backend policy remains authoritative
  - response-format instructions needed for the provider adapter to map output back into `ModelTurnResult`
- Prompt construction must not query the database directly or bypass `ContextService`.

### Tool-Use Contract
- The model may suggest only tools that are already visible through `available_tools`.
- The provider adapter must fail closed on any returned tool request that:
  - names an unavailable capability
  - omits required arguments
  - returns non-object arguments
  - returns more tool requests than the configured per-turn maximum
- Fail-closed handling for malformed tool requests in this slice is:
  - no unsafe tool executes
  - the run records a classified failure or a bounded assistant-safe fallback according to the plan
  - existing audit and observability surfaces remain consistent with what happened
- The provider adapter must not execute tools directly. Tool execution continues to happen only in `src/graphs/nodes.py`.

### Policy and Approval Contract
- `src/policies/service.py` remains authoritative for deterministic command classification, approval lookup, exact-match approval enforcement, and deny rules.
- The LLM path must not weaken any current backend policy boundary:
  - if the user message is a deterministic approval command, backend classification wins without asking the provider to interpret it
  - if a provider suggests a governed tool without an exact active approval, backend code still blocks execution or creates a proposal according to current graph behavior
  - if a provider suggests a denied or unregistered tool, backend code still rejects it
- Prompt instructions may describe approvals, but prompt wording alone is never sufficient authorization.

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

### Configuration Contract
- `src/config/settings.py` and `.env.example` must gain explicit provider-runtime settings.
- Minimum settings in this slice are:
  - `llm_provider`
  - `llm_api_key`
  - `llm_base_url` nullable
  - `llm_model`
  - `llm_timeout_seconds`
  - `llm_max_retries`
  - `llm_temperature`
  - `llm_max_output_tokens` nullable
  - `llm_max_tool_requests_per_turn`
  - `llm_disable_tools`
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
- This slice must document whether provider retries are handled inside the adapter, by the worker, or both, and must cap the combined retry budget.

## Acceptance Criteria
- A normal inbound user message can produce a natural-language assistant reply through a real provider-backed adapter while preserving the existing gateway, worker, graph, and persistence boundaries.
- A provider-generated allowed tool request is translated into `ToolRequest`, executed only by existing graph-node logic, audited, and reflected in the assistant response.
- A provider-generated governed tool request without an active exact approval does not execute and instead follows the current approval-gated behavior already implemented in the graph.
- A malformed provider tool-call response does not execute any unsafe behavior and results in a classified failure or safe fallback consistent with the final implementation plan.
- A provider timeout or transient provider outage results in accurate run failure classification and retry behavior without corrupting transcript or artifact state.
- The repository test suite can exercise the provider-backed runtime through stubs or fakes without requiring live provider access.

## Test Expectations
- Unit tests for provider response translation into `ModelTurnResult`, including plain-text replies, single-tool replies, multiple-tool replies up to the configured cap, and malformed tool-call payloads
- Unit tests for prompt rendering so visible tools, approval instructions, and bounded context inputs are present in the backend-authored prompt structure
- Unit tests for configuration validation covering missing credentials, invalid retry or timeout settings, and deliberate rule-based fallback mode
- Runtime tests proving backend policy still blocks denied, unknown, or approval-gated tools even when the provider suggests them
- Integration-style tests proving one accepted run keeps append-only transcript, tool audit, artifact, and manifest behavior unchanged under the provider-backed path
- Failure-path tests proving timeout, auth failure, and provider-unavailable scenarios remain observable and classify correctly
