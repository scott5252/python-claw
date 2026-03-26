# Tasks 010: Typed Tool Schemas and Hybrid Intent Control

## Alignment Decisions

### Gap 1: Governed approval identity does not yet reflect schema identity
Options considered:
- Option A: keep `tool_schema_name` and `tool_schema_version` prompt-only and exclude them from durable approval identity
- Option B: persist schema identity only in audit metadata while keeping approval identity based on `typed_action_id` plus canonical arguments
- Option C: keep `typed_action_id` stable, but include `tool_schema_name` and `tool_schema_version` in governed proposal, approval, replay, and exact-match lookup identity
- Option D: encode schema version into `typed_action_id` and treat every schema revision as a new typed action

Selected option:
- Option C

### Gap 2: The authoritative validation boundary between provider and graph is underspecified
Options considered:
- Option A: let provider adapters perform full schema validation and pass only validated requests to the graph
- Option B: duplicate full schema validation in both provider adapters and graph execution
- Option C: skip provider-side screening entirely and let the graph handle all malformed tool-call envelopes
- Option D: allow provider adapters to reject only coarse malformed envelopes while keeping graph-time schema validation authoritative

Selected option:
- Option D

### Gap 3: Deterministic non-administrative shortcuts are not explicitly normalized into the shared schema pipeline
Options considered:
- Option A: keep deterministic non-administrative shortcuts such as `send ...` as special-case execution paths
- Option B: remove deterministic non-administrative shortcuts entirely and force all non-admin requests through model interpretation
- Option C: keep deterministic non-administrative shortcuts only if they emit the same raw `ToolRequest` shape that then flows through shared validation, canonicalization, approval, and execution logic
- Option D: expand deterministic parsing to all tool intents and reduce the provider path to text-only answers

Selected option:
- Option C

### Gap 4: `remote_exec` extras policy and backend-owned execution envelope fields are not explicit enough
Options considered:
- Option A: reject every unknown field for every tool, including `remote_exec`
- Option B: allow arbitrary extra fields for every tool and let tool bodies ignore what they do not need
- Option C: make extras policy schema-owned: fixed-shape tools reject extras, while `remote_exec` uses one explicit open-key scalar JSON map with reserved-key exclusions and keeps backend envelope metadata out of provider-visible arguments
- Option D: defer `remote_exec` typed-schema work and leave it dictionary-based for this slice

Selected option:
- Option C

## Tasks

