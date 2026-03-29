# Spec 016: Human Handoff, Collaboration, and Approval UX

## Purpose
Add durable human-collaboration controls so a session can move safely between automated handling and operator-managed handling, while also upgrading approval-required actions from text-only prompts into structured, channel-aware approval UX.

## Non-Goals
- Replacing the canonical session identity, routing tuple, or session-key rules from Spec 001
- Building a full ticketing system, workforce-management product, SLA engine, or omnichannel CRM
- Allowing unrestricted simultaneous human and assistant outbound replies on the same session
- Weakening Spec 003 exact approval matching or broadening approvals across sessions, agents, or channels
- Letting child sessions, provider-native tools, or hidden prompts bypass takeover state or operator controls
- Introducing free-form mutable shared documents instead of append-only collaboration notes and audit records
- Replacing the existing outbound dispatcher, queue, or diagnostics systems rather than extending them

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
- Spec 015

## Scope
- Durable session automation state for `assistant_active`, `human_takeover`, and `paused`
- Durable assignment metadata for queue ownership, assignee changes, and operator collaboration context
- Append-only operator notes and collaboration events suitable for audit and diagnostics
- Queue-time and dispatch-time enforcement so automated runs do not continue replying while a session is under human control
- Structured approval-request artifacts that explain why approval is needed and expose safe action affordances
- Channel-aware approval decisions from user-facing surfaces where supported, with signed and auditable action handling
- Admin and diagnostics write and read surfaces for takeover, resume, pause, reassignment, notes, approval decisions, and collaboration history
- Tests covering state transitions, blocked-run release, outbound suppression, approval actions, and operator conflict prevention

## Implementation Clarifications
- Operator-authored collaboration and approval mutations in this slice require a durable operator principal identifier in addition to operator access control.
- The gateway auth layer may derive that principal from trusted headers or upstream auth context, but write paths must persist a stable operator identifier for:
  - `assigned_operator_id`
  - note authorship
  - collaboration-event actors
  - operator approval and denial audit records
- Authorization alone is insufficient; implementations must not use only a bearer token string or anonymous operator access as the durable actor identity contract.
- When outbound delivery is suppressed because the session is no longer `assistant_active`, the suppressed reply must not be persisted as a normal user-visible assistant transcript message.
- Suppressed assistant output must instead remain in audit-visible artifacts such as delivery payloads, run diagnostics, governance artifacts, or collaboration events so future model context and user-facing transcript reads reflect only content actually delivered to the end user.
- Approval prompt creation is split into two responsibilities:
  - graph and governance code decide that approval is required and emit one canonical structured approval-prompt artifact
  - dispatcher and approval services materialize one durable `approval_action_prompts` row per rendered surface when message and surface context are known
- The `approval_action_prompts.message_id` foreign key refers to the assistant message or durable outbound artifact that carried the rendered prompt on that surface; prompt rows must not be finalized before that linkage is known.
- Collaboration-aware queue gating applies to every automation trigger that targets a `primary` session and can produce user-visible outbound handling, not only inbound user messages and delegation-result continuations.
- In this slice that explicitly includes:
  - inbound user messages
  - delegation-result continuation runs
  - scheduler-fired runs for `primary` sessions
- New future trigger kinds targeting `primary` sessions must fail closed into the collaboration-aware gating path unless a later spec explicitly narrows that rule.

## Current-State Baseline
- `src/sessions/service.py` always resolves or creates the canonical session, appends the inbound user message, and enqueues an `execution_run`; there is no session automation-state gate yet.
- `src/jobs/service.py` always claims eligible runs, invokes the graph, and dispatches outbound replies for non-child sessions; it does not re-check whether a human has taken control since enqueue time.
- `src/graphs/nodes.py` still communicates approval workflows primarily through assistant text such as `Reply approve <proposal_id>`, and `src/policies/service.py` still recognizes `approve` and `revoke` as deterministic text commands.
- `apps/gateway/api/admin.py` exposes read surfaces for sessions, runs, agents, delegations, and pending approvals, but it does not yet expose mutation routes for takeover, assignment, notes, or approval actions.
- `apps/gateway/api/slack.py`, `apps/gateway/api/telegram.py`, and `apps/gateway/api/webchat.py` accept inbound/provider traffic, but there is no durable interactive-approval callback contract yet.
- `src/channels/dispatch.py` and the channel adapters already own outbound delivery and streaming, but they do not yet understand structured approval prompts or suppress sends based on takeover state.
- `src/observability/diagnostics.py` can explain run, delivery, and delegation state, but it cannot yet reconstruct collaboration history, queue ownership, or handoff decisions.

