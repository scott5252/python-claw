# Plan 016: Human Handoff, Collaboration, and Approval UX

## Target Modules
- `src/config/settings.py`
- `src/db/models.py`
- `src/domain/schemas.py`
- `src/sessions/repository.py`
- `src/sessions/service.py`
- `src/jobs/repository.py`
- `src/jobs/service.py`
- `src/channels/dispatch.py`
- `src/channels/adapters/slack.py`
- `src/channels/adapters/telegram.py`
- `src/channels/adapters/webchat.py`
- `src/policies/service.py`
- `src/graphs/state.py`
- `src/graphs/nodes.py`
- `src/security/signing.py`
- `src/observability/diagnostics.py`
- `apps/gateway/api/admin.py`
- `apps/gateway/api/slack.py`
- `apps/gateway/api/telegram.py`
- `apps/gateway/api/webchat.py`
- `apps/gateway/deps.py`
- `migrations/versions/`
- `tests/`

## Success Conditions
- Every `primary` session has durable collaboration state on `sessions`, with append-only notes and collaboration history stored separately.
- Inbound user messages and delegation-result continuation messages still append to transcript while `human_takeover` or `paused`, but their `execution_runs` are created in durable `blocked` state with an explicit `blocked_reason`.
- Scheduler-fired work targeting `primary` sessions follows the same collaboration-aware gating rules as other user-visible automation triggers.
- Worker claiming never picks up blocked runs, and resume releases blocked runs in deterministic queue order without duplicating logical work.
- Human takeover suppresses user-visible outbound assistant delivery at dispatch time even when the run started before takeover.
- Suppressed outbound replies do not become normal assistant transcript messages.
- Approval-required actions create one durable structured approval prompt artifact plus human-readable fallback instructions.
- Prompt rendering is split cleanly between graph-side canonical prompt creation and dispatcher or approval-service-side per-surface prompt-row materialization.
- Interactive approval decisions are handled through one backend-owned decision service that verifies provider authenticity, signed one-time tokens, prompt status, expiry, and Spec 003 exactness.
- Text approvals remain supported and continue to use the same proposal mutation semantics as interactive and admin decisions.
- Operator write routes enforce optimistic concurrency via `expected_collaboration_version`, record append-only collaboration events, and fail cleanly with `409` on stale clients.
- Operator-authored mutations persist a durable operator principal identifier rather than only proving admin access.
- Admin and diagnostics surfaces can reconstruct assignment, takeover, notes, blocked runs, suppressed deliveries, approval prompts, and approval decisions.
- Child and system sessions remain inspectable but do not gain first-class human handoff mutation flows in this slice.

## Current Codebase Constraints From Specs 001-015
- Spec 001 made `sessions` and `messages` the canonical append-only conversation record, so collaboration controls must extend session metadata and additive audit tables instead of encoding takeover as transcript text.
- Specs 002, 003, and 010 already centralize tool execution, approval exactness, and typed action identity in backend services; interactive approval UX must stay a presentation layer over those exact semantics rather than becoming a second authority.
- Spec 005 established `execution_runs` as the durable queue owner with retry on the same row, which is a good fit for `status=blocked` and later ordered release on resume.
- Specs 007, 012, and 013 already route outbound delivery through `src/channels/dispatch.py` and provider adapters, so suppression and structured approval-prompt rendering should be added there instead of pushed into graph code.
- Spec 012 kept gateway provider routes as translation boundaries, which matches the new requirement that Slack, Telegram, and Webchat callbacks normalize requests and then call one shared approval-decision service.
- Spec 013 separated delivery-side operational state from canonical transcript state, which supports dispatch-time suppression and structured approval prompt delivery without mutating transcript truth.
- Spec 014 added `session_kind` and durable session ownership; Spec 016 explicitly limits first-class collaboration controls to `session_kind=primary`.
- Spec 015 already uses internal continuation messages and durable trigger kinds, so delegation-result messages must also pass through the new collaboration-aware queue gating instead of bypassing takeover state.
- Current implementation seams line up well with the spec:
  - `SessionService.process_inbound(...)` is the canonical inbound entrypoint and current run creator
  - `JobsRepository.claim_next_eligible_run(...)` and `RunExecutionService.process_next_run(...)` own queue claim and dispatch timing
  - `graphs/nodes.py` currently emits text-only approval guidance and performs text approval decisions inline
  - `PolicyService.classify_turn(...)` currently recognizes only `approve` and `revoke`
  - `OutboundDispatcher.dispatch_run(...)` is the single outbound orchestrator
  - `apps/gateway/api/admin.py` already holds session, run, and governance read surfaces with operator auth patterns
