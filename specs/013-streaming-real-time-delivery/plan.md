# Plan 013: Streaming and Real-Time Delivery

## Target Modules
- `src/providers/models.py`
- `src/graphs/state.py`
- `src/graphs/assistant_graph.py`
- `src/graphs/nodes.py`
- `src/jobs/service.py`
- `src/channels/adapters/base.py`
- `src/channels/adapters/webchat.py`
- `src/channels/adapters/slack.py` only if the slice enables live adapter behavior beyond capability declaration
- `src/channels/adapters/telegram.py` only if the slice enables live adapter behavior beyond capability declaration
- `src/channels/dispatch.py`
- `src/channels/dispatch_registry.py`
- `src/sessions/repository.py`
- `src/db/models.py`
- `src/domain/schemas.py`
- `src/config/settings.py`
- `src/observability/failures.py`
- `src/observability/logging.py`
- `src/observability/diagnostics.py`
- `apps/gateway/api/webchat.py`
- `apps/gateway/deps.py`
- `migrations/versions/`
- `tests/`

## Success Conditions
- The worker can emit live assistant text only during the final answer phase while preserving the existing backend-owned tool-planning, approval, validation, and tool-execution flow.
- `messages` remain the only canonical assistant transcript truth, and successful turns still persist exactly one final assistant message row after final answer completion.
- Partial output is stored only as additive operational delivery state tied to `outbound_deliveries`, `outbound_delivery_attempts`, and a new ordered stream-event table.
- Stream-event rows become durably visible to SSE and other replay readers through dispatcher-owned short transactions rather than relying on one long-lived worker transaction.
- Streaming-capable channels use one stable logical delivery identity plus append-only attempts and append-only stream events rather than mutable transcript rows or per-token delivery rows.
- Streaming remains bounded to plain-text assistant responses in this slice; replies, media refs, voice refs, and structured outbound intents continue through the whole-message dispatch path.
- The dispatcher remains the only outbound orchestration boundary and owns stream setup, event persistence, live fan-out, finalization, failure, cancellation, and pre-first-delta fallback to the existing whole-message path.
- `webchat` gains a concrete authenticated SSE surface scoped by `(channel_account_id, stream_id)` with reconnect based on a durable monotonic event cursor, while the existing Spec 012 polling endpoint remains intact for replay and fallback.
- A restarted attempt for the same logical streamed delivery is replayed to browser clients as a reset or replace of the in-progress response once the new attempt emits `stream_started`.
- Retry, cancellation, and worker recovery all derive from durable run, delivery, attempt, and stream-event state rather than in-memory provider cursors.
- The implementation remains testable with fakes or stubs and does not require live provider streaming connectivity in the default suite.

## Migration Order
1. Define the streaming data contract first:
   - additive delivery and attempt status fields
   - one append-only `outbound_delivery_stream_events` table
   - repository helpers for ordered append, replay, attempt lookup, and text reconstruction
2. Extend the adapter and dispatcher seams before touching runtime orchestration:
   - capability flags for streaming support
   - bounded adapter methods for open, append, finalize, and abort
   - dispatcher-owned stream lifecycle methods that persist before fan-out
3. Add the provider final-answer streaming seam additively alongside the existing one-shot path:
   - keep `complete_turn(...)` intact
   - add one final-answer streaming contract that yields ordered backend-owned deltas plus one authoritative final aggregate result
4. Wire graph and worker ownership next:
   - keep planning and tool work unchanged
   - start user-visible streaming only once final answer generation begins
   - persist the final assistant transcript row only after successful final aggregate completion
5. Add `webchat` SSE last, after durable event storage exists:
   - build the wire contract on durable stream events
   - support reconnect via event cursor
   - preserve Spec 012 polling as fallback and replay
6. Finish with observability, diagnostics, and failure-path coverage so active streaming, interruption, fallback, and recovery are explainable before rollout.

## Implementation Shape
- Preserve the current ownership model already present in the codebase:
  - `RunExecutionService` owns claimed-run lifecycle and terminal run transitions
  - graph code owns context assembly, prompt construction, policy checks, and tool execution
  - the dispatcher owns all outbound delivery orchestration
  - channel adapters remain transport seams rather than orchestration layers
