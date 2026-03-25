# Plan 009: Provider-Backed LLM Runtime

## Target Modules
- `pyproject.toml`
- `.env.example`
- `apps/gateway/deps.py`
- `src/config/settings.py`
- `src/providers/models.py`
- `src/graphs/prompts.py`
- `src/graphs/state.py`
- `src/graphs/nodes.py`
- `src/jobs/service.py`
- `src/policies/service.py`
- `src/sessions/repository.py`
- `src/observability/failures.py`
- `src/observability/logging.py`
- `src/observability/metrics.py`
- `tests/test_runtime.py`
- `tests/test_integration.py`
- `tests/test_observability.py`
- add one focused provider-runtime test module if the existing runtime tests become too overloaded, for example `tests/test_provider_runtime.py`

## Migration Order
1. Add the provider-runtime dependency and configuration surface first:
   - extend `pyproject.toml` with the chosen provider SDK
   - extend `src/config/settings.py` with explicit LLM provider settings and validation rules
   - update `.env.example` with local scaffold and provider-backed examples
2. Refactor the provider seam in `src/providers/models.py` without changing graph callers:
   - preserve `ModelAdapter`
   - keep `RuleBasedModelAdapter` available for scaffold mode
   - add one provider-backed adapter plus one bounded provider-error contract and any helper translation types inside the provider module boundary
3. Expand prompt construction in `src/graphs/prompts.py` so the provider adapter receives one structured backend-authored prompt payload with explicit context, tool-visibility, and safety guidance without querying the database directly.
   - carry that payload through `AssistantState` so the adapter method signature can remain stable
4. Update graph integration only where required to preserve compatibility:
   - continue to pass `available_tools`
   - keep policy-controlled tool binding in `src/graphs/nodes.py`
   - add the explicit LLM-originated governance-proposal path for governed tools that lack exact approval, with governance proposal persistence as the only canonical requested-action record on that path
   - add one additive provider-execution metadata return path from `ModelTurnResult` into manifest and observability persistence
   - add any bounded execution metadata needed in `state.context_manifest`
5. Wire provider failure mapping into the existing observability and run-failure path so transport-class failures remain retryable run failures while malformed semantic output becomes a bounded safe completion path using one canonical durable pattern.
6. Add unit coverage for prompt rendering, adapter translation, configuration validation, and malformed responses before or alongside full runtime integration updates.
7. Finish with integration coverage proving the provider-backed path preserves append-only runtime behavior already covered in Specs 001 through 008, including the explicit combined retry-budget cap for provider and worker retries.

## Implementation Shape
- Preserve the current ownership boundaries already visible in the codebase:
  - `apps/gateway/deps.py` selects and wires the model adapter
  - `ContextService` assembles context
  - `src/graphs/prompts.py` renders model input
  - `src/providers/models.py` talks to the provider and translates responses
  - `src/graphs/nodes.py` executes tools, persists artifacts, and appends assistant messages
- Keep provider specifics isolated:
  - no provider-native objects leak into graph, repository, policy, or API modules
  - response parsing and retry logic live in the provider adapter layer
  - provider-call failures cross the module boundary only through one bounded provider-error contract with category, retryability, and safe detail
  - prompt rendering remains backend-authored and testable independently of the provider SDK
- Prefer one provider-backed adapter first rather than an incomplete multi-provider abstraction. The setting names should still allow later extension.
- Treat rule-based behavior as an explicit fallback mode for local scaffolding only, not as an implicit silent fallback when provider config is broken.
- Default runtime mode remains `rule_based` for local development and CI unless deployments explicitly select provider-backed mode.

## Provider Integration Design
### Adapter Layout
- Keep `ModelAdapter` as the stable protocol-like base.
- Keep `RuleBasedModelAdapter` for scaffold mode and deterministic tests.
- Add one concrete adapter such as `ProviderBackedModelAdapter`.
- Add provider-local helpers for:
  - request payload construction from rendered prompts and visible tools
  - timeout and retry handling
  - provider response parsing
  - translation into `ModelTurnResult` and `ToolRequest`
  - failure mapping and sanitization
- Return bounded execution metadata through an additive field on `ModelTurnResult` so manifest and diagnostics persistence does not depend on adapter side channels.
- Expose one bounded provider-error contract from this module so worker retry and failure classification do not need provider-SDK-specific string parsing.

### Prompt Strategy
- Replace the current raw newline transcript prompt with a structured rendering function.
- The prompt builder should expose a provider-agnostic prompt payload shape even if the first implementation serializes it to text for a specific SDK.
- Carry that prompt payload through `AssistantState` so the graph remains the owner of prompt meaning while the adapter keeps the current `complete_turn(state, available_tools)` signature.
- Define one canonical typed backend-owned payload with explicit required sections:
  - `system_instructions`
  - `conversation`
  - `attachments`
  - `tools`
  - `approval_guidance`
  - `response_contract`
  - `metadata`
