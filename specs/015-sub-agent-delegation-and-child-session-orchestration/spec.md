# Spec 015: Sub-Agent Delegation and Child Session Orchestration

## Purpose
Add bounded, auditable specialist delegation so a primary assistant can create, track, and consume child-agent work without bypassing the existing gateway-first, worker-owned, append-only session and run architecture.

## Non-Goals
- Hidden prompt-only helper agents or provider-native model spawning outside the typed tool layer
- Replacing `sessions`, `execution_runs`, or the current worker queue with a second orchestration system
- Arbitrary fan-out or recursive delegation without explicit policy limits
- Human handoff, operator reassignment, or approval UX beyond existing admin and diagnostics surfaces
- Sharing the full parent transcript or parent active approvals with child agents by default
- Cross-session memory merging or automatic promotion of all child-session transcript content into the parent context window

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
- Spec 010
- Spec 011
- Spec 012
- Spec 013
- Spec 014

## Scope
- First-class durable delegation records linking parent session, parent message, parent run, child session, child run, parent agent, and child agent
- A typed delegation capability exposed through the tool registry and bound through profile-aware policy controls
- Child-session creation flows that extend `src/sessions/service.py` and `src/sessions/repository.py` instead of inventing a second session path
- Child-run enqueueing and execution flows that reuse `src/jobs/service.py`, `src/jobs/repository.py`, and the existing worker claim or retry lifecycle
- Bounded parent-to-child context packaging and explicit child-to-parent result return behavior
- Parent follow-up execution that re-enters the parent session through durable transcript state rather than in-memory callbacks
- Diagnostics and admin read surfaces for delegation lineage, lifecycle timing, retry state, and failure causes
- Tests covering successful delegation, child failure, child retry, cancellation, policy denial, and audit visibility

## Current-State Baseline
- `src/sessions/service.py` currently resolves or creates one session per routing tuple, appends the inbound user message, and queues one `execution_run` tied to that message.
- `src/sessions/repository.py` already supports `session_kind`, `parent_session_id`, and durable `owner_agent_id`, but only routing-driven primary-session creation is implemented today.
- `src/jobs/service.py` already owns the claimed run lifecycle, graph invocation, retry decisions, and final completion or failure transitions for `execution_runs`.
- `src/jobs/repository.py` already provides one durable run row per logical trigger identity, with retry handled on that same row rather than by creating new runs.
- `src/agents/service.py` can already resolve per-agent execution bindings, including agent-specific model, policy, and tool profile keys.
- `src/tools/registry.py`, `src/policies/service.py`, and `src/graphs/nodes.py` already provide the typed tool-binding seam and the policy-aware tool execution path that delegation must use.
- `src/context/service.py` currently assembles context from one session’s transcript and derived artifacts only; there is no bounded parent-to-child or child-to-parent context-transfer mechanism yet.
- No current table records delegation lineage, no current tool expresses delegation explicitly, and no current runtime flow resumes a parent session from child completion.

## Data Model Changes
- `delegations`
  - `id` primary key
  - `parent_session_id` non-null foreign key to `sessions.id`
  - `parent_message_id` non-null foreign key to `messages.id`
  - `parent_run_id` non-null foreign key to `execution_runs.id`
  - `parent_tool_call_correlation_id` non-null
  - `parent_agent_id` non-null
  - `child_session_id` non-null foreign key to `sessions.id`
  - `child_message_id` non-null foreign key to `messages.id`
  - `child_run_id` non-null foreign key to `execution_runs.id`
  - `child_agent_id` non-null foreign key to `agent_profiles.agent_id`
  - `parent_result_message_id` nullable foreign key to `messages.id`
  - `parent_result_run_id` nullable foreign key to `execution_runs.id`
  - `status` with values `queued`, `running`, `completed`, `failed`, `cancelled`
  - `depth` non-null integer
  - `delegation_kind` non-null stable classifier such as `research`, `coding`, `planning`, or `general`
  - `task_text` non-null bounded text sent to the child agent
  - `context_payload_json` non-null bounded packaged parent context sent to the child session
  - `result_payload_json` nullable structured child result summary returned to the parent path
  - `failure_detail` nullable
  - `cancel_reason` nullable
  - `created_at`
  - `queued_at`
  - `started_at` nullable
  - `completed_at` nullable
  - `updated_at`
  - required indexes
    - unique index on `delegations(parent_run_id, parent_tool_call_correlation_id)`
    - lookup index on `delegations(parent_session_id, created_at)`
    - lookup index on `delegations(parent_run_id, created_at)`
    - lookup index on `delegations(child_session_id, created_at)`
    - lookup index on `delegations(child_run_id)`
    - lookup index on `delegations(status, updated_at)`
