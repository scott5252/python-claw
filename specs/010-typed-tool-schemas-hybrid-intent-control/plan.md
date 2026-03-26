# Plan 010: Typed Tool Schemas and Hybrid Intent Control

## Target Modules
- `src/tools/registry.py`
- `src/tools/local_safe.py`
- `src/tools/messaging.py`
- `src/tools/remote_exec.py`
- `src/tools/typed_actions.py`
- `src/graphs/state.py`
- `src/graphs/nodes.py`
- `src/graphs/prompts.py`
- `src/providers/models.py`
- `src/policies/service.py`
- `src/sessions/repository.py`
- `src/observability/audit.py`
- `src/observability/failures.py`
- `src/observability/logging.py`
- `src/config/settings.py` only if schema-related settings or validation toggles are required
- `tests/`

## Success Conditions
- Every executable tool in this slice exposes one explicit backend-owned typed input schema with deterministic validation and canonicalization.
- `echo_text` and `send_message` reject unknown fields fail-closed, while `remote_exec` uses one explicit open-key invocation schema with documented allowed scalar JSON value types and reserved-key exclusions.
- One canonical bound-tool exposure shape feeds prompt-visible tool guidance, provider-native tool definitions, and runtime validation for a turn.
- The canonical bound-tool exposure shape is carried on `AssistantState` for the turn and is not reconstructed later from prompt-only hints or from `available_tools: list[str]` alone.
- Provider adapters receive backend-authored schemas and perform only coarse malformed-envelope screening; `src/graphs/nodes.py` remains the authoritative validation and canonicalization boundary.
- Governed approval identity includes canonical validated arguments plus `tool_schema_name` and `tool_schema_version`, while `typed_action_id` remains stable across schema revisions.
- Governed schema identity is sourced durably from the governed resource payload on `resource_versions.resource_payload`, with any mirrored fields elsewhere treated as additive only.
- Deterministic `approve` and `revoke` handling remains in `src/policies/service.py`, and any deterministic non-administrative shortcut is normalized into the same shared tool-request validation and execution path as provider-backed requests.
- Schema-invalid requests never execute, never create approvals, and never create governed proposals.
- The graph materializes one validated-call representation before approval lookup, proposal creation, or invocation, while preserving compatibility with the existing `ToolRequest` and `ModelTurnResult` contracts where practical.

## Migration Order
1. Prefer no schema migration if existing append-only tool-event, manifest, and observability payloads can already store bounded validation metadata.
2. If durable storage lacks a bounded place for schema-validation details needed by the spec, add one additive migration only after the runtime contracts are defined:
   - schema name or version
   - canonical arguments JSON or hash
   - validation error code
   - bounded invalid-field metadata
3. Do not change governance tables or approval state machines in this slice.

## Implementation Shape
- Preserve the current architecture boundary:
  - `src/tools/registry.py` owns tool-definition metadata
  - `src/graphs/nodes.py` owns authoritative validation, canonicalization, approval enforcement, and execution sequencing
  - `src/policies/service.py` owns deterministic control-intent classification and approval matching
  - `src/providers/models.py` translates backend-owned schemas into provider-native tool definitions
- Replace loose argument handling incrementally rather than rewriting the whole runtime:
  - define typed request models first
  - extend `ToolDefinition` to surface schema metadata, validation hooks, canonicalization hooks, and typed invocation
  - introduce one bound-tool exposure shape derived from the registry after policy filtering
  - switch prompt guidance and provider schema export to that bound-tool exposure
  - update graph execution to validate and canonicalize before any approval lookup, proposal creation, or invocation
  - keep the existing message, proposal, audit, and outbound intent flows intact
- Keep Spec 009 prompt ownership intact:
  - `src/graphs/prompts.py` may still describe tools for conversational guidance
  - prompt guidance must be rendered from the same bound-tool exposure used for provider schema export and runtime validation lookup
  - provider-executable tool schemas must come from the canonical registry schema contract, not prompt-only hints
