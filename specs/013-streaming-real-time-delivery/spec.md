# Spec 013: Streaming and Real-Time Delivery

## Purpose
Add streaming-safe or near-real-time assistant response delivery without breaking the existing gateway-first, worker-owned, append-only execution model. This slice must let supported channels expose assistant progress before a full turn finishes while preserving durable execution runs, final transcript writes, delivery auditability, and retry-safe recovery.

## Non-Goals
- Replacing `execution_runs` with provider-owned streaming sessions or long-lived websocket workers
- Making partial assistant output part of the canonical transcript history
- Reworking approval, governance, or tool-execution authority outside backend-owned runtime code
- Adding rich interactive UI surfaces, provider-native cards, or collaboration UX beyond bounded streaming text delivery
- Requiring every supported channel to stream token-by-token when the provider or transport cannot support it safely
- Introducing sub-agent delegation, human handoff, or multi-session orchestration

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

## Scope
- Extend the provider-backed model seam so supported runtimes can emit incremental text events and still return one authoritative final turn result
- Add a backend-owned streaming event contract between runtime, worker, dispatcher, and channel adapters
- Persist partial-delivery progress as additive operational state separate from canonical assistant transcript rows
- Keep final assistant message persistence append-only and durable only once the assistant turn reaches a terminal outcome
- Extend channel adapter capabilities so supported channels can open, append to, finalize, or abort a streamed response while unsupported channels continue to use the current whole-message dispatch path
- Add one concrete real-time browser-facing delivery contract for `webchat`
- Add tests covering partial delivery, finalization, cancellation, retry-safe recovery, and fallback to non-streaming delivery

## Current-State Baseline
- `src/providers/models.py` currently exposes only `complete_turn(...)`, which returns one `ModelTurnResult` after the provider call completes.
- `src/graphs/assistant_graph.py` and `src/graphs/nodes.py` execute one full assistant turn before any outbound delivery begins.
- `src/jobs/service.py` owns run claiming, graph invocation, after-turn job enqueueing, and completion or retry transitions for `execution_runs`.
- `src/channels/dispatch.py` currently dispatches only after the turn has completed, creating durable `outbound_deliveries` plus append-only `outbound_delivery_attempts`.
- `apps/gateway/api/webchat.py` currently offers durable whole-message polling only; it does not expose live partial-response delivery.
- `messages` remain the canonical append-only transcript store, while outbound delivery metadata is additive operational state.

## Implementation Gap Resolutions
### Gap 1: Canonical Transcript Truth vs Partial User-Facing Output
Streaming exposes text before the turn is complete, but the current architecture treats append-only transcript writes as the canonical assistant history. The draft must choose whether partial content is transcript truth or operational delivery state.

Options considered:
- Option A: write partial assistant transcript rows and update them in place until completion
- Option B: treat partial output as additive outbound operational state and persist one final assistant transcript row only when the turn completes
- Option C: keep partial output in memory only and do not persist it durably
- Option D: persist every token as its own transcript message

Selected option:
- Option B

Decision:
- Canonical transcript truth remains one append-only final assistant message row per assistant turn outcome in this slice.
- Partial text shown to users before turn completion is delivery-side operational state only and must not mutate canonical transcript rows in place.
- If a stream is cancelled or fails before completion, the system may retain delivery-side partial events for diagnostics and retry visibility, but it must not fabricate a completed assistant transcript message from incomplete output.

### Gap 2: Streaming Boundary Relative to Tool Planning and Execution
Provider-backed turns may include tool planning, approval gating, or remote execution. The draft must define whether user-visible streaming begins during that entire turn or only during the final answer phase.

Options considered:
- Option A: stream everything, including provider-native tool-planning deltas, directly to users
- Option B: delay user-visible streaming until the runtime reaches the final assistant-text generation phase after any required tool or approval work
- Option C: forbid streaming on any turn that could use tools
- Option D: move tool execution into the channel adapter so streaming can stay simple

Selected option:
- Option B

Decision:
- User-visible streaming in this slice begins only once the backend has reached the final assistant text-generation phase for the turn.
- Tool proposals, approval checks, deterministic policy decisions, and remote execution remain backend-owned internal steps and are not forwarded as raw provider deltas to end-user channels.
- Tool-using turns may therefore have a later first-token time than text-only turns, but once final assistant generation begins the result may stream incrementally through the same delivery contract.