- `delegation_events`
  - append-only audit table for lifecycle visibility
  - `id`
  - `delegation_id` non-null foreign key to `delegations.id`
  - `event_kind`
  - `status`
  - `actor_kind` with values such as `parent_run`, `child_run`, `system`, `operator`
  - `actor_ref` nullable
  - `payload_json`
  - `created_at`
  - required indexes
    - lookup index on `delegation_events(delegation_id, id)`
    - lookup index on `delegation_events(created_at)`
- `messages`
  - expand the runtime contract to allow additive internal system-trigger rows used for delegation continuation
  - no existing user-facing rows are mutated in place
- `execution_runs`
  - keep the existing retry model
  - add `trigger_kind` support for at least:
    - `delegation_child`
    - `delegation_result`
  - add lookup index on `execution_runs(trigger_kind, trigger_ref, created_at)` only if the current trigger identity index is insufficient for diagnostics

## Settings and Registry Changes
- Extend settings-backed `policy_profiles` from Spec 014 with explicit delegation controls:
  - `delegation_enabled` boolean, default `false`
  - `max_delegation_depth` integer, minimum `0`
  - `allowed_child_agent_ids` explicit allowlist
  - optional `max_active_delegations_per_run`
  - optional `max_active_delegations_per_session`
- Add a typed tool capability named `delegate_to_agent`
  - the capability name is part of the normal tool registry and tool profile allowlist system
  - agents that should never delegate must not see this tool
- The child agent’s own `tool_profile_key`, `policy_profile_key`, and sandbox resolution remain authoritative inside the child run
- Delegation policy must be the intersection of:
  - parent agent tool visibility
  - parent policy profile delegation flags
  - explicit child-agent allowlist
  - child agent enabled status
  - depth and concurrency bounds

## Contracts
### Delegation Tool Contract
- Delegation is allowed only through the typed `delegate_to_agent` tool.
- The tool must use schema-validated inputs. Required fields:
  - `child_agent_id`
  - `task_text`
  - `delegation_kind`
- Optional bounded fields may include:
  - `expected_output`
  - `notes`
- The model must not choose raw tool names or hidden agent identities outside registered capability and agent-profile validation.
- If the tool is unavailable in the bound tool set, delegation fails closed as a normal policy-denied tool request.

### Delegation Service Contract
- `DelegationService` or equivalent is the sole owner of delegation creation, child-session creation, child-run enqueueing, completion, failure, cancellation, and parent-result reentry.
- Delegation creation must happen inside one transaction boundary that:
  - validates parent run ownership and policy
  - creates the `delegations` row
  - creates the child session
  - appends the initial child trigger message
  - enqueues the child run
  - records the initial `delegation_events`
- The service must be idempotent per parent tool-call correlation identity so worker retry cannot create duplicate child sessions for the same logical delegation request.