- Keep hybrid intent control explicit:
  - deterministic `approve` and `revoke` parsing runs before provider use
  - deterministic non-administrative shortcuts may remain only if they emit the same raw tool-request shape consumed by the shared validation and execution pipeline
  - natural-language requests continue through the provider-backed path when not deterministically classified
  - backend validation remains authoritative for both deterministic and provider-originated execution paths
- Standardize canonicalization once:
  - validate raw input into typed request objects
  - serialize validated objects deterministically
  - use that serialization for approval lookup, proposal packets, hashes, and audit payloads
  - include `tool_schema_name` and `tool_schema_version` in governed approval identity inputs without changing `typed_action_id`
- Keep the post-validation contract explicit without forcing a full runtime redesign:
  - preserve raw request compatibility where helpful
  - create one graph-owned validated-call helper after schema validation succeeds
  - pass typed validated input to tool implementations
  - persist canonical validated arguments for approval and governance identity
- Tighten error handling without changing run ownership:
  - schema failures should complete safely with assistant guidance
  - provider transport failures should keep Spec 009 retry semantics
  - provider malformed tool envelopes should be rejected before execution but should not become the source of field-level validity rules
  - schema-invalid governed requests should not create proposals

## Contracts to Implement
### Tool Schema and Registry Contracts
- `src/tools/registry.py`
  - extend `ToolDefinition` to include `capability_name`, `description`, `input_schema`, `schema_version`, `validate(...)`, `canonicalize(...)`, and `invoke(...)`
  - keep per-turn binding and policy-filtered visibility unchanged
  - define one canonical bound-tool exposure shape with prompt guidance, provider-facing schema export, schema identity, and backend validation or canonicalization handles
  - ensure provider-facing schema export and runtime validation use the same canonical definition
- `src/tools/local_safe.py`
  - define the typed request model for `echo_text`
  - reject unknown fields fail-closed
  - remove raw argument parsing from the tool body
- `src/tools/messaging.py`
  - define the typed request model for `send_message`
  - reject unknown fields fail-closed
  - keep outbound intent creation behavior unchanged for valid inputs
- `src/tools/remote_exec.py`
  - define the typed request model for `remote_exec`
  - implement one explicit open-key invocation schema rather than an untyped dictionary convention
  - allow only approval-relevant scalar JSON values in provider-visible arguments
  - exclude backend-owned execution envelope metadata from provider-visible schemas, canonical arguments, and approval identity
  - ensure approval lookup and runtime execution consume canonical validated arguments only
- `src/tools/typed_actions.py`
  - keep `typed_action_id` stable across schema revisions
  - align typed-action lookup and governed approval identity inputs with canonical validated arguments plus schema identity where necessary

### Runtime and Policy Contracts
- `src/graphs/state.py`
  - grow tool-definition, bound-tool exposure, validated-call, or tool-error helper types additively if the runtime needs explicit schema-validation result structures
  - preserve `ToolRequest`, `ToolEvent`, and `ModelTurnResult` compatibility where possible
- `src/graphs/nodes.py`
  - treat provider and deterministic tool arguments as untrusted raw input until bound-schema validation succeeds
  - validate raw tool arguments against the bound schema before execution
  - canonicalize validated arguments before approval checks and proposal creation
  - use graph-time validation as the authoritative source for required fields, field types, defaults, extras policy, and canonicalization
  - persist bounded validation failures as safe semantic failures
  - keep assistant message persistence, tool audits, governed proposal creation, and outbound-intent behavior backend-owned
- `src/policies/service.py`
  - preserve deterministic `approve` and `revoke` classification
  - ensure any deterministic non-administrative shortcut emits the same request shape expected by the shared validation path
  - move approval hashing and exact-match lookup to depend on canonical validated arguments plus schema identity rather than raw dictionaries where needed
  - ensure no schema-invalid governed request can produce an approval lookup hit or a new proposal

### Provider and Prompt Contracts
- `src/providers/models.py`
  - replace ad hoc provider tool-schema construction with registry-owned schema export from the bound-tool exposure contract
  - consume bound-tool exposure entries carried on `AssistantState` as the authoritative provider-schema source, while keeping `available_tools` as a compatibility filter only
  - keep malformed-tool-call handling bounded and safe
  - limit provider-side screening to coarse malformed-envelope checks such as unknown tool names, non-object arguments, and request-count overflow
  - distinguish provider malformed structure from backend schema-validation failure for observability