## Data Model Changes
- `sessions`
  - add `automation_state` non-null with values:
    - `assistant_active`
    - `human_takeover`
    - `paused`
  - add `assigned_operator_id` nullable
  - add `assigned_queue_key` nullable
  - add `automation_state_reason` nullable bounded text
  - add `automation_state_changed_at` nullable then non-null after backfill
  - add `assignment_updated_at` nullable
  - add `collaboration_version` non-null integer default `1`
  - required indexes
    - lookup index on `sessions(automation_state, last_activity_at)`
    - lookup index on `sessions(assigned_operator_id, last_activity_at)`
    - lookup index on `sessions(assigned_queue_key, last_activity_at)`
- `execution_runs`
  - add `blocked_reason` nullable
  - allow `status=blocked` as a first-class durable queue state
  - add optional `blocked_at` nullable
  - required indexes
    - lookup index on `execution_runs(status, blocked_at, created_at)`
    - lookup index on `execution_runs(session_id, status, created_at)` remains sufficient if expanded to include `blocked`
- `session_operator_notes`
  - append-only internal notes table
  - `id` primary key
  - `session_id` non-null foreign key to `sessions.id`
  - `author_kind` with values such as `operator` or `system`
  - `author_id`
  - `note_kind` with values such as `internal`, `handoff_summary`, `approval_context`, or `resolution`
  - `body`
  - `created_at`
  - required indexes
    - lookup index on `session_operator_notes(session_id, id)`
    - lookup index on `session_operator_notes(author_id, created_at)`
- `session_collaboration_events`
  - append-only audit table for takeover, pause, resume, assignment, note creation, and operator actions
  - `id` primary key
  - `session_id` non-null foreign key to `sessions.id`
  - `event_kind`
  - `actor_kind` with values such as `operator`, `assistant`, `end_user`, `system`, `channel_user`
  - `actor_id` nullable
  - `automation_state_before` nullable
  - `automation_state_after` nullable
  - `assigned_operator_before` nullable
  - `assigned_operator_after` nullable
  - `assigned_queue_before` nullable
  - `assigned_queue_after` nullable
  - `related_run_id` nullable foreign key to `execution_runs.id`
  - `related_note_id` nullable foreign key to `session_operator_notes.id`
  - `related_proposal_id` nullable foreign key to `resource_proposals.id`
  - `payload_json`
  - `created_at`
  - required indexes
    - lookup index on `session_collaboration_events(session_id, id)`
    - lookup index on `session_collaboration_events(event_kind, created_at)`
    - lookup index on `session_collaboration_events(actor_kind, actor_id, created_at)`
- `approval_action_prompts`
  - durable approval-prompt and signed-action tracking table
  - `id` primary key
  - `proposal_id` non-null foreign key to `resource_proposals.id`
  - `session_id` non-null foreign key to `sessions.id`
  - `agent_id` non-null
  - `message_id` non-null foreign key to `messages.id`
  - `channel_kind`
  - `channel_account_id`
  - `transport_address_key` nullable
  - `approve_token_hash` non-null unique
  - `deny_token_hash` non-null unique
  - `status` with values `pending`, `approved`, `denied`, `expired`, `revoked`, `superseded`
  - `expires_at`
  - `decided_at` nullable
  - `decided_via` nullable with values such as `text_command`, `channel_action`, `admin_api`
  - `decider_actor_id` nullable
  - `presentation_payload_json`
  - `created_at`
  - `updated_at`
  - required indexes
    - lookup index on `approval_action_prompts(proposal_id, created_at)`
    - lookup index on `approval_action_prompts(session_id, status, created_at)`
    - lookup index on `approval_action_prompts(status, expires_at)`