- Main implementation gaps to close:
  - no session automation state or assignment metadata
  - no blocked run status or release path
  - no internal notes or collaboration audit tables
  - no approval prompt durability or signed action lifecycle
  - no operator mutation APIs for takeover, pause, resume, assign, notes, or approval decision
  - no dispatch-time suppression contract
  - no diagnostics that explain collaboration state transitions or suppressed work

## Migration Order
1. Extend durable queue and session state first:
   - session collaboration fields on `sessions`
   - `blocked` run state support on `execution_runs`
2. Add append-only collaboration storage:
   - `session_operator_notes`
   - `session_collaboration_events`
3. Add approval-prompt durability:
   - `approval_action_prompts`
   - optional nullable `approval_prompt_id` on `governance_transcript_events` if join precision is needed
4. Add required indexes and backfill existing sessions to:
   - `automation_state=assistant_active`
   - `collaboration_version=1`
   - null assignment fields
5. Update repositories and service contracts before wiring routes so state transitions, blocked-run release, and approval decisions are testable without HTTP.
6. Wire worker gating and dispatch suppression next so takeover is safe before interactive approval UX lands.
7. Add channel-specific approval presentation and callback ingestion after the shared approval-decision service exists.
8. Finish with admin surfaces, diagnostics, and full coverage for races, idempotency, conflicts, and fallback behavior.

## Implementation Shape
- Introduce one explicit `SessionCollaborationService` as the sole owner of:
  - takeover
  - pause
  - resume
  - assign and reassign
  - note creation
  - append-only collaboration event creation
  - ordered release of blocked runs
- Introduce one explicit `ApprovalDecisionService` as the sole owner of:
  - approval prompt creation and re-presentation
  - action token signing and hash persistence
  - prompt lifecycle transitions
  - exact proposal validation
  - idempotent approve or deny handling for text, admin, and channel-action inputs
- Keep current architectural boundaries intact:
  - inbound/provider routes normalize and authenticate transport requests
  - repositories persist state
  - `RunExecutionService` stays the only worker-owned run executor
  - `OutboundDispatcher` stays the only outbound send orchestrator
  - graph nodes still decide when approval is required, but not how approval UX is delivered
- Treat collaboration state as current state on `sessions` and immutable history in separate append-only tables.
- Treat approval prompts as presentation-state artifacts that reference the canonical governance proposal lifecycle rather than replacing it.

## Workstreams
### 1. Settings and Shared Enums
- Extend `src/config/settings.py` with:
  - `default_assignment_queue_key`
  - `approval_action_token_ttl_seconds`
  - per-channel interactive approval support flags
  - a flag controlling whether takeover suppresses in-flight outbound sends in addition to queued work
  - `operator_note_max_chars`
- Validate these settings fail closed:
  - token TTL must be positive
  - max note size must be positive
  - channel-interactive support defaults to disabled unless explicitly enabled
- Extend enum-like string domains in `src/db/models.py` and response models for:
  - `sessions.automation_state`
  - `execution_runs.status=blocked`
  - `outbound delivery` suppressed kinds or completion outcomes
  - prompt statuses such as `pending`, `approved`, `denied`, `expired`, `revoked`, `superseded`

### 2. Durable Data Model and Repositories
- Add session collaboration columns to `SessionRecord`:
  - `automation_state`
  - `assigned_operator_id`
  - `assigned_queue_key`
  - `automation_state_reason`
  - `automation_state_changed_at`
  - `assignment_updated_at`
  - `collaboration_version`
- Extend `ExecutionRunRecord` with:
  - `blocked_reason`
  - `blocked_at`
- Add new models and indexes for:
  - `SessionOperatorNoteRecord`
  - `SessionCollaborationEventRecord`
  - `ApprovalActionPromptRecord`
- Add repository helpers in `src/sessions/repository.py` and, if helpful, a small approval repository/service package for:
  - row-locked session collaboration fetch and mutation
  - optimistic version check support
  - append-only note and collaboration event creation
  - creation of blocked runs and ordered release of blocked runs
  - prompt lookup by proposal, surface, status, and token hash
  - superseding older pending prompts on the same surface
  - prompt reconciliation when the underlying proposal reaches terminal state
- Preserve append-only behavior:
  - notes are never updated or deleted
  - collaboration events are never mutated
  - blocked runs are unblocked by status transition on the same row, not by inserting duplicate runs

### 3. Collaboration Service and State Transition Contract
- Implement `SessionCollaborationService` with transactional methods for:
  - `takeover_session(...)`
  - `pause_session(...)`
  - `resume_session(...)`
  - `assign_session(...)`
  - `add_operator_note(...)`