- Include in that payload:
  - conversation history selected by `ContextService`
  - any summary text already injected into `AssistantState.messages`
  - attachment metadata already assembled into the manifest
  - visible tools with descriptions and backend-authored usage guidance
  - explicit instructions that backend policy and approvals are authoritative
  - response-format instructions describing how plain text and tool requests must map back into `ModelTurnResult`
  - bounded non-secret execution metadata such as prompt strategy identifier and configured tool-call mode
- Keep prompt construction pure and deterministic so it can be snapshot-tested.
- Do not leave tool or approval instructions as undocumented adapter-local string glue.
- Treat `available_tools` as the backend-authorized name-only execution list, not as a substitute for the richer prompt tool metadata.

### Tool Translation
- The first provider-backed implementation must continue to emit the existing `ToolRequest` contract, even if the provider offers native function-calling semantics.
- Translate provider-native tool calls into:
  - backend-generated or provider-provided `correlation_id`
  - canonical `capability_name`
  - JSON-object `arguments`
- Reject or sanitize:
  - unknown tool names
  - non-JSON argument payloads
  - arrays, scalars, or string blobs where object arguments are required
  - excessive tool-call fan-out beyond the configured limit
- For governed tools returned by the provider without an exact approval match, route the request into the existing governance proposal lifecycle rather than treating it as executable.
- For LLM-originated governed requests without exact approval, preserve one explicit persistence sequence:
  - do not persist a separate `tool_proposal` artifact before governance persistence
  - create the governance proposal through the existing repository path
  - treat the resulting `proposal_id` as the canonical correlation identifier for audit and approval UX on that path
  - persist the proposal packet and audit trail through the same approval-owned lifecycle used by deterministic governed requests
  - finish the turn with assistant text that instructs the user to approve the proposal through the existing approval command flow

### Failure Handling
- Map provider exceptions and malformed responses into bounded internal failure types before they reach worker retry logic.
- Keep retry behavior layered and bounded:
  - provider adapter may perform a small number of fast retries for transient provider conditions
  - worker retries remain the outer durability mechanism for turn execution
  - the combined retry budget must be explicit in settings and tests, with total provider call attempts capped at `worker_attempt_count * (1 + llm_max_retries)`
- Keep assistant fallback behavior intentional:
  - malformed semantic provider output from an otherwise successful response becomes a safe assistant-visible fallback or bounded failed-tool completion path
  - infrastructure failures propagate as classified run failures so Spec 005 retry behavior remains meaningful
  - if a one-pass repair retry for malformed semantic output is implemented, it must be explicit, bounded to one attempt, and covered by tests
- Persist malformed semantic output through one canonical durable pattern:
  - if the returned payload is tool-shaped enough to identify a stable capability name and correlation identifier, persist a bounded failed tool result artifact for that attempted request and do not execute the tool
  - do not invent a `tool_proposal` artifact for payloads that are too malformed to trust
  - if the payload is too malformed to identify a stable capability name and correlation identifier, persist a bounded assistant fallback message plus durable observability only
  - this path completes the run safely and does not trigger worker retry solely because the semantic payload was invalid

## Service and Module Boundaries
### `apps/gateway/deps.py`
- Add adapter selection based on settings.
- Keep graph assembly unchanged outside the model selection seam.
- Fail clearly during graph construction if provider-backed mode is selected without required credentials.
- Default to `rule_based` runtime mode unless configuration explicitly selects provider-backed execution.

### `src/config/settings.py`
- Add provider settings with sane defaults for local scaffold mode.
- Validate timeout, retry, tool-request limits, and supported `llm_tool_call_mode` values.
- Add the full provider-runtime settings surface named in the updated spec:
  - `runtime_mode`
  - `llm_provider`
  - `llm_api_key`
  - `llm_base_url`
  - `llm_model`
  - `llm_timeout_seconds`
  - `llm_max_retries`
  - `llm_temperature`
  - `llm_max_output_tokens`
  - `llm_tool_call_mode`
  - `llm_max_tool_requests_per_turn`
  - `llm_disable_tools`
- Keep secret-bearing fields excluded from logs and diagnostics.

### `src/providers/models.py`
- Add the provider-backed adapter.
- Keep the translation boundary from provider-native payloads into `ModelTurnResult`.
- Centralize provider failure mapping and sanitization here.
- Keep provider-native request and response objects inside this module boundary only.
- Make adapter retry ownership explicit here for retryable transport-class failures only.
- Expose one bounded provider-error contract here so retryability and provider failure categories remain structured outside the SDK boundary.

### `src/graphs/prompts.py`
- Replace the current minimal string prompt with a richer backend-owned rendering contract.
- Accept the current `AssistantState` plus tool metadata needed for clear provider guidance.
- Avoid direct repository reads or any side effects.
- Return a structured prompt payload owned by backend code, with provider serialization happening later in the adapter layer.

### `src/graphs/state.py`
- Keep the existing dataclasses stable where possible.
- Add one typed prompt-payload field on `AssistantState` so the graph can hand backend-authored prompt structure to the adapter without changing the adapter signature.
- Add one bounded execution-metadata field on `ModelTurnResult` so the adapter can return provider name, model name, prompt strategy, tool-call mode, provider attempt count, and semantic-fallback classification for manifest or observability persistence.
- Do not break current graph and test call sites without need.

