# Tasks 015: Sub-Agent Delegation and Child Session Orchestration

## Implementation Readiness Review

- The spec is implementable on the current codebase because Specs 001 through 014 already established the required foundation:
  - Spec 001 made `sessions` and append-only `messages` the durable conversation boundary
  - Specs 002, 003, and 010 made model actions flow through typed tools, policy checks, and exact approval scope
  - Specs 004 and 011 centralized context assembly and bounded derived context inputs
  - Spec 005 made `execution_runs` idempotent by trigger identity and worker-owned across retry
  - Spec 006 preserved sandbox isolation by `agent_id`
  - Specs 007 through 013 reinforced append-only delivery, diagnostics, and real-time execution without introducing a second orchestrator
  - Spec 014 added durable `agent_profiles`, session ownership, `session_kind`, `parent_session_id`, and per-run model or policy or tool profile persistence
- The current runtime seams line up well with Spec 015:
  - `src/sessions/service.py` already owns inbound session or message creation and run enqueueing
  - `src/jobs/repository.py` already provides idempotent `create_or_get_execution_run(...)`
  - `src/jobs/service.py` is still the single worker-owned execution path and is the right place to react to child-run start, completion, retry, and terminal failure
  - `src/context/service.py` is the existing home for bounded context assembly and should gain an explicit delegation packager rather than parent transcript reach-through
  - `src/tools/registry.py`, `src/graphs/nodes.py`, and `src/policies/service.py` already provide the typed-tool seam where `delegate_to_agent` belongs
- The highest-risk implementation failures to prevent are:
  - creating child sessions through routing-key lookup and colliding with canonical primary sessions
  - duplicating child sessions, child runs, continuation messages, or continuation runs when parent tools or child completion handlers retry
  - allowing parent approvals, active resources, or sandbox scope to bleed into child sessions
  - allowing delegated child runs to reply directly to users instead of returning through durable parent continuation
  - letting parent runs wait synchronously for child completion and breaking lane ordering or worker ownership
  - over-sharing parent transcript state instead of packaging bounded, auditable context
  - wiring delegation logic directly into graph nodes or worker branches instead of centralizing lifecycle ownership in one service
- The tasks below are ordered to prove idempotency, isolation, and queue-order invariants first, then add the durable data model, then add the `DelegationService` orchestration seam, then wire tool, worker, diagnostics, and integration behavior through the existing architecture.

## Tasks

