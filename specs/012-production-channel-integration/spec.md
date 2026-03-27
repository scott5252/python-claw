# Spec 012: Production Channel Integration

## Purpose
Replace the current thin local channel behavior with real transport integrations for `slack`, `telegram`, and `webchat` while preserving the existing gateway-first, worker-owned, append-only execution model. This slice must make the current channel abstractions usable with real inbound and outbound transport traffic without moving orchestration, session routing, policy enforcement, approval handling, or transcript ownership out of the backend.

## Non-Goals
- Token-by-token streaming or partial-response transport delivery
- Rich provider-native layouts beyond bounded text, reply targeting, and first-pass media sends
- Cross-channel identity resolution or CRM-style user unification beyond the existing routing tuple
- Replacing the generic `POST /inbound/message` contract as the canonical gateway entry shape
- Moving outbound retry ownership into provider SDKs or background adapter daemons
- Adding human handoff, collaboration UX, or channel-surface approval workflows beyond what existing gateway and governance flows already support

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

## Scope
- Replace the synthetic send behavior in `src/channels/adapters/slack.py`, `src/channels/adapters/telegram.py`, and `src/channels/adapters/webchat.py` with real provider-backed transport implementations
- Add provider-facing inbound entrypoints that translate Slack, Telegram, and production webchat traffic into the existing canonical `InboundMessageRequest` shape before handing off to `SessionService.process_inbound(...)`
- Extend the outbound dispatcher and channel adapter contracts so durable delivery records can carry real provider identifiers, retryability classification, reply-thread targeting, and bounded receipt metadata
- Preserve and extend the existing idempotency boundary so provider retries, webhook redelivery, and worker replay do not create duplicate transcript rows or duplicate logical outbound deliveries
- Add transport-specific authentication, request verification, and bounded provider metadata handling for inbound traffic
- Add tests covering real adapter translation, inbound acceptance, outbound send success and failure mapping, retry-safe replay, and diagnostics visibility

## Current-State Baseline
- `POST /inbound/message` is the only real inbound entry surface today, and it already persists transcript state, inbound attachment staging rows, queued runs, and dedupe records before returning `202 Accepted`.
- `src/channels/dispatch.py` already owns directive parsing, chunking, delivery-row creation, adapter send calls, and append-only attempt auditing.
- `src/channels/adapters/*.py` are currently thin stubs that return synthetic provider message identifiers derived from hashes rather than calling real transports.
- `README.md` documents the current `webchat` path as a local adapter exercised through the same gateway API, not a separate browser transport service.
- Spec 007 introduced transport-aware delivery auditing and media normalization, but not real provider transports, webhook verification, rate limiting, or delivery receipt handling.

## Implementation Gap Resolutions
### Gap 1: Canonical Gateway Ownership vs Provider-Specific Inbound Endpoints
Real transports need provider-specific webhook or callback endpoints, but the current architecture requires the gateway to remain the single source of transcript persistence, routing, and dedupe.

Options considered:
- Option A: let each provider endpoint create sessions and messages directly
- Option B: proxy provider requests into `POST /inbound/message` over HTTP inside the same app
- Option C: add provider-specific ingress handlers that authenticate and translate provider payloads into the existing `SessionService.process_inbound(...)` contract in-process
- Option D: move inbound translation into channel adapters and call them from the worker

Selected option:
- Option C

Decision:
- Provider-specific inbound routes belong to the gateway app, but they are translation-only boundaries.
- Slack, Telegram, and webchat ingress handlers authenticate provider traffic, translate it into the existing canonical inbound contract, and then call the same session service used by `POST /inbound/message`.
- `POST /inbound/message` remains the canonical backend-owned ingress contract and test seam; provider routes are additive transport translators, not parallel orchestration paths.

### Gap 2: Outbound Delivery Identity vs Provider Receipt State
The existing delivery model stores one logical delivery row plus append-only attempts, but real transports may expose provider message IDs, timestamps, thread IDs, or later receipt updates.