### `src/graphs/nodes.py`
- Preserve deterministic approval and tool-execution ownership.
- Build and attach the typed prompt payload before provider execution, then keep `available_tools` as the final backend-authorized execution list.
- Continue to append messages, tool proposals, tool events, and context manifests in the same order for normal allowed tool execution paths.
- Add one explicit branch for provider-originated governed tool requests that lack approval so the graph creates proposals and emits the same approval guidance pattern used elsewhere, without persisting a competing `tool_proposal` artifact first.
- Add one explicit safe-completion branch for malformed semantic provider output so the graph persists either the bounded failed-tool result pattern or the assistant-fallback-plus-observability pattern, depending on whether the attempted tool identity is stable enough to trust.
- Persist bounded provider execution metadata returned in `ModelTurnResult` into `context_manifests` so later diagnostics can explain which provider path produced the turn.

### `src/jobs/service.py`
- Keep worker retry ownership unchanged while making provider retry composition explicit.
- Ensure transport-class provider failures map into the existing retryable run-failure path through the bounded provider-error contract rather than provider-specific exception parsing.
- Ensure malformed semantic output is treated as a safe completion and does not consume extra worker retries solely because the provider payload was semantically invalid.
- Preserve the explicit combined retry-budget cap in execution flow and failure tests.

### `src/policies/service.py`
- Preserve deterministic command classification for `approve` and `revoke`.
- Keep exact-match approval enforcement unchanged.
- Optionally expose small helper metadata used in prompt instructions, but do not move enforcement into prompts.
- Keep backend visibility and approval lookups authoritative for provider-suggested tool requests.

### `src/sessions/repository.py`
- Reuse the existing governance proposal creation path for LLM-originated governed requests.
- Preserve append-only artifact history and avoid introducing a second requested-action record for governed LLM requests without approval.

### `src/observability/*`
- Reuse existing structured logging and failure classification utilities where possible.
- Add provider-safe logging helpers or event fields for provider name, model name, bounded failure detail, retry count, degraded status, and semantic-output fallback classification.
- Keep redaction guarantees from Spec 008: no API keys, bearer tokens, raw authorization headers, full prompts, or full completions in logs, metrics, traces, or diagnostics payloads.

## Risk Areas
- Provider SDK selection may introduce a dependency that is awkward to stub or too opinionated about request shapes.
- Prompt changes could accidentally weaken deterministic approval-command handling if provider interpretation is allowed too early.
- Malformed tool-call handling could become ambiguous unless the adapter and graph share one clear fail-closed durable behavior.
- Layered retry logic could unintentionally multiply delays if adapter retries and worker retries are both unbounded.
- Silent fallback to the rule-based adapter would make production misconfiguration hard to detect.
- LLM-originated governed tool suggestions could diverge from the existing governance flow unless the proposal-creation path is made explicit in graph code and repository usage.

## Rollback Strategy
- Keep `RuleBasedModelAdapter` available and selectable through configuration while the provider-backed path lands.
- Make the new dependency additive in `pyproject.toml` so reverting to scaffold mode is a configuration change first.
- Keep graph, repository, and API contracts stable so rollback does not require undoing earlier specs.
- If provider metadata is added to manifests or observability payloads, keep it additive and optional so old rows remain readable without migration rollback.

## Test Strategy
### Unit
- Provider adapter translation tests with stubbed provider responses
- Prompt rendering snapshot or fixture-based tests
- Tests for typed prompt-payload construction on `AssistantState`
- Settings validation tests for default `rule_based` mode, explicit provider-backed mode, missing credentials, retry or timeout bounds, and supported `llm_tool_call_mode` values
- Failure-classification tests for timeout, auth failure, malformed responses, and unknown tool names
- Tests for bounded provider-error mapping and retryability decisions without provider-SDK string matching in worker code
- Tests covering the canonical malformed-semantic-output persistence split:
  - failed tool result only when a stable tool identity can be trusted
  - assistant fallback plus observability only when the payload is too malformed to trust
- Tests proving bounded execution metadata returns through `ModelTurnResult` and persists into manifests or observability without side channels
- Tests proving total provider call attempts remain bounded by `worker_attempt_count * (1 + llm_max_retries)`

### Integration
- Existing graph/runtime tests updated to exercise provider-backed plain-answer and tool-using flows through stubs
- Governance-path tests proving LLM-originated governed tool requests create proposals rather than executing without approval, and do so without persisting a separate `tool_proposal` artifact
- End-to-end worker-path tests proving append-only transcript, tool audit, outbound intent, and context manifest behavior remains intact
- Failure-path integration tests proving run classification and retry semantics stay consistent when provider calls fail
- Observability tests proving provider metadata and failure categories are visible in bounded redacted form without leaking secrets

## Rollout Notes
- Land the provider adapter behind explicit configuration so local development and CI can continue using deterministic stubs.
- Prefer enabling the provider-backed adapter in a narrow local or staging configuration first.
- Do not remove scaffold-mode coverage in the same slice; it remains the lowest-risk rollback path.