1. Confirm the current tool, graph, provider, governance, and policy seams in `src/tools/registry.py`, `src/graphs/nodes.py`, `src/providers/models.py`, `src/policies/service.py`, `src/sessions/repository.py`, and `src/tools/typed_actions.py` so Spec 010 tightens existing contracts instead of introducing a parallel execution path.
2. Add high-risk unit tests first for typed request-model validation covering `echo_text`, `send_message`, and `remote_exec`, including valid inputs, missing required fields, extra fields, wrong types, empty-string edge cases where relevant, deterministic validation-error shapes, and fail-closed unknown-field rejection for fixed-shape schemas.
3. Add high-risk `remote_exec` schema tests first proving the open-key invocation schema accepts only the allowed scalar JSON value types, rejects reserved backend-owned keys, rejects nested or non-scalar values, and excludes execution-envelope metadata from canonical arguments.
4. Add high-risk canonicalization and approval-identity tests first for the shared validation and serialization path in `src/policies/service.py` or a new shared helper, proving equivalent validated inputs serialize identically, field order does not affect hashes, schema-invalid inputs never produce approval-identity hashes, and governed approval identity changes when `tool_schema_name` or `tool_schema_version` changes without changing `typed_action_id`.
5. Add high-risk policy and hybrid-intent tests first proving deterministic `approve <proposal_id>` and `revoke <proposal_id>` classification still bypasses provider interpretation, and any deterministic non-administrative shortcut such as `send ...` is normalized into the same raw `ToolRequest` flow used by provider-backed requests instead of a separate pre-validation execution path.
6. Add high-risk registry, prompt, and provider-schema tests first proving each bound tool exposes one canonical schema definition and one bound-tool exposure shape that runtime validation, prompt guidance, and provider-facing tool export all consume, with no prompt-only schema drift or hard-coded argument assumptions.
7. Add high-risk governance identity tests first proving governed schema identity is sourced from the governed resource payload, mirrored fields do not become an independent source of truth, and replayed approvals continue to match only when schema identity and canonical validated arguments both match.
8. Extend `src/tools/registry.py` so `ToolDefinition` includes schema identity, schema export, validation, canonicalization, bounded usage guidance, and typed invocation hooks while preserving policy-filtered binding behavior.
9. Update `src/graphs/state.py` with the smallest additive type changes needed for one canonical bound-tool exposure contract carried on `AssistantState`, plus one graph-owned validated-call or equivalent post-validation helper type and any bounded tool-error helper types, while preserving `ToolRequest`, `ToolEvent`, and `ModelTurnResult` compatibility where possible.
10. Implement the typed request model and invocation changes in `src/tools/local_safe.py` so `echo_text` consumes validated typed input, rejects unknown fields fail-closed, and no longer parses raw dictionaries inside the tool body.
11. Implement the typed request model and invocation changes in `src/tools/messaging.py` so `send_message` consumes validated typed input, rejects unknown fields fail-closed, preserves trimmed outbound-intent behavior for valid requests, and returns bounded validation guidance for invalid ones.
12. Implement the typed request model and invocation changes in `src/tools/remote_exec.py` so provider-visible invocation arguments come only from the validated flat scalar open-key schema, canonical argument serialization and approval identity consume only canonical validated arguments, reserved runtime-owned envelope fields stay outside provider-visible arguments, and backend-owned execution metadata is injected after validation rather than supplied by the provider.
13. Update `src/tools/typed_actions.py` and the related approval-identity helpers so `typed_action_id` stays stable across schema revisions while governed exact-match identity can include `tool_schema_name` and `tool_schema_version` additively.
14. Refactor shared canonicalization and approval-key construction in `src/policies/service.py` so approval lookup, exact-match enforcement, and any deterministic non-administrative shortcut normalization operate on validated canonical arguments plus schema identity where required instead of raw untrusted dictionaries.
15. Update `src/graphs/nodes.py` so every tool request from deterministic or provider-backed paths is treated as untrusted raw input until bound-schema validation succeeds, then converted into the graph-owned validated-call representation before approval checks, proposal creation, tool invocation, or append-only tool-event persistence.
16. Add the safe-completion path in `src/graphs/nodes.py` for schema-invalid tool requests so the assistant returns bounded guidance, observability records the validation failure, no tool executes, no approval lookup hits occur for invalid governed requests, and schema-invalid governed requests do not create proposals.
17. Refactor provider tool-schema export and rule-based shortcut handling in `src/providers/models.py` so provider-facing tool definitions come from the canonical registry-owned bound-tool exposure contract carried on `AssistantState`, provider-side screening stays limited to coarse malformed-envelope checks such as unknown tool names, non-object arguments, and request-count overflow, and no provider path becomes the authoritative source of field-level validation or canonicalization.
18. Update `src/graphs/prompts.py` and any prompt-tool metadata helpers so human-readable tool guidance is rendered from the same bound-tool exposure entry used for provider schema export and runtime validation lookup, without keeping `argument_guidance` as a second schema authority.
19. Extend `src/sessions/repository.py` and `src/observability/audit.py` only as needed so append-only tool events, governance proposal payloads, approval packets, replayed approval identity, and audit records can persist bounded schema-validation metadata, canonical validated arguments, `tool_schema_name`, and `tool_schema_version`, with the governed resource payload remaining the authoritative durable source for governed schema identity.
20. Extend `src/observability/failures.py` and `src/observability/logging.py` so provider malformed envelopes, backend schema-validation failures, approval denials, and transport-class provider failures are classified distinctly and remain bounded for user, operator, and retry surfaces.
21. Add runtime tests proving schema-valid safe-tool requests still execute, schema-valid `send_message` requests still create outbound intents, schema-valid approved `remote_exec` requests still execute through the current governed path, schema-valid but unapproved `remote_exec` requests still create proposals using canonical validated arguments plus schema identity, and backend-owned execution-envelope metadata never leaks into provider-visible schemas or approval identity.
22. Add failure-path tests proving malformed provider tool payloads, unavailable tool names, non-object arguments, deterministic shortcut requests that fail schema validation, and schema-invalid provider arguments all complete safely without execution, without proposal creation for invalid governed requests, without accidental worker-retry inflation, and with bounded assistant-visible guidance.
23. Add backward-compatibility integration tests proving append-only transcript, tool-audit, proposal, approval, replay, manifest, and outbound-intent flows remain intact after typed schema enforcement lands, with `approve` and `revoke` still bypassing provider interpretation.
24. Finish with verification that provider-backed runtime still uses backend-owned schema definitions, deterministic administrative commands still bypass the model, any deterministic non-administrative shortcut routes into the shared validation and execution pipeline, and no tool execution path remains that accepts raw unvalidated arguments directly from provider output.