- Keep streaming additive rather than invasive:
  - do not replace `complete_turn(...)`
  - do not rewrite the transcript persistence model
  - do not add a second worker path or a gateway-owned live inference loop
- Treat streaming as delivery behavior for a completed backend-owned answer phase:
  - internal planning remains hidden
  - only final assistant text deltas may become live user-visible events
  - non-streaming providers and channels continue to use the current path
- Make durable event append the source of truth:
  - persist the ordered event first
  - then fan it out to adapters and SSE listeners
  - then rely on the durable record for reconnect, diagnostics, and retry behavior
- Make the delivery transaction boundary explicit:
  - commit delivery attempts and stream events through short dispatcher-owned transactions
  - keep final transcript persistence and terminal run status in the worker-owned completion flow
- Keep rollout bounded for this slice:
  - implement the full backend streaming contract and `webchat` SSE
  - keep streaming limited to plain-text assistant responses
  - treat Slack and Telegram streaming as capability-driven optional follow-up unless they can be added cleanly behind the same seam

## Service and Module Boundaries
### `src/providers/models.py`
- Preserve the existing `ModelAdapter.complete_turn(...)` path for non-streaming and compatibility.
- Add one additive final-answer streaming path, for example a generator or callback-driven method, that:
  - emits ordered assistant text deltas only
  - returns one authoritative final aggregate result equivalent to the completed answer phase
  - reports execution metadata indicating streaming, fallback, or degradation
- Keep provider-native token payloads or SDK stream objects hidden inside this module.
- Allow providers that cannot stream to satisfy the contract by emitting no deltas and returning only the final aggregate result.

### `src/graphs/state.py`
- Add minimal typed carriers for streaming metadata needed during a turn, such as:
  - whether streaming is eligible for the current turn
  - whether final-answer streaming was used or fell back
  - bounded stream summary metadata for manifest or observability use
- Keep `response_text`, `assistant_message_id`, `tool_events`, and manifest ownership intact.
- Do not make `AssistantState` hold raw provider stream objects or live transport state.

### `src/graphs/nodes.py` and `src/graphs/assistant_graph.py`
- Preserve current orchestration for:
  - degraded continuity handling
  - policy classification
  - tool binding and validation
  - proposal creation
  - tool execution
- Refactor only enough to separate two phases cleanly:
  - backend-owned planning or tool phase
  - final assistant answer generation phase
- Ensure the final answer phase can be executed through either:
  - one-shot completion
  - final-answer streaming completion
- Keep transcript persistence backend-owned and append-only.
- Do not emit live user-facing stream events from graph code directly; graph code should expose the final-answer generation seam to the worker or dispatcher-owned streaming path.

### `src/jobs/service.py`
- Keep `RunExecutionService` as the owner of streaming lifecycle inside a claimed run.
- Add explicit sequencing for:
  - pre-stream work: attachment normalization, fast-path extraction, context assembly, policy, and tools
  - final answer generation: streaming-capable or non-streaming path
  - final transcript persistence
  - delivery finalization and after-turn jobs
- Fail closed when transcript persistence or stream finalization does not satisfy the contract.
- Ensure a run that emitted partial output but never reached a durable final answer remains a non-success run.
- Keep the worker-owned run and final-transcript transaction separate from dispatcher-owned short transactions used to commit live stream events for SSE visibility.
- Keep retry classification explicit:
  - pre-first-delta stream setup failure may fall back to non-streaming dispatch
  - post-first-delta failure must record a failed or interrupted attempt and recover through a new attempt

### `src/channels/adapters/base.py`
- Grow `ChannelCapabilities` additively with flags for:
  - `supports_streaming_text`
  - `supports_stream_finalize`
  - `supports_stream_abort`
- Add bounded transport methods for streaming-capable adapters, for example:
  - `begin_text_stream(...)`
  - `append_text_delta(...)`
  - `finalize_text_stream(...)`
  - `abort_text_stream(...)`
- Keep existing `send_text_chunk(...)` and `send_media(...)` intact for non-streaming paths.
- Standardize structured streaming results and failures without leaking provider transport internals.