### Child Session Contract
- Each delegation creates exactly one durable child session with `session_kind=child`.
- `child_session.parent_session_id` must equal the delegation’s `parent_session_id`.
- Child sessions are never resolved through the Spec 001 routing tuple.
- Child sessions must be created only through an explicit internal creation path, not `get_or_create_session(...)` on the parent routing key.
- The child session must:
  - inherit `channel_kind` and `channel_account_id` from the parent session for runtime compatibility
  - copy the parent session’s `scope_kind`, `peer_id`, `group_id`, and `scope_name` unless a narrower internal scope rule is introduced explicitly in implementation
  - set `owner_agent_id` to the delegated child agent
  - use a synthetic unique `session_key` such as `child:{parent_session_id}:{delegation_id}`
- Child sessions must be durable and inspectable even when the child run fails.

### Child Trigger Message Contract
- The child run must start from one durable transcript row in the child session.
- That row must be append-only and must contain the bounded packaged task given to the child agent.
- The child trigger message must not claim to be an external channel message:
  - `role=system`
  - `external_message_id=null`
  - `sender_id` uses a reserved internal namespace such as `system:delegation:{parent_agent_id}` so transcript rendering and diagnostics can classify it as non-user, non-channel-originated work
- The packaged child input may be human-readable text, structured JSON text, or a hybrid format, but it must be deterministic and auditable through stored transcript plus `context_payload_json`.

### Parent-To-Child Context Contract
- Parent context sharing is explicit and bounded.
- The packaged child context must include:
  - parent session id
  - parent message id
  - parent run id
  - parent agent id
  - delegation depth
  - task text
  - a bounded conversation summary or bounded recent-turn excerpt from the parent session
- Parent context sharing may also include:
  - the latest valid summary snapshot
  - bounded retrieval or memory snippets already assembled for the parent run
  - bounded attachment references or extracted attachment text already visible to the parent run
- Parent context sharing must not include by default:
  - the full parent transcript when it exceeds the configured delegation package limit
  - raw approval packets unrelated to the delegated task
  - parent active approvals as reusable child approvals
  - hidden provider-native prompt state
- The parent policy or packaging service must cap:
  - maximum packaged transcript turns
  - maximum packaged bytes or tokens
  - maximum attachment excerpts

### Child Execution Contract
- Child execution uses the existing worker-owned `execution_runs` lifecycle.
- The child run must:
  - use `session_id=child_session_id`
  - use `message_id=child_message_id`
  - use `agent_id=child_agent_id`
  - persist its own `model_profile_key`, `policy_profile_key`, and `tool_profile_key`
  - use `trigger_kind=delegation_child`
  - use `trigger_ref=delegation_id`
  - use `lane_key=child_session_id`
- Child run retry must reuse the same `execution_run` row and must not create a second delegation record or a second child session.
- When the child run transitions to running, the delegation status must become `running` and `started_at` must be set.
- Child sessions are internal execution boundaries in this slice:
  - child runs must not produce user-visible outbound delivery directly
  - if a child tool emits an outbound intent artifact, runtime dispatch for that child run must suppress channel delivery and preserve the artifact only for audit or diagnostics
  - only the parent continuation path may decide whether any user-visible response is ultimately sent

### Child Result Contract
- Delegation in this slice is asynchronous relative to the parent run.
- The parent run may acknowledge that delegation has started, but it must not synchronously block waiting for child completion inside the same claimed run.
- On child completion, the runtime must produce one structured `result_payload_json` containing at minimum:
  - `delegation_id`
  - `child_session_id`
  - `child_run_id`
  - `child_agent_id`
  - `status`
  - `summary_text`
  - optional bounded artifact references
  - optional failure or follow-up indicators
- The result builder must be deterministic and bounded:
  - prefer the child run's final assistant message as the source of `summary_text`
  - when no final assistant message exists, derive `summary_text` from bounded child tool outcomes, structured artifacts, or a bounded failure summary
  - the result builder must not require exporting or summarizing the full child transcript to produce `result_payload_json`
- The child result must be returned to the parent through durable state, not an in-memory callback:
  - append one internal continuation message to the parent session
  - enqueue one parent follow-up run with `trigger_kind=delegation_result` and `trigger_ref=delegation_id`
