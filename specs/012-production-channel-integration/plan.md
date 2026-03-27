# Plan 012: Production Channel Integration

## Target Modules
- `pyproject.toml` only if a transport dependency materially improves maintainability over direct HTTP calls
- `.env.example`
- `apps/gateway/main.py`
- `apps/gateway/deps.py`
- `apps/gateway/api/inbound.py`
- `apps/gateway/api/admin.py` only if production `webchat` polling lands on the existing authenticated read surface
- `apps/gateway/api/` add provider-facing ingress modules for `slack`, `telegram`, and `webchat`
- `src/config/settings.py`
- `src/domain/schemas.py`
- `src/gateway/idempotency.py`
- `src/routing/service.py` only if additive helpers are needed for deterministic provider mapping or reply-safe routing metadata
- `src/sessions/service.py`
- `src/sessions/repository.py`
- `src/channels/adapters/base.py`
- `src/channels/adapters/slack.py`
- `src/channels/adapters/telegram.py`
- `src/channels/adapters/webchat.py`
- `src/channels/dispatch.py`
- `src/channels/dispatch_registry.py`
- `src/observability/failures.py`
- `src/observability/logging.py`
- `src/observability/diagnostics.py`
- `src/db/models.py`
- `migrations/versions/`
- `tests/`

## Success Conditions
- The repo gains real provider-backed inbound and outbound transport behavior for `slack`, `telegram`, and production `webchat` without bypassing the existing session service, idempotency service, worker execution flow, or outbound dispatcher.
- Provider-facing ingress routes remain translation-only boundaries that authenticate or verify requests, map supported provider payloads into the existing canonical inbound contract, and preserve current `202 Accepted` behavior through `SessionService.process_inbound(...)`.
- A typed settings-backed channel-account registry keyed by canonical `channel_account_id` becomes the only runtime source for choosing fake versus real transport mode, credentials, verification secrets, bounded per-account transport metadata, and validation behavior.
- The plan explicitly implements one normative per-provider canonical mapping matrix for supported Slack, Telegram, and webchat inbound event shapes so session reuse and duplicate suppression stay deterministic.
- Provider verification or control requests are handled at the gateway boundary without creating transcript rows, dedupe rows, sessions, or execution runs.
- Production `webchat` lands as canonical HTTP inbound plus dedicated client-authenticated durable polling for whole-message outbound delivery, not token streaming or SSE.
- Session routing remains owned by the canonical Spec 001 tuple while one additive durable transport-address contract makes outbound sends deterministic for real providers.
- Outbound delivery and attempt records remain the single outbound truth source while gaining bounded provider identifiers, threading metadata, and retryability classification.
- Tests exercise the end-to-end channel flow with fakes or stubs and do not require live provider access in the default suite.

## Migration Order
1. Define the channel-account configuration and dependency-resolution surface first:
   - add a settings-backed per-channel account registry keyed by canonical `channel_account_id`
   - include `channel_kind`, adapter mode, outbound credentials, inbound verification configuration, bounded base-URL overrides, and bounded per-account transport policy metadata
   - keep fake adapter entries available through the same registry for tests and local development
2. Define the shared transport and mapping contracts before wiring any live endpoint:
   - grow `ChannelAdapter` additively for structured success, structured failure, bounded threading metadata, and provider correlation data
   - define one normative provider-mapping matrix for supported inbound event shapes
   - define one durable transport-address contract resolved at ingress and reused by outbound sends
   - define control-request handling separately from canonical message-ingress handling
   - define the concrete production `webchat` polling auth and cursor contract before implementing routes
3. Add additive persistence only where real providers require durable correlation:
   - bounded session-level transport-address metadata
   - bounded provider metadata fields on outbound deliveries or attempts
   - inbound provider event identity or callback identity if replay visibility needs durable storage
   - optional bounded receipt or callback reconciliation records keyed back to existing outbound deliveries
4. Add provider-facing gateway ingress routes that verify requests, translate supported payloads into the canonical inbound contract, and call the existing session-service path directly in-process.
5. Extend dispatcher and account resolution before channel-specific transport swaps:
   - resolve the effective adapter and account config from the shared registry
   - preserve one transport request per durable attempt
   - keep durable logical-delivery and attempt creation ahead of provider send calls
