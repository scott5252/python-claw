# Plan 015: Sub-Agent Delegation and Child Session Orchestration

## Target Modules
- `src/config/settings.py`
- `src/db/models.py`
- `src/domain/schemas.py`
- `src/agents/service.py`
- `src/sessions/repository.py`
- `src/sessions/service.py`
- `src/jobs/repository.py`
- `src/jobs/service.py`
- `src/context/service.py`
- `src/graphs/state.py`
- `src/graphs/nodes.py`
- `src/graphs/prompts.py`
- `src/tools/registry.py`
- `src/policies/service.py`
- `src/observability/diagnostics.py`
- `apps/gateway/api/admin.py`
- `apps/gateway/deps.py`
- `migrations/versions/`
- `tests/`

## Success Conditions
- Delegation exists only as the typed `delegate_to_agent` tool and is invisible unless both tool profile and policy profile allow it.
- Every successful delegation request creates exactly one durable `delegations` row, one durable child `sessions` row with `session_kind=child`, one child trigger `messages` row, and one child `execution_runs` row.
- Delegation creation is idempotent on `(parent_run_id, parent_tool_call_correlation_id)` and never duplicates child sessions or child runs during worker retry.
- Child execution stays on the existing worker-owned `execution_runs` lifecycle with `trigger_kind=delegation_child`.
- Child runs cannot directly dispatch user-visible outbound delivery even if they emit outbound intent artifacts.
- Child completion updates durable delegation state and re-enters the parent session through exactly one internal continuation message plus exactly one `delegation_result` run.
- Child completion derives `result_payload_json` through one deterministic bounded extractor rather than ad hoc transcript scraping.
- Child terminal failure updates durable delegation state, stores bounded failure detail, and remains fully auditable without duplicating or fabricating parent continuation state.
- Parent continuation runs execute on the parent session lane and preserve existing queue ordering rather than introducing a priority bypass.
- Parent and child policy, approval, tool, and sandbox scopes remain isolated.
- Operators can inspect delegation lineage, timing, retry visibility, and failure details through admin or diagnostics surfaces.

## Current Codebase Constraints From Specs 001-014
- Spec 001 made `sessions` and append-only `messages` the canonical conversation store, so child orchestration must extend those tables rather than create a second transcript path.
- Spec 002 and Spec 010 already route all model-side actions through typed tools, validated inputs, and policy-aware registry binding; delegation must plug into that seam rather than add prompt-only helper behavior.
- Spec 003 keeps approvals exact to `(session_id, agent_id)` and fail-closed; child sessions therefore cannot inherit parent approvals or active resources.
- Spec 004 centralized context assembly in `src/context/service.py`, but that service currently assembles only from one session; delegation needs an explicit packaging path for bounded parent-to-child context and bounded child-result exposure back into the parent session.
- Spec 005 and the current `src/jobs/repository.py` use one durable `execution_runs` row per logical trigger identity with retry on the same row, which is a strong fit for child-run and parent-continuation idempotency.
- Spec 006 already keys sandbox resolution off `agent_id`, so child work can stay isolated if the child run persists the delegated agent as its owner.
- Specs 007 through 013 added attachments, outbox jobs, delivery state, and diagnostics, so delegation needs to preserve append-only transcript truth while avoiding automatic full child-transcript promotion into the parent context.
- Spec 014 already introduced `sessions.owner_agent_id`, `sessions.session_kind`, `sessions.parent_session_id`, and per-run model or policy or tool profile persistence; 015 should build directly on those fields instead of redesigning ownership.
- Current code already has the essential seams:
  - `SessionRepository.get_or_create_session(...)` supports `session_kind` and `parent_session_id`
  - `JobsRepository.create_or_get_execution_run(...)` is idempotent on trigger identity
  - `AgentProfileService.resolve_binding_for_session(...)` and `resolve_binding_for_run(...)` already produce per-agent execution bindings
  - `ToolRegistry.bind_tools(...)` and `PolicyService.is_tool_visible(...)` already govern capability exposure
  - `RunExecutionService.process_next_run(...)` is the single worker-owned execution path