### `src/channels/dispatch.py`
- Keep the dispatcher as the only outbound orchestrator.
- Extend it with a streaming-aware lifecycle that can:
  - create or reuse one logical streamed delivery row for the assistant response
  - create append-only attempts with explicit stream lifecycle state
  - append ordered stream events with monotonic sequence numbers
  - persist before live fan-out
  - finalize, fail, cancel, or interrupt attempts
  - reconstruct fallback eligibility based on whether a `text_delta` has already been durably emitted
- Preserve the current whole-message path for:
  - unsupported channels
  - disabled streaming
  - ineligible response shapes such as reply directives, media refs, voice refs, or structured outbound intents
  - pre-first-delta fallback
- Keep logical delivery identity stable across retries for the same assistant response.
- Use the same logical delivery identity across restarted attempts, and treat a later attempt's `stream_started` event as the client-visible reset signal for that delivery.

### `src/channels/adapters/webchat.py`
- Keep production webchat grounded in the durable `stream_id` transport identity from Spec 012.
- Extend the adapter so it can support backend-owned streaming methods without making the browser transport the source of truth.
- Use bounded metadata only, such as `stream_id`, stream mode, and any browser-facing response identifiers.
- Preserve current whole-message polling compatibility.

### `apps/gateway/api/webchat.py`
- Keep the existing authenticated inbound submission and polling routes.
- Add an authenticated SSE endpoint scoped by `(channel_account_id, stream_id)`.
- Support reconnect using a durable event cursor from stream-event rows, using `Last-Event-ID` or an explicit equivalent.
- Ensure the SSE endpoint is a read surface over durable backend-owned stream events rather than an in-memory worker channel.
- Ensure SSE replay semantics let clients replace prior partial output for a `delivery_id` when a newer `attempt_id` begins with `stream_started`.
- Preserve the current poll endpoint as:
  - whole-message replay
  - non-streaming fallback
  - post-run visibility when SSE is unavailable

### `src/sessions/repository.py`
- Add repository helpers for:
  - create or get streamed delivery rows
  - create streaming attempts
  - append ordered stream events with uniqueness by attempt plus sequence number
  - mark attempts as `streaming`, `finalized`, `failed`, `cancelled`, or `interrupted`
  - mark logical deliveries as sent, failed, cancelled, or interrupted in a way consistent with current delivery reporting
  - list stream events by `(channel_account_id, stream_id)` and cursor for SSE replay
  - reconstruct emitted text from ordered deltas for diagnostics or retry visibility
- Keep transcript writes and session routing separate from streaming state.

### `src/db/models.py` and `migrations/versions/`
- Extend `outbound_deliveries` additively for streaming-aware delivery kinds and bounded completion metadata.
- Extend `outbound_delivery_attempts` additively for:
  - stream lifecycle state
  - optional provider stream identifier
  - last emitted sequence number
  - completion mode or interruption reason
- Add `outbound_delivery_stream_events` with:
  - `id`
  - `outbound_delivery_attempt_id`
  - `sequence_number`
  - `event_kind`
  - bounded `payload_json`
  - `created_at`
- Add required indexes and uniqueness guarantees from the spec.
- Keep the schema append-only in spirit: no mutable partial transcript table and no second conversation store.

### `src/domain/schemas.py`
- Add only the bounded API schemas needed for `webchat` SSE and any streaming diagnostics responses.
- Keep backend identifiers, payload fields, and replay cursors explicit and stable.
- Avoid introducing API shapes that let clients infer or control backend run ownership.

### `src/config/settings.py`
- Add only the settings needed to bound streaming behavior, such as:
  - enable or disable runtime streaming
  - enable or disable webchat SSE
  - bounded preview or replay limits
  - optional streaming heartbeat or idle timeout settings if the implementation needs them
- Keep defaults safe for local development and CI with fake streaming support.

### `src/observability/logging.py`, `src/observability/failures.py`, and `src/observability/diagnostics.py`
- Emit structured correlated events for:
  - stream open
  - first delta emitted
  - progress
  - finalize
  - cancellation or interruption
  - fallback to non-streaming
  - failure and retry
