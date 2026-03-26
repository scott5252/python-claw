# Spec 010: Typed Tool Schemas and Hybrid Intent Control

## Purpose
Make LLM-driven tool use reliable by replacing loose dictionary-based tool arguments with explicit typed schemas, while preserving deterministic backend handling for high-risk control intents such as approval and revocation commands.

## Non-Goals
- Replacing the current provider adapter abstraction or redesigning Spec 009 prompt ownership
- Introducing retrieval, memory extraction, or attachment-content understanding
- Implementing sub-agent delegation, agent profiles, or session-ownership changes
- Adding new transport integrations or streaming delivery behavior
- Moving approval enforcement or tool execution authority out of backend code
- Replacing the existing governance lifecycle or exact-match approval model

## Upstream Dependencies
- Spec 001
- Spec 002
- Spec 003
- Spec 004
- Spec 005
- Spec 006
- Spec 007
- Spec 008
- Spec 009

## Scope
- Introduce explicit typed input schemas for `echo_text`, `send_message`, and `remote_exec`
- Extend the tool registry so each visible tool exposes stable schema metadata, validation behavior, and canonical serialization inputs
- Define one canonical bound-tool exposure shape that feeds prompt construction, provider-native tool definitions, and runtime validation from the same registry-owned source
- Ensure provider adapters receive backend-authored tool schemas rather than lightweight argument hints only
- Preserve deterministic command parsing in `src/policies/service.py` for `approve` and `revoke`, and keep any similarly high-risk administrative intent out of model interpretation
- Validate all LLM-originated and deterministic tool arguments against the same backend-owned schema contract before execution
- Standardize canonical argument serialization after validation so approval matching, proposal hashing, audit records, and proposal packets stay stable
- Improve assistant-visible error handling for invalid tool arguments and malformed provider tool payloads
- Preserve backward-compatible runtime behavior for safe non-governed tools and governed proposal creation, while tightening validation and observability

## Implementation Gap Resolutions
### Gap 1: Schema Version Participation in Approval Identity
The original draft required `schema_version` metadata, but it did not define whether schema-version changes should affect proposal reuse, approval matching, or execution identity for governed tools.

Options considered:
- Option A: treat schema version as prompt-only metadata and exclude it from all durable records and approval identity
- Option B: persist schema version in audit and tool-event metadata only, but keep approval identity based on typed action plus canonical arguments only
- Option C: persist schema version durably and require it to participate in governed proposal and approval identity without changing `typed_action_id`
- Option D: encode schema version into `typed_action_id` and treat every schema revision as a new typed action

Selected option:
- Option C

Decision:
- `schema_version` remains additive metadata on bound tools, but for governed tools it must also participate in exact approval identity.
- `typed_action_id` stays stable across schema revisions.
- Governance proposal payloads, approval packets, and exact-match approval lookup inputs for governed tools must include `tool_schema_name` and `tool_schema_version` alongside canonical validated arguments so a schema change cannot silently reuse an approval created under different argument semantics.

### Gap 2: Authoritative Validation Boundary Between Provider and Graph
The original draft required both provider-side malformed-payload handling and backend validation, but it did not clearly separate coarse provider screening from authoritative schema validation.

Options considered:
- Option A: let provider adapters perform full schema validation and pass only validated requests to the graph
- Option B: require duplicate full validation in both provider adapters and graph execution
- Option C: perform no provider-side screening and rely entirely on graph-time validation
- Option D: allow provider adapters to perform coarse envelope screening only, while graph-time validation against bound tool schemas remains authoritative

Selected option:
- Option D

Decision:
- Provider adapters may reject only coarse malformed payloads such as unknown tool names, non-object arguments where an object is required, or request-count overflow.
- Provider adapters must not become the source of truth for required fields, field types, defaults, extras policy, or canonicalization.
- `src/graphs/nodes.py` remains the authoritative validation boundary that turns untrusted raw arguments into validated typed requests, canonical arguments, approval checks, and execution decisions.

### Gap 3: Deterministic Non-Administrative Shortcuts Under Hybrid Intent Control
The original draft preserved deterministic `approve` and `revoke`, but it did not define how existing deterministic action shortcuts such as `send ...` should interact with the new schema pipeline.

