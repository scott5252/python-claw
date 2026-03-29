# Tasks 016: Human Handoff, Collaboration, and Approval UX

## Implementation Readiness Review

- The spec is implementable on the current codebase because Specs 001 through 015 already established the required foundation:
  - Spec 001 made `sessions` and `messages` the canonical append-only conversation record
  - Spec 003 made approval scope exact on proposal, session, agent, typed action, and canonical params
  - Spec 005 made `execution_runs` the durable queue owner with idempotent trigger semantics and worker-owned execution
  - Specs 007, 012, and 013 centralized outbound delivery and channel translation in `src/channels/dispatch.py` and the gateway channel routes
  - Spec 014 added durable `owner_agent_id`, `session_kind`, and per-run execution binding persistence
  - Spec 015 added child-session and continuation flows that now need collaboration-aware gating when they re-enter a `primary` session
- The current runtime seams line up well with Spec 016:
  - `src/sessions/service.py` is already the canonical inbound entry point and the right place to append transcript state while delegating queue gating to a collaboration-aware helper
  - `src/jobs/repository.py` already owns durable run creation and claim semantics and is the natural seam for `status=blocked`
  - `src/jobs/service.py` is already the single worker-owned execution path and the safest place to re-check collaboration state before outbound dispatch
  - `src/channels/dispatch.py` is already the only outbound orchestrator and should become the renderer for structured approval prompts and suppressed outcomes
  - `src/graphs/nodes.py` already decides when approval is required, but currently still emits text-only approval guidance and inline text approval handling
  - `apps/gateway/api/admin.py` already hosts operator-protected read surfaces and should gain the new collaboration and approval write routes
  - `apps/gateway/api/slack.py`, `apps/gateway/api/telegram.py`, and `apps/gateway/api/webchat.py` already form the transport translation boundary where interactive approval callbacks can be normalized before calling one shared backend decision service
- The highest-risk implementation failures to prevent are:
  - allowing inbound or delegation-result work to bypass takeover state and queue normally
  - allowing scheduler-fired work for a `primary` session to bypass takeover state and queue normally
  - letting a run claimed before takeover still send a user-visible reply because queue-time blocking was the only enforcement
  - persisting a suppressed reply as a normal assistant transcript message and thereby leaking undelivered content into future context assembly
  - storing collaboration state only in worker memory or only in transcript text and making race-sensitive enforcement non-durable
  - allowing stale operator clients to overwrite newer takeover, pause, resume, or assignment decisions without conflict detection
  - turning structured approval prompts into a second approval authority instead of a presentation layer over Spec 003 exactness
  - trusting interactive callbacks based only on visible `proposal_id` instead of signed one-time tokens and backend-owned prompt state
  - materializing approval prompt rows before the rendered assistant message or outbound artifact is known, leaving prompt audit linkage ambiguous
  - leaking operator notes into normal model context or outbound user delivery
  - proving only admin access without persisting a durable operator principal identifier for assignees, note authors, and operator decisions
  - introducing first-class takeover mutations for child sessions instead of preserving the `primary`-session-only boundary from the spec
- The tasks below are ordered to prove the highest-risk correctness rules first, then add the durable data model, then land the collaboration and approval services, then wire worker, channel, admin, diagnostics, and integration behavior through the existing architecture.

## Tasks