- Each operator-authored mutation must:
  - apply only to `primary` sessions in this slice
  - lock the session row
  - receive a durable operator principal identifier from the gateway auth layer
  - require `expected_collaboration_version`
  - fail with a conflict on version mismatch before any partial write
  - increment `collaboration_version`
  - update the relevant timestamps and reason fields
  - append one collaboration event
  - optionally append a linked operator note
- Keep assignment orthogonal to automation state:
  - assignment-only changes should not imply takeover
  - takeover or pause should not force assignment changes
- On resume to `assistant_active`, release blocked runs for that session in `created_at`, then `id` order, idempotently.

### 4. Collaboration-Aware Run Creation and Queue Claiming
- Update `SessionService.process_inbound(...)` so inbound transcript append remains unchanged, but run creation becomes collaboration-aware:
  - `assistant_active` creates normal queued runs
  - `human_takeover` and `paused` create blocked runs with explicit `blocked_reason`
- Apply the same collaboration-aware run creation path to delegation-result continuation enqueueing and any other `primary` session automation triggers introduced earlier.
- Apply the same collaboration-aware run creation path to scheduler-fired runs targeting `primary` sessions so manual takeover cannot be bypassed through scheduled automation.
- Extend `JobsRepository.create_or_get_execution_run(...)` to support creating blocked runs without breaking trigger-key idempotency.
- Ensure `claim_next_eligible_run(...)` never considers `status=blocked`.
- Keep child-session and system-session flows out of first-class collaboration gating in this slice unless a primary-session continuation is being queued.

### 5. In-Flight Suppression and Delivery Semantics
- Re-check session collaboration state in `RunExecutionService.process_next_run(...)` after graph execution and before outbound dispatch.
- If the session is no longer `assistant_active` at dispatch time:
  - preserve audit continuity without appending a normal assistant transcript message for undelivered content
  - suppress user-visible outbound delivery
  - record a collaboration event linked to the run
  - mark delivery state with explicit suppressed outcome rather than `sent`
- Keep this best-effort:
  - do not interrupt the graph mid-turn
  - do block unclaimed work at queue time
  - do suppress already-running work if takeover wins before dispatch
- Update `src/channels/dispatch.py` and any repository helpers so structured approval prompts and suppressed deliveries are visible in delivery records and diagnostics.

### 6. Structured Approval Prompt Generation
- Replace approval UX that currently lives only in `state.response_text` inside `src/graphs/nodes.py`.
- When approval is required:
  - keep readable fallback text in the assistant response
  - also create one canonical structured approval prompt payload containing:
    - `proposal_id`
    - `capability_name`
    - `typed_action_id`
    - bounded canonical params preview
    - explanation text
    - supported decisions
    - fallback instructions
- Persist one `approval_action_prompts` row per rendered surface with hashed one-time approve and deny tokens only after the dispatcher or approval service knows the durable message or outbound artifact that rendered that prompt on the surface.
- Record approval-prompt governance audit linkage so diagnostics can reconstruct which prompt was shown for which proposal and message.

### 7. Shared Approval Decision Service
- Move approval decision execution out of graph-only text handling into a reusable backend service.
- The service should accept normalized submissions from:
  - text command
  - operator/admin API
  - Slack interactive callback
  - Telegram callback query
  - Webchat decision endpoint
- Shared validation sequence:
  - verify surface authenticity where applicable
  - verify signed action token and compare by durable hash
  - verify prompt is still pending and unexpired
  - verify proposal remains actionable for the same session and agent
  - apply exact Spec 003 approval or denial semantics idempotently
  - mark the winning prompt row terminal and reconcile sibling pending prompts
  - return the already-recorded outcome for duplicate callbacks or replays
- Keep fallback text approvals supported by routing them through the same decision service instead of leaving them as a separate semantic path.
- Extend `PolicyService.classify_turn(...)` carefully:
  - keep `approve <proposal_id>` and `revoke <proposal_id>` fallback behavior
  - add `deny <proposal_id>` only if needed for parity with the new decision contract and tests

### 8. Channel Rendering and Callback Ingress
- Keep `src/channels/dispatch.py` as the canonical renderer from one approval-prompt payload to channel-specific UX.
- Slack:
  - extend the adapter to render approval buttons or equivalent block actions
  - add a verified interactive callback route under `apps/gateway/api/slack.py`
- Telegram:
  - extend the adapter to render inline keyboard approvals
  - normalize callback query handling through the Telegram provider route
- Webchat:
  - include structured approval actions in poll and SSE payloads
  - add a write endpoint for authenticated decision submission
- Unsupported channels:
  - deliver only fallback plain-text instructions
  - never rely on interactivity as the sole approval path
- Provider routes should stay translation-only:
  - authenticate provider or client
  - normalize the requested decision, actor identity, and token
  - call `ApprovalDecisionService`