1. Confirm the current delegation integration seams in `src/config/settings.py`, `src/db/models.py`, `src/domain/schemas.py`, `src/sessions/repository.py`, `src/sessions/service.py`, `src/jobs/repository.py`, `src/jobs/service.py`, `src/context/service.py`, `src/graphs/state.py`, `src/graphs/nodes.py`, `src/graphs/prompts.py`, `src/tools/registry.py`, `src/policies/service.py`, `src/observability/diagnostics.py`, `apps/gateway/api/admin.py`, and `apps/gateway/deps.py` so Spec 015 extends the current session, queue, worker, tool, and diagnostics architecture rather than introducing a second orchestration path.
2. Add high-risk repository and migration tests first proving `delegations` and `delegation_events` enforce uniqueness on `(parent_run_id, parent_tool_call_correlation_id)`, preserve append-only event history, and support the required parent, child, status, and timeline lookup indexes.
3. Add high-risk service tests first proving delegation creation is idempotent under retry or concurrent re-entry, creates exactly one child session, one child trigger message, one child run, and one initial event set, and never duplicates those rows when the same parent tool-call correlation id is replayed.
4. Add high-risk service tests first proving parent continuation enqueueing is idempotent per `delegation_id`, creates exactly one internal continuation message and exactly one `delegation_result` run, and suppresses duplicates when child completion handling is retried or races.
5. Add high-risk policy tests first proving delegation fails closed when the tool is not visible, `delegation_enabled` is false, the child agent is not allowlisted, the child agent is disabled, linked child profiles are disabled, depth exceeds the configured maximum, or active-concurrency limits are already exhausted.
6. Add high-risk worker tests first proving child-run retry reuses the same `execution_runs` row and same `delegations` row, child retry does not create a second child session, child start marks the delegation `running`, child dead-letter marks the delegation `failed`, and cancellation suppresses late parent continuation even if the child eventually completes.
7. Add high-risk worker or integration tests first proving child-produced outbound intents never dispatch directly to external channels and remain only as durable internal artifacts for audit or bounded parent-result extraction.
8. Add high-risk service tests first proving child result payload construction is deterministic and bounded, preferring the final child assistant message and falling back to bounded tool outcomes, artifacts, or failure summaries when no final assistant message exists.
9. Extend `src/config/settings.py` so `policy_profiles` gain explicit delegation controls with fail-closed validation for `delegation_enabled`, `max_delegation_depth`, `allowed_child_agent_ids`, `max_active_delegations_per_run`, and `max_active_delegations_per_session`, including normalization, deduplication, and non-negative or positive bounds as appropriate.
10. Add explicit settings-backed delegation packaging limits in `src/config/settings.py` for transcript turns, retrieval or memory items, attachment excerpts, and serialized bytes or token-estimate budget, with positive bounds and default-safe validation.
11. Preserve default-safe behavior in settings by keeping delegation disabled unless both the parent policy profile enables delegation and the parent tool profile explicitly allowlists the `delegate_to_agent` capability.
12. Extend `src/db/models.py` and add a migration under `migrations/versions/` for the additive delegation durability contract:
   - add `delegations` with parent, child, status, depth, packaged-context, result-payload, failure, cancellation, and timing fields
   - add `delegation_events` as an append-only audit table
   - extend validated string domains additively for `messages.role=system` if needed and `execution_runs.trigger_kind` values `delegation_child` and `delegation_result`
   - add all required foreign keys, unique constraints, and lookup indexes
13. Add internal delegation read or write schemas in `src/domain/schemas.py` or a focused `src/delegations/schemas.py` module for:
   - delegation creation inputs and bounded result payloads
   - delegation detail, event, and page responses for admin or diagnostics reads
   - any explicit packaged-context contract shared across service and tests
14. Introduce a focused `src/delegations/` package and implement `src/delegations/repository.py` as the durable delegation persistence seam, including helpers to:
   - create or get a delegation by `(parent_run_id, parent_tool_call_correlation_id)`
   - append ordered delegation events
   - count active delegations by parent run and parent session
   - fetch delegation detail by id, parent run, child run, child session, and agent
   - mark delegation `running`, `completed`, `failed`, or `cancelled`
   - create or get the parent continuation message and parent continuation run idempotently
