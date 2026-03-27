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

### Gap 6: Provider-Specific Canonical Routing and Dedupe Mapping
Real inbound transports do not all expose the same identity shape for direct chats, channels, rooms, thread replies, or webhook redelivery. The current draft requires canonical mapping into the Spec 001 routing tuple, but it does not yet define the per-provider normalization strongly enough to guarantee deterministic session reuse and duplicate suppression.

Options considered:
- Option A: add a normative per-provider mapping matrix for supported inbound event shapes covering `external_message_id`, `sender_id`, `peer_id`, `group_id`, and ignored event types
- Option B: leave provider mapping implementation-defined and document it only in adapter code
- Option C: introduce a second provider-specific routing store that tracks native conversation identity outside the canonical session tuple
- Option D: reduce the slice to one inbound conversation shape per provider and defer the rest

Selected option:
- Option A

Decision:
- This spec must define one explicit per-provider canonical mapping table for the supported Slack, Telegram, and webchat inbound message shapes in this slice.
- For each supported provider event shape, the spec must document:
  - which native identifier becomes `external_message_id` for gateway dedupe
  - which native actor becomes `sender_id`
  - whether the event maps to `peer_id` or `group_id`
  - how thread-root or reply-container identifiers participate in routing, if at all
  - which provider events are ignored rather than translated into canonical inbound messages
- The mapping must preserve the Spec 001 invariant that the same normalized routing inputs produce the same session identity without requiring provider-specific session caches.

### Gap 7: Verified Provider Control Requests vs Canonical Message Ingress
Some providers require verified non-message control flows such as webhook challenge requests, endpoint verification handshakes, or setup callbacks. The current draft requires verified ingress and also keeps transcript creation gateway-owned, but it does not yet define how these provider control requests fit the architecture without creating fake transcript rows.

Options considered:
- Option A: treat provider verification or challenge traffic as gateway-owned control requests that are verified and answered without entering transcript, dedupe, or run creation paths
- Option B: force all provider callbacks, including setup or challenge flows, through the canonical inbound message contract
- Option C: require separate out-of-band manual setup and omit runtime challenge handling from the product contract
- Option D: defer inbound support for any provider that requires challenge or verification callbacks

Selected option:
- Option A

Decision:
- This slice may include provider-specific verification or challenge endpoints at the gateway boundary when a supported provider requires them.
- Verified control requests are not canonical inbound messages and must not create transcript rows, dedupe records, sessions, or execution runs.
- Only provider requests that successfully translate into the canonical inbound message envelope may enter `SessionService.process_inbound(...)`.
- The spec must explicitly distinguish control-request success semantics from canonical message-acceptance semantics in API tests and observability.

### Gap 8: Concrete Production Webchat Delivery Contract
The current draft keeps `webchat` in scope and allows bounded non-streaming transport behavior, but it does not choose one concrete delivery contract. That ambiguity would block API design, adapter shape, and end-to-end tests.

Options considered:
- Option A: define production webchat in this slice as HTTP inbound plus durable polling for outbound whole-message delivery
- Option B: define production webchat as HTTP inbound plus whole-message SSE push
- Option C: define production webchat as HTTP inbound plus server-to-client callback delivery
- Option D: remove `webchat` from this slice and focus only on Slack and Telegram

Selected option:
- Option A

Decision:
- Production `webchat` in this slice uses canonical HTTP inbound submission plus durable polling for outbound whole-message delivery.
- Polling returns already-persisted whole outbound delivery results only; it does not introduce token streaming, partial transcript state, or provider-owned orchestration.
- The polling contract must reconcile to the same `sessions`, `messages`, `execution_runs`, `outbound_deliveries`, and `outbound_delivery_attempts` records already used by the worker-owned backend path.
- Whole-message push or SSE-style delivery remains a possible later extension, but it is not the required production webchat contract for Spec 012.

### Gap 9: Channel Account and Credential Resolution
Real transports require provider tokens, signing secrets, webhook secrets, base URLs, and per-account transport settings. The current draft says secrets remain settings-only inputs, but it does not yet define how `channel_account_id` resolves to a concrete adapter configuration or how tests select fake versus real transports.

Options considered:
- Option A: support exactly one configured account per channel kind through flat environment variables
- Option B: add a settings-backed per-channel account registry keyed by `channel_account_id`, including adapter mode and bounded transport configuration
- Option C: create a new database-owned channel-account table that becomes the primary runtime configuration source
- Option D: require an external secret manager or control plane and leave in-process resolution unspecified

Selected option:
- Option B

Decision:
- This slice uses a settings-backed per-channel account registry keyed by canonical `channel_account_id`.
- The registry must be sufficient to resolve, per account:
  - whether the adapter runs in fake or real transport mode
  - outbound credentials or tokens
  - inbound verification or signing-secret configuration
  - any bounded provider base URL override or transport mode metadata
  - any bounded per-account delivery settings such as rate-limit policy identifiers
- Tests and local development must be able to select fake adapter entries through the same registry contract without requiring live provider credentials.
- Secrets remain settings-only inputs in this slice and must not be copied into transcript, manifest, artifact, or diagnostics payloads.