### Gap 3: Ownership of Live Delivery Within the Existing Run Lifecycle
Streaming introduces a temptation to let gateway handlers or provider SDK callbacks own the live response loop, but current execution ownership belongs to the worker and `execution_runs`.

Options considered:
- Option A: let gateway request handlers keep open streaming responses and invoke the runtime directly
- Option B: create a second streaming worker outside `execution_runs`
- Option C: keep the worker and claimed `execution_run` as the owners of stream production and finalization
- Option D: move live delivery entirely into provider SDK webhook flows

Selected option:
- Option C

Decision:
- A streamed assistant response is still produced inside one claimed `execution_run`.
- The worker remains responsible for context assembly, tool execution, live output emission, final transcript persistence, outbound reconciliation, after-turn jobs, and terminal run state.
- Streaming must not create a second orchestration path that bypasses run claims, retries, or diagnostics.

### Gap 4: Delivery Identity for Streamed Output vs Existing Whole-Message Deliveries
The current dispatcher models one logical delivery row per chunk or media item. Streaming needs a stable durable identity for a multi-event response without losing retry semantics.

Options considered:
- Option A: create one delivery row per streamed token
- Option B: keep one logical delivery row for the streamed response and attach append-only stream events to the active attempt
- Option C: bypass durable delivery rows for streaming and store only a provider stream identifier
- Option D: keep only the final whole-message delivery and do not record partial stream activity

Selected option:
- Option B

Decision:
- Streaming text delivery in this slice uses one logical outbound delivery identity for the assistant response on a streaming-capable channel.
- Append-only attempt rows continue to represent transport attempts.
- A new additive stream-event child record must capture ordered partial-delivery events for the active attempt rather than overloading transcript rows or creating one logical delivery per token.

### Gap 5: Replay and Retry Behavior After Mid-Stream Failure
A stream may fail after users have already seen some output. The draft must choose whether retries resume, restart, or silently drop partial state.

Options considered:
- Option A: resume from arbitrary token offsets inside provider streams
- Option B: restart the delivery attempt from the beginning using durable event state and mark the prior attempt failed
- Option C: ignore failure if any partial output was shown
- Option D: retry in memory only without durable attempt boundaries

Selected option:
- Option B

Decision:
- The durable retry owner remains the worker and dispatcher.
- If a streamed delivery attempt fails and is retryable, the failed attempt is recorded as failed with the partial event history already emitted, and a later retry creates a new attempt for the same logical streamed delivery.
- Exact provider-native stream resumption is not required in this slice.
- Channel adapters may support best-effort restart semantics such as replacing a temporary message, reopening a browser event stream, or sending a clearly restarted partial sequence, but the backend durability model assumes restart rather than token-exact resume.

### Gap 6: Cancellation and Interruption Semantics
Real-time delivery needs a clear model for user disconnects, worker shutdown, or explicit cancellation requests.

Options considered:
- Option A: treat every disconnect as success and keep streaming in the background
- Option B: let channels cancel delivery independently of run state
- Option C: define backend-owned cancellation states for the stream attempt and distinguish them from successful completion
- Option D: omit cancellation handling from the spec

Selected option:
- Option C

Decision:
- This slice introduces explicit stream-attempt interruption semantics separate from success and failure.
- A worker shutdown, explicit backend cancellation, or channel transport cancellation must produce an append-only interruption or cancellation event plus a non-success terminal state for the active attempt.
- If the assistant turn never reaches durable completion, no final assistant transcript row may be fabricated from partial output.
- If the assistant text was durably completed before the transport was interrupted, the final transcript may still exist while the delivery attempt records interruption and later retry behavior separately.

### Gap 7: Concrete Browser-Facing Real-Time Contract
Spec 012 intentionally stopped at production webchat polling. This slice needs one real-time contract without forcing every provider route to become websocket-based.

Options considered:
- Option A: require websockets for all channels
- Option B: add server-sent events for `webchat` while keeping other channels capability-driven
- Option C: retrofit the existing poll endpoint to deliver token deltas only
- Option D: defer all browser real-time behavior and focus only on Slack or Telegram

Selected option:
- Option B

Decision:
- This slice adds a concrete `webchat` real-time delivery contract using SSE.
- The existing polling contract from Spec 012 remains valid as the durable non-streaming fallback and replay surface.
- Other channels remain capability-driven: they may support live partial delivery if their adapter can do so safely, but this spec does not require browser websocket infrastructure or provider-native token streaming for every adapter.

