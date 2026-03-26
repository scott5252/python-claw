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
- Ensure provider adapters receive backend-authored tool schemas rather than lightweight argument hints only
- Preserve deterministic command parsing in `src/policies/service.py` for `approve` and `revoke`, and keep any similarly high-risk administrative intent out of model interpretation
- Validate all LLM-originated and deterministic tool arguments against the same backend-owned schema contract before execution
- Standardize canonical argument serialization after validation so approval matching, proposal hashing, audit records, and proposal packets stay stable
- Improve assistant-visible error handling for invalid tool arguments and malformed provider tool payloads
- Preserve backward-compatible runtime behavior for safe non-governed tools and governed proposal creation, while tightening validation and observability

## Data Model Changes
- No new canonical business-state tables are required for this slice.
- No governance lifecycle tables change in this slice.
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
- Tool implementations must receive typed validated request objects or a validated canonical payload produced from those objects, rather than raw unvalidated model output dictionaries.

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
- Tool visibility remains policy-filtered before a schema is exposed to the model.
- A tool omitted by policy must also be omitted from provider-facing tool schemas.
- The registry must not expose one schema to the provider and validate against a materially different schema at execution time.

### Provider Tool-Schema Contract
- `src/providers/models.py` must consume backend-owned tool schema metadata from the registry rather than inferring schemas from prompt hints or hard-coded assumptions.
- Provider-facing tool definitions in this slice must be derived from the canonical tool schema contract, not reconstructed ad hoc per provider.
- Provider adapters may translate the backend-owned schema into provider-native function or tool formats, but they must not become the authoritative source for required fields, types, defaults, or additional-property behavior.
- The provider translation layer must support at least:
  - object-shaped input schema
  - required vs optional field semantics
  - field descriptions
  - rejection of malformed non-object arguments before execution
- If a provider returns tool-call arguments that fail backend schema validation, the runtime must not execute the tool.

### Hybrid Intent-Control Contract
- `src/policies/service.py` remains authoritative for deterministic parsing of high-risk control intents.
- At minimum, the following user intents must continue to bypass model interpretation:
  - `approve <proposal_id>`
  - `revoke <proposal_id>`
- This slice may add more deterministic administrative classifications only if they are explicitly documented and tested, but it must not reduce the deterministic scope already implemented.
- Hybrid intent control in this slice means:
  - normal natural-language requests may be interpreted by the provider-backed LLM and routed into typed tool execution
  - high-risk control commands are classified deterministically before provider invocation
  - backend validation remains authoritative even for LLM-suggested tools
- The model may help interpret a normal user request such as “send this to the channel” into a tool call, but it may not decide whether approval commands, revocations, or exact approval matching semantics are valid.

### Validation and Canonicalization Contract
- Validation happens before any tool executes and before approval matching is evaluated for governed tools.
- Validation must be shared across deterministic and LLM-originated tool paths so the same request shape yields the same canonical arguments.
- Canonicalization must operate on validated typed data, not raw input dictionaries.
- Canonical argument serialization must remain:
  - deterministic
  - ASCII-safe
  - key-order stable
  - bounded to the validated schema-defined fields
- Approval matching, proposal hashing, proposal-packet rendering, and exact-match enforcement must all use canonical arguments produced after schema validation.
- Unknown or extra arguments must not silently alter approval identity. This slice must define one explicit behavior for extras:
  - either reject them fail-closed
  - or normalize them in a schema-defined way
- The chosen behavior must be consistent between provider-requested tools, deterministic tool paths, governance proposal creation, and execution-time approval enforcement.

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
- A validation failure must never create an approval record, activate a resource, or execute a tool.

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

### Backward-Compatibility Contract
- The runtime must preserve the current high-level behavior of:
  - safe local tool execution for valid requests
  - outbound intent creation for valid `send_message`
  - governance proposal creation for valid but unapproved `remote_exec`
  - deterministic `approve` and `revoke` handling
- The main behavioral change in this slice is stricter validation and clearer error reporting, not a new approval model or new tool-authority boundary.
- Existing append-only persistence and worker-owned execution responsibilities remain unchanged.

## Runtime Invariants
- Every tool that executes in provider-backed mode is validated against one explicit backend-owned input schema first.
- Deterministic approval and revocation commands are classified before provider interpretation.
- Approval identity is computed from canonical validated arguments, not raw model output.
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
- `src/tools/registry.py` exposes provider-consumable schema metadata and runtime validation hooks from the same canonical tool definition.
- Provider-facing tool schemas are derived from backend-owned typed tool schemas rather than lightweight prompt hints or provider-local hard-coding.
- Deterministic `approve` and `revoke` commands are still handled by backend classification before any model interpretation.
- A schema-valid governed tool request without exact active approval creates a proposal using canonical validated arguments, and a schema-invalid request does not create a proposal.
- Invalid LLM tool arguments produce safe assistant-visible guidance plus durable bounded observability rather than generic execution failure.
- Approval matching, proposal hashing, and audit payloads use canonical validated arguments consistently across deterministic and LLM-originated tool paths.
- Existing append-only transcript, artifact, audit, worker, and outbound-intent ownership boundaries remain intact.

## Test Expectations
- Unit tests for typed tool-schema validation on valid, missing, extra, malformed, and type-confused arguments
- Unit tests for canonical argument serialization stability across field order and equivalent validated inputs
- Unit tests for registry exposure proving provider-facing schemas and execution-time validation come from the same canonical definition
- Unit tests for provider translation proving typed schemas become bounded provider tool definitions without provider-local schema drift
- Policy tests proving deterministic `approve` and `revoke` classification still bypass provider interpretation
- Runtime tests proving schema-invalid tool requests do not execute, do not create governed approvals, and produce bounded assistant-visible guidance
- Runtime tests proving schema-valid governed requests use canonical validated arguments for proposal creation and exact approval matching
- Integration tests proving current valid `echo_text`, `send_message`, and approved `remote_exec` flows continue to work under the stricter schema contract
