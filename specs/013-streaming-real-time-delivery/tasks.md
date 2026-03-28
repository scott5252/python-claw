# Tasks 013: Streaming and Real-Time Delivery

## Implementation Readiness Review

- The spec and plan are implementable against the current codebase, but the work must explicitly separate four concerns that are still collapsed today:
  - final-answer generation versus tool-planning execution in `src/graphs/nodes.py`
  - final transcript persistence versus outbound delivery in `src/jobs/service.py` and `src/graphs/nodes.py`
  - whole-message dispatch versus streamed-attempt orchestration in `src/channels/dispatch.py`
  - whole-message webchat polling versus real-time SSE replay in `apps/gateway/api/webchat.py`
- The highest-risk implementation failures to guard against are:
  - letting partial text become canonical transcript truth
  - allowing graph code or gateway handlers to own live streaming directly
  - degrading a post-first-delta stream into a whole-message send within the same attempt
  - making SSE depend on in-memory worker state instead of durable stream-event rows
  - accidentally attempting to stream reply or media-bearing responses that still require whole-message dispatch semantics
  - leaving client restart behavior ambiguous when a later attempt replaces a partially emitted response
- The tasks below are structured to lock down those invariants first with tests, then add the persistence and dispatch seams, then wire provider and worker orchestration, and only then expose browser-facing SSE.

## Tasks

1. Confirm the current streaming-touching seams in `src/providers/models.py`, `src/graphs/state.py`, `src/graphs/nodes.py`, `src/graphs/assistant_graph.py`, `src/jobs/service.py`, `src/channels/dispatch.py`, `src/channels/adapters/base.py`, `src/channels/adapters/webchat.py`, `apps/gateway/api/webchat.py`, `src/sessions/repository.py`, `src/db/models.py`, and the existing `tests/` coverage so Spec 013 extends the worker-owned, dispatcher-owned, append-only architecture instead of creating a second runtime or delivery path.
2. Add high-risk repository tests first proving one streamed assistant response uses one stable logical `outbound_delivery` identity, append-only attempts, and append-only ordered stream events, with unique `(attempt_id, sequence_number)` enforcement, ordered replay, bounded text reconstruction, and stable reuse across retry.
3. Add high-risk dispatcher tests first proving the streaming-aware dispatcher persists `stream_started` and `text_delta` events before fan-out through committed dispatcher-owned short transactions, keeps fallback to non-streaming legal only before the first durable `text_delta`, creates a new attempt after post-first-delta failure, and never creates a second logical assistant-response identity for the same turn.
4. Add high-risk worker-orchestration tests first proving partial output can be emitted only during the final answer phase, planning or tool execution does not surface raw provider deltas, the final assistant transcript row is committed only after authoritative final completion, and runs that emitted partial output but never durably completed remain non-success runs.
5. Add high-risk webchat API tests first proving SSE is scoped by `(channel_account_id, stream_id)`, authenticates through the existing webchat client token boundary, replays from durable cursor state via `Last-Event-ID` or equivalent, coexists with Spec 012 polling, resets the client-visible in-progress response when a newer attempt starts for the same `delivery_id`, and never exposes provider-native payloads or backend-only ownership identifiers as the subscription key.
6. Extend `src/db/models.py` and add a migration under `migrations/versions/` for the additive streaming durability contract:
   - extend `outbound_deliveries` with bounded streaming-aware delivery metadata and a distinct streaming text delivery kind
   - extend `outbound_delivery_attempts` with stream lifecycle status, optional provider stream identifier, last emitted sequence number, and bounded completion or interruption metadata
   - add `outbound_delivery_stream_events` with append-only ordered events, bounded payload JSON, and the required uniqueness and lookup indexes
   - preserve `messages` as the only canonical transcript store
