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
  - `src/graphs/nodes.py` owns validation, approval enforcement, and execution sequencing
  - `src/policies/service.py` owns deterministic control-intent classification and approval matching
  - `src/providers/models.py` translates backend-owned schemas into provider-native tool definitions
- Replace loose argument handling incrementally rather than rewriting the whole runtime:
  - define typed request models first
  - extend `ToolDefinition` to surface schema metadata and validation hooks
  - switch provider schema export to the new canonical definitions
  - update graph execution to validate and canonicalize before any approval lookup or invocation
  - keep the existing message, proposal, audit, and outbound intent flows intact
- Keep Spec 009 prompt ownership intact:
  - `src/graphs/prompts.py` may still describe tools for conversational guidance
  - provider-executable tool schemas must come from the canonical registry schema contract, not prompt-only hints
- Keep hybrid intent control explicit:
  - deterministic `approve` and `revoke` parsing runs before provider use
  - natural-language requests continue through the provider-backed path when not deterministically classified
  - backend validation remains authoritative for both deterministic and provider-originated execution paths
- Standardize canonicalization once:
  - validate raw input into typed request objects
  - serialize validated objects deterministically
  - use that serialization for approval lookup, proposal packets, hashes, and audit payloads
- Tighten error handling without changing run ownership:
  - schema failures should complete safely with assistant guidance
  - provider transport failures should keep Spec 009 retry semantics
  - schema-invalid governed requests should not create proposals

## Contracts to Implement
### Tool Schema and Registry Contracts
- `src/tools/registry.py`
  - extend `ToolDefinition` to include schema metadata, validation, canonicalization, and typed invocation
  - keep per-turn binding and policy-filtered visibility unchanged
  - ensure provider-facing schema export and runtime validation use the same canonical definition
- `src/tools/local_safe.py`
  - define the typed request model for `echo_text`
  - remove raw argument parsing from the tool body
- `src/tools/messaging.py`
  - define the typed request model for `send_message`
  - keep outbound intent creation behavior unchanged for valid inputs
- `src/tools/remote_exec.py`
  - define the typed request model for `remote_exec`
  - ensure approval lookup and runtime execution consume canonical validated arguments only
- `src/tools/typed_actions.py`
  - align typed-action lookup with the new canonical validated-argument shape where necessary

### Runtime and Policy Contracts
- `src/graphs/state.py`
  - grow tool-definition or tool-error helper types additively if the runtime needs explicit schema-validation result structures
  - preserve `ToolRequest`, `ToolEvent`, and `ModelTurnResult` compatibility where possible
- `src/graphs/nodes.py`
  - validate raw tool arguments against the bound schema before execution
  - canonicalize validated arguments before approval checks and proposal creation
  - persist bounded validation failures as safe semantic failures
  - keep assistant message persistence, tool audits, governed proposal creation, and outbound-intent behavior backend-owned
- `src/policies/service.py`
  - preserve deterministic `approve` and `revoke` classification
  - move approval hashing and exact-match lookup to depend on canonical validated arguments rather than raw dictionaries where needed
  - ensure no schema-invalid governed request can produce an approval lookup hit or a new proposal

### Provider and Prompt Contracts
- `src/providers/models.py`
  - replace ad hoc provider tool-schema construction with registry-owned schema export
  - keep malformed-tool-call handling bounded and safe
  - distinguish provider malformed structure from backend schema-validation failure for observability
- `src/graphs/prompts.py`
  - keep conversational tool guidance aligned with the new typed schemas
  - avoid creating a second schema authority in prompt-only metadata

### Persistence and Observability Contracts
- `src/sessions/repository.py`
  - persist canonical validated arguments and bounded validation metadata through existing append-only tool-event or governance paths
  - preserve existing proposal and approval packet flows
- `src/observability/audit.py`
  - record schema version, canonical argument identity, and validation-failure detail where bounded and useful
- `src/observability/failures.py` and `src/observability/logging.py`
  - classify and emit schema-validation failures distinctly from provider transport failures and approval denials

## Risk Areas
- Provider-facing schemas drifting away from execution-time validation if two different schema-generation paths exist
- Approval mismatches caused by hashing raw tool arguments instead of validated canonical arguments
- Silent acceptance of unknown extra fields that alter approval identity or tool semantics
- Overloading prompt tool guidance until it becomes a second conflicting schema source
- Treating schema validation failures as infrastructure failures and accidentally triggering retries
- Breaking backward-compatible valid flows for `echo_text`, `send_message`, or approved `remote_exec`
- Letting deterministic control commands fall back to the model path and weakening governance safety

## Rollback Strategy
- Keep schema changes additive and tool-by-tool so the old runtime contracts can be restored if needed.
- Preserve deterministic policy classification and existing governance tables throughout rollout.
- If provider schema export causes regressions, disable provider tool exposure while keeping backend schema validation in place for deterministic flows.
- If durable validation metadata proves too disruptive, keep the bounded event contract in observability first and add durable storage later without changing validation semantics.

## Test Strategy
- Unit:
  - typed request-model validation for each tool
  - canonical serialization stability
  - registry schema exposure and provider export alignment
  - deterministic control-intent classification
  - approval lookup behavior with canonical validated arguments
- Runtime:
  - valid safe-tool execution
  - valid `send_message` outbound intent creation
  - valid `remote_exec` with exact approval
  - schema-invalid tool request safe completion
  - schema-valid but unapproved governed request proposal creation
- Integration:
  - provider-backed tool turn with schema-valid arguments
  - malformed provider tool payload safe completion
  - deterministic `approve` and `revoke` bypass of provider interpretation
  - append-only audit and proposal behavior unchanged except for richer validation metadata

## Constitution Check
- Gateway-first and worker-owned execution remain unchanged.
- Tool execution stays backend-owned and append-only-audited.
- Approval-before-activation remains enforced through exact backend checks.
- Hybrid intent control narrows risk by keeping administrative commands deterministic.
- The slice strengthens validation without moving authority to the model or provider layer.