6. Replace synthetic outbound adapter behavior channel by channel while preserving dispatcher ownership, reply abstraction, and retry-safe replay.
7. Extend observability and diagnostics so inbound acceptance, control-request handling, provider correlation identifiers, and transport failures remain explainable before broad integration rollout.
8. Finish with unit, API, repository, and integration coverage proving the gateway-first, worker-owned, append-only model still holds for all supported channels.

## Implementation Shape
- Preserve the current architecture already visible in the codebase and prior specs:
  - `POST /inbound/message` remains the canonical backend-owned ingress contract and test seam
  - provider-facing routes are additive translation-only boundaries inside the gateway app
  - `SessionService.process_inbound(...)` remains the canonical message-ingest orchestrator
  - `IdempotencyService` remains authoritative for inbound dedupe
  - `OutboundDispatcher` remains authoritative for outbound logical delivery and attempt sequencing
  - channel adapters remain transport boundaries rather than orchestration layers
- Do not proxy provider routes back into `POST /inbound/message` over HTTP:
  - provider handlers verify the request
  - they translate the payload into the canonical inbound envelope
  - they call the same session-service contract in-process
- Keep real provider logic isolated:
  - provider SDK clients, signing checks, webhook challenge handling, and request or response payloads stay in provider-facing gateway or adapter modules
  - graph, tool, context, governance, and policy modules remain provider-agnostic
- Keep retry ownership explicit and layered:
  - the dispatcher and worker remain the durable retry owners
  - adapters perform at most one provider request per durable attempt
  - if provider-native idempotency keys are supported, derive them from durable delivery or attempt identity rather than ephemeral process state
- Keep rollout incremental:
  - one shared account-resolution and transport contract
  - then provider ingress and webchat polling seams
  - then channel-specific outbound transport implementations
  - then diagnostics and integration coverage

## Service and Module Boundaries
### Gateway and Ingress Responsibilities
- `apps/gateway/api/inbound.py`
  - keep `/inbound/message` unchanged as the canonical internal and test ingress contract
  - do not absorb provider-specific verification or translation logic into the generic route
- `apps/gateway/api/` provider-facing ingress modules
  - add dedicated Slack, Telegram, and webchat routes owned by the gateway app
  - authenticate or verify provider traffic before any transcript or dedupe write
  - distinguish provider control requests from canonical message requests
  - call `SessionService.process_inbound(...)` only after successful translation into the canonical inbound contract
- `apps/gateway/main.py`
  - register the additive provider ingress routes and any production webchat polling routes without weakening existing health or diagnostics boundaries
- `apps/gateway/deps.py`
  - inject the channel-account registry, transport-aware adapters, and any verification helpers without introducing hidden globals

### Settings and Account Resolution
- `src/config/settings.py`
  - add a settings-backed per-channel account registry keyed by canonical `channel_account_id`
  - each account entry must be sufficient to resolve:
    - `channel_kind`
    - fake versus real adapter mode
    - outbound tokens or credentials
    - inbound signing-secret or verification-token settings
    - bounded provider base-URL overrides
    - bounded per-account transport policy identifiers such as rate-limit policy
  - fail clearly when an explicitly enabled real transport account lacks required credentials
  - keep secrets excluded from logs and diagnostics
- `src/channels/dispatch_registry.py`
  - stop hard-coding one adapter instance per channel kind only
  - resolve the effective adapter and account configuration through the shared registry so tests and production use the same contract

### Canonical Inbound Mapping and Session Ownership
- `src/domain/schemas.py`
  - keep `InboundMessageRequest` as the canonical backend-owned envelope
  - add only the minimal additive request or response schemas needed for provider ingress and production webchat polling
- `src/sessions/service.py`
  - remain the only owner of canonical message-ingest orchestration
  - accept translated provider inputs without knowing provider-native payload shapes
  - preserve current dedupe, transcript persistence, attachment staging, and run-creation behavior
  - accept additive durable transport-address inputs without moving provider payload handling into the session layer
- `src/gateway/idempotency.py`
  - remain the only durable inbound dedupe mechanism
  - continue keying replay on `(channel_kind, channel_account_id, external_message_id)` no matter which provider route translated the message
- `src/routing/service.py`
  - keep Spec 001 routing invariants intact
  - keep session identity separate from any additive durable transport-address metadata
  - add helpers only if supported provider mapping needs deterministic normalization beyond the current tuple handling