- `governance_transcript_events`
  - keep existing append-only behavior
  - may add nullable `approval_prompt_id` foreign key if needed for precise audit joins
- `outbound_deliveries`
  - extend supported `delivery_kind` and `completion_status` values to include structured approval prompt and suppressed outcomes
  - schema change is optional if the current string columns are reused, but the contract must make those values explicit and test-covered

## Settings and Registry Changes
- Add collaboration settings in `src/config/settings.py` for:
  - default assignment queue key
  - approval action token TTL
  - whether each channel kind supports interactive approval decisions
  - whether operator takeover should block new automation immediately for queued work only or also suppress in-flight outbound sends
  - maximum operator note size
- Keep deterministic text approvals from Spec 003 as a required fallback even when interactive approvals are enabled.
- Extend channel-account settings only as needed for provider-specific signing or callback verification, without duplicating approval state into channel config.

## Contracts
### Session Collaboration Contract
- `SessionCollaborationService` or equivalent is the sole owner of:
  - takeover
  - pause
  - resume
  - assignment and reassignment
  - operator-note creation
  - collaboration-event recording
  - release of blocked automation after resume
- Collaboration state applies only to user-facing `primary` sessions in this slice.
- `child` and `system` sessions remain durable and inspectable, but operator handoff controls are not exposed as first-class mutation flows for them in this spec.
- Assignment is orthogonal to automation state:
  - a session may remain `assistant_active` while assigned to a queue or operator
  - a session may move to `human_takeover` or `paused` without changing assignee
- The two non-automated states have distinct meaning:
  - `human_takeover` means automated user-visible handling is disabled because a human operator or operator workflow is actively responsible for the session
  - `paused` means automated user-visible handling is disabled, but no active human conversation ownership is implied by state alone
- `assigned_operator_id` may be null in any automation state, but implementations should not infer human ownership from assignment alone:
  - `assigned_operator_id` without `human_takeover` is assignment metadata only
  - `human_takeover` without `assigned_operator_id` is allowed for queue-owned or unassigned manual handling
- Allowed state transitions:
  - `assistant_active -> human_takeover`
  - `assistant_active -> paused`
  - `human_takeover -> assistant_active`
  - `human_takeover -> paused`
  - `paused -> assistant_active`
  - `paused -> human_takeover`
- Every state or assignment mutation must:
  - lock or otherwise serialize on the session row
  - increment `collaboration_version`
  - append one `session_collaboration_events` row
  - optionally append one operator note when provided
- Every operator-authored state or assignment mutation route must accept `expected_collaboration_version`.
- If the stored `collaboration_version` does not match `expected_collaboration_version`, the mutation must fail with a conflict response such as HTTP `409` and must not partially apply any state, assignment, or note changes.
- Row locking and version checks are complementary in this slice:
  - row locking prevents concurrent write interleaving
  - `expected_collaboration_version` prevents stale operator clients from silently overwriting a more recent decision

### Queue Gating Contract
- New automated work for a `primary` session may be created only through collaboration-aware queue rules.
- When `automation_state=assistant_active`:
  - inbound user messages create normal queued runs
  - delegation-result parent continuations create normal queued runs
  - scheduler-fired runs targeting `primary` sessions create normal queued runs
- When `automation_state=human_takeover` or `paused`:
  - inbound user messages still append to the transcript
  - parent continuation messages for delegation results still append to the transcript
  - scheduler-fire payload messages still append to the transcript
  - the corresponding `execution_runs` must be created in `status=blocked`
  - `blocked_reason` must identify the collaboration state that prevented automatic execution
- The worker claim path must never claim runs whose `status=blocked`.
- When a session returns to `assistant_active`, blocked runs for that session must be released in durable queue order using `created_at` then `id`.
- Releasing blocked runs must be idempotent and must not create duplicate runs.