1. Confirm the current collaboration, queue, approval, dispatch, and admin seams in `src/config/settings.py`, `src/db/models.py`, `src/domain/schemas.py`, `src/sessions/repository.py`, `src/sessions/service.py`, `src/jobs/repository.py`, `src/jobs/service.py`, `src/channels/dispatch.py`, `src/channels/adapters/slack.py`, `src/channels/adapters/telegram.py`, `src/channels/adapters/webchat.py`, `src/graphs/state.py`, `src/graphs/nodes.py`, `src/policies/service.py`, `src/security/signing.py`, `src/observability/diagnostics.py`, `apps/gateway/api/admin.py`, `apps/gateway/api/slack.py`, `apps/gateway/api/telegram.py`, `apps/gateway/api/webchat.py`, and `apps/gateway/deps.py` so Spec 016 extends the existing session, queue, worker, governance, channel, and diagnostics architecture rather than introducing parallel flows.
2. Add high-risk migration and repository tests first proving `sessions` collaboration fields backfill to `automation_state=assistant_active`, `collaboration_version=1`, null assignment metadata, and stable timestamps for existing rows without changing session identity or ownership semantics from Specs 001 and 014.
3. Add high-risk repository tests first proving `execution_runs` supports first-class `status=blocked`, persists `blocked_reason` and `blocked_at`, excludes blocked rows from normal eligibility scans, and can release blocked rows in deterministic `created_at` then `id` order without duplicating logical work.
4. Add high-risk repository tests first proving `session_operator_notes` and `session_collaboration_events` stay append-only, preserve note-to-event linkage, support the required session, actor, and timeline lookups, and never mutate or delete historical rows.
5. Add high-risk repository and service tests first proving operator-authored collaboration mutations require `expected_collaboration_version`, fail with no partial write on mismatch, serialize on the session row, increment `collaboration_version`, and append exactly one collaboration event per successful state or assignment mutation.
6. Add high-risk service tests first proving inbound user messages and delegation-result continuation messages still append transcript state while `human_takeover` or `paused`, but create blocked runs with explicit `blocked_reason` instead of normal queued work.
7. Add high-risk service tests first proving scheduler-fired runs for `primary` sessions follow the same collaboration-aware blocking and ordered-release semantics as inbound and delegation-result triggers.
8. Add high-risk service tests first proving resume to `assistant_active` releases previously blocked work idempotently and in durable queue order, without creating duplicate runs, duplicate continuation messages, or duplicate triggers when retries or concurrent resumes occur.
9. Add high-risk worker tests first proving a run claimed before takeover may still finish graph execution, but outbound delivery is suppressed when the session is no longer `assistant_active` at dispatch time, with a durable suppressed delivery outcome, one collaboration event explaining the race, and no normal assistant transcript row for undelivered content.
10. Add high-risk service tests first proving collaboration controls fail closed for `child` and `system` sessions, keeping first-class mutation routes scoped to `session_kind=primary` in this slice.
11. Add high-risk approval prompt lifecycle tests first proving there is at most one `pending` prompt per `(proposal_id, session_id, agent_id, channel_kind, transport_address_key)` surface, re-presentation supersedes older pending prompts on the same surface, and terminal decisions reconcile sibling pending prompts deterministically.
12. Add high-risk approval prompt materialization tests first proving per-surface prompt rows are created only after the rendered assistant message or outbound artifact is known and linked durably.
13. Add high-risk approval decision tests first proving text commands, admin decisions, Slack callbacks, Telegram callbacks, and Webchat decisions all route through one shared semantic path, remain exact to proposal and agent identity, reject expired or mismatched tokens, and return the already-recorded durable outcome on duplicate callback replay.
14. Extend `src/config/settings.py` with collaboration settings for `default_assignment_queue_key`, `approval_action_token_ttl_seconds`, per-channel interactive-approval support flags, `takeover_suppresses_inflight_dispatch`, and `operator_note_max_chars`, with fail-closed validation for positive bounds and disabled-by-default interactive behavior.
15. Keep deterministic text approvals from Spec 003 as a required fallback in settings and service wiring even when interactive approvals are enabled for a channel.
16. Extend enum-like validated domains in `src/db/models.py` and related runtime contracts for `sessions.automation_state`, `execution_runs.status=blocked`, approval prompt statuses, approval decision sources, and explicit outbound delivery suppressed or approval-prompt outcomes.
17. Extend `src/db/models.py` and add a migration under `migrations/versions/` for the additive collaboration durability contract:
    - add session collaboration columns on `sessions`
    - add `blocked_reason` and `blocked_at` to `execution_runs`
    - add `session_operator_notes`
    - add `session_collaboration_events`
    - add `approval_action_prompts`
    - add required indexes and any optional nullable `approval_prompt_id` governance linkage only if needed for precise audit joins
18. Preserve additive migration safety by backfilling collaboration defaults before enforcing final non-null constraints and by not changing canonical session keys, historical transcript rows, or exact approval records from earlier specs.
19. Extend `src/domain/schemas.py` with explicit request and response models for:
    - collaboration state snapshots
    - automation detail reads
    - operator notes
    - collaboration events
    - collaboration write requests carrying `expected_collaboration_version`
    - approval prompt rows
    - normalized approval decision requests and responses