- The `delegations` row must store the created `parent_result_message_id` and `parent_result_run_id` once continuation is successfully enqueued.
- Parent continuation enqueueing must be idempotent per `delegation_id`.
- The child-completion path must, in one transaction boundary:
  - lock or otherwise serialize on the target `delegations` row
  - create or look up exactly one parent continuation message keyed to the delegation
  - create or look up exactly one parent follow-up run with `trigger_kind=delegation_result` and `trigger_ref=delegation_id`
  - persist `parent_result_message_id` and `parent_result_run_id` on the `delegations` row atomically with that enqueue outcome
- Retried or duplicated child completion handling must not append a second continuation message or enqueue a second parent follow-up run for the same delegation.
- The continuation message must use:
  - `role=system`
  - `external_message_id=null`
  - `sender_id` in a reserved internal namespace such as `system:delegation_result:{child_agent_id}`
- The continuation message must be clearly non-channel-originated and auditable.

### Parent Follow-Up Contract
- The parent follow-up run re-enters the normal graph path using the parent session.
- The parent follow-up run must use the existing parent session owner agent, not the child agent.
- Parent context assembly for a `delegation_result` run must expose the delegation result in a bounded way and must not automatically inline the entire child transcript.
- Parent follow-up runs participate in the same parent-session lane and queue ordering rules as other runs for that session.
- `delegation_result` runs must not bypass, overtake, or execute in parallel with already-queued earlier eligible runs for the same parent session.
- The parent agent may then:
  - respond to the user with the child result
  - decide to perform additional non-delegated work
  - delegate again only if depth and policy still allow it

### Status and Failure Contract
- Delegation logical status is distinct from run retry substate.
- Allowed delegation status transitions:
  - `queued -> running`
  - `queued -> cancelled`
  - `running -> completed`
  - `running -> failed`
  - `running -> cancelled`
- Child run retry while the run is still logically in progress does not change delegation status away from `running`.
- If the child run reaches terminal failed or dead-letter state, the delegation must become `failed` and store a bounded failure detail.
- If a queued or running delegation is cancelled, the system must:
  - mark the delegation `cancelled`
  - record a cancellation event
  - prevent new parent-result continuation from being enqueued for that delegation

### Cancellation Contract
- Add an internal or admin cancellation path for delegations.
- Cancellation must be best-effort and auditable:
  - queued child runs should transition to `cancelled`
  - already running child runs may complete their current attempt, but the delegation must still become logically cancelled and suppress parent continuation if completion arrives after cancellation
- Best-effort cancellation in this slice means:
  - the system must attempt to cancel queued child runs through the current run-state model
  - the system does not need to interrupt an already running child graph mid-attempt
  - a running child that later completes after cancellation must record completion as ignored for parent-continuation purposes
- Cancellation must never delete child sessions, child messages, or already-written audit events.

### Policy and Depth Contract
- Delegation depth is counted from the parent session chain:
  - primary sessions start at depth `0`
  - a child of depth `0` starts at depth `1`
  - each further child increments by one
- The runtime must deny delegation when:
  - the parent policy profile has `delegation_enabled=false`
  - the child agent is not in the parent policy profile allowlist
  - the computed child depth exceeds `max_delegation_depth`
  - the child agent profile is disabled
  - the child agent resolves to missing or disabled linked profiles
  - the parent already exceeds active delegation concurrency limits
- A child agent’s successful delegation to its own child is allowed only when that child agent also has visible `delegate_to_agent` capability and policy depth remains within bounds.
- Delegation concurrency limits must be enforced from durable delegation state, not from in-memory counters and not from child run state alone.
- For concurrency checks in this slice, an "active delegation" means a `delegations` row whose `status` is `queued` or `running`.
- `max_active_delegations_per_run`, when configured, applies to the count of active delegations for the exact `parent_run_id`.
- `max_active_delegations_per_session`, when configured, applies to the count of active delegations for the exact `parent_session_id`.
- Concurrency checks and delegation creation must occur in the same transaction boundary so concurrent tool executions cannot both pass the limit check and create excess delegations.