Options considered:
- Option A: keep deterministic non-administrative shortcuts as special-case execution paths outside typed schema validation
- Option B: remove all deterministic non-administrative shortcuts and force every non-admin request through the LLM path
- Option C: allow deterministic non-administrative shortcuts only if they normalize into the same `ToolRequest` flow used by provider-backed requests
- Option D: expand deterministic parsing to all tool intents and reduce the provider path to text-only answers

Selected option:
- Option C

Decision:
- This slice keeps deterministic parsing mandatory only for high-risk administrative control intents such as `approve <proposal_id>` and `revoke <proposal_id>`.
- Existing or future deterministic non-administrative shortcuts may remain only if they emit the same raw tool-request shape that then flows through shared schema validation, canonicalization, approval enforcement, audit persistence, and execution logic.
- No deterministic non-administrative shortcut may create proposals, approvals, or tool results through a separate pre-validation path.

### Gap 4: Extras Policy and `remote_exec` Request Shape
The original draft required explicit typed schemas but did not resolve how to handle open-ended invocation arguments for `remote_exec`, nor whether unknown fields should be rejected or normalized.

Options considered:
- Option A: reject all extra or unknown fields for every tool, including `remote_exec`
- Option B: allow arbitrary extras for every tool and rely on tool implementations to ignore what they do not need
- Option C: make extras behavior schema-owned: fixed-shape tools reject extras, while `remote_exec` uses an explicit open-key validated scalar map schema and reserves runtime-only metadata outside provider-visible arguments
- Option D: defer `remote_exec` typed-schema work to a later spec and keep it dictionary-based for now

Selected option:
- Option C

Decision:
- Extras behavior is schema-owned, with a repository standard of fail-closed fixed-shape schemas unless a tool explicitly declares an open-key schema.
- `echo_text` and `send_message` use fixed-shape schemas and reject unknown fields.
- `remote_exec` uses one explicit typed open-key invocation schema whose user- or model-supplied fields are limited to canonical scalar JSON values suitable for exact approval matching and template substitution.
- Runtime-generated execution envelope fields such as correlation identifiers or retry counters are backend-owned metadata, not provider-visible tool arguments, and must not participate in approval identity or provider-exposed schema export.

## Data Model Changes
- No new canonical business-state tables are required for this slice.
- No governance lifecycle tables change in this slice.
- Governed schema identity for approval matching and replay must have one authoritative durable source:
  - `tool_schema_name`
  - `tool_schema_version`
- The authoritative durable source for governed schema identity in this slice is the governed resource payload stored on `resource_versions.resource_payload`.
- Approval rows, active-resource rows, proposal packets, tool events, manifests, and audit payloads may mirror schema identity additively for lookup, diagnostics, and replay performance, but they must not become a competing source of truth.
- If a replay, approval lookup, or proposal-packet path needs schema identity and a mirrored field is absent, the implementation must derive it from the governed resource payload rather than inventing a default.
- Existing append-only artifact, manifest, and audit payloads may grow additively to persist bounded schema metadata such as:
  - `tool_schema_name`
  - `tool_schema_version`
  - `canonical_arguments_json`
  - `canonical_arguments_hash`
  - `validation_error_code`
  - `validation_error_fields`
- If the current append-only payload shapes can already carry those bounded fields, no migration is required.
- If durable tool-event storage currently lacks a bounded place for schema-validation metadata, one additive migration is allowed, but this spec must not create a second source of truth for tool requests outside the existing tool-event, governance, run, and observability records.

## Contracts
### Typed Tool Schema Contract
- Every executable tool exposed through `src/tools/registry.py` must publish one explicit backend-owned input schema.
- The schema contract must be typed, validated, and serializable, and must not be an informal `dict[str, Any]` convention.
- The initial schema implementation in this slice must cover:
  - `src/tools/local_safe.py`
  - `src/tools/messaging.py`
  - `src/tools/remote_exec.py`
- The implementation may use Pydantic request models or an equivalent typed validation system, but the repository standard for this slice is explicit request-model classes rather than ad hoc field checks inside tool functions.
- Each schema must have:
  - stable tool-facing name
  - stable schema class or type identity
  - bounded human-readable description
  - deterministic JSON-schema export or equivalent provider-facing schema representation
  - validation entrypoint that accepts untrusted input and returns either a typed validated request or a bounded validation error
  - canonical serialization entrypoint that renders the validated request into stable JSON for hashing, approvals, and audit