Options considered:
- Option A: keep only the current `provider_message_id` field and drop all other receipt state
- Option B: mutate transcript rows with provider delivery metadata
- Option C: extend outbound delivery and attempt payloads additively with bounded provider delivery metadata while keeping `outbound_deliveries` as the logical source of outbound state
- Option D: create a second transport-state store outside the main database

Selected option:
- Option C

Decision:
- `outbound_deliveries` and `outbound_delivery_attempts` remain authoritative for outbound delivery state.
- This slice may add bounded provider metadata fields or bounded JSON payloads needed for real delivery correlation, retry safety, and diagnostics, but transcript rows remain transcript-only.
- Later provider receipt or callback information must reconcile back into the existing delivery records rather than becoming a second outbound truth source.

### Gap 3: Retry Ownership Between Dispatcher and Provider SDKs
Real transports introduce retryable network failures, provider throttling, and redelivery semantics that can overlap dangerously with the current worker retry model.

Options considered:
- Option A: let adapters retry internally without durable attempt records
- Option B: move all retries to external provider queues
- Option C: keep the worker and dispatcher as the durable retry owners while adapters perform at most one transport request per attempt
- Option D: retry all failures synchronously inside `dispatch_run(...)` until success

Selected option:
- Option C

Decision:
- One dispatcher attempt corresponds to one transport request per chunk or media delivery.
- Adapters return structured success or failure information, including retryability classification where possible, but they do not own multi-attempt loops.
- Durable attempt creation still happens before each provider send, and resumed worker execution remains the outer retry mechanism.

### Gap 4: Channel Threading and Reply Semantics
The current dispatcher supports `reply_to_external_id`, but real channels do not all model replies the same way.

Options considered:
- Option A: normalize every channel to a single universal reply field and ignore provider-specific threading details
- Option B: expose full provider-native threading payloads to graph code
- Option C: keep one backend-owned reply abstraction with additive provider metadata for transport-specific threading fields
- Option D: defer reply support entirely until after production integrations land

Selected option:
- Option C

Decision:
- The backend keeps `reply_to_external_id` as the portable reply intent.
- Adapters translate that into provider-specific thread identifiers, reply targets, or conversation references.
- Any extra provider threading metadata needed for follow-up sends stays in bounded delivery metadata and session or message attachment metadata, not in assistant prompt state.

### Gap 5: Production Webchat Shape Before Streaming
The current repo has a local `webchat` adapter but no browser transport server. This spec needs a real production-grade webchat transport without accidentally implementing Spec 013 streaming.

Options considered:
- Option A: require WebSocket token streaming immediately
- Option B: keep `webchat` as a synthetic local-only test adapter and exclude it from production scope
- Option C: implement production webchat as durable non-streaming inbound or outbound HTTP or SSE-compatible message delivery with polling or push callbacks, while deferring token streaming
- Option D: collapse `webchat` into the generic `/inbound/message` endpoint permanently

Selected option:
- Option C

Decision:
- `webchat` remains in scope for this spec, but only for durable production transport behavior, not token streaming.
- The webchat transport in this slice may use bounded server-originated delivery mechanisms such as durable polling endpoints or whole-message push callbacks, but it must still map into the same session, transcript, delivery, and dispatcher model as the other channels.
- Partial-token streaming remains deferred to Spec 013.

## Data Model Changes
- Preserve existing `sessions`, `messages`, `execution_runs`, `inbound_message_attachments`, `message_attachments`, `outbound_deliveries`, and `outbound_delivery_attempts` as the main durable transport-facing records.
- Additive persistence may be introduced only where real transports require durable identity or callback correlation, for example:
  - provider webhook event identity or delivery receipt identity
  - provider conversation or thread metadata needed for reply-safe follow-up sends
  - bounded provider failure classification metadata beyond the current `error_code` and `error_detail`