### Gap 8: Observability and Diagnostics for Streaming
The existing observability model explains runs, deliveries, attachments, and node execution, but not partial streamed progress or mid-stream failure.

Options considered:
- Option A: log partials only in application logs
- Option B: add bounded durable stream-event visibility plus correlated diagnostics metadata
- Option C: expose raw provider streaming payloads in diagnostics for debugging
- Option D: treat streamed output as opaque and diagnose only final run status

Selected option:
- Option B

Decision:
- Streaming must remain diagnosable through durable bounded records correlated to `trace_id`, `execution_run_id`, `session_id`, logical delivery identity, and attempt identity.
- Diagnostics should expose stream state, sequence counts, termination reason, and whether a final transcript was committed, while keeping raw provider payloads redacted and bounded.

### Gap 9: Provider Contract for Final-Answer-Only Streaming
The draft says user-visible streaming starts only during the final assistant-text generation phase, but the current provider seam still exposes only `complete_turn(...)` and does not define how the runtime reaches a streamable final-answer phase without leaking tool-planning deltas.

Options considered:
- Option A: extend `complete_turn(...)` so it streams all provider events and let the graph filter user-visible deltas
- Option B: add one additive provider method for final-answer streaming only, invoked after backend-owned planning, approval, and tool work is complete
- Option C: keep the provider seam non-streaming and simulate streaming by chunking the final completed text
- Option D: introduce a provider-owned long-lived streaming session abstraction that spans both planning and final generation

Selected option:
- Option B

Decision:
- The provider contract in this slice must grow additively with one final-answer streaming path separate from the existing one-shot `complete_turn(...)` path.
- Backend-owned planning, approval checks, typed tool validation, and tool execution must still complete before the runtime invokes provider streaming for user-visible output.
- The streaming provider path must emit only final assistant-text deltas plus one authoritative final aggregate result for the same answer phase.
- Providers that cannot satisfy this contract may fall back to the existing non-streaming completion path without changing graph or policy ownership.

### Gap 10: Durability Boundary for Partial Event Emission
The draft requires durable stream-event records and reconnect-safe SSE behavior, but it does not yet define whether partial events are persisted before delivery, after delivery, or only periodically.

Options considered:
- Option A: emit partial output to adapters and SSE clients first, then persist best-effort
- Option B: persist each backend-owned stream event durably before fan-out to live transport surfaces
- Option C: buffer partials in memory and flush them to storage periodically
- Option D: persist only periodic checkpoints instead of the emitted event sequence

Selected option:
- Option B

Decision:
- Each ordered backend-owned stream event must be durably recorded before it is treated as delivered to any live adapter or browser SSE subscriber.
- Live delivery fan-out may read directly from the just-persisted event or from a bounded in-process handoff, but durable persistence is the source of truth for replay, reconnect, diagnostics, and crash recovery.
- The implementation may batch commits only if ordered durability, replay visibility, and monotonic cursor semantics remain equivalent to per-event durable append behavior.
- The system must not depend on in-memory partial text as the only source of truth for what was emitted.

### Gap 11: Concrete Webchat SSE Identity and Event Envelope
The draft chooses SSE for `webchat`, but it does not yet define the concrete subscription identity, reconnect cursor, or event payload shape strongly enough to guarantee interoperable API and repository behavior with the existing Spec 012 polling and `stream_id` model.

Options considered:
- Option A: leave the SSE wire contract implementation-defined as long as it uses durable records
- Option B: define SSE as scoped by `(channel_account_id, stream_id)` with reconnect via a monotonic event cursor and one bounded backend-owned event envelope
- Option C: scope SSE by `session_id`
- Option D: scope SSE by `execution_run_id`

Selected option:
- Option B

Decision:
- The `webchat` SSE surface in this slice must be scoped by the existing durable `stream_id` transport identity together with `channel_account_id`, rather than by backend-only identifiers such as `session_id` or `execution_run_id`.
- Reconnect must use a monotonic backend-owned cursor, such as `Last-Event-ID` or an equivalent explicit `after_event_id`, sourced from durable stream-event records.
- The SSE event envelope must be bounded and explicit enough to support replay and reconciliation, including at minimum:
  - `event_id`
  - `delivery_id`
  - `attempt_id`
  - `sequence_number`
  - `event_kind`
  - bounded event payload fields
- The existing polling contract remains the whole-message replay and fallback surface, while SSE provides the live partial-delivery surface over the same durable stream identity.