- Fixed-shape schemas must fail closed on unknown fields unless the schema explicitly declares open-key behavior.
- In this slice:
  - `echo_text` and `send_message` must use fixed-shape schemas
  - `remote_exec` must use one explicit open-key invocation schema rather than an untyped free-form dictionary convention
- The provider-visible `remote_exec` schema must describe only approval-relevant invocation arguments.
- Runtime-owned execution envelope fields such as `tool_call_id` and `execution_attempt_number` are not part of the provider-visible tool schema and are not part of approval identity.
- Tool implementations must receive typed validated request objects or a validated canonical payload produced from those objects, rather than raw unvalidated model output dictionaries.
- For governed tools, the schema-identity values used by approval matching and replay must be the same values persisted in the governed resource payload; mirrored copies in approval or audit records are additive only.

### Tool Registry Contract
- `src/tools/registry.py` remains the sole binding surface for executable tools.
- `ToolDefinition` must grow additively so each bound tool exposes:
  - `capability_name`
  - `description`
  - `input_schema`
  - `schema_version`
  - `validate(...)`
  - `canonicalize(...)`
  - `invoke(...)`
- The registry must provide enough metadata for two distinct consumers:
  - provider adapters that need provider-facing tool schemas
  - graph/runtime code that needs backend validation and canonicalization before execution or approval matching
- The registry must also provide enough metadata for prompt construction so the human-readable tool guidance shown to the model is derived from the same bound tool definition rather than from a second prompt-only hint structure.
- Tool visibility remains policy-filtered before a schema is exposed to the model.
- A tool omitted by policy must also be omitted from provider-facing tool schemas.
- The registry must not expose one schema to the provider and validate against a materially different schema at execution time.

### Bound Tool Exposure Contract
- This slice must define one canonical backend-owned bound-tool exposure shape derived from the registry after policy filtering and before provider invocation.
- The bound-tool exposure contract is the only allowed source for:
  - prompt-visible tool metadata in `src/graphs/prompts.py`
  - provider-native tool or function definitions in `src/providers/models.py`
  - runtime validation and canonicalization lookup before execution
- The contract may be implemented as a dedicated dataclass or equivalent typed model, but it must carry at minimum:
  - `capability_name`
  - `description`
  - `schema_version`
  - bounded human-readable usage guidance suitable for prompt rendering
  - provider-facing schema export derived from the same backend-owned typed schema
  - backend validation and canonicalization handles or references
- `PromptPayload.tools` from Spec 009 may evolve additively in this slice, but prompt assembly must no longer rely on a prompt-only `argument_guidance` shape that can drift from execution-time validation.
- A provider adapter may reformat the bound-tool exposure into provider-native JSON, but it must not recreate tool descriptions, required fields, or argument semantics from separate prompt hints.
- If a tool is visible in prompt guidance for a provider-backed turn, the same bound-tool exposure entry must also be the basis for provider schema export and execution-time validation for that turn.
- The canonical bound-tool exposure contract in this slice must be carried on `AssistantState` as a backend-owned per-turn structure rather than inferred later from `available_tools: list[str]` alone.
- `ModelAdapter.complete_turn(...)` may keep the existing `available_tools: list[str]` parameter for backward compatibility, but provider-backed execution in this slice must consume the bound-tool exposure entries carried on `AssistantState` as the authoritative source for tool meaning and schema export.

### Provider Tool-Schema Contract
- `src/providers/models.py` must consume backend-owned tool schema metadata from the registry rather than inferring schemas from prompt hints or hard-coded assumptions.
- Provider-facing tool definitions in this slice must be derived from the canonical tool schema contract and the bound-tool exposure contract, not reconstructed ad hoc per provider.
- Provider adapters may translate the backend-owned schema into provider-native function or tool formats, but they must not become the authoritative source for required fields, types, defaults, or additional-property behavior.
- The provider translation layer must support at least:
  - object-shaped input schema
  - required vs optional field semantics
  - field descriptions
  - rejection of malformed non-object arguments before execution