20. Extend `src/sessions/repository.py` with collaboration-aware helpers for row-locked session reads, optimistic-version-checked state mutations, assignment updates, append-only note insertion, append-only collaboration-event insertion, blocked-run release queries, approval prompt persistence, prompt lookup by token hash, and prompt reconciliation when proposal state changes.
21. Keep note and collaboration-event persistence append-only and ensure repository helpers never update or delete prior note rows, event rows, transcript messages, delivery attempts, approvals, or proposals.
22. Introduce `SessionCollaborationService` as the sole owner of takeover, pause, resume, assignment, note creation, collaboration-event recording, blocked-run release, and collaboration-aware run enqueue policy for `primary` sessions.
23. Implement transactional collaboration service methods for `takeover_session(...)`, `pause_session(...)`, `resume_session(...)`, `assign_session(...)`, and `add_operator_note(...)`, each requiring `expected_collaboration_version`, updating timestamps and reason fields, appending exactly one collaboration event plus an optional linked note, and persisting a durable operator principal identifier for operator-authored actions.
24. Keep assignment orthogonal to automation state in the collaboration service so assignment-only changes do not imply takeover, and takeover or pause do not force assignment changes unless explicitly requested.
25. Update `src/sessions/service.py` so `process_inbound(...)` remains the canonical transcript append entry point, but delegates run creation to a collaboration-aware path that creates normal queued runs only when the session is `assistant_active` and durable blocked runs otherwise.
26. Apply the same collaboration-aware run creation path to delegation-result continuation enqueueing, scheduler-fired `primary`-session work, and any other `primary`-session automation triggers already introduced by Specs 005 and 015 so takeover state cannot be bypassed through internal continuation flows or scheduled automation.
27. Extend `src/jobs/repository.py` so `create_or_get_execution_run(...)` can create blocked runs on the same durable row and trigger identity contract, and make `claim_next_eligible_run(...)` ignore blocked rows completely.
28. Add an explicit blocked-run release helper in `src/jobs/repository.py` that transitions eligible blocked rows back to `queued` idempotently, in durable order, without creating new run rows.
29. Refactor `src/jobs/service.py` so `RunExecutionService.process_next_run(...)` reloads the current session collaboration state after graph execution and before outbound dispatch, suppressing user-visible outbound delivery when the session is no longer `assistant_active`.
30. When dispatch-time suppression occurs, preserve audit continuity without appending a normal assistant transcript message for undelivered content, append one collaboration event linked to the run, and mark delivery artifacts with explicit suppressed outcomes rather than `sent`.
31. Keep dispatch-time suppression best-effort and non-destructive by not interrupting graphs mid-turn, not deleting prior transcript rows, and not cancelling already-running work solely because takeover happened after claim.
32. Extend `src/channels/dispatch.py` and supporting repository helpers so the dispatcher can render structured approval prompt payloads, write durable approval-prompt delivery records, and represent suppressed delivery outcomes in a way diagnostics can inspect without re-parsing transcript text.
33. Introduce one shared `ApprovalDecisionService` as the sole owner of approval prompt creation, signed token issuance and hash persistence, prompt status transitions, exact proposal validation, idempotent approve or deny handling, sibling-prompt reconciliation, and decision-source normalization for text, admin, and channel-action inputs.
34. Implement signed approval action token generation and verification in `src/security/signing.py` or a focused approval module so the server stores only token hashes durably, enforces expiry, and never approves work from callback payload display fields alone.
35. Refactor `src/graphs/nodes.py` so approval-required turns still create readable fallback assistant text, but also create one canonical structured approval prompt payload containing `proposal_id`, `capability_name`, `typed_action_id`, bounded canonical params preview, explanation text, explicit supported decisions, and fallback plain-text instructions.
36. Persist one `approval_action_prompts` row per rendered approval surface only after the rendered assistant message or outbound artifact is known, including hashed approve and deny token material, current prompt status, presentation payload, expiry, and decision metadata needed for audit and idempotent replay.
37. Route fallback text approvals through the new shared approval-decision service instead of leaving text approval as a graph-only semantic branch, while preserving the exact Spec 003 approval and activation behavior.
38. Extend `src/policies/service.py` carefully so `approve <proposal_id>` fallback remains supported, `revoke <proposal_id>` behavior is preserved, and `deny <proposal_id>` is added only if required for parity with the new approval-decision contract and tests.
39. Keep `src/channels/dispatch.py` as the only renderer from one structured approval prompt payload to channel-specific UX:
    - Slack renders buttons or equivalent actions when interactive approvals are enabled
    - Telegram renders inline keyboard actions when interactive approvals are enabled
    - Webchat exposes structured approval actions in poll and SSE payloads when interactive approvals are enabled
    - unsupported channels fall back to plain text instructions only