### Gap 12: Stream-Attempt State Machine and Fallback Boundary
The draft describes finalize, failure, cancellation, interruption, and fallback behavior, but it does not yet define one explicit stream-attempt state machine or when fallback from streaming to non-streaming is still allowed.

Options considered:
- Option A: keep stream-attempt state implementation-defined and rely only on event kinds
- Option B: define explicit stream-attempt lifecycle states and allow fallback to non-streaming only before the first user-visible text delta is emitted
- Option C: allow fallback from streaming to whole-message delivery at any point within the same attempt
- Option D: treat any streaming downgrade after stream start as a terminal run failure with no alternative delivery path

Selected option:
- Option B

Decision:
- Stream attempts in this slice must use one explicit lifecycle with bounded durable states, including:
  - `pending_open`
  - `streaming`
  - `finalized`
  - `failed`
  - `cancelled`
  - `interrupted`
- Fallback from streaming to the existing non-streaming whole-message path is allowed only before the first user-visible `text_delta` event is durably emitted.
- Once a `text_delta` has been durably emitted, any retry or restart must occur as a new attempt under the same logical streamed delivery rather than by silently converting the same attempt into a whole-message send.
- Attempt terminal state and event history together must be sufficient to explain whether the stream finalized cleanly, failed before first output and fell back, or emitted partial output and later required retry or cancellation.

### Gap 13: Durable Visibility Boundary Across Worker and SSE Sessions
The draft requires durable pre-fan-out event persistence, but the current worker lifecycle is organized around one long-lived run transaction. The spec must define how stream events become durably visible to live SSE readers before the run reaches terminal completion.

Options considered:
- Option A: keep one worker transaction and require per-event commits from that same run transaction
- Option B: use dispatcher-owned short write transactions for stream attempts and stream events, separate from the worker-owned run and final-transcript transaction
- Option C: keep partial events in memory and flush them to the database periodically
- Option D: make SSE read from in-memory worker state and treat the database as eventual reconciliation only

Selected option:
- Option B

Decision:
- Durable stream-attempt and stream-event writes in this slice must be committed through a dispatcher-owned short transaction boundary that is separate from the worker-owned final transcript and terminal run transition path.
- This additive transaction split exists only for delivery-side operational state. It must not move transcript truth, run ownership, tool authority, or policy authority out of the worker-owned backend flow.
- SSE readers and other replay surfaces must treat the committed stream-event rows as the live source of truth; they must not depend on uncommitted worker transaction state or process-local buffers.
- The final assistant transcript row and terminal run status may still commit later, after authoritative final answer completion and delivery reconciliation.

### Gap 14: Streaming Eligibility for Reply Directives, Media, and Structured Outbound Intents
The current backend supports whole-message reply directives, media refs, and tool-produced outbound intents. The draft must decide whether this slice streams all of those shapes or only bounded plain-text assistant responses.

Options considered:
- Option A: restrict streaming in this slice to plain-text assistant responses with no reply directives, media refs, or tool-produced structured outbound intents that require whole-message dispatch semantics
- Option B: buffer the whole response until directives and media refs are fully known, then retroactively stream it
- Option C: extend the runtime and adapter contract to stream typed reply, media, and structured outbound-intent events in this slice
- Option D: attempt to parse reply directives and media refs incrementally from partial text deltas

Selected option:
- Option A

Decision:
- Streaming eligibility in this slice is limited to bounded plain-text assistant responses.
- Any response shape that requires whole-message parsing or structured dispatch semantics, including reply directives, media refs, voice refs, or tool-produced outbound intents with additive transport metadata, must use the existing non-streaming whole-message dispatch path.
- The worker or dispatcher must determine streaming eligibility before the first durable `text_delta` is emitted.
- This restriction is additive and bounded to Spec 013; a later slice may extend streaming to richer outbound shapes through explicit typed contracts.

### Gap 15: Client Reconciliation Semantics for New Attempts After Partial Failure
The draft says a post-first-delta retry creates a new attempt under the same logical delivery, but it does not yet define how the webchat client should reconcile partial output from the failed attempt with a restarted attempt.

Options considered:
- Option A: define a new `stream_started` event on a later `attempt_id` for the same `delivery_id` as a client-visible reset or replace signal for the in-progress response
- Option B: expose only the latest attempt to the browser and hide prior failed attempts from SSE replay
- Option C: replay all attempts verbatim and leave reconciliation fully implementation-defined in the browser client
- Option D: suppress failed-attempt partial deltas from SSE entirely and expose them only through diagnostics