### Approval and Sandbox Contract
- Spec 003 approval matching remains exact to the current `session_id` and `agent_id`.
- Parent approvals do not transfer to child sessions.
- Child runs must satisfy their own approval and policy checks independently.
- Sandbox resolution continues to key off the child run’s `agent_id` through existing Spec 006 services.

### Diagnostics and Admin Contract
- Add read surfaces for:
  - `GET /sessions/{session_id}/delegations`
  - `GET /delegations/{delegation_id}`
  - `GET /delegations/{delegation_id}/events`
  - `GET /agents/{agent_id}/delegations` or equivalent diagnostics query
- Session and run diagnostics must expose:
  - parent and child session ids
  - parent and child run ids
  - parent and child agent ids
  - delegation status
  - depth
  - timing fields
  - terminal failure detail when present
- Delegation read surfaces must let operators reconstruct:
  - who delegated
  - to which child agent
  - when the child started and finished
  - whether retries occurred on the child run
  - whether the parent continuation was queued or suppressed

## Runtime Invariants
- Every delegation is represented by exactly one durable delegation record.
- Every delegation creates exactly one durable child session.
- Every child run executes through the existing `execution_runs` worker lifecycle.
- Parent and child agents keep distinct policy, tool, approval, and sandbox scopes.
- Parent work and child work communicate through durable database state only.
- Child completion cannot fabricate a user-visible parent answer without a corresponding durable parent continuation path.
- Delegation retries never duplicate child sessions or delegation records.
- Disabling or deleting routing-based ownership semantics from Spec 014 is out of scope; child sessions build on them additively.

## Security Constraints
- Delegation is fail-closed by default and disabled unless an agent’s tool and policy profiles explicitly allow it.
- Child agents must come from the durable enabled agent registry; arbitrary model-supplied identifiers are rejected.
- Parent approvals, active resources, and sandbox permissions do not broaden into child scope automatically.
- Child sessions are internal durable boundaries and must not be accidentally exposed as channel-routable user sessions.
- Delegation diagnostics require the same operator protections as the existing admin and diagnostics endpoints.

## Operational Considerations
- The child-session creation path must be separate from routing-tuple session creation so internal child sessions cannot collide with user-facing session keys.
- Child sessions should be treated as non-delivery sessions in this slice:
  - existing runtime-owned outbound tools may remain visible to some agents for future flexibility, but child-run delivery must still fail closed at dispatch time
  - this prevents a delegated child from replying directly to the user and bypassing the durable parent continuation model
- The continuation-message contract should be chosen to fit the current graph shape with minimal churn:
  - because `src/jobs/service.py` currently expects a concrete `message_id`, the safest implementation path in this slice is to append an internal parent continuation message and queue the follow-up parent run against that message
  - support for `execution_runs.message_id=null` can remain a future optimization rather than a requirement here
- Delegation packaging should use explicit settings-backed limits rather than service-local constants so transcript-turn caps, retrieval counts, attachment excerpt counts, and serialized size budgets are operator-visible and testable.
- The delegation service must record enough event detail to distinguish:
  - policy denial before creation
  - child run queued
  - child run started
  - child run retried
  - child run completed
  - child run failed
  - child completion ignored because the delegation was already cancelled
- Child result payloads should be bounded summaries, not full transcript exports.
- Any future streaming behavior inside child runs remains governed by Spec 013 and must not bypass the delegation audit trail.

## Implementation Gap Resolutions
### Gap 1: Prompt-Only Delegation vs Typed, Governed Delegation
The model could try to invent hidden helper behavior in prompt text, but that would bypass policy, audit, and durable state.

Options considered:
- Option A: describe specialist helpers in prompt instructions only
- Option B: let provider-native tool calling spawn child models directly
- Option C: add a first-class `delegate_to_agent` capability in the typed tool registry and route all delegation through a service layer
- Option D: encode delegation as a synthetic outbound message and let the worker infer intent later