- Current gaps that the implementation must close:
  - no delegation tables or repository helpers
  - no internal child-session creation path separate from routing-derived sessions
  - no bounded delegation context packager
  - no parent continuation or child completion re-entry flow
  - no diagnostics or admin reads for delegation lineage

## Migration Order
1. Add delegation durability first:
   - `delegations`
   - `delegation_events`
2. Add required foreign keys, uniqueness, and lookup indexes:
   - unique `(parent_run_id, parent_tool_call_correlation_id)`
   - parent session and parent run lookups
   - child session and child run lookups
   - status and updated-at lookup
   - event paging lookups
3. Extend any enums or validated string domains additively as needed for:
   - `messages.role=system` if role validation is currently too narrow in code paths
   - `execution_runs.trigger_kind` values `delegation_child` and `delegation_result`
4. Add repository and service helpers before wiring runtime tool execution so delegation creation and completion semantics are explicit and testable.
5. Add settings and policy-profile validation for delegation controls before exposing the tool in any tool profile.
6. Wire the typed tool and worker lifecycle integration next:
   - delegation creation during parent tool execution
   - child status updates during worker transitions
   - parent continuation enqueue on child completion
7. Finish with admin or diagnostics surfaces and full success or failure or retry or cancellation coverage.

## Implementation Shape
- Keep delegation additive to the current architecture:
  - no second orchestrator
  - no provider-native child spawning
  - no in-memory callback from child to parent
- Introduce one explicit `DelegationService` as the sole owner of:
  - delegation policy validation
  - child depth computation
  - active-concurrency checks
  - parent-to-child context packaging
  - delegation row creation
  - child session creation
  - child trigger message append
  - child run enqueue
  - lifecycle event recording
  - child completion or failure handling
  - cancellation handling
  - parent continuation enqueue
- Reuse existing persistence and execution seams instead of bypassing them:
  - `SessionRepository` still writes messages and sessions
  - `JobsRepository` still creates and advances runs
  - `RunExecutionService` still owns claimed-run execution
  - graph nodes still execute tools only through typed registry bindings
- Keep child and parent coupling bounded and auditable:
  - package only explicit bounded context into the child trigger
  - store that package in `context_payload_json`
  - store only a bounded structured child result in `result_payload_json`
  - append the parent continuation as a normal internal transcript row
- Preserve queue ordering:
  - child runs get `lane_key=child_session_id`
  - parent continuation runs get `lane_key=parent_session_id`
  - no separate fast lane for delegation results

## Workstreams
### 1. Settings and Policy Controls
- Extend `PolicyProfileConfig` in `src/config/settings.py` with:
  - `max_delegation_depth`
  - `allowed_child_agent_ids`
  - optional `max_active_delegations_per_run`
  - optional `max_active_delegations_per_session`
- Add explicit delegation packaging settings in `src/config/settings.py` for:
  - transcript turn cap
  - retrieval or memory item cap
  - attachment excerpt cap
  - serialized bytes or token-estimate cap
- Validate these fields fail closed:
  - depth is non-negative
  - child-agent allowlist is normalized and deduplicated
  - concurrency limits are positive when set
  - packaging limits are positive and explicit when delegation packaging is enabled
- Keep default behavior disabled by default:
  - `delegation_enabled=False`
  - no agent sees delegation unless the tool profile also explicitly allowlists `delegate_to_agent`

### 2. Durable Data Model and Repository Contracts
- Add `DelegationRecord` and `DelegationEventRecord` in `src/db/models.py`.
- Add repository helpers, preferably in `src/sessions/repository.py` unless a small `src/delegations/` package is introduced:
  - create or get delegation by `(parent_run_id, parent_tool_call_correlation_id)`
  - count active delegations by parent run and parent session
  - list delegations by session, run, child session, child run, and agent
  - append delegation events
  - get delegation detail with child and parent linkage
  - mark delegation running, completed, failed, cancelled
  - create or get the parent continuation message keyed to `delegation_id`
  - create or get the parent continuation run keyed to `trigger_kind=delegation_result`, `trigger_ref=delegation_id`