- Extend diagnostics so operators can inspect:
  - whether a run used streaming
  - which delivery and attempt were involved
  - event count and last sequence number
  - whether a final transcript row exists
  - how the active or terminal attempt ended
- Keep all payloads bounded and redacted.

## Contracts to Implement
### Final-Answer Streaming Contract
- The provider seam must expose one additive contract for final-answer streaming only.
- That contract must not expose raw tool-planning deltas to end users.
- It must yield ordered backend-owned text delta events plus one final aggregate completed answer.
- The same answer phase must still produce authoritative execution metadata usable by manifests and diagnostics.

### Stream Lifecycle Contract
- One logical streamed assistant response maps to one `outbound_delivery` row.
- Each retry or restart maps to a new `outbound_delivery_attempt`.
- Each attempt owns an ordered append-only event sequence.
- Attempt lifecycle must be explicit and bounded:
  - `pending_open`
  - `streaming`
  - `finalized`
  - `failed`
  - `cancelled`
  - `interrupted`

### Partial Output Persistence Contract
- Partial output exists only in delivery-side stream events.
- Allowed durable event kinds should be explicit and minimal, at least:
  - `stream_started`
  - `text_delta`
  - `stream_finalized`
  - `stream_cancelled`
  - `stream_failed`
- Each event must be durably appended before it becomes visible to adapters or SSE readers.
- Event payloads must be bounded and sufficient to reconstruct emitted text deterministically.

### Fallback Contract
- Fallback from streaming to whole-message delivery is allowed only before the first durable `text_delta`.
- After the first durable `text_delta`, recovery must use a new attempt under the same logical delivery.
- Fallback must not create a second logical assistant response identity for the same turn.

### Transcript Reconciliation Contract
- A successful streamed turn must end with:
  - one final assistant transcript row
  - one completed logical delivery state
  - one finalized attempt
- If transcript persistence fails after stream finalization work has started, the run must fail closed and diagnostics must surface the inconsistency.
- If transcript persistence succeeds but transport finalization fails, transcript truth remains canonical while delivery state records the transport problem separately.

### Webchat SSE Contract
- The SSE route must authenticate through the existing webchat client boundary.
- Subscription scope is `(channel_account_id, stream_id)`, not `session_id` or `execution_run_id`.
- Reconnect uses a durable monotonic backend cursor.
- Each SSE event envelope must include at minimum:
  - `event_id`
  - `delivery_id`
  - `attempt_id`
  - `sequence_number`
  - `event_kind`
  - bounded payload fields
- The existing poll route remains valid for replay and fallback.

## Concrete Implementation Steps
1. Add the streaming persistence layer.
   - Extend the delivery and attempt models.
   - Add `OutboundDeliveryStreamEventRecord`.
   - Add repository helpers and repository tests first so later layers build on stable durability rules.
2. Refactor dispatcher ownership next.
   - Split current whole-message dispatch from a new streaming-aware path.
   - Keep assistant-response delivery identity stable by deriving one streamed delivery from the same run-scoped assistant response source the current webchat fallback uses.
   - Add attempt state transitions, event append, and bounded failure classification.
3. Extend the adapter seam.
   - Add capability flags and no-op or unsupported defaults.
   - Implement fake or local webchat streaming behavior first because `webchat` is the required real-time contract in this spec.
   - Leave Slack and Telegram on non-streaming unless their streaming path can reuse the exact same dispatcher contract safely.
4. Introduce the provider final-answer streaming seam.
   - Keep `complete_turn(...)` for current tests and fallback.
   - Add translation from provider streaming responses into backend-owned ordered text deltas and one final aggregate result.
   - Preserve one-shot fallback when provider streaming is disabled or unavailable.
5. Adjust graph and worker orchestration.
   - Separate backend-owned planning or tool work from answer generation.
   - Invoke the streaming provider path only after all planning and tool work is complete.
   - Route ordered deltas into the dispatcher-owned streaming delivery path.
   - Persist the final assistant message only after authoritative final answer completion.
6. Add the `webchat` SSE surface.
   - Read durable stream events by `(channel_account_id, stream_id)` and cursor.
   - Emit SSE envelopes directly from durable rows.
   - Keep poll behavior untouched for whole-message fallback and replay.