### In-Flight Run and Dispatch Contract
- Human takeover must stop automatic user-visible assistant replies even if the run was queued before the takeover.
- Queue-time gating alone is insufficient; dispatch-time enforcement is also required.
- `src/jobs/service.py` must re-check session collaboration state before outbound dispatch.
- If a run has already produced assistant output but the session is no longer `assistant_active` at dispatch time:
  - transcript continuity may still be preserved through audit-visible non-transcript artifacts
  - user-visible outbound delivery must be suppressed
  - delivery records must reflect a suppressed outcome rather than `sent`
  - one collaboration event must explain why outbound delivery was suppressed
  - the suppressed reply must not be appended as a normal assistant transcript message that would later appear in model context or user transcript reads
- This spec does not require forcibly interrupting an already running graph mid-turn.
- Best-effort behavior for in-flight work is:
  - prevent claim for not-yet-started work through `blocked`
  - suppress outbound for already-running work if takeover wins the race before dispatch

### Approval Prompt Contract
- Approval-required actions must produce one structured approval prompt in addition to human-readable fallback text.
- The structured prompt must include at minimum:
  - `proposal_id`
  - `capability_name`
  - `typed_action_id`
  - bounded canonical params preview
  - explanation text for why approval is required
  - explicit supported decisions such as `approve` and `deny`
  - fallback plain-text instructions for channels without interactive support
- `src/graphs/nodes.py` remains responsible for deciding that approval is required, but prompt presentation must no longer rely solely on embedded free-form assistant text.
- The approval prompt should be represented as a durable artifact or structured outbound payload that `src/channels/dispatch.py` can transform into channel-specific UX.
- Implementations should treat prompt generation as a two-step lifecycle:
  - canonical prompt artifact creation before rendering
  - per-surface durable prompt-row creation once the outbound message or delivery artifact for that surface is known
- Per-surface prompt rows must not be finalized without a durable link to the rendered assistant message or outbound artifact that presented the prompt.

### Approval Action Contract
- Interactive approval must remain exact to the underlying proposal, session, and agent identity from Spec 003.
- Channel actions must never approve work based only on a visible `proposal_id`.
- Each actionable prompt must create one durable `approval_action_prompts` row with one-time signed action tokens for at least:
  - approve
  - deny
- The server may encode signed decision tokens however implementation prefers, but it must persist only token hashes durably.
- Channel-action handling must:
  - verify the provider callback signature or authenticated webchat caller as appropriate
  - verify the signed action token
  - verify the prompt is still `pending` and not expired
  - verify the linked proposal is still actionable for the same session and agent
  - record the resulting decision idempotently
- Duplicate callback delivery for the same action token must resolve to the same durable outcome.
- Decisions taken through channel actions must use the same proposal mutation paths as text commands or admin APIs:
  - `approve` maps to the existing exact approval and activation flow
  - `deny` maps to durable proposal denial
- Text commands such as `approve <proposal_id>` remain supported as the fallback path and must continue to produce the same exact approval semantics.
- Prompt rows are presentation-state artifacts, not a second approval authority:
  - multiple historical prompt rows may exist for the same `proposal_id`
  - at most one `pending` prompt row may exist at a time for a given `(proposal_id, session_id, agent_id, channel_kind, transport_address_key)` surface
- When the system re-presents an approval request to the same surface, any older `pending` prompt for that same surface must transition to `superseded` before the newer prompt becomes `pending`.
- When a proposal reaches a terminal decision through text command, channel action, admin API, expiry, or revocation:
  - the prompt row that carried the winning decision records the terminal decision outcome
  - any other still-`pending` prompt rows for that proposal must be transitioned durably to `superseded`, `expired`, or `revoked` as appropriate
- Duplicate callback or replay handling for a previously decided prompt must return the already-recorded durable outcome rather than creating a second decision.

### Channel Surface Contract
- `src/channels/dispatch.py` remains the only outbound send orchestrator.
- Channel-specific approval UX is additive:
  - Slack may render buttons or similar block actions and use a dedicated interactivity callback route
  - Telegram may render inline-keyboard actions through its existing webhook path or an additive callback-aware route
  - Webchat may expose structured approval actions in poll and SSE payloads plus a write endpoint for decision submission