### Gap 10: Canonical Session Routing vs Durable Transport Addressing
Spec 001 correctly defines session continuity in terms of the canonical routing tuple, but real provider sends also need a stable transport destination such as a Slack conversation id, Telegram chat id, or webchat delivery stream key. The current draft talks about reply metadata, but it does not yet define where the base outbound transport address lives or how it is reused safely across later sends.

Options considered:
- Option A: treat the canonical `peer_id` or `group_id` as the only outbound destination identity for every provider
- Option B: resolve the provider destination ad hoc from recent inbound payloads or provider lookups on every outbound send
- Option C: persist a bounded transport-address envelope additively at ingress, tied to the session as the durable outbound destination, while keeping reply or thread targeting additive at the delivery level
- Option D: reduce scope to only providers whose routing tuple already equals the outbound send target

Selected option:
- Option C

Decision:
- Session continuity remains defined only by the canonical routing tuple from Spec 001.
- This slice also introduces one bounded durable transport-address contract resolved during verified ingress and reused for outbound sends.
- The transport address is operational metadata, not transcript truth and not a second routing store.
- Reply or thread targeting remains additive delivery metadata layered on top of the durable base transport address.

## Data Model Changes
- Preserve existing `sessions`, `messages`, `execution_runs`, `inbound_message_attachments`, `message_attachments`, `outbound_deliveries`, and `outbound_delivery_attempts` as the main durable transport-facing records.
- Additive persistence may be introduced only where real transports require durable identity or callback correlation, for example:
  - bounded session-level transport-address metadata needed to derive the real provider send target
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

### Durable Transport Address Contract
- Verified provider ingress must also resolve one bounded transport-address envelope for the destination the backend will use on later outbound sends.
- The durable transport address must be sufficient to support one provider send request without re-reading raw webhook payloads or performing transcript-dependent inference.
- The durable transport address is additive operational state only:
  - it does not replace the canonical routing tuple
  - it does not participate in transcript truth
  - it does not become a second session-routing store
- Reply or thread targeting metadata for individual sends remains additive delivery or attempt metadata layered on top of the durable transport address.

### Outbound Adapter Contract
- `src/channels/adapters/base.py` remains the shared adapter seam for this slice, but it must grow additively to support real transports.
- Real adapters must expose:
  - channel capability metadata
  - one bounded text-send method
  - one bounded media-send method where supported
  - one bounded structured error or result contract suitable for retry classification and diagnostics
- Real adapters must accept a resolved durable transport address rather than inferring the destination only from `session_id`.
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

### Production Webchat Polling Contract
- Production `webchat` polling must use a dedicated webchat client-auth boundary rather than operator diagnostics auth.
- Polling must be replay-safe and cursor-based using a monotonic backend cursor such as `after_delivery_id`.
- Polling responses may include only bounded delivery projections needed by the browser client, never provider secrets or raw webhook payloads.

### Channel-Account Registry Shape Contract
- The settings-backed channel-account registry must use one typed validated shape, not ad hoc flat variables.
- Each registry entry must include:
  - `channel_account_id`
  - `channel_kind`
  - `mode` with at least `fake` and `real`
  - provider-specific outbound credential references or values
  - provider-specific inbound verification settings
  - optional bounded base-URL override
  - optional bounded transport policy identifiers
- Validation must fail closed when a `real` account omits required provider settings for its `channel_kind`.

## Canonical Mapping Matrix
### Slack
- Supported inbound message shape:
  - verified event-callback message traffic only
- Canonical mapping to implement:
  - dedupe on `slack:{conversation_id}:{message_ts}` using the Slack conversation id plus the Slack message `ts`, not the webhook envelope `event_id`
  - `sender_id` from the native Slack actor id
  - channel or conversation identity maps to `group_id` for channel-like traffic and `peer_id` for direct-message traffic
  - the durable transport address for outbound sends is the Slack conversation id
  - thread replies reuse the same routing tuple unless the supported implementation needs additive bounded thread metadata only for reply targeting
- Ignore in this slice:
  - reaction events
  - edit or delete events
  - presence or membership changes
  - slash commands and interactive payloads

### Telegram
- Supported inbound message shape:
  - verified webhook message traffic for bot conversations in direct or group contexts
- Canonical mapping to implement:
  - dedupe on `telegram:{chat_id}:{message_id}` using both the Telegram chat id and the Telegram message id
  - `sender_id` from the native Telegram sender id
  - direct chats map to `peer_id`
  - group or supergroup chats map to `group_id`
  - the durable transport address for outbound sends is the Telegram `chat_id`
  - reply-target metadata remains additive and transport-local rather than becoming a second routing key
- Ignore in this slice:
  - edited-message updates
  - callback queries
  - inline-button interactions
  - presence-like or membership-only updates

### Webchat
- Supported inbound message shape:
  - canonical production webchat HTTP message submission
- Canonical mapping to implement:
  - dedupe on the stable client-supplied message id when present, otherwise on a server-issued canonical message id returned at acceptance time
  - `sender_id` from the webchat actor identity
  - direct browser-user conversations map to `peer_id`
  - shared-room behavior maps to `group_id` only if the slice supports it explicitly through the same canonical tuple rules
  - the durable transport address for outbound sends and polling is the webchat session delivery stream identity resolved by the gateway
- Ignore in this slice:
  - ephemeral typing or presence signals
  - token-streaming events
  - UI-only control messages that are not canonical user messages

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