- Provider adapters may perform only coarse envelope screening before returning `ModelTurnResult`, such as:
  - rejecting unknown tool names
  - rejecting malformed non-object arguments where an object is required
  - rejecting request-count overflow
- Provider adapters must not perform the authoritative schema validation that decides extras policy, canonicalization, approval identity, or execution eligibility.
- If a provider returns tool-call arguments that fail backend schema validation, the runtime must not execute the tool.

### Hybrid Intent-Control Contract
- `src/policies/service.py` remains authoritative for deterministic parsing of high-risk control intents.
- At minimum, the following user intents must continue to bypass model interpretation:
  - `approve <proposal_id>`
  - `revoke <proposal_id>`
- This slice may add more deterministic administrative classifications only if they are explicitly documented and tested, but it must not reduce the deterministic scope already implemented.
- Deterministic non-administrative shortcuts are allowed only if they are normalized into the same shared tool-request validation and execution pipeline used for provider-backed tool requests.
- Deterministic non-administrative shortcuts must not bypass schema validation, canonicalization, approval matching, proposal creation rules, or append-only tool-event persistence.
- Hybrid intent control in this slice means:
  - normal natural-language requests may be interpreted by the provider-backed LLM and routed into typed tool execution
  - high-risk control commands are classified deterministically before provider invocation
  - backend validation remains authoritative even for LLM-suggested tools
- The model may help interpret a normal user request such as “send this to the channel” into a tool call, but it may not decide whether approval commands, revocations, or exact approval matching semantics are valid.
- When a deterministic non-administrative shortcut is retained, it must emit the same raw request envelope shape used by provider-backed tool calls and then enter the shared validation path before proposal creation, approval matching, execution, or append-only tool-event persistence.

### Validation and Canonicalization Contract
- Validation happens before any tool executes and before approval matching is evaluated for governed tools.
- Validation must be shared across deterministic and LLM-originated tool paths so the same request shape yields the same canonical arguments.
- Canonicalization must operate on validated typed data, not raw input dictionaries.
- Canonical argument serialization must remain:
  - deterministic
  - ASCII-safe
  - key-order stable
  - bounded to the validated schema-defined fields
- Extras behavior in this slice is explicit:
  - fixed-shape schemas reject unknown fields fail-closed
  - open-key schemas must define exactly which value types are allowed and which reserved keys are forbidden
- `remote_exec` canonical arguments must exclude backend-owned execution envelope metadata and include only approval-relevant invocation arguments from the validated open-key schema.
- Approval matching, proposal hashing, proposal-packet rendering, and exact-match enforcement must all use canonical arguments produced after schema validation.
- For governed tools, exact approval identity must also include `tool_schema_name` and `tool_schema_version` so schema changes cannot silently reuse approvals created under older argument semantics.
- The chosen extras behavior and schema-version behavior must be consistent between provider-requested tools, deterministic tool paths, governance proposal creation, and execution-time approval enforcement.
- The runtime must distinguish between:
  - raw untrusted tool-call input
  - validated typed request data
  - canonical validated arguments used for approvals, proposal identity, and audit
- This slice may preserve the existing raw `ToolRequest.arguments` shape for compatibility, but graph execution must create one graph-owned validated-call representation before any approval lookup, proposal creation, or tool invocation occurs.
- The validated-call representation must carry at minimum:
  - `capability_name`
  - `tool_schema_name`
  - `tool_schema_version`
  - validated typed request object or equivalent typed payload
  - `canonical_arguments_json`
  - `canonical_arguments_hash`
- Tool events and audit records may persist both bounded raw input and canonical validated arguments when helpful, but canonical validated arguments are the only arguments that may participate in approval identity, proposal hashing, or governed execution decisions.

### Tool Execution Contract
- `src/graphs/nodes.py` remains the only component that executes tools.
- Execution flow in this slice must be:
  - bind visible tools from the registry
  - validate raw tool arguments against the bound tool schema
  - canonicalize validated arguments
  - enforce approval requirements using canonical validated arguments
  - invoke the tool with the validated request object or canonical validated payload
  - persist tool event, audit, assistant response, and any proposal artifacts