- Unsupported channels must fall back to plain text instructions and normal transcript-driven approval commands.
- Channel surfaces must never be the only source of truth for approval state; durable repository state remains authoritative.
- Provider-facing approval routes are translation-only boundaries in the same sense as inbound channel routes from Spec 012:
  - Slack, Telegram, and Webchat handlers may verify provider authenticity and extract the normalized action payload
  - those handlers must then call one backend-owned approval decision service rather than reimplementing proposal mutation, token validation, or idempotency rules per channel
- The normalized approval-decision submission contract for that service must include at minimum:
  - decision source such as `channel_action`, `text_command`, or `admin_api`
  - requested decision such as `approve` or `deny`
  - opaque signed action token or prompt identity
  - authenticated actor identity as available from the surface
  - channel or transport metadata needed for audit
- Exact approval validation, prompt-status checks, proposal-state checks, idempotency, and terminal proposal mutation remain backend-owned responsibilities of the shared service layer, not the channel adapters or route handlers.

### Operator Action Contract
- Add authenticated operator write surfaces for:
  - takeover
  - pause
  - resume
  - assign or reassign
  - note creation
  - operator approval or denial
- Operator write routes must require the same operator protections as the existing admin endpoints.
- Operator write routes must also receive a durable operator principal identifier from the gateway auth layer and persist that identifier in assignment, notes, collaboration events, and operator-driven approval decisions.
- Operator actions must append collaboration events and must not mutate or delete prior notes, transcript messages, proposals, approvals, or delivery attempts.

### Notes and Collaboration History Contract
- Operator notes are internal-only data and must not enter model context or outbound user delivery by default.
- Notes are append-only in this slice.
- Collaboration history must make it possible to reconstruct:
  - who took over the session
  - when the session was paused or resumed
  - who reassigned the session and to whom
  - which runs were blocked or suppressed because of collaboration state
  - which approval prompts were shown and how they were decided

### Diagnostics and Admin Contract
- Extend session read surfaces to expose:
  - `automation_state`
  - `assigned_operator_id`
  - `assigned_queue_key`
  - `automation_state_reason`
  - `automation_state_changed_at`
  - `assignment_updated_at`
  - `collaboration_version`
- Add read surfaces for:
  - `GET /sessions/{session_id}/notes`
  - `GET /sessions/{session_id}/collaboration`
  - `GET /sessions/{session_id}/automation`
  - `GET /sessions/{session_id}/approval-prompts`
- Add write surfaces for:
  - `POST /sessions/{session_id}/takeover`
  - `POST /sessions/{session_id}/pause`
  - `POST /sessions/{session_id}/resume`
  - `POST /sessions/{session_id}/assign`
  - `POST /sessions/{session_id}/notes`
  - `POST /sessions/{session_id}/governance/{proposal_id}/decision`
- Diagnostics for a run and for a session must expose whether the run was:
  - queued normally
  - blocked by collaboration state
  - suppressed at dispatch time
- Diagnostics for a session must expose active blocked-run counts and the most recent collaboration events.

## Runtime Invariants
- A `primary` session always has exactly one current automation state.
- Assignment metadata never changes transcript or approval identity.
- Automated replies are user-visible only when the session is `assistant_active` at dispatch time.
- Blocked runs are durable queue state, not in-memory flags.
- Releasing blocked runs after resume does not create duplicate logical work.
- Approval decisions remain exact to the proposal, session, agent, and canonical arguments from Spec 003 regardless of whether the decision came from text, admin, or channel action.
- Operator notes and collaboration events are append-only and audit-visible.
- Human takeover does not silently delete queued runs, child sessions, approvals, or prior transcript state.