### 9. Admin API and Operator UX Surface
- Extend `apps/gateway/api/admin.py` with authenticated write routes for:
  - `POST /sessions/{session_id}/takeover`
  - `POST /sessions/{session_id}/pause`
  - `POST /sessions/{session_id}/resume`
  - `POST /sessions/{session_id}/assign`
  - `POST /sessions/{session_id}/notes`
  - `POST /sessions/{session_id}/governance/{proposal_id}/decision`
- Add read routes for:
  - `GET /sessions/{session_id}/notes`
  - `GET /sessions/{session_id}/collaboration`
  - `GET /sessions/{session_id}/automation`
  - `GET /sessions/{session_id}/approval-prompts`
- Extend `src/domain/schemas.py` with request and response models for:
  - collaboration state snapshots
  - note rows
  - collaboration event rows
  - approval prompt rows
  - approval decision requests
- Reuse existing operator authorization dependencies from admin and diagnostics routes.

### 10. Diagnostics and Audit Visibility
- Extend `src/observability/diagnostics.py` so run details can explain whether work was:
  - queued normally
  - blocked by takeover or pause
  - suppressed at dispatch time
- Extend session diagnostics to expose:
  - current automation state and assignment
  - active blocked-run count
  - recent collaboration events
  - approval prompt history
- Make collaboration events detailed enough to diagnose race cases:
  - takeover before claim
  - takeover after claim but before dispatch
  - resume releasing blocked work
  - duplicate interactive callbacks
- Keep operator notes internal-only in diagnostics and never feed them into model context.

## Testing Strategy
### Unit Tests
- Session collaboration service state transitions, version conflicts, and append-only event creation.
- Blocked-run creation and ordered release behavior.
- Approval prompt lifecycle rules:
  - one pending prompt per proposal/surface
  - supersede on re-presentation
  - reconcile siblings on terminal decision
  - duplicate callback idempotency
- Signed token generation, hashing, verification, and expiry handling.
- Policy and graph behavior for approval-required turns with structured prompt creation plus fallback text.

### Integration Tests
- Inbound message while `assistant_active` creates a normal queued run.
- Inbound message while `human_takeover` or `paused` appends transcript and creates a blocked run.
- Resume releases blocked runs once and in order.
- Run claimed before takeover persists transcript but suppresses outbound delivery when takeover happens before dispatch.
- Text approval fallback still approves exactly the same proposal as interactive/admin approval.
- Slack, Telegram, and Webchat callback normalization paths all reach the shared approval-decision service and enforce signature or token verification.
- Admin operator routes require auth, enforce `expected_collaboration_version`, and return `409` on stale writes.
- Child sessions remain excluded from first-class takeover mutation routes.

### Regression Coverage
- Existing session identity, transcript append, approval exactness, streaming delivery, and delegation flows continue to work when collaboration state is left at the default `assistant_active`.
- Existing diagnostics and pending-approval reads continue to function with the added fields.

## Recommended Implementation Sequence
1. Migrations and ORM models for collaboration state, blocked runs, notes, events, and approval prompts.
2. Repository helpers plus `SessionCollaborationService` with full state transition tests.
3. Collaboration-aware run creation and blocked-run release.
4. Worker-side dispatch suppression and delivery-state changes.
5. Shared `ApprovalDecisionService` and prompt persistence.
6. Graph and policy changes so approval-required turns emit structured prompts plus fallback text.
7. Channel dispatch rendering and channel callback ingress.
8. Admin write and read routes plus request/response schemas.
9. Diagnostics expansion and final race-condition coverage.

## Plan Review
- The plan covers each required contract from Spec 016:
  - durable collaboration state
  - blocked queue semantics
  - dispatch-time suppression
  - structured approval prompt artifacts
  - exact and idempotent interactive approvals
  - operator mutation APIs
  - diagnostics and auditability
- The dependency ordering is safe for implementation because the highest-risk correctness primitives land first:
  - schema and repository changes before route work
  - queue and dispatch enforcement before UI affordances
  - shared decision services before per-channel callbacks
- No step requires violating earlier spec boundaries:
  - session identity stays on Spec 001 rules
  - approval exactness stays on Spec 003 rules
  - worker ownership stays on Spec 005
  - channel translation boundaries stay on Spec 012
  - streaming remains additive per Spec 013
  - child-session behavior from Spec 015 is preserved
- The remaining design choice to keep explicit during implementation is where to place the approval-prompt repository logic:
  - either inside `src/sessions/repository.py` for expedience
  - or in a small dedicated approval/governance service module for clearer ownership
  - either path is implementable as long as one backend-owned decision service remains the single authority