- Tool implementations must not duplicate policy checks or schema parsing that belong to the graph and registry contracts, except for narrow runtime assertions about required infrastructure such as node-runner availability.
- Governed tool requests such as `remote_exec` must create proposals and exact-match approvals using canonical validated arguments only.
- If a deterministic non-administrative shortcut produces a tool request, it must enter this same execution flow before any proposal creation or execution occurs.
- A validation failure must never create an approval record, activate a resource, or execute a tool.
- The graph may keep compatibility with existing raw request contracts, but it must be the component that materializes the validated-call representation and passes typed validated input into the tool implementation.
- Tool implementations must not be responsible for stripping provider-visible extras, removing backend-owned envelope fields, or re-canonicalizing approval arguments internally.

### Error Handling Contract
- Invalid tool arguments must become bounded assistant-visible guidance rather than generic runtime crashes.
- The runtime must distinguish at least these semantic failure families:
  - provider returned malformed tool-call structure
  - provider named an unavailable tool
  - provider returned arguments that fail schema validation
  - deterministic user request mapped to a tool but failed schema validation
  - approval missing for a schema-valid governed request
- Schema-validation failures must be recorded durably in existing tool-event or observability paths with bounded field-level detail safe for user and operator surfaces.
- Assistant-visible guidance for validation failure should explain what is missing or invalid without exposing internal stack traces or secret data.
- Malformed semantic output from the provider remains a safe-completion path, not an unsafe execution path.
- Transport-class provider failures remain governed by Spec 009 failure semantics and are not redefined by this spec.
- If raw provider output is preserved in a failure record, it must be bounded and must remain non-authoritative; any canonical argument fields recorded for that failure must come from successful backend validation only.

### Backward-Compatibility Contract
- The runtime must preserve the current high-level behavior of:
  - safe local tool execution for valid requests
  - outbound intent creation for valid `send_message`
  - governance proposal creation for valid but unapproved `remote_exec`
  - deterministic `approve` and `revoke` handling
- The main behavioral change in this slice is stricter validation and clearer error reporting, not a new approval model or new tool-authority boundary.
- Existing append-only persistence and worker-owned execution responsibilities remain unchanged.
- The slice may add a new graph-owned validated-call helper type and a bound-tool exposure carrier on `AssistantState`, but it must preserve compatibility with the existing high-level `ModelTurnResult`, `ToolRequest`, and worker-owned execution flow from Specs 002 and 009.

## Clarifications
- The canonical implementation path for this slice is a minimal additive one rather than a full runtime redesign.
- Governed schema identity is sourced from `resource_versions.resource_payload` and may be mirrored elsewhere additively, but replay and exact approval matching must remain semantically anchored to that payload.
- One backend-owned `BoundToolExposure`-style per-turn carrier on `AssistantState` is the authoritative source for:
  - prompt-visible tool guidance
  - provider-facing tool schema export
  - graph-time validation and canonicalization lookup
- `available_tools: list[str]` may remain as a compatibility filter for adapters, but it is not sufficient by itself to define tool semantics in this slice.
- The shared runtime flow is:
  - receive raw tool-call input from a provider or deterministic shortcut
  - resolve the matching bound-tool exposure
  - validate into a typed request object
  - build canonical validated arguments
  - perform approval lookup or proposal creation using schema identity plus canonical validated arguments
  - invoke the tool with typed validated input plus backend-owned runtime metadata
- For `remote_exec`, the provider-visible request shape in this slice is one flat open-key map of approval-relevant invocation arguments whose values are limited to scalar JSON values.
- Backend-owned execution envelope metadata for `remote_exec`, including `tool_call_id` and `execution_attempt_number`, must be injected by the backend after validation and must not appear in provider-visible schemas, canonical approval arguments, governed proposal identity, or approval matching keys.

## Runtime Invariants
- Every tool that executes in provider-backed mode is validated against one explicit backend-owned input schema first.
- Deterministic approval and revocation commands are classified before provider interpretation.
- Approval identity is computed from canonical validated arguments, not raw model output.
- Prompt-visible tool guidance, provider-facing tool schemas, and execution-time validation are derived from the same bound tool definition for a turn.
- Provider-facing tool schemas and execution-time validation remain aligned.
- Unknown or malformed tool arguments never execute.
- Tool execution, approval creation, audit persistence, and outbound intent creation remain backend-owned responsibilities.