- `src/graphs/prompts.py`
  - render conversational tool guidance from the same bound-tool exposure entry used for provider schema export and runtime validation lookup
  - avoid creating a second schema authority in prompt-only metadata or `argument_guidance`

### Persistence and Observability Contracts
- `src/sessions/repository.py`
  - persist canonical validated arguments, schema identity, and bounded validation metadata through existing append-only tool-event or governance paths
  - preserve existing proposal and approval packet flows
- `src/observability/audit.py`
  - record schema name, schema version, canonical argument identity, and validation-failure detail where bounded and useful
- `src/observability/failures.py` and `src/observability/logging.py`
  - classify and emit provider malformed envelopes, schema-validation failures, approval denials, and provider transport failures distinctly

## Risk Areas
- Provider-facing schemas drifting away from execution-time validation if two different schema-generation paths exist
- Approval mismatches caused by hashing raw tool arguments or omitting schema identity from governed approval matching
- Approval replay ambiguity if schema identity is mirrored in multiple places without one durable authoritative source
- Silent acceptance of unknown extra fields that alter approval identity or tool semantics
- `remote_exec` open-key schemas accidentally admitting non-scalar or reserved runtime-owned fields
- Overloading prompt tool guidance until it becomes a second conflicting schema source
- Letting provider adapters become the source of truth for field validity and canonicalization
- Treating schema validation failures as infrastructure failures and accidentally triggering retries
- Breaking backward-compatible valid flows for `echo_text`, `send_message`, or approved `remote_exec`
- Letting deterministic control commands fall back to the model path and weakening governance safety
- Allowing deterministic non-administrative shortcuts to bypass the shared validation and proposal pipeline

## Rollback Strategy
- Keep schema changes additive and tool-by-tool so the old runtime contracts can be restored if needed.
- Preserve deterministic policy classification and existing governance tables throughout rollout.
- If provider schema export causes regressions, disable provider tool exposure while keeping backend schema validation in place for deterministic flows.
- If durable validation metadata proves too disruptive, keep the bounded event contract in observability first and add durable storage later without changing validation semantics.

## Test Strategy
- Unit:
  - typed request-model validation for each tool
  - fixed-shape unknown-field rejection for `echo_text` and `send_message`
  - `remote_exec` open-key allowed-value and reserved-key enforcement
  - canonical serialization stability
  - schema-version approval identity changes without `typed_action_id` drift
  - governed approval replay using schema identity sourced from governed resource payload
  - registry schema exposure, prompt guidance, and provider export alignment through one bound-tool exposure entry
  - provider coarse-screening behavior versus graph-authoritative validation behavior
  - deterministic control-intent classification
  - approval lookup behavior with canonical validated arguments plus schema identity
- Runtime:
  - valid safe-tool execution
  - valid `send_message` outbound intent creation
  - valid `remote_exec` with exact approval
  - schema-invalid tool request safe completion
  - schema-valid but unapproved governed request proposal creation
  - schema-invalid governed request creates neither approval nor proposal
  - backend-owned execution envelope metadata stays out of provider-visible schemas and approval hashes
  - graph-owned validated-call representation is created before approval lookup or invocation
- Integration:
  - provider-backed tool turn with schema-valid arguments
  - malformed provider tool payload safe completion
  - deterministic `approve` and `revoke` bypass of provider interpretation
  - deterministic non-administrative shortcut normalization into the shared validation and execution path, if any such shortcut exists
  - append-only audit and proposal behavior unchanged except for richer validation metadata

## Constitution Check
- Gateway-first and worker-owned execution remain unchanged.
- Tool execution stays backend-owned and append-only-audited.
- Approval-before-activation remains enforced through exact backend checks.
- Hybrid intent control narrows risk by keeping administrative commands deterministic.
- The slice strengthens validation without moving authority to the model or provider layer.