## Security Constraints
- Operator write routes require operator authorization and must be denied by default without it.
- Interactive approval decisions must verify provider authenticity plus one-time signed decision tokens.
- Approval action tokens must expire and must be stored durably only as hashes.
- Channel callbacks must fail closed when proposal state, session identity, agent identity, or prompt status do not match.
- Human collaboration metadata must not broaden tool visibility, approval scope, or sandbox scope.
- Operator notes are internal and must not be injected into normal model context unless a later spec explicitly authorizes it.

## Operational Considerations
- `src/sessions/service.py` should remain the canonical inbound entry point, but collaboration-aware run blocking should be delegated to one explicit service or helper rather than spread across route handlers.
- `src/jobs/service.py` is the safest enforcement point for dispatch-time suppression because it already owns run lifecycle and outbound dispatch invocation.
- `src/channels/dispatch.py` should translate one canonical approval prompt payload into channel-specific UX rather than letting each graph path handcraft provider payloads.
- Webchat should continue to support polling and SSE; approval actions should reuse those delivery channels rather than inventing a separate browser-only state store.
- Collaboration events should be detailed enough to diagnose races such as:
  - takeover before run claim
  - takeover after run claim but before dispatch
  - resume releasing blocked inbound work
  - duplicate interactive approval callbacks
- Migration and backfill must initialize existing sessions to:
  - `automation_state=assistant_active`
  - `collaboration_version=1`
  - null assignment fields unless operators choose defaults explicitly

## Implementation Gap Resolutions
### Gap 1: Where Collaboration State Lives
The implementation needs one authoritative place for takeover and assignment state that both inbound and worker paths can observe.

Options considered:
- Option A: store collaboration state only in ephemeral worker memory
- Option B: create a separate control table and leave `sessions` unchanged
- Option C: add current collaboration state directly to `sessions` and keep append-only history in a separate events table
- Option D: encode takeover only as a special message in the transcript

Selected option:
- Option C

Decision:
- Current collaboration state lives on `sessions`, while immutable history lives in `session_collaboration_events`.
- This keeps reads cheap and makes race-sensitive enforcement practical.

### Gap 2: What Happens To Automation During Takeover
Inbound messages and parent continuations still need durable state even when automation is paused.

Options considered:
- Option A: reject inbound traffic while a human owns the session
- Option B: append messages but drop the corresponding automation work
- Option C: create durable `blocked` runs and release them when the session returns to `assistant_active`
- Option D: let runs queue normally and hope operators win the race manually

Selected option:
- Option C

Decision:
- Collaboration state blocks automation by creating durable blocked runs rather than rejecting or dropping work.
- This preserves transcript continuity and makes resumption deterministic.

### Gap 3: How To Stop Already-Running Automation
Queue-time blocking alone cannot stop a run that was claimed moments before an operator took over.

Options considered:
- Option A: interrupt the graph mid-turn
- Option B: ignore the race and allow the reply anyway
- Option C: allow the turn to finish for audit continuity, but suppress outbound delivery if dispatch happens after takeover
- Option D: delete the assistant output after the run finishes

Selected option:
- Option C

Decision:
- Dispatch-time suppression is required in addition to queue-time blocking.
- This is additive to the current worker architecture and avoids destructive transcript mutation.

### Gap 4: How Interactive Approval Decisions Stay Exact
Channel buttons are convenient, but raw provider payloads are not safe approval identity.

Options considered:
- Option A: trust the callback payload’s `proposal_id`
- Option B: embed full approval packets directly in callback payloads
- Option C: use durable prompt rows plus expiring signed action tokens whose hashes are stored server-side
- Option D: disable interactive approvals and keep text-only approvals forever

Selected option:
- Option C

Decision:
- Interactive approval actions are durable, signed, exact, and idempotent.
- The server remains authoritative for whether a proposal is still actionable.

### Gap 5: Where Operator Notes Belong
Operators need durable internal notes, but those notes should not silently leak into user-visible transcripts or model context.

Options considered:
- Option A: store notes as normal transcript messages
- Option B: store notes only in logs
- Option C: create a dedicated append-only internal notes table plus collaboration events
- Option D: mutate session rows with one latest note field

Selected option:
- Option C

Decision:
- Internal notes remain separate from user transcript state and model context by default.
- Audit visibility comes from append-only note rows and linked collaboration events.