Selected option:
- Option C

Decision:
- Delegation is a normal typed capability with schema validation, tool visibility rules, audit hooks, and policy enforcement.
- Hidden prompt-only or provider-managed spawning is explicitly out of scope.

### Gap 2: Synchronous Waiting vs Asynchronous Parent Continuation
The parent run cannot safely queue child work and then block waiting for it without introducing nested orchestration, lane deadlocks, or a second runtime path.

Options considered:
- Option A: run the child graph inline inside the parent claimed run
- Option B: queue the child run and block the parent worker until completion
- Option C: make delegation asynchronous, let the child run complete independently, then re-enter the parent session through a durable continuation run
- Option D: force every delegated task to reply directly to the user from the child session

Selected option:
- Option C

Decision:
- Delegation uses asynchronous child execution plus a durable parent follow-up run.
- This preserves the existing worker model and avoids inventing in-memory callbacks or nested run ownership.

### Gap 3: Child Session Identity vs Canonical Routing-Tuple Sessions
Spec 014 added `session_kind=child`, but current session creation still assumes routing-tuple resolution for durable session identity.

Options considered:
- Option A: reuse the parent routing session and only tag child runs
- Option B: create child sessions through the same routing key as the parent
- Option C: create a new internal child-session path with a synthetic unique session key and explicit parent linkage
- Option D: avoid sessions entirely and store child work only as artifacts

Selected option:
- Option C

Decision:
- Child work gets its own durable session.
- The child session is not routing-derived and therefore cannot collide with or replace the parent’s user-facing session.

### Gap 4: Parent Context Sharing vs Context Explosion
Copying the full parent transcript into every child session would be expensive, leaky, and hard to govern.

Options considered:
- Option A: copy the full parent transcript into the child session every time
- Option B: expose no parent context beyond the task string
- Option C: package a bounded delegation context with recent turns, summaries, and already-available derived context under explicit limits
- Option D: let the child session query the parent transcript directly at runtime

Selected option:
- Option C

Decision:
- Delegation packages a bounded parent context snapshot.
- The child session remains context-isolated while still receiving enough information to do useful work.

### Gap 5: Child Completion Reentry Shape
The current worker path expects runs to anchor on a concrete session and message, but child completion needs to resume work in the parent session.

Options considered:
- Option A: allow `execution_runs.message_id=null` and special-case parent continuation everywhere now
- Option B: mutate the parent assistant message in place when the child finishes
- Option C: append one internal continuation message to the parent session and queue a normal follow-up run on that message
- Option D: write the child result only to a diagnostics table and never resume the parent automatically

Selected option:
- Option C

Decision:
- Parent continuation reuses the current run model by anchoring follow-up work on a durable internal message in the parent session.
- This is the least disruptive path for the current codebase and keeps the continuation auditable.

### Gap 6: Delegation Logical Status vs Child Run Retry State
The child run already has `queued`, `running`, `retry_wait`, `failed`, and other statuses, but operators also need one higher-level delegation status.

Options considered:
- Option A: expose only child run status and skip delegation state
- Option B: mirror every run status exactly onto the delegation row
- Option C: keep one simpler logical delegation status plus append-only events that preserve retry details
- Option D: record delegation state only in logs

Selected option:
- Option C

Decision:
- `delegations.status` tracks the high-level lifecycle, while `delegation_events` and child run diagnostics preserve retry and attempt detail.
- This keeps read surfaces understandable without losing audit fidelity.

### Gap 7: Parent Approval Scope vs Child Independence
Parent sessions may already have approvals or active resources, but reusing them in child scope would violate Spec 003 exact-scoping rules.

Options considered:
- Option A: inherit parent approvals automatically into the child session
- Option B: share approvals only when parent and child agent ids match
- Option C: keep approvals exact to session and agent, requiring child work to satisfy its own governance rules
- Option D: disable approval-gated tools for all delegated work permanently

Selected option:
- Option C