15. Keep delegation event storage append-only and ensure repository helpers never mutate or delete historical child-session, child-message, child-run, or event rows.
16. Extend `src/sessions/repository.py` with an explicit internal child-session creation helper that does not rely on routing-tuple canonical lookup, requires `session_kind=child`, requires `parent_session_id`, sets `owner_agent_id=child_agent_id`, and persists a synthetic unique `session_key` such as `child:{parent_session_id}:{delegation_id}`.
17. Extend `src/sessions/service.py` with a child-session creation path that derives `channel_kind`, `channel_account_id`, `scope_kind`, `peer_id`, `group_id`, and `scope_name` from the parent session while ensuring child sessions are never created through the normal `get_or_create_session(...)` routing flow.
18. Extend `src/context/service.py` with an explicit delegation packaging helper that produces both a structured `context_payload_json` and a deterministic child trigger message body from the same bounded parent snapshot rather than overloading the normal single-session `assemble(...)` path.
19. Make the delegation packaging helper include at minimum the parent session id, parent message id, parent run id, parent agent id, child agent id, delegation depth, delegation kind, task text, and a bounded recent-transcript excerpt or summary snapshot, while optionally including bounded retrieval, memory, and already-visible attachment context from the parent run.
20. Centralize delegation package limits in settings or one clearly-owned configuration surface so transcript turns, retrieval or memory item counts, attachment excerpts, and serialized bytes or token-estimate limits are explicit, testable, and fail closed when exceeded.
21. Ensure parent-to-child packaging never transfers full parent transcripts by default, active approvals, unrelated approval packets, reusable active resources, or hidden provider-native prompt state.
22. Implement `src/delegations/service.py` as the sole `DelegationService` lifecycle owner for policy validation, depth computation, concurrency checks, context packaging, child-session creation, child trigger message append, child-run enqueue, event recording, child completion handling, terminal failure handling, cancellation, and parent continuation enqueue.
23. In `DelegationService`, validate delegation creation inside one transaction boundary that confirms the parent run, parent session, parent owner, and child agent are consistent; enforces allowlist, enabled-profile, depth, and active-concurrency checks; creates or gets the delegation row; creates the child session; appends the child trigger message; creates or gets the child run; and appends initial lifecycle events atomically.
24. Define delegation depth from the durable session chain so `primary` sessions start at depth `0`, child sessions increment from their parent, and nested delegation is denied once the computed child depth would exceed `max_delegation_depth`.
25. Define active delegations exactly as rows with `status IN ('queued', 'running')` and keep the run-level and session-level concurrency checks serialized inside the same creation transaction so concurrent parent tool calls cannot over-create delegations.
26. Extend `src/policies/service.py` with explicit delegation-policy evaluation helpers rather than burying delegation logic inside generic visibility checks, while preserving the existing exact approval-match behavior from Spec 003.
27. Add a typed tool factory for `delegate_to_agent` with schema-validated required fields `child_agent_id`, `task_text`, and `delegation_kind`, plus optional bounded `expected_output` and `notes`, and register it in `src/tools/registry.py` as a normal capability subject to tool-profile and policy-profile filtering.
28. Make the `delegate_to_agent` tool implementation call `DelegationService` rather than writing sessions, messages, or runs directly, and return only a bounded asynchronous acknowledgement payload that the parent can safely mention without waiting for child completion.
29. Extend `src/graphs/state.py` runtime structures if needed so tool execution and later parent continuation handling can carry delegation-related metadata without fabricating transcript state or bypassing normal tool-event persistence.
30. Refactor `src/graphs/nodes.py` so `delegate_to_agent` proposals, validation failures, execution outcomes, and tool-result persistence behave like other typed tools, but parent runs never synchronously wait for child completion inside the claimed parent run.
31. Update `src/graphs/prompts.py` tool guidance so the model understands delegation is an explicit typed capability, asynchronous, bounded, and unavailable unless exposed through the bound tool set.
32. Extend `src/jobs/repository.py` only additively so child runs and parent continuation runs reuse `create_or_get_execution_run(...)` with `trigger_kind=delegation_child` and `trigger_kind=delegation_result`, preserving one durable run row per logical trigger identity and parent-lane ordering semantics from Spec 005.
33. Refactor `src/jobs/service.py` so the existing worker-owned `process_next_run(...)` path reacts to delegation-linked runs without splitting into a second execution path:
   - on child-run start, mark delegation `running`, set `started_at`, and append a lifecycle event
   - on child-run retry, preserve logical `running` status and append retry visibility
   - suppress user-visible outbound dispatch for child runs even if they persist outbound intents
   - on child-run terminal failure or dead-letter, mark delegation `failed`, store bounded `failure_detail`, and append failure events
   - on child-run completion, call `DelegationService` to build a deterministic bounded result payload and enqueue the parent continuation exactly once