## Security Constraints
- Schema validation must fail closed on malformed or type-confused provider output.
- Provider-generated arguments remain untrusted input even when they conform to a provider-native schema.
- Governed capabilities must continue to require exact active approval after validation and canonicalization.
- Validation error payloads must be bounded and sanitized before entering logs, diagnostics, or assistant-visible responses.
- This slice must not introduce provider-authored enforcement logic, implicit capability escalation, or client-side approval shortcuts.

## Operational Considerations
- Tool-schema metadata should be easy to inspect in tests and diagnostics so schema drift is visible.
- The implementation should keep provider-specific tool-schema translation isolated so additional providers can reuse the same backend-owned schema contract later.
- Error metrics and structured logs should distinguish validation failures from provider transport failures and approval denials.
- Canonical-argument stability is operationally important because it affects proposal reuse, approval matching, and audit interpretation across retries.
- The implementation should preserve local and CI testability without live provider access by keeping schema validation and provider translation separately unit-testable.

## Acceptance Criteria
- Each executable tool in `src/tools/local_safe.py`, `src/tools/messaging.py`, and `src/tools/remote_exec.py` has one explicit typed input schema with deterministic validation and canonicalization behavior.
- `echo_text` and `send_message` reject unknown fields fail-closed, while `remote_exec` uses one explicit open-key invocation schema with documented allowed value types and reserved-key exclusions.
- `src/tools/registry.py` exposes provider-consumable schema metadata and runtime validation hooks from the same canonical tool definition.
- Prompt construction, provider-native tool definitions, and execution-time validation all consume the same bound-tool exposure contract for a given turn, so tool descriptions and argument semantics cannot drift across those surfaces.
- Provider-facing tool schemas are derived from backend-owned typed tool schemas rather than lightweight prompt hints or provider-local hard-coding.
- Governed approval identity includes canonical validated arguments plus schema identity metadata, so schema-version changes do not silently reuse prior approvals.
- Deterministic `approve` and `revoke` commands are still handled by backend classification before any model interpretation.
- Any deterministic non-administrative shortcut still flows through the same shared tool-request validation and execution path as provider-backed tool requests.
- A schema-valid governed tool request without exact active approval creates a proposal using canonical validated arguments, and a schema-invalid request does not create a proposal.
- Invalid LLM tool arguments produce safe assistant-visible guidance plus durable bounded observability rather than generic execution failure.
- Approval matching, proposal hashing, and audit payloads use canonical validated arguments consistently across deterministic and LLM-originated tool paths.
- Existing append-only transcript, artifact, audit, worker, and outbound-intent ownership boundaries remain intact.

## Test Expectations
- Unit tests for typed tool-schema validation on valid, missing, extra, malformed, and type-confused arguments
- Unit tests for canonical argument serialization stability across field order and equivalent validated inputs
- Unit tests proving schema-version changes for governed tools alter approval identity deterministically without changing `typed_action_id`
- Unit tests for registry exposure proving provider-facing schemas and execution-time validation come from the same canonical definition
- Unit tests proving prompt-visible tool guidance, provider-facing schema export, and runtime validation metadata are all derived from the same bound-tool exposure entry for a turn
- Unit tests for provider translation proving typed schemas become bounded provider tool definitions without provider-local schema drift
- Unit tests proving provider adapters reject coarse malformed tool envelopes while graph-time schema validation remains the authoritative decision point for field validity and canonicalization
- Policy tests proving deterministic `approve` and `revoke` classification still bypass provider interpretation
- Policy and runtime tests proving deterministic non-administrative shortcuts, if present, are normalized into the same validation and execution path rather than a separate special-case path
- Runtime tests proving schema-invalid tool requests do not execute, do not create governed approvals, and produce bounded assistant-visible guidance
- Runtime tests proving schema-valid governed requests use canonical validated arguments for proposal creation and exact approval matching
- Runtime tests proving backend-owned execution envelope metadata does not enter provider-visible schemas or approval hashes
- Integration tests proving current valid `echo_text`, `send_message`, and approved `remote_exec` flows continue to work under the stricter schema contract