### Gap 6: Assignment State vs Automation State
Assignment and takeover are related but not identical. Treating them as one field would make normal queue ownership awkward.

Options considered:
- Option A: encode assignment only in free-form notes
- Option B: collapse assignment and automation into one overloaded enum
- Option C: keep automation state and assignment metadata as separate but coordinated concerns
- Option D: postpone assignment entirely

Selected option:
- Option C

Decision:
- This spec models assignment separately from automation state.
- That supports queue ownership, reassignment, and human takeover without conflating them.

### Gap 7: Operational Meaning Of `human_takeover` vs `paused`
The spec introduces two non-automated session states, but implementation would be inconsistent unless their meanings are explicit and stable across admin, diagnostics, and queueing flows.

Options considered:
- Option A: collapse both states into one manual-only state
- Option B: define `human_takeover` as operator-owned handling and `paused` as a neutral automation hold state
- Option C: make `paused` only a short-lived timer-based freeze and `human_takeover` the only durable manual state
- Option D: leave the distinction implicit in assignment fields or free-form reason text

Selected option:
- Option B

Decision:
- `human_takeover` means a human operator or manual workflow is actively responsible for the conversation.
- `paused` means automation is off, but no human ownership is implied by state alone.
- Assignment metadata remains orthogonal and must not be used as the only source of truth for whether a session is under active human control.

### Gap 8: How Operator Write Conflicts Are Prevented
This spec adds `collaboration_version` and requires serialized mutation, but stale operator clients still need an explicit conflict contract so they do not overwrite newer takeover or assignment changes silently.

Options considered:
- Option A: last-write-wins with no explicit conflict signaling
- Option B: rely on row locking only and let clients retry blindly
- Option C: require optimistic concurrency using `expected_collaboration_version`
- Option D: add an operator checkout or lease model before any write is allowed

Selected option:
- Option C

Decision:
- Operator-authored write routes in this slice require `expected_collaboration_version`.
- If the supplied version does not match the stored session version, the write fails with a conflict and no partial mutation is committed.
- Row locking still applies inside the mutation transaction, but optimistic version matching is the external correctness contract for operator clients.

### Gap 9: Approval Prompt Lifecycle And Re-Presentation
Structured approval prompts are durable artifacts, but the spec must define how repeated presentation, replay, and terminal decisions interact so prompt state does not drift from proposal state.

Options considered:
- Option A: allow unlimited simultaneously pending prompts per proposal
- Option B: allow one active prompt per proposal and channel surface, superseding older prompt rows on re-presentation
- Option C: allow only one global prompt for a proposal across all channels
- Option D: treat prompts as best-effort delivery artifacts with no durable lifecycle beyond token expiry

Selected option:
- Option B

Decision:
- Multiple historical prompt rows may exist for audit, but only one `pending` prompt may exist at a time for a given `(proposal_id, session_id, agent_id, channel_kind, transport_address_key)` surface.
- Re-presenting the same approval on the same surface supersedes the older pending prompt before the new prompt becomes active.
- Terminal proposal outcomes must reconcile any other still-pending prompt rows for that proposal into non-pending terminal or superseded states.

### Gap 10: Shared Backend Contract For Interactive Approval Ingress
Interactive approval support spans Slack, Telegram, and Webchat, but exact approval logic must stay centralized or each channel route will drift in security, idempotency, and audit behavior.

Options considered:
- Option A: let each provider route implement approval-decision behavior independently
- Option B: define one backend-owned normalized approval-decision service and keep provider routes translation-only
- Option C: force every channel to use one universal public callback endpoint
- Option D: ship interactive approvals only for Webchat and defer the other channels

Selected option:
- Option B

Decision:
- Provider-specific routes remain responsible only for transport authentication and payload normalization.
- One backend-owned approval decision service performs token verification, prompt lookup, proposal exactness checks, idempotent mutation, and audit recording.
- This preserves the Spec 012 gateway-owned normalization pattern while keeping Spec 003 approval enforcement exact and consistent across channels.