Selected option:
- Option A

Decision:
- When a retry starts a new attempt for an existing logical streamed delivery, the new attempt's `stream_started` event must be interpreted by the webchat SSE contract as a reset or replace signal for the client-visible in-progress response for that `delivery_id`.
- Historical failed-attempt rows and events remain durably stored for diagnostics, auditability, and replay visibility, but browser-facing reconstruction of the active response must prefer the latest attempt once that later attempt begins.
- The SSE event contract must therefore preserve `delivery_id` and `attempt_id` together so clients can deterministically replace prior partial output when a restart occurs.

## Data Model Changes
- Preserve `messages` as the canonical transcript source of truth and keep assistant transcript writes append-only.
- Preserve `execution_runs`, `outbound_deliveries`, and `outbound_delivery_attempts` as the main durable run and delivery state holders.
- Extend `outbound_deliveries` additively for streaming-aware logical delivery metadata, for example:
  - `delivery_kind` must support a streaming text value distinct from the current whole-message text chunk path
  - bounded stream summary metadata such as final delivered character count, completion mode, or stream-capability mode may be mirrored additively
- Extend `outbound_delivery_attempts` additively for stream-attempt state, for example:
  - active streaming status
  - optional provider stream identifier
  - last emitted sequence number
  - interruption reason or completion mode
- Add one append-only child table for ordered streaming events tied to the active outbound delivery attempt:
  - `outbound_delivery_stream_events`
  - `id`
  - `outbound_delivery_attempt_id`
  - `sequence_number`
  - `event_kind`
  - bounded `payload_json`
  - `created_at`
- Required indexes:
  - unique index on `outbound_delivery_stream_events(outbound_delivery_attempt_id, sequence_number)`
  - lookup index on `outbound_delivery_stream_events(outbound_delivery_attempt_id, created_at)`
- This slice must not create a second transcript store, mutable partial transcript rows, or provider-owned stream state outside the main database.

## Contracts
### Model Streaming Contract
- `src/providers/models.py` must grow additively to support incremental provider output for adapters that can stream.
- The backend-owned model contract in this slice must support:
  - ordered text-emission events for the final assistant response phase
  - one authoritative final aggregate result equivalent to the current `ModelTurnResult`
  - bounded execution metadata describing whether streaming was used, degraded, or fell back to non-streaming completion
- The repository standard for this slice is additive streaming support rather than replacement of `complete_turn(...)`.
- The additive streaming path must be a final-answer streaming contract invoked only after backend-owned planning, approval, and tool work completes, rather than a provider-owned stream spanning the whole turn lifecycle.
- Providers that cannot stream may still satisfy the contract by emitting no partial events and returning only the final aggregate result.

### Runtime and Graph Contract
- `src/graphs/assistant_graph.py` and `src/graphs/nodes.py` remain backend-owned orchestration layers.
- The graph must keep tool planning, validation, approval checks, and tool execution authoritative in backend code.
- User-visible streaming begins only during the final assistant-text generation phase.
- `AssistantState` may grow additively to carry bounded streaming metadata, but final `response_text`, `assistant_message_id`, `tool_events`, and context-manifest ownership remain backend-owned and durable.
- Prompt construction in `src/graphs/prompts.py` remains backend-authored. Streaming does not let provider payloads bypass prompt assembly, validation, or policy seams.

### Worker Contract
- `src/jobs/service.py` remains the owner of streaming lifecycle execution inside a claimed run.
- The worker must:
  - claim the run and preserve normal concurrency controls
  - execute any pre-stream normalization, context assembly, and tool work
  - open or initiate live delivery only after the turn reaches final assistant-generation phase
  - emit ordered partial-delivery events through the dispatcher or a streaming-delivery service owned by the backend
  - commit the final assistant transcript row only when the assistant turn completes successfully
  - finalize or abort the stream delivery state before the run reaches terminal status
- A run that emits partial output but fails before turn completion must still end in a classified non-success run state and must not pretend the assistant turn completed cleanly.
- The worker-owned run transaction is not required to hold stream-event writes open until terminal run completion. Delivery-side attempt and stream-event commits may occur earlier through an additive dispatcher-owned short transaction boundary so live SSE readers can observe committed events safely.