Decision:
- Delegated work stays governance-isolated.
- Parent approvals do not transfer into child scope, preserving exact approval identity.

### Gap 8: Parent Continuation Idempotency on Child Completion
Child completion can be retried, replayed after worker failure, or race with cancellation. Without a tighter contract, the system could append duplicate continuation messages or enqueue duplicate `delegation_result` runs.

Options considered:
- Option A: append the continuation message best-effort, then create-or-get the parent run
- Option B: dedupe only the parent run and allow duplicate continuation messages
- Option C: make parent reentry fully idempotent in one transaction by serializing on the delegation row, creating or looking up exactly one continuation message, creating or looking up exactly one `delegation_result` run, and storing both foreign keys atomically
- Option D: skip the continuation message and allow `execution_runs.message_id=null` for delegation results

Selected option:
- Option C

Decision:
- Parent continuation must be idempotent per `delegation_id`, not only per run trigger.
- Duplicate or replayed child completion handling must resolve to the same parent continuation message and the same parent follow-up run.

### Gap 9: Internal Transcript Role for Delegation Messages
The draft allows internal delegation rows in `messages`, but without choosing a concrete transcript role the implementation would have ambiguity in context assembly, transcript rendering, and diagnostics behavior.

Options considered:
- Option A: use `role=user` with a synthetic sender
- Option B: standardize on `role=system` for both child trigger and parent continuation messages
- Option C: add a new `role=internal` enum in this slice
- Option D: keep delegation triggers out of `messages` and store them only in delegation tables

Selected option:
- Option B

Decision:
- This slice standardizes on `role=system` for delegation-created transcript rows.
- Internal delegation rows remain append-only transcript state, but are explicitly non-channel-originated through `external_message_id=null` and a reserved internal `sender_id` namespace.

### Gap 10: Precise Definition of Active Delegation Concurrency
The draft introduces optional per-run and per-session delegation concurrency limits, but it does not define exactly what counts as active or how the limits are enforced safely under races.

Options considered:
- Option A: count child `execution_runs` in nonterminal statuses
- Option B: count `delegations.status IN ('queued', 'running')` and enforce the limit inside the same transaction that creates a delegation
- Option C: count only `running` delegations and ignore queued ones
- Option D: enforce the limit only in memory at tool-execution time

Selected option:
- Option B

Decision:
- Concurrency is defined from durable delegation state rather than child run state.
- Both queued and running delegations count as active for limit enforcement in this slice.

### Gap 11: Ordering of Parent Continuation vs Other Parent-Session Runs
The parent continuation run re-enters the same session as normal inbound work. The draft must choose whether `delegation_result` runs preserve existing session-lane ordering or introduce a new priority path.

Options considered:
- Option A: give `delegation_result` runs priority over normal inbound runs
- Option B: keep normal session-lane FIFO ordering and let continuation runs behave like any other queued run for the parent session
- Option C: run continuation work on a separate lane in parallel with the parent session
- Option D: merge child results into the next inbound parent run instead of creating a standalone continuation run

Selected option:
- Option B

Decision:
- Parent continuation follows the existing Spec 005 queue and lane rules for the parent session.
- This slice does not introduce priority overtaking or a second parent-session lane for delegation results.

### Gap 12: Child Sessions vs User-Visible Outbound Delivery
The current runtime can dispatch outbound intents from any completed run, but delegated child work in this slice is supposed to return through the parent continuation path instead of replying directly to the user.

Options considered:
- Option A: allow child runs to use normal outbound delivery like primary sessions
- Option B: rely only on child tool profiles to avoid outbound tools
- Option C: suppress user-visible outbound dispatch for child runs at runtime even if a child tool emits an outbound intent artifact
- Option D: add a separate child-only outbound tool family now

Selected option:
- Option C

Decision:
- Child runs are execution-only in this slice and must not deliver directly to external channels.
- Any child-produced outbound intent remains durable for audit but is not dispatched; only the parent continuation may lead to user-visible delivery.