7. Extend `src/sessions/repository.py` with streaming repository helpers for creating or reusing logical streamed deliveries, creating stream attempts, appending ordered events, updating attempt lifecycle state, replaying events by attempt and by `(channel_account_id, stream_id)`, reconstructing emitted text deterministically, and exposing bounded fallback-eligibility checks derived from durable state rather than in-memory flags.
8. Add repository coverage for the new helpers in `tests/test_repository.py` or a dedicated streaming repository test module, including event ordering, attempt transitions, replay pagination or cursor semantics, stream-text reconstruction, attempt reuse rules, and retry-safe behavior after failure or interruption.
9. Extend `src/channels/adapters/base.py` additively so `ChannelCapabilities` can declare `supports_streaming_text`, `supports_stream_finalize`, and `supports_stream_abort`, and so the adapter seam exposes bounded streaming transport methods such as begin, append, finalize, and abort without leaking sockets, SDK stream objects, or provider-native callbacks outside the adapter boundary.
10. Add adapter-contract tests first proving non-streaming adapters can remain on the existing whole-message path, streaming-capable adapters can report unsupported operations cleanly, and structured streaming transport results or failures stay bounded and provider-agnostic.
11. Refactor `src/channels/dispatch.py` so the dispatcher remains the sole outbound orchestrator while gaining a streaming-aware lifecycle that can:
   - create or reuse one logical streamed delivery
   - create append-only attempts with explicit stream states
   - append durable stream events before transport or SSE fan-out using short dispatcher-owned commit boundaries
   - open, append, finalize, fail, cancel, or interrupt attempts
   - reject or downgrade ineligible response shapes such as reply directives, media refs, voice refs, or structured outbound intents to the existing whole-message path before the first durable `text_delta`
   - fall back to the existing whole-message path only before the first durable `text_delta`
   - recover post-first-delta failures by opening a new attempt under the same logical delivery