### Dispatcher and Adapter Responsibilities
- `src/channels/adapters/base.py`
  - extend the shared seam additively with:
    - structured send success metadata
    - structured send failure metadata with retryability classification
    - durable transport-address inputs
    - bounded provider threading or correlation metadata
    - any transport-local verification or translation helpers that do not become a second orchestration layer
  - keep the interface narrow:
    - one bounded text-send method
    - one bounded media-send method where supported
- `src/channels/dispatch.py`
  - remain the only orchestrator for outbound transport sends
  - continue to own directive parsing, capability checks, deterministic chunking, durable logical-delivery creation, durable attempt creation, adapter send calls, and durable reconciliation
  - gain durable transport-address resolution, bounded provider correlation persistence, reply-thread translation inputs, retryability mapping, and per-account backoff or rate-limit policy enforcement
- `src/channels/adapters/slack.py`
  - replace synthetic send behavior with a real Slack transport path
  - support signature verification inputs, outbound text send, reply-thread translation, bounded media send, and structured failure mapping
  - keep Slack challenge or control-request behavior outside transcript creation
- `src/channels/adapters/telegram.py`
  - replace synthetic send behavior with a real Telegram transport path
  - support verified webhook ingress assumptions for this slice, outbound text send, reply translation, bounded media send, voice-safe media handling, and structured failure mapping
- `src/channels/adapters/webchat.py`
  - replace the local-only behavior with a production webchat transport contract
  - support canonical HTTP inbound submission plus dedicated client-authenticated durable whole-message polling for outbound delivery visibility
  - keep this slice strictly non-streaming

### Persistence and Diagnostics Responsibilities
- `src/db/models.py` and `migrations/versions/`
  - prefer additive persistence changes only where transport requirements exceed the current schema
  - candidate additions:
    - bounded session-level transport-address metadata
    - bounded provider metadata on outbound deliveries or attempts
    - inbound provider event identity rows for replay visibility or webhook dedupe diagnostics
    - bounded receipt or callback correlation rows keyed to existing outbound deliveries
  - do not create a second transcript store, a second routing store, or a provider-owned outbound queue
- `src/sessions/repository.py`
  - reuse current session, message, attachment, delivery, and attempt helpers where possible
  - add repository helpers only as needed for:
    - durable transport-address persistence and lookup
    - provider event lookup or replay visibility
    - richer outbound correlation metadata persistence
    - receipt or callback reconciliation back to existing delivery rows
    - production webchat polling reads over already-persisted outbound deliveries
- `src/observability/logging.py`
  - emit structured redacted events for provider ingress acceptance or rejection, control-request handling, transport send attempts, and classified failures
- `src/observability/failures.py`
  - centralize real transport failure classification so rate limits, auth failures, malformed requests, and transport-unavailable failures do not rely on scattered string parsing
- `src/observability/diagnostics.py`
  - extend bounded diagnostics surfaces so operators can inspect provider event identity, delivery attempts, retryability, and provider correlation identifiers without storing raw secrets or full webhook payloads

## Contracts to Implement
### Channel-Account Registry Contract
- One settings-backed registry keyed by canonical `channel_account_id`.
- The same registry contract must support:
  - fake adapters in tests and local development
  - real adapters in configured environments
  - explicit `channel_kind`
  - outbound credentials
  - inbound verification settings
  - bounded per-account transport metadata
- Secrets remain settings-only inputs and must not be copied into transcript, manifests, artifacts, or diagnostics payloads.

### Canonical Inbound Mapping Contract
- Document one explicit per-provider mapping table for every supported inbound message shape in this slice.
- The mapping must define, per supported event shape:
  - which native identifier becomes `external_message_id`
  - which native actor becomes `sender_id`
  - whether the message routes through `peer_id` or `group_id`
  - how thread-root or reply-container identifiers affect routing, if at all
  - which event shapes are ignored rather than translated
- The mapping must preserve the Spec 001 invariant that the same normalized routing tuple yields the same session identity.

### Provider Control-Request Contract
- Provider verification, challenge, or setup callbacks are gateway-owned control requests.
- Successful control-request handling must not create transcript rows, dedupe rows, sessions, or execution runs.
- API tests and observability must distinguish control-request success from canonical message acceptance.

### Outbound Delivery and Replay Contract
- `outbound_deliveries` and `outbound_delivery_attempts` remain authoritative for outbound state.
- One durable attempt corresponds to one transport request.
- The logical-delivery key remains `(outbound_intent_id, chunk_index)`.
- If a provider supports outbound idempotency keys, derive them from existing durable identities.
- Provider receipt or callback data must reconcile back to existing delivery rows rather than creating a second outbound truth source.