### Gap 13: Authoritative Source of the Child Result Payload
The spec requires `result_payload_json.summary_text`, but without a concrete extraction rule implementation could become inconsistent across successful, tool-heavy, and partially failed child runs.

Options considered:
- Option A: always use the child run's final assistant message only
- Option B: summarize the entire child transcript at completion time
- Option C: define a deterministic bounded result builder that prefers the final assistant message and falls back to bounded tool outcomes, artifacts, or failure summaries
- Option D: require a new explicit child `return_to_parent` tool in this slice

Selected option:
- Option C

Decision:
- `result_payload_json` is built by a deterministic service-owned extractor.
- The extractor prefers the final assistant message, then bounded structured child outputs, and never requires full transcript export.

### Gap 14: Concrete Configuration Surface for Delegation Packaging Limits
The spec defines bounded context packaging, but implementation still needs one authoritative place to configure and validate those limits.

Options considered:
- Option A: hardcode the limits inside `DelegationService`
- Option B: infer delegation limits from unrelated existing runtime context settings
- Option C: add explicit settings-backed delegation packaging limits for transcript turns, retrieval items, attachment excerpts, and serialized size budget
- Option D: define packaging limits separately inside each policy profile in this slice

Selected option:
- Option C

Decision:
- Delegation packaging limits are explicit settings-backed controls.
- This keeps the first implementation testable, operator-visible, and fail-closed without overloading per-policy configuration.

### Gap 15: Exact Cancellation Behavior Under the Current Worker Model
The spec says cancellation is best-effort, but the current worker lifecycle does not yet provide a full cooperative interrupt for already running child graphs.

Options considered:
- Option A: mark only the delegation row cancelled and never touch the child run row
- Option B: cancel queued child runs when possible, mark running delegations logically cancelled, and suppress late parent continuation if the running child later finishes
- Option C: add full running-graph interruption in this slice
- Option D: defer cancellation entirely out of this slice

Selected option:
- Option B

Decision:
- This slice supports durable queued-run cancellation plus logical cancellation of already running child work.
- Running children may finish their current attempt, but their late completion cannot enqueue a parent continuation after cancellation.

## Acceptance Criteria
- A parent run can invoke a visible typed delegation tool and create one durable delegation record, one child session, one child trigger message, and one child execution run in one transaction.
- The child run executes through the normal worker lifecycle with its own agent-specific binding, tools, policies, and sandbox identity.
- Child runs cannot produce direct user-visible outbound delivery; any child-produced outbound intent is suppressed from dispatch and kept only as durable internal state.
- Parent-to-child context transfer is bounded, auditable, and does not automatically copy the full parent transcript.
- Child completion writes one structured result payload from a deterministic bounded extractor and queues one parent continuation run through a durable parent continuation message.
- Child failure and child dead-letter states mark the delegation failed and prevent silent success fabrication.
- Delegation retry behavior is idempotent: worker replay does not create duplicate delegations or duplicate child sessions.
- Cancellation is durable and auditable, and cancellation suppresses parent continuation if a late child completion arrives afterward.
- Diagnostics can reconstruct full delegation lineage from parent session and run to child session and run, including status and timing.

## Test Expectations
- Unit tests for delegation policy checks:
  - delegation disabled
  - disallowed child agent
  - disabled child agent
  - depth exceeded
  - concurrency limit exceeded
- Unit tests for delegation service idempotency on parent worker retry
- Unit tests for child-session creation rules and synthetic session-key behavior
- Unit tests for parent-to-child context packaging bounds
- Unit tests for child-run outbound-dispatch suppression
- Unit tests for deterministic child result payload extraction with and without a final assistant message
- Integration tests for successful parent delegation, child execution, child completion, and parent follow-up response
- Integration tests for child failure, child dead-letter, and parent-visible failure handling
- Integration tests for cancellation before child start and cancellation after child start
- Diagnostics tests for delegation lineage, event ordering, and terminal failure visibility