- If new durable tables are required in this slice, they must remain transport-additive and append-only in spirit, for example:
  - inbound provider event records for webhook dedupe or replay visibility
  - delivery receipt or callback records keyed to existing outbound deliveries
- This slice must not create a second transcript source of truth, a second session-routing store, or a provider-owned outbound queue separate from `execution_runs` and `outbound_deliveries`.

## Contracts
### Inbound Transport Contract
- The gateway app owns provider-facing ingress routes for supported channels in this slice.
- Each ingress route must:
  - authenticate or verify the inbound provider request
  - parse provider payloads into one canonical inbound message envelope
  - resolve attachments into the existing canonical attachment input shape when present
  - derive or preserve the provider event identity used for idempotency
  - call the same backend session-processing path used by `POST /inbound/message`
- Provider ingress handlers may not:
  - create messages directly through repository calls
  - bypass the idempotency service
  - invoke the worker or graph directly
- Transport-specific inbound payload translation must fail closed on malformed or unverified requests.

### Canonical Inbound Mapping Contract
- Real transport ingress must map into the existing canonical inbound fields:
  - `channel_kind`
  - `channel_account_id`
  - `external_message_id`
  - `sender_id`
  - `content`
  - `peer_id` or `group_id`
  - optional canonical `attachments`
- The transport-specific `external_message_id` must be stable enough to preserve the dedupe guarantees already enforced by `src/gateway/idempotency.py`.
- If a provider uses event IDs that differ from message IDs, the implementation must explicitly document which identity is used for gateway dedupe and why.
- Message-edit, delete, reaction, or presence events are out of scope unless they can be cleanly mapped into the existing inbound message semantics without creating a second message lifecycle.

### Outbound Adapter Contract
- `src/channels/adapters/base.py` remains the shared adapter seam for this slice, but it must grow additively to support real transports.
- Real adapters must expose:
  - channel capability metadata
  - one bounded text-send method
  - one bounded media-send method where supported
  - one bounded structured error or result contract suitable for retry classification and diagnostics
- Real adapters may add helper methods for inbound verification or payload translation, but shared dispatcher code remains the owner of chunking, directive parsing, attempt creation, and durable state transitions.
- Provider-native SDK clients or HTTP payloads must not leak beyond the adapter boundary into graph, session, policy, or worker code.

### Dispatcher Contract
- `src/channels/dispatch.py` remains the only orchestrator for outbound transport sends.
- The dispatcher must continue to:
  - parse directives
  - check adapter capabilities
  - chunk text deterministically
  - create durable logical-delivery rows before send
  - create append-only attempt rows before each transport request
  - reconcile adapter results into durable sent or failed state
- This slice extends the dispatcher so it can also:
  - persist real provider message IDs and bounded threading metadata
  - classify retryable vs terminal transport failures without parsing provider error strings everywhere else
  - enforce any configured per-channel or per-account backoff and rate-limit policy
- The dispatcher must remain resumable and idempotent across worker retries.

### Idempotency and Replay Contract
- Inbound provider retries or webhook redelivery must continue to collapse onto the existing gateway dedupe model keyed by channel, account, and external message identity.
- Outbound replay must continue to reuse the existing logical-delivery key of `(outbound_intent_id, chunk_index)` rather than creating new logical delivery rows.
- If a provider supports outbound idempotency headers or request identifiers, those values must derive from the existing durable delivery or attempt identity rather than from ephemeral process state.
- Transport callbacks or receipts must reconcile back to existing rows instead of generating new logical outbound sends.

### Security Contract
- Inbound provider traffic must be authenticated or verified before any transcript or dedupe write occurs.
- Provider secrets, bot tokens, signing secrets, and webhook verification data remain settings-only inputs and must not be persisted in transcript, manifests, artifacts, or diagnostics payloads.
- Provider metadata stored on inbound attachments, inbound event rows, or outbound deliveries must remain bounded and must not become a trust anchor for authorization decisions beyond verified request metadata.
- The new transport endpoints must not weaken the existing diagnostics auth or gateway health boundaries introduced in Spec 008.