### Durable Transport Address Contract
- Verified ingress resolves one bounded durable transport-address envelope per session.
- The durable transport address is additive operational state only and never replaces the canonical Spec 001 routing tuple.
- Outbound sends use the durable transport address plus additive reply or thread metadata, rather than inferring a provider destination from `session_id` alone.

### Production Webchat Contract
- Production `webchat` in this slice is:
  - canonical HTTP inbound submission
  - durable polling for whole outbound message delivery
- Polling reads only already-persisted outbound delivery results.
- Polling must not introduce token streaming, SSE, partial transcript state, or provider-owned orchestration.
- Reply and media support stay bounded to what the durable delivery model can already express cleanly.
- Polling must use a dedicated webchat client-auth boundary rather than operator diagnostics auth.
- Polling must be replay-safe and cursor-based using a monotonic backend cursor such as `after_delivery_id`.

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

## Risk Areas
- Provider-facing ingress routes could accidentally bypass the session service and create a second inbound orchestration path.
- The wrong per-provider `external_message_id` choice could break current dedupe guarantees under webhook redelivery.
- A hard-coded one-adapter-per-channel design could make per-account credential resolution and fake-versus-real transport selection impossible to test cleanly.
- Internal adapter retries could multiply with worker retries and make delivery behavior nondeterministic.
- Provider control requests could accidentally create transcript artifacts if they are not separated clearly from canonical message ingress.
- Webchat scope could drift into streaming, SSE, or browser-session orchestration that belongs to Spec 013.
- Receipt or callback reconciliation could create a second outbound truth source if it is not tied back to existing delivery rows.

## Rollback Strategy
- Keep all transport integrations behind explicit account-registry configuration so fake adapters remain selectable.
- Land gateway routes, persistence changes, and dispatcher changes additively so disabling one provider is a configuration rollback first.
- Preserve `/inbound/message` and the existing worker-owned dispatcher contracts so local and CI workflows still function if production transport integrations are disabled.
- If one provider integration regresses, disable that provider account or provider-specific route without removing the shared session-service, idempotency, and dispatcher boundaries.
- Keep production `webchat` polling additive so disabling it does not affect canonical transcript ingestion or the existing read surfaces.

## Test Strategy
### Unit
- provider payload translation into the canonical inbound shape for Slack, Telegram, and webchat
- provider verification failure, malformed payload rejection, and control-request handling
- channel-account registry parsing and fake-versus-real adapter resolution
- dedupe identity selection per supported provider event shape
- adapter success metadata and structured failure mapping
- reply or thread translation and bounded provider metadata persistence
- production webchat polling response shaping over existing durable delivery rows

### Repository
- additive provider-event persistence helpers if introduced
- additive delivery or attempt metadata persistence
- receipt or callback reconciliation keyed to existing delivery rows
- idempotent logical-delivery reuse under retry
- bounded polling reads for production webchat over persisted outbound deliveries

### API
- provider-facing ingress routes prove verified requests reach the same session-processing path as `POST /inbound/message`
- provider control or challenge routes return the correct success semantics without creating transcript state
- malformed or unverified provider requests fail closed before dedupe or transcript writes
- production webchat polling returns already-persisted whole-message delivery state only

### Integration
- provider-originated inbound accept preserves current dedupe, routing, transcript persistence, and queued-run creation behavior
- worker execution and outbound delivery still flow through the existing queue and dispatcher path after provider-originated inbound messages
- outbound delivery through real adapter seams with fakes or stubs preserves chunk ordering, logical-delivery idempotency, reply handling, and media gating
- inbound webhook redelivery and outbound send retry remain replay-safe
- diagnostics visibility explains provider event acceptance, control-request handling, delivery attempts, and classified failures without raw secret leakage

## Constitution Check
- Gateway-first execution preserved: provider-facing routes translate into the existing gateway-owned session service rather than creating a second orchestration path.
- Transcript-first durability preserved: only canonical message ingress creates transcript rows; provider control requests stay outside transcript and run creation.
- Worker-owned execution preserved: adapters do one transport request at a time while the worker and dispatcher remain the durable retry owners.
- Observable, bounded transport state preserved: provider identifiers, retryability, and threading metadata stay additive, redacted, and tied back to existing canonical delivery records.