### Streaming Delivery Contract
- The dispatcher remains the only backend orchestrator for outbound transport sends.
- This slice extends the dispatcher contract so it can also:
  - create or reuse one logical streamed delivery row
  - create append-only stream attempts
  - append ordered stream events for partial text emission
  - finalize, fail, or cancel the active attempt
  - fall back to the existing non-streaming dispatch path when the channel or account does not support streaming
- The dispatcher must preserve the existing durable-delivery identity rules and must not create duplicate logical streamed deliveries for the same assistant response.
- If streaming degrades before the first user-visible `text_delta`, the dispatcher may fall back to the existing non-streaming path without creating a second logical response identity.
- If streaming degrades after the first user-visible `text_delta`, recovery must create a new attempt under the same logical streamed delivery rather than converting the active attempt into a whole-message send.
- Delivery-side stream persistence must be committed before live adapter or SSE fan-out through a short dispatcher-owned transaction boundary rather than depending on a still-open worker run transaction.
- Streaming is eligible only for bounded plain-text assistant responses in this slice. If the response requires whole-message directive parsing, reply targeting, media refs, voice refs, or structured outbound-intent handling, the dispatcher must use the existing non-streaming whole-message path.

### Channel Adapter Contract
- `src/channels/adapters/base.py` remains the shared adapter seam.
- Adapter capabilities must grow additively so each adapter can declare whether it supports:
  - live streaming text delivery
  - finalization of a streamed response
  - explicit abort or cancellation handling
- Streaming-capable adapters must expose bounded backend-owned methods for:
  - opening or beginning a stream attempt
  - appending partial text
  - finalizing the response
  - aborting or cancelling the response
- Non-streaming adapters may omit those behaviors and continue to use the current whole-message text-send methods.
- Provider-native payloads, sockets, or SDK stream objects must not leak beyond the adapter boundary into graph, policy, or session code.

### Partial Output Persistence Contract
- Partial output is represented only in outbound-delivery operational state, not in `messages`.
- Stream-event payloads must be bounded and ordered, and must record enough information to reconstruct what users were sent during one attempt without storing raw provider transport internals.
- Each stream event must be durably appended before it becomes the source for live delivery fan-out, reconnect replay, or diagnostics visibility.
- Allowed stream event kinds in this slice must be explicit and bounded, for example:
  - `stream_started`
  - `text_delta`
  - `stream_finalized`
  - `stream_cancelled`
  - `stream_failed`
- If the implementation chooses to store text deltas rather than cumulative snapshots, the event contract must still allow deterministic reconstruction of the emitted text for diagnostics.

### Final Transcript and Delivery Reconciliation Contract
- A successful streamed response must end with:
  - one durable final assistant transcript row
  - one logical outbound streamed delivery in sent or equivalent completed state
  - one terminal stream attempt marked finalized or sent
- The final assistant transcript row must contain the authoritative completed assistant text, not a provider-specific partial snapshot.
- If delivery succeeds but transcript persistence fails, the run must fail closed and diagnostics must show the inconsistency rather than silently declaring success.
- If transcript persistence succeeds but final transport finalization fails, the transcript remains canonical while delivery state records the failed or retryable transport outcome separately.

### Webchat Real-Time Contract
- `apps/gateway/api/webchat.py` must grow additively with an SSE delivery endpoint for supported browser clients.
- The SSE contract in this slice must:
  - authenticate through the existing webchat client boundary rather than operator diagnostics auth
  - scope events by `(channel_account_id, stream_id)`, where `stream_id` is the durable webchat stream identity already introduced in Spec 012
  - emit bounded ordered backend-owned stream events derived from durable stream-event records
  - support reconnect from a monotonic cursor such as `Last-Event-ID` or an equivalent `after_event_id` tied to the durable stream-event record identity
- The SSE event envelope must include bounded identifiers sufficient for replay and reconciliation, including `event_id`, `delivery_id`, `attempt_id`, `sequence_number`, `event_kind`, and bounded event payload fields.
- If a later attempt starts for the same logical `delivery_id`, the new attempt's `stream_started` event is the client-visible reset signal for the in-progress response. Clients must replace prior partial output for that `delivery_id` with the latest attempt once that reset event is observed.
- The existing polling endpoint remains available for durable whole-message replay, non-streaming clients, and fallback behavior when SSE is unavailable.