- Preserve append-only behavior:
  - `delegation_events` is append-only
  - `messages` only gets new internal system rows
  - existing user-visible transcript rows are never mutated

### 3. Child Session Creation Path
- Add an explicit internal child-session creation method in `src/sessions/service.py` and `src/sessions/repository.py` rather than routing through normal canonical session lookup.
- The child-session helper should:
  - derive `channel_kind`, `channel_account_id`, `scope_kind`, `peer_id`, `group_id`, and `scope_name` from the parent session
  - set `session_kind=child`
  - set `parent_session_id=parent_session_id`
  - set `owner_agent_id=child_agent_id`
  - use a synthetic unique `session_key` such as `child:{parent_session_id}:{delegation_id}`
- Reject any attempt to create a child session through the normal routing key path.

### 4. Delegation Context Packaging
- Extend `src/context/service.py` with an explicit delegation packaging helper rather than overloading the normal single-session `assemble(...)` contract.
- The packaging helper should produce:
  - a bounded structured payload stored in `context_payload_json`
  - a deterministic child trigger message body derived from the same payload
- Package contents should include:
  - parent session id
  - parent message id
  - parent run id
  - parent agent id
  - child agent id
  - delegation depth
  - delegation kind
  - task text
  - optional expected output or notes
  - bounded recent transcript excerpt and or summary snapshot
  - bounded retrieval or memory snippets already assembled for the parent run
  - bounded attachment references or extracted text already available to the parent run
- Package limits should be settings-backed or clearly centralized:
  - transcript turns cap
  - retrieval or memory item cap
  - attachment excerpt cap
  - serialized bytes or token-estimate cap
- Keep child context isolated:
  - do not embed full parent transcript by default
  - do not transfer active approvals
  - do not include hidden provider-native prompt state

### 5. Typed Tool and Graph Integration
- Add a new typed tool factory for `delegate_to_agent`.
- Register it in `src/tools/registry.py` and expose it only through normal profile-aware binding.
- Add a schema-validated input model with required fields:
  - `child_agent_id`
  - `task_text`
  - `delegation_kind`
- Optional fields:
  - `expected_output`
  - `notes`
- The tool implementation should not create child runs directly; it should delegate to `DelegationService`.
- The tool result should be a bounded acknowledgement payload suitable for the parent run to communicate that delegation was queued asynchronously.
- In `src/graphs/nodes.py`:
  - persist the tool proposal and tool result like any other tool
  - avoid synchronous waiting for child completion
  - keep parent response generation asynchronous-friendly so the run can finish after delegation is queued
- In `src/graphs/prompts.py`, update any tool guidance so the model understands delegation is asynchronous, bounded, and typed.

### 6. Delegation Policy Enforcement
- Extend `PolicyService` with explicit delegation checks instead of burying them inside generic visibility logic.
- Validate all of the following before delegation creation:
  - parent tool visibility allows `delegate_to_agent`
  - parent policy profile has `delegation_enabled=True`
  - requested child agent is allowlisted by the parent policy profile
  - requested child agent exists and is enabled
  - child agent resolves to valid enabled linked profiles
  - computed child depth does not exceed `max_delegation_depth`
  - active-concurrency limits are not exceeded for the parent run or parent session
- Keep the concurrency check in the same transaction as delegation creation so two concurrent tool calls cannot both pass and over-create.
- Define active delegations exactly as rows with `status IN ('queued', 'running')`.

### 7. Child Run Execution Lifecycle
- Reuse `JobsRepository.create_or_get_execution_run(...)` for the child run with:
  - `session_id=child_session_id`
  - `message_id=child_message_id`
  - `agent_id=child_agent_id`
  - child binding profile keys
  - `trigger_kind=delegation_child`
  - `trigger_ref=delegation_id`
  - `lane_key=child_session_id`
- Update `RunExecutionService.process_next_run(...)` to recognize delegation-linked runs without creating a second worker path.
- On child run start:
  - mark delegation `running`
  - set `started_at`
  - append a `delegation_events` lifecycle record