12. Keep `src/channels/dispatch_registry.py` and channel-account resolution compatible with the existing Spec 012 registry while allowing capability-based selection of streaming versus non-streaming behavior without introducing adapter-owned orchestration or account-specific streaming side channels.
13. Extend `src/channels/adapters/webchat.py` to support the backend-owned streaming transport contract using the existing durable `stream_id`, while preserving whole-message polling compatibility and keeping the browser transport a read surface over durable backend events instead of the source of truth.
14. Leave `src/channels/adapters/slack.py` and `src/channels/adapters/telegram.py` on capability-declared non-streaming behavior unless a clean reuse of the same dispatcher contract is available; if they remain non-streaming in this slice, add explicit tests proving they continue to use the existing whole-message delivery path safely.
15. Extend `src/providers/models.py` additively with one final-answer streaming seam alongside `complete_turn(...)`, translating provider-native streaming responses into ordered backend-owned text deltas plus one authoritative final aggregate result and bounded execution metadata indicating streaming, degradation, or fallback.
16. Add provider-runtime tests in `tests/test_provider_runtime.py` covering final-answer streaming translation, no-delta fallback for non-streaming providers, bounded execution metadata for manifests and diagnostics, and the guarantee that tool-planning deltas or other provider-native internal events do not escape the provider seam as user-visible stream events.
17. Extend `src/graphs/state.py` only as needed with bounded streaming metadata describing whether the turn is streaming-eligible, whether final-answer streaming was used or fell back, and summary metadata needed by the worker or diagnostics, while keeping raw provider stream objects and live transport state out of `AssistantState`.
18. Refactor `src/graphs/nodes.py` and `src/graphs/assistant_graph.py` so backend-owned planning, approval, validation, tool execution, and prompt assembly remain unchanged in authority but the final answer phase becomes a distinct seam that can execute through either one-shot completion or final-answer streaming without graph code directly owning outbound event fan-out.
19. Move final assistant transcript persistence responsibility out of the graph-only happy path so the implementation can delay the canonical assistant message write until the worker has an authoritative final aggregate answer, while still preserving append-only transcript semantics and context-manifest persistence.
20. Add runtime tests in `tests/test_runtime.py`, `tests/test_integration.py`, or new streaming-focused test modules proving tool-using turns may stream only after tools finish, text-only turns may stream immediately at answer generation, and approval or governance flows remain backend-owned and non-streaming.
21. Refactor `src/jobs/service.py` so `RunExecutionService` remains the owner of streaming lifecycle execution inside a claimed run, explicitly sequencing pre-stream work, streamed or non-streamed final answer generation, final transcript persistence, delivery finalization, and after-turn job enqueueing, while keeping delivery-side stream commits separate from the final worker-owned transcript and run completion transaction.
22. Add worker failure-path tests proving pre-first-delta stream setup failures can fall back to whole-message delivery under the same logical response identity, post-first-delta failures mark the active attempt failed or interrupted and require retry via a new attempt, transcript persistence failures fail closed even if delivery activity began, and interrupted streams do not fabricate completed assistant transcript rows.
23. Extend `apps/gateway/api/webchat.py` with an authenticated SSE endpoint scoped by `(channel_account_id, stream_id)` that reads durable event rows, supports replay from a monotonic cursor, emits bounded SSE envelopes containing `event_id`, `delivery_id`, `attempt_id`, `sequence_number`, `event_kind`, and bounded payload fields, treats a newer attempt's `stream_started` for the same `delivery_id` as a client-visible reset signal, and preserves the existing poll route for replay and non-streaming fallback.
24. Extend `src/domain/schemas.py` only as needed with explicit bounded wire models for webchat SSE events, reconnect cursors, and any additive streaming diagnostics payloads, while keeping backend run ownership and control fields out of client-controlled inputs.
25. Extend `apps/gateway/deps.py` and any supporting dependency wiring so the gateway can construct the streaming-aware webchat read surface and any dispatcher or repository collaborators needed for durable event replay without hidden globals or process-local pubsub assumptions.
26. Add API tests for webchat SSE authentication, empty-stream behavior, incremental replay after reconnect, coexistence with the existing poll endpoint, and the guarantee that the SSE surface is derived from persisted rows rather than worker-local memory.
27. Extend `src/observability/logging.py`, `src/observability/failures.py`, and `src/observability/diagnostics.py` so operators can inspect stream open, first delta, progress, finalize, fallback, failure, cancellation, interruption, attempt counts, last emitted sequence number, and whether a final assistant transcript row exists, all in bounded redacted form.
28. Add observability and diagnostics tests proving streaming and fallback states are correlated to `trace_id`, `execution_run_id`, `session_id`, delivery identity, and attempt identity, while raw provider token payloads, secrets, and unbounded partial text are not exposed.
29. Update configuration in `src/config/settings.py` and `.env.example` only as needed for safe bounded streaming controls such as enabling runtime streaming, enabling webchat SSE, replay limits, and optional heartbeat or idle timeout values, with defaults that remain safe for local development and CI.
30. Add end-to-end integration coverage proving streamed text can become visible to a webchat client before run completion from committed delivery-side event rows, the final assistant transcript is persisted only once after successful completion, poll fallback still works when SSE is unavailable, retry after partial failure creates a new attempt under the same logical delivery and resets the client-visible in-progress response, and cancelled or interrupted streams remain diagnosable without claiming transcript success.
31. Add regression coverage proving unsupported channels and disabled streaming settings continue to use the existing whole-message delivery path, existing Spec 012 webchat polling remains valid, and current non-streaming provider behavior still passes under the additive streaming seam.
32. Update any relevant developer-facing docs such as `README.md` only after behavior is implemented so the documented runtime and webchat delivery contracts match the shipped streaming design, especially the distinction between canonical transcript truth and delivery-side partial state.
33. Finish with a final implementation review against `specs/013-streaming-real-time-delivery/spec.md` and `specs/013-streaming-real-time-delivery/plan.md`, confirming the tasks and resulting implementation preserve gateway-first ingress, worker-owned run execution, dispatcher-owned delivery orchestration, append-only transcript truth, durable pre-fan-out event persistence, pre-first-delta-only fallback, webchat SSE replay by durable cursor, and retry-safe recovery via new attempts rather than mutable transcript or transport state.

## Final Task Review

- Coverage against the spec is complete:
  - provider streaming seam
  - graph and worker orchestration changes
  - dispatcher and adapter lifecycle changes
  - additive persistence and replay
  - webchat SSE contract
  - observability, diagnostics, fallback, cancellation, and retry
- Coverage against the current codebase is concrete:
  - tasks target the modules that currently own transcript writes, delivery orchestration, provider completion, and webchat polling
  - tasks explicitly call out the needed ownership shift where current code is too eager to persist the final assistant message or too limited to whole-message dispatch
- The task list is implementation-ready because it specifies:
  - which risks must be tested first
  - which seams must remain authoritative
  - which fallback and retry boundaries are allowed
  - which response shapes are intentionally ineligible for streaming in this slice
  - which transaction boundary makes live SSE visibility compatible with worker-owned run completion
  - which modules need additive changes rather than replacements
- The task list should support successful implementation of Spec 013 without under-specifying the hardest parts of the slice.