### Idempotency and Recovery Contract
- Streaming must not weaken the existing inbound or outbound idempotency model.
- Logical streamed delivery identity must remain stable across worker replay for the same assistant response.
- A retried stream creates a new attempt under the same logical delivery rather than a new logical response identity.
- If a worker crashes mid-stream, recovery must derive from durable run, delivery, attempt, and stream-event state rather than from in-memory provider cursors only.
- A failed pre-first-delta streaming setup may fall back to non-streaming completion under the same logical response identity, but any failure after the first durably emitted `text_delta` must recover through a new attempt rather than an in-place downgrade.

### Observability and Diagnostics Contract
- Streaming execution must emit correlated structured events for:
  - stream start
  - stream progress
  - stream finalize
  - stream cancel or interrupt
  - stream failure
- Diagnostics must be able to answer:
  - whether a given run used streaming or fell back to non-streaming delivery
  - which logical streamed delivery and attempt belonged to the run
  - how many partial events were emitted
  - whether a final assistant transcript row was committed
  - why a stream ended as finalized, cancelled, or failed
- Stored diagnostics data must remain bounded and redacted; raw provider token payloads are not required in this slice.

## Runtime Invariants
- The gateway remains the sole entrypoint for durable inbound transcript creation.
- The worker remains the owner of live stream production, final transcript writes, and run terminal-state transitions.
- Partial user-visible output is never canonical transcript truth.
- Final assistant transcript rows remain append-only and are never updated in place to reflect streaming progress.
- Unsupported or disabled channels still deliver through the existing whole-message dispatch path.
- Delivery retries remain durable and replay-safe even when a prior stream attempt already emitted partial output.

## Security Constraints
- Streaming must not bypass approval checks, typed tool validation, or backend-owned prompt assembly.
- Provider or browser stream endpoints must use the same or stricter authentication boundaries as their non-streaming transport equivalents.
- Partial-output records, stream-event payloads, and diagnostics must remain bounded and follow the existing redaction rules from Spec 008.
- Secrets, provider tokens, and raw transport credentials must not be persisted in stream events, transcript rows, or diagnostics payloads.

## Operational Considerations
- Streaming increases the duration of some outbound attempts, so stale-attempt detection and diagnostics must distinguish active streaming from abandoned or dead streams.
- Local development and CI must still support non-streaming adapters and fake streaming providers without requiring live provider connectivity.
- The implementation should remain safe when a provider advertises streaming but the connection downgrades or fails, by falling back to non-streaming completion where possible.
- Browser reconnect behavior for `webchat` must be durable and cursor-based rather than dependent on one long-lived process-local connection.

## Acceptance Criteria
- Supported runtime paths can emit incremental assistant text during the final answer phase and still produce one authoritative final `ModelTurnResult`.
- The worker can stream partial assistant output without bypassing `execution_runs`, final transcript persistence, delivery auditing, or diagnostics correlation.
- Partial output is stored only as additive delivery-side stream state and never as mutable transcript content.
- Streaming-capable channels can begin, append, finalize, and abort streamed responses through the adapter boundary, while unsupported channels continue to use the current non-streaming dispatch path.
- `webchat` exposes a concrete real-time SSE delivery surface with reconnect-safe bounded events, while preserving the existing polling fallback from Spec 012.
- Mid-stream failure, cancellation, or worker restart produces durable attempt and stream-event state that explains what happened and allows retry-safe recovery.
- The repository test suite can cover streaming behavior with fakes or stubs and does not require live provider streaming connectivity.

## Test Expectations
- Unit tests for provider streaming translation into ordered backend-owned text events plus final aggregate turn result
- Unit tests for graph or runtime behavior proving tool planning remains backend-owned and user-visible streaming begins only during final answer generation
- Dispatcher tests covering logical streamed delivery creation, ordered stream-event persistence, finalization, cancellation, and retry-safe new-attempt behavior
- Repository tests for append-only stream-event ordering, uniqueness by attempt plus sequence number, and reconstruction of emitted partial text
- Adapter tests for streaming capability declaration, live append behavior, finalize behavior, abort behavior, and fallback to non-streaming text sends
- API tests for `webchat` SSE authentication, reconnect cursor behavior, and compatibility with the existing polling endpoint
- Integration tests proving streamed text can reach a client before full run completion while the final transcript row is persisted only at successful turn completion
- Integration tests proving cancellation, provider failure, and worker retry produce correct run, delivery, attempt, and diagnostics state without duplicate logical streamed deliveries