34. Keep parent continuation runs on `lane_key=parent_session_id` and ensure `delegation_result` work does not bypass or overtake already-queued parent-session work.
35. Add a bounded parent-continuation message contract that appends one internal `messages` row to the parent session with `role=system`, `external_message_id=null`, and a reserved `sender_id` namespace such as `system:delegation_result:{child_agent_id}` so continuation state is durable, auditable, and clearly non-channel-originated.
36. Extend parent context assembly so `delegation_result` runs can see the structured child result in a bounded way through durable state while still not inlining the full child transcript into the parent context window by default.
37. Add a best-effort internal or admin cancellation path on `DelegationService` that marks queued or running delegations `cancelled`, persists `cancel_reason`, appends cancellation events, cancels queued child runs when possible under the current run model, treats already running child runs as logically cancelled without requiring in-flight interruption, and suppresses any later parent continuation if the child completes after cancellation.
38. Extend `src/observability/diagnostics.py` so session and run diagnostics can surface delegation linkage, parent and child ids, depth, status, timing, retry visibility, failure detail, and whether parent continuation was queued or suppressed.
39. Extend `apps/gateway/api/admin.py` and any supporting service methods with operator-protected delegation read surfaces for `GET /sessions/{session_id}/delegations`, `GET /delegations/{delegation_id}`, `GET /delegations/{delegation_id}/events`, and `GET /agents/{agent_id}/delegations` or an equivalent diagnostics query.
40. Add repository and admin read coverage proving child sessions remain durable and inspectable after child failure or cancellation, and delegation read paths reconstruct who delegated to whom, when the child started or finished, whether retries occurred, and whether continuation was queued or intentionally suppressed.
41. Add graph and tool tests proving `delegate_to_agent` is absent when not bound, schema validation errors are recorded like other tool failures, policy-denied delegation fails closed, and the parent run returns promptly after queueing child work instead of blocking.
42. Add service and integration tests proving successful end-to-end delegation from parent turn through child session creation, child run completion, parent continuation enqueue, bounded parent follow-up context exposure without full child transcript promotion, and direct child outbound suppression.
43. Add service and integration tests proving child terminal failure records bounded failure detail and remains fully auditable without fabricating parent continuation state, and proving cancellation before child completion suppresses late continuation while preserving all already-written child artifacts.
44. Add integration tests proving nested delegation works only within configured depth, child sessions remain policy and sandbox isolated from their parents, parent approvals do not transfer, and child agents must satisfy their own enabled-profile and approval requirements independently.
45. Update any relevant operator-facing docs only after behavior lands so delegation enablement, policy allowlisting, diagnostics reads, parent or child isolation rules, and current non-goals around prompt-only helper agents or synchronous waiting match the implemented feature.
46. Finish with a final implementation review against `specs/015-sub-agent-delegation-and-child-session-orchestration/spec.md` and `specs/015-sub-agent-delegation-and-child-session-orchestration/plan.md`, confirming the delivered work preserves the gateway-first, worker-owned, append-only session and run architecture; routes delegation only through the typed tool layer; creates exactly one durable child session and one durable delegation record per logical request; keeps parent and child approvals, tools, policies, and sandboxes isolated; suppresses direct child outbound delivery; re-enters the parent only through durable continuation state; preserves queue ordering on both child and parent lanes; and fails closed when delegation settings, policy, or service wiring are absent or incomplete.
47. Update `apps/gateway/deps.py` and any related construction paths so one injected `DelegationService` instance is available to tool execution, worker lifecycle handling, admin reads, and diagnostics code without introducing process-global hidden state or a second orchestration entry path.

## Final Task Review

- Coverage against the spec is complete:
  - durable delegation records and append-only lifecycle events
  - explicit policy-profile and tool-profile gating for `delegate_to_agent`
  - internal child-session creation separate from routing-derived primary sessions
  - bounded parent-to-child packaging and bounded child-to-parent result return
  - deterministic bounded child-result extraction
  - direct child outbound suppression
  - child execution and parent continuation on the existing `execution_runs` lifecycle
  - cancellation, retry, failure, diagnostics, and admin-read behavior
- Coverage against the current codebase is concrete:
  - tasks anchor the new orchestration in one `DelegationService` instead of scattering logic through graph nodes or ad hoc worker branches
  - tasks reuse `src/sessions/`, `src/jobs/`, `src/context/`, `src/tools/`, `src/policies/`, and admin or diagnostics seams that already exist today
  - tasks explicitly preserve Spec 005 trigger-idempotent run creation and Spec 014 durable agent ownership semantics
- The task list should support successful implementation of Spec 015 because it forces the team to prove the hardest invariants first:
  - child-session and continuation idempotency under retry
  - exact parent or child isolation for approvals, tools, policy, and sandbox scope
  - bounded context packaging instead of transcript leakage
  - asynchronous parent re-entry through durable transcript and run state only
  - operator visibility into delegation lineage, retries, timing, and failure causes