7. Extend observability and diagnostics.
   - Add stream lifecycle events and failure categories.
   - Expose delivery, attempt, and transcript reconciliation state through diagnostics helpers.
8. Add end-to-end coverage.
   - Start with repository and dispatcher tests.
   - Then API tests for SSE auth and reconnect.
   - Then integration tests for partial visibility before run completion and for retry or cancellation semantics.

## Risk Areas
- Graph orchestration could become tangled if streaming is introduced before the final-answer phase is separated cleanly from planning and tool execution.
- Delivery identity could drift if whole-message fallback and streamed delivery use different logical response keys.
- Transcript and delivery reconciliation could become inconsistent if the worker finalizes transport before the final assistant message is durably persisted.
- SSE replay could be flaky if it depends on in-memory worker state rather than durable event rows.
- Retry handling could violate the spec if post-first-delta fallback silently converts an active streamed attempt into a whole-message send.
- Provider streaming translation could leak provider-native event shapes unless the provider seam normalizes them fully inside `src/providers/models.py`.

## Rollback Strategy
- Keep the provider streaming path additive and feature-gated so the existing one-shot completion path remains available.
- Keep dispatcher whole-message logic intact while introducing streaming as a parallel bounded code path under the same orchestrator.
- Ship `webchat` SSE only after durable stream-event persistence exists; if SSE regresses, disable the SSE endpoint while keeping whole-message polling intact.
- Avoid changing session routing, inbound ingestion, approval state, or transcript data contracts in this slice so rollback is local to runtime, delivery, and webchat read surfaces.

## Test Strategy
- Unit:
  - provider streaming translation into ordered text deltas and one final aggregate result
  - capability flags and unsupported streaming adapter behavior
  - stream attempt lifecycle transitions and fallback eligibility checks
  - bounded text reconstruction from ordered stream events
- Repository:
  - unique sequence numbering per attempt
  - ordered replay by attempt and by `(channel_account_id, stream_id)`
  - attempt-state transitions and latest-sequence tracking
- Dispatcher:
  - create or reuse one logical streamed delivery
  - append and persist events before fan-out
  - finalize success path
  - pre-first-delta fallback to whole-message delivery
  - post-first-delta retry as a new attempt
  - cancellation or interruption path
- API:
  - `webchat` SSE authentication
  - cursor or `Last-Event-ID` replay behavior
  - coexistence of SSE with the existing polling endpoint
- Integration:
  - streamed text visible to a client before full run completion
  - final assistant transcript persisted only after successful completion
  - worker failure or retry after partial output creates a new attempt under the same logical delivery
  - cancelled or interrupted streams do not fabricate a completed assistant transcript

## Constitution Check
- Gateway-first ownership is preserved because inbound transcript creation still begins at the gateway and SSE is a read surface over backend-owned durable events.
- Worker-owned execution is preserved because live streaming occurs inside a claimed `execution_run`.
- Transcript-first durability is preserved because partial output never becomes canonical transcript truth.
- Approval, policy, and tool execution remain backend-owned because user-visible streaming begins only after those steps are complete.
- Append-only durability is preserved because transcript rows, attempts, and stream events all remain append-only records.

## Plan Review
- Spec clarified: `yes`
- Plan analyzed: `yes`
- Constitution check passed: `yes`
- Ready for implementation: `yes`

### Review Notes
- The plan is intentionally staged so the riskiest invariants are locked down first: durable event ordering, stable logical delivery identity, and post-first-delta retry behavior.
- The plan should successfully implement the spec because it reuses the existing strongest seams in this repo instead of bypassing them:
  - worker-owned run lifecycle in `src/jobs/service.py`
  - backend-owned turn orchestration in `src/graphs/`
  - dispatcher-owned delivery orchestration in `src/channels/dispatch.py`
  - Spec 012 webchat transport identity and polling surface in `apps/gateway/api/webchat.py`
- The one area that must stay disciplined during implementation is graph refactoring. We should keep answer generation as a clean final phase rather than spreading streaming callbacks across policy and tool code.
- The plan remains bounded to this slice because it does not require live streaming for every provider, websockets for all channels, mutable transcript rows, or provider-owned orchestration.