### Observability and Diagnostics Contract
- Existing diagnostics must remain able to explain:
  - inbound acceptance for real provider traffic
  - outbound delivery attempts and failure reasons
  - attachment normalization inputs derived from provider payloads
- This slice should expose enough bounded transport metadata to answer:
  - which provider event created a message
  - which provider message or thread a delivery targeted
  - whether a failed delivery was retryable, rate-limited, unauthorized, malformed, or transport-unavailable
- Observability must remain redacted and bounded; full raw webhook payloads should not be stored durably unless explicitly redacted and justified.

## Runtime Invariants
- The gateway remains the sole entrypoint for durable inbound transcript creation, even when provider-specific webhook routes are added.
- Worker-owned execution and dispatcher-owned outbound delivery remain unchanged as the main orchestration pattern.
- Channel adapters remain transport-specific boundaries, not policy engines or graph orchestrators.
- Session routing continues to derive from the canonical routing tuple, not from provider-specific session caches.
- Transcript rows remain authoritative conversation history; provider delivery or callback metadata is additive operational state only.
- Real transport failures must produce classified durable delivery or run state rather than silent adapter-local retries or dropped sends.

## Security Constraints
- All new provider-facing ingress routes require explicit request verification and bounded failure behavior.
- Secrets must stay out of logs, manifests, artifacts, and diagnostics payloads.
- Adapter request and response logging must follow the Spec 008 redaction model.
- This slice must not introduce direct provider-triggered execution paths that bypass approvals, typed validation, or session routing.

## Operational Considerations
- Real channels will introduce provider rate limits, transient outages, credential misconfiguration, and callback replay; this slice must document which failures are retryable and which are terminal.
- Local development and CI must still be able to run with stubbed or fake transport adapters instead of live provider credentials.
- The repo should remain runnable without real Slack, Telegram, or webchat credentials by selecting a non-production adapter configuration for tests.
- Any new provider SDK dependencies must remain isolated enough to stub cleanly in unit and integration tests.

## Acceptance Criteria
- Slack, Telegram, and production webchat inbound traffic can enter through provider-facing gateway routes, be verified and translated into the existing canonical inbound processing path, and preserve current dedupe, routing, transcript persistence, and queued-run creation semantics.
- Slack, Telegram, and production webchat outbound sends use real transport integrations behind the existing dispatcher and adapter boundary rather than synthetic hash-based send results.
- Outbound delivery rows and attempts persist real provider message correlation data and classified failure metadata without creating a second outbound state store.
- Inbound provider retries and webhook redelivery do not create duplicate transcript messages when they map to the same canonical dedupe identity.
- Worker replay or retry does not create duplicate logical outbound deliveries for the same `(outbound_intent_id, chunk_index)` even when the provider send must be attempted again.
- Channel reply threading works through the existing `reply_to_external_id` abstraction with bounded provider-specific translation hidden behind adapters.
- The repository test suite can exercise transport behavior with fakes or stubs and does not require live provider connectivity.

## Test Expectations
- Unit tests for provider payload translation into the canonical inbound message shape for Slack, Telegram, and webchat
- Unit tests for inbound verification failure, malformed provider payload rejection, and bounded provider metadata handling
- Unit tests for adapter result and failure translation, including retryable transport failures, auth failures, rate limits, and terminal invalid-request failures
- Dispatcher tests proving real adapter integration preserves chunk ordering, logical-delivery idempotency, reply handling, and media capability gating
- API tests for provider-facing ingress routes proving they map into the same session-processing and dedupe behavior as `POST /inbound/message`
- Integration tests proving inbound accept, worker execution, outbound delivery, and diagnostics all work end to end for each supported channel using stubs or fakes
