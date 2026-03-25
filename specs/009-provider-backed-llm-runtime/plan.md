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
- `src/policies/service.py`
- `src/observability/`
- `tests/test_runtime.py`
- `tests/test_integration.py`
- add one focused provider-runtime test module if the existing runtime tests become too overloaded, for example `tests/test_provider_runtime.py`

## Migration Order
1. Add the provider-runtime dependency and configuration surface first:
   - extend `pyproject.toml` with the chosen provider SDK
   - extend `src/config/settings.py` with explicit LLM provider settings and validation rules
   - update `.env.example` with local scaffold and provider-backed examples
2. Refactor the provider seam in `src/providers/models.py` without changing graph callers:
   - preserve `ModelAdapter`
   - keep `RuleBasedModelAdapter` available for scaffold mode
   - add one provider-backed adapter and any helper translation types inside the provider module boundary
3. Expand prompt construction in `src/graphs/prompts.py` so the provider adapter receives explicit backend-authored context, tool-visibility, and safety guidance without querying the database directly.
4. Update graph integration only where required to preserve compatibility:
   - continue to pass `available_tools`
   - keep policy-controlled tool binding in `src/graphs/nodes.py`
   - add any bounded execution metadata needed in `state.context_manifest`
5. Wire provider failure mapping into the existing observability and run-failure path so worker retries and diagnostics stay accurate.
6. Add unit coverage for prompt rendering, adapter translation, configuration validation, and malformed responses before or alongside full runtime integration updates.
7. Finish with integration coverage proving the provider-backed path preserves append-only runtime behavior already covered in Specs 001 through 008.

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
  - prompt rendering remains backend-authored and testable independently of the provider SDK
- Prefer one provider-backed adapter first rather than an incomplete multi-provider abstraction. The setting names should still allow later extension.
- Treat rule-based behavior as an explicit fallback mode for local scaffolding only, not as an implicit silent fallback when provider config is broken.

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

### Prompt Strategy
- Replace the current raw newline transcript prompt with a structured rendering function.
- The prompt builder should expose a provider-agnostic prompt payload shape even if the first implementation serializes it to text for a specific SDK.
- Include:
  - system instructions for assistant behavior and formatting
  - conversation history selected by `ContextService`
  - attachment metadata already assembled into the manifest
  - visible tools with descriptions from the bound registry
  - explicit instructions that backend policy and approvals are authoritative
- Keep prompt construction pure and deterministic so it can be snapshot-tested.

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

### Failure Handling
- Map provider exceptions and malformed responses into bounded internal failure types before they reach worker retry logic.
- Keep retry behavior layered and bounded:
  - provider adapter may perform a small number of fast retries for transient provider conditions
  - worker retries remain the outer durability mechanism for turn execution
  - the combined retry budget must be explicit in settings and tests
- Keep assistant fallback behavior intentional:
  - malformed provider output may become a safe assistant error response if the implementation chooses that route
  - infrastructure failures should generally propagate as classified run failures so Spec 005 retry behavior remains meaningful

## Service and Module Boundaries
### `apps/gateway/deps.py`
- Add adapter selection based on settings.
- Keep graph assembly unchanged outside the model selection seam.
- Fail clearly during graph construction if provider-backed mode is selected without required credentials.

### `src/config/settings.py`
- Add provider settings with sane defaults for local scaffold mode.
- Validate timeout, retry, and tool-request limits.
- Keep secret-bearing fields excluded from logs and diagnostics.

### `src/providers/models.py`
- Add the provider-backed adapter.
- Keep the translation boundary from provider-native payloads into `ModelTurnResult`.
- Centralize provider failure mapping and sanitization here.

### `src/graphs/prompts.py`
- Replace the current minimal string prompt with a richer backend-owned rendering contract.
- Accept the current `AssistantState` plus tool metadata needed for clear provider guidance.
- Avoid direct repository reads or any side effects.

### `src/graphs/state.py`
- Keep the existing dataclasses stable where possible.
- Only add additive fields if truly necessary for provider metadata or prompt payload structure.
- Do not break current graph and test call sites without need.

### `src/graphs/nodes.py`
- Preserve deterministic approval and tool-execution ownership.
- Pass richer prompt inputs or visible tool metadata to the provider adapter only as needed.
- Continue to append messages, tool proposals, tool events, and context manifests in the same order.

### `src/policies/service.py`
- Preserve deterministic command classification for `approve` and `revoke`.
- Keep exact-match approval enforcement unchanged.
- Optionally expose small helper metadata used in prompt instructions, but do not move enforcement into prompts.

### `src/observability/`
- Reuse existing structured logging and failure classification utilities where possible.
- Add provider-safe logging helpers or event fields only if required for clear diagnostics.

## Risk Areas
- Provider SDK selection may introduce a dependency that is awkward to stub or too opinionated about request shapes.
- Prompt changes could accidentally weaken deterministic approval-command handling if provider interpretation is allowed too early.
- Malformed tool-call handling could become ambiguous unless the adapter defines one clear fail-closed behavior.
- Layered retry logic could unintentionally multiply delays if adapter retries and worker retries are both unbounded.
- Silent fallback to the rule-based adapter would make production misconfiguration hard to detect.

## Rollback Strategy
- Keep `RuleBasedModelAdapter` available and selectable through configuration while the provider-backed path lands.
- Make the new dependency additive in `pyproject.toml` so reverting to scaffold mode is a configuration change first.
- Keep graph, repository, and API contracts stable so rollback does not require undoing earlier specs.
- If provider metadata is added to manifests or observability payloads, keep it additive and optional so old rows remain readable without migration rollback.

## Test Strategy
### Unit
- Provider adapter translation tests with stubbed provider responses
- Prompt rendering snapshot or fixture-based tests
- Settings validation tests for provider mode, missing credentials, and retry or timeout bounds
- Failure-classification tests for timeout, auth failure, malformed responses, and unknown tool names

### Integration
- Existing graph/runtime tests updated to exercise provider-backed plain-answer and tool-using flows through stubs
- End-to-end worker-path tests proving append-only transcript, tool audit, outbound intent, and context manifest behavior remains intact
- Failure-path integration tests proving run classification and retry semantics stay consistent when provider calls fail

## Rollout Notes
- Land the provider adapter behind explicit configuration so local development and CI can continue using deterministic stubs.
- Prefer enabling the provider-backed adapter in a narrow local or staging configuration first.
- Do not remove scaffold-mode coverage in the same slice; it remains the lowest-risk rollback path.