40. Extend `apps/gateway/api/slack.py`, `apps/gateway/api/telegram.py`, and `apps/gateway/api/webchat.py` with authenticated approval-decision ingress that verifies provider or client authenticity, normalizes decision submissions, and delegates exact approval handling to `ApprovalDecisionService` instead of mutating proposals directly in the route layer.
41. Add a Webchat approval decision write endpoint and ensure the existing poll and SSE read surfaces can return structured approval action payloads without inventing a browser-local approval state store.
42. Extend `apps/gateway/api/admin.py` with operator-protected write routes for `POST /sessions/{session_id}/takeover`, `POST /sessions/{session_id}/pause`, `POST /sessions/{session_id}/resume`, `POST /sessions/{session_id}/assign`, `POST /sessions/{session_id}/notes`, and `POST /sessions/{session_id}/governance/{proposal_id}/decision`, all enforcing `expected_collaboration_version` where required and returning `409` on stale writes.
43. Extend `apps/gateway/api/admin.py` with operator-protected read routes for `GET /sessions/{session_id}/notes`, `GET /sessions/{session_id}/collaboration`, `GET /sessions/{session_id}/automation`, and `GET /sessions/{session_id}/approval-prompts`, while also extending existing session reads with the new collaboration state and assignment fields.
44. Reuse the existing operator authorization dependencies in `apps/gateway/deps.py` and dependency wiring so collaboration services, approval-decision services, dispatcher collaborators, and diagnostics expansion are injected explicitly without hidden globals.
45. Extend `src/observability/diagnostics.py` so run detail can explain whether work was queued normally, blocked by collaboration state, or suppressed at dispatch time, and can surface the relevant blocked reason, suppression reason, and prompt or collaboration links where applicable.
46. Extend session diagnostics and admin read surfaces so operators can inspect current automation state, assignment metadata, active blocked-run counts, recent collaboration events, operator notes, approval prompt history, and the durable decision trail for structured approvals.
47. Keep operator notes internal-only by excluding them from normal model context assembly, outbound user delivery, and any channel-facing payloads unless a later spec explicitly authorizes otherwise.
48. Add repository, service, and API tests proving collaboration mutation routes are operator-protected, reject non-operator callers by default, and fail cleanly with `409` plus no partial mutation when `expected_collaboration_version` is stale.
49. Add integration tests proving inbound traffic while `assistant_active` creates normal queued runs, inbound traffic while `human_takeover` or `paused` appends transcript and creates blocked runs, and resume releases blocked runs once and in order.
50. Add integration tests proving delegation-result continuation messages for `primary` sessions respect collaboration-aware blocking and ordered release semantics instead of bypassing takeover state through Spec 015 internal continuation flows.
51. Add worker and integration tests proving takeover after claim but before dispatch produces transcript continuity plus suppressed outbound delivery, explicit suppressed delivery records, and collaboration-event visibility in diagnostics.
52. Add graph, service, and integration tests proving approval-required turns emit both fallback text and structured prompt artifacts, one pending prompt per proposal surface is enforced, duplicate callback replay is idempotent, and terminal decisions reconcile sibling pending prompts correctly.
53. Add channel integration tests proving Slack, Telegram, and Webchat callback normalization all reach the shared approval-decision service, verify authenticity and signed tokens, and never approve based only on visible `proposal_id`.
54. Add regression coverage proving existing session identity, transcript append, pending-approval reads, exact approval semantics, streaming delivery, child-session delegation behavior, and diagnostics continue to work when collaboration state remains at the default `assistant_active`.
55. Update operator-facing docs only after behavior lands so the documented takeover, pause, resume, assignment, notes, approval prompt UX, interactive callback support, blocked-run semantics, dispatch suppression behavior, and child-session non-goals match the implemented feature.
56. Finish with a final implementation review against `specs/016-human-handoff-collab-and-ux/spec.md` and `specs/016-human-handoff-collab-and-ux/plan.md`, confirming the delivered work keeps current collaboration state on `sessions` plus immutable append-only history in dedicated tables, preserves Spec 001 canonical session identity, preserves Spec 003 exact approval semantics across text, admin, and interactive decisions, preserves Spec 005 worker ownership and durable queue semantics, preserves Spec 012 channel translation boundaries, preserves Spec 013 streaming and delivery architecture, preserves Spec 015 child-session boundaries, blocks new automation durably during takeover or pause, suppresses already-running outbound replies when takeover wins before dispatch, keeps operator notes internal-only, and fails closed when collaboration or interactive approval wiring is absent or invalid.

## Final Task Review

- Coverage against the spec is complete:
  - durable `sessions` collaboration state and assignment metadata
  - durable blocked-run queue semantics on `execution_runs`
  - append-only operator notes and collaboration events
  - dispatch-time suppression for already-running work
  - structured approval prompt artifacts with signed one-time action tokens
  - one shared approval-decision service for text, admin, and channel actions
  - operator mutation APIs and collaboration reads
  - diagnostics for blocked, suppressed, assigned, and approval-prompt state
- Coverage against the current codebase is concrete:
  - tasks anchor run gating in `src/sessions/service.py`, `src/jobs/repository.py`, and `src/jobs/service.py`
  - tasks keep outbound presentation in `src/channels/dispatch.py` and channel routes as translation-only boundaries
  - tasks reuse the existing admin and diagnostics seams instead of inventing a separate operator control plane
  - tasks preserve Spec 015 delegation continuations while making them collaboration-aware when they target `primary` sessions
- The task list should support successful implementation of Spec 016 because it forces the team to prove the hardest invariants first:
  - durable blocked-run creation and ordered release
  - dispatch-time suppression when takeover wins the race after claim
  - optimistic concurrency for operator actions with no partial writes
  - exact, signed, idempotent approval decisions across every ingress path
  - strict separation between internal operator notes and user-visible or model-visible conversation state