- On child run retry:
  - keep delegation status logically `running`
  - append an event that preserves retry visibility
- Child runs must be treated as non-delivery runs in this slice:
  - if child execution persists outbound intents, runtime dispatch must suppress external channel delivery
  - the persisted artifacts remain available for audit, diagnostics, and bounded parent-result extraction
- On child run terminal failure or dead-letter:
  - mark delegation `failed`
  - store bounded `failure_detail`
  - append failure event
  - do not enqueue the normal parent continuation path for that failed child run in this slice

### 8. Child Completion and Parent Continuation
- Add a child-completion handler owned by `DelegationService`.
- When a child run completes, the service should:
  - serialize on the delegation row
  - build bounded `result_payload_json` from a deterministic extractor that prefers the final assistant message and falls back to bounded child artifacts, tool outcomes, or failure summaries
  - check whether the delegation was already cancelled
  - if cancelled, record an ignored-completion event and stop
  - otherwise create or look up exactly one internal continuation message in the parent session
  - create or look up exactly one parent follow-up run
  - persist `parent_result_message_id` and `parent_result_run_id` atomically
  - mark delegation `completed`
  - append completion events
- The continuation message should use:
  - `role=system`
  - `external_message_id=null`
  - reserved `sender_id` such as `system:delegation_result:{child_agent_id}`
- The parent follow-up run should use:
  - `session_id=parent_session_id`
  - `message_id=parent_result_message_id`
  - `agent_id=parent_agent_id`
  - the persisted parent binding keys from the original parent session owner
  - `trigger_kind=delegation_result`
  - `trigger_ref=delegation_id`
  - `lane_key=parent_session_id`
- Update parent context assembly so `delegation_result` runs see the structured result in a bounded way without inlining the full child transcript.

### 9. Cancellation Semantics
- Add a best-effort internal or admin cancellation method on `DelegationService`.
- Define best-effort cancellation concretely for this slice:
  - queued child runs should transition to `cancelled` when the current run model allows it
  - already running child runs are marked logically cancelled at the delegation layer but do not require in-flight graph interruption
  - any later completion from a cancelled child run must not enqueue parent continuation
- Cancellation should:
  - mark delegation `cancelled`
  - persist `cancel_reason`
  - append an audit event
  - suppress future parent continuation enqueue
- For queued child runs:
  - add repository support to mark the run cancelled when still claimable if feasible under the current run state model
- For already running child runs:
  - allow the current attempt to finish
  - ignore late completion when the delegation is already logically cancelled
- Never delete child sessions, child messages, child runs, or delegation events.

### 10. Admin and Diagnostics Surfaces
- Extend `src/domain/schemas.py` with:
  - delegation detail response
  - delegation event response
  - delegation page response
- Add operator-protected read paths, likely in `apps/gateway/api/admin.py`:
  - `GET /sessions/{session_id}/delegations`
  - `GET /delegations/{delegation_id}`
  - `GET /delegations/{delegation_id}/events`
  - `GET /agents/{agent_id}/delegations` or equivalent diagnostics query
- Extend `src/observability/diagnostics.py` so run detail can surface:
  - delegation id if the run is parent or child linked
  - parent and child ids
  - delegation status
  - timing fields
  - parent continuation presence or suppression
  - child retry visibility from child run plus `delegation_events`

## Recommended Module Layout
- Add a new `src/delegations/` package if the logic starts to sprawl across sessions or jobs:
  - `src/delegations/repository.py`
  - `src/delegations/service.py`
  - `src/delegations/schemas.py` only if a local internal schema module helps
- If the team prefers to avoid a new package in this slice, keep the public orchestration owner as `DelegationService` but still centralize the implementation in one place rather than scattering lifecycle code across graph nodes, jobs, and sessions.

## Transaction Boundaries
- Delegation creation transaction:
  - validate parent run and parent session ownership
  - enforce policy and concurrency limits
  - create or get `delegations` row
  - create child session
  - append child trigger message
  - create or get child run
  - append initial events
- Child-running transition:
  - mark child run running through `JobsRepository`
  - update delegation status to `running` if not already set
  - append lifecycle event
- Child-completion transaction:
  - lock delegation row
  - persist `result_payload_json`
  - create or get parent continuation message
  - create or get parent continuation run
  - store parent continuation foreign keys
  - update delegation terminal status and timestamps
  - append completion events
- Cancellation transaction:
  - mark delegation cancelled
  - persist cancel reason
  - append cancellation event
  - optionally cancel queued child run if still eligible

## Risk Areas
- Creating child sessions through the normal routing path would risk session-key collisions and accidental user-visible exposure.
- Failing to serialize on delegation creation or parent continuation could duplicate child sessions, continuation messages, or continuation runs.
- Allowing the parent run to wait synchronously on the child would create lane deadlocks and break the existing worker ownership model.
- Over-sharing parent context would violate bounded-context and approval-isolation requirements.
- Reusing parent approvals or active resources in the child session would break Spec 003 exact-scope guarantees.
- Storing only child run status without high-level delegation status would make operator diagnostics confusing, especially across retry.
- Forgetting to keep parent continuation on the parent lane would create out-of-order execution relative to other parent-session work.
- Letting graph nodes mutate delegation state directly instead of calling a service would make retry and idempotency correctness fragile.

## Rollback Strategy
- Keep the schema additive:
  - new delegation tables
  - new trigger kinds
  - new admin reads
- Default to delegation-disabled behavior when settings or service wiring are absent.
- Keep existing session routing, worker processing, and non-delegation turns untouched so the feature can be disabled by:
  - removing `delegate_to_agent` from tool profiles
  - leaving `delegation_enabled=false`
- If parent continuation wiring is incomplete, fail closed by recording delegation failure rather than fabricating a parent reply path.

## Testing Strategy
- Migration tests:
  - delegation table creation and indexes
  - trigger-kind compatibility for `delegation_child` and `delegation_result`
- Repository tests:
  - idempotent delegation creation on `(parent_run_id, parent_tool_call_correlation_id)`
  - child session creation with synthetic key and correct parent linkage
  - active-delegation counting by run and session
  - idempotent parent continuation message and run creation
  - delegation event append and ordered readback
- Service tests:
  - policy denial for disabled delegation
  - policy denial for non-allowlisted child agent
  - policy denial for exceeded depth
  - policy denial for exceeded concurrency limits
  - successful delegation creation with expected child session, message, run, and event rows
  - child completion queues exactly one parent continuation
  - child completion replay does not duplicate parent continuation
  - cancellation suppresses late parent continuation
  - child terminal failure records bounded failure detail and audit visibility
- Worker tests:
  - child run marks delegation `running` on start
  - child retry keeps delegation logically `running` and appends retry visibility
  - child dead-letter marks delegation `failed`
  - parent `delegation_result` run stays on the parent lane and does not bypass queued earlier parent-session work
- Graph and tool tests:
  - `delegate_to_agent` is absent when not visible in the bound tool set
  - tool schema validation errors are recorded like other tool failures
  - parent turn does not synchronously wait for child completion
  - parent follow-up run sees bounded child result but not the full child transcript
- API and diagnostics tests:
  - session-level delegation listing
  - delegation detail and event read endpoints
  - agent-level delegation diagnostics
  - operator protections match existing admin expectations
- Integration tests:
  - end-to-end successful delegation from parent turn through child completion and parent follow-up
  - child retry path reusing the same child run row
  - cancellation before child completion
  - delegation failure visibility without duplicate continuations
  - nested child delegation within allowed depth and denial beyond configured depth

## Constitution Check
- Gateway-first and worker-owned execution are preserved because child work still flows through durable sessions, messages, and `execution_runs`.
- Transcript-first durability is preserved because both child trigger and parent continuation are append-only internal `messages` rows and delegation lineage is additive.
- Capability governance is preserved because delegation is a normal typed tool with explicit profile and policy gating, and parent approvals do not transfer.
- Context continuity is preserved because delegation packages bounded context instead of copying or merging full transcripts across sessions.
- Observability is preserved because operators get explicit delegation reads, event history, failure detail, and parent/child linkage.
