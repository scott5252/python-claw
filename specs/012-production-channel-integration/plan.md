# Plan 012: Production Channel Integration

## Target Modules
- `apps/gateway/api/inbound.py`
- `apps/gateway/api/` add provider-facing ingress modules for supported channels
- `apps/gateway/main.py`
- `apps/gateway/deps.py`
- `src/config/settings.py`
- `src/domain/schemas.py`
- `src/gateway/idempotency.py`
- `src/routing/service.py` only if transport mapping needs additive routing helpers
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
- The repo gains real inbound and outbound transport integrations for `slack`, `telegram`, and `webchat` without bypassing the existing session service, idempotency service, worker execution flow, or outbound dispatcher.
- Provider-facing ingress routes authenticate requests, translate payloads into the canonical inbound message contract, and preserve current `202 Accepted` behavior through the existing gateway-owned persistence path.
- The current synthetic adapter behavior in `src/channels/adapters/*.py` is replaced with provider-backed implementations or provider-backed adapter seams that still keep transport specifics inside the adapter boundary.
- `src/channels/dispatch.py` continues to own directive parsing, chunking, delivery row creation, and attempt auditing while gaining bounded provider failure mapping, real provider identifiers, and transport-safe retry behavior.
- Inbound and outbound replay stay idempotent under provider retries, worker retries, and callback redelivery.
- Tests can exercise the full channel flow with fakes or stubs and do not require live external provider access in the default suite.

## Migration Order
1. Define the transport configuration and credential surface first:
   - add explicit per-channel settings for enablement, credentials, endpoint secrets, and webhook verification
   - keep local or fake adapters available for tests and scaffold environments
2. Define the shared transport contracts before implementing channel specifics:
   - grow `ChannelAdapter` additively for structured send errors or results
   - define shared inbound translation or verification helper contracts
   - define any bounded provider metadata additions for deliveries or inbound events
3. Add additive persistence only where real providers require durable correlation:
   - inbound provider event identity if needed for webhook replay visibility
   - outbound provider metadata or receipt correlation fields if the current delivery schema is insufficient
4. Add provider-facing gateway ingress routes that authenticate requests and translate payloads into the canonical inbound session-service path.
5. Replace synthetic outbound adapter behavior channel by channel while preserving dispatcher ownership and durable attempt recording.
6. Extend diagnostics and observability so real transport states remain explainable before broad integration testing.
7. Finish with end-to-end tests proving transport flows preserve the existing gateway-first, worker-owned, append-only model.

## Implementation Shape
- Preserve the current architecture already visible in the codebase:
  - `SessionService.process_inbound(...)` remains the canonical message-ingest orchestrator
  - `IdempotencyService` remains authoritative for inbound dedupe
  - `OutboundDispatcher` remains authoritative for outbound logical delivery and attempt sequencing
  - channel adapters remain thin transport boundaries rather than orchestration layers
- Add transport-specific ingress in the gateway, not in the worker:
  - inbound Slack, Telegram, and webchat routes belong in `apps/gateway/api/`
  - those routes authenticate and translate provider payloads
  - they then call the same session service already used by `/inbound/message`
- Keep real provider logic isolated:
  - provider SDKs, webhook signature logic, and provider request or response payloads remain inside channel-specific modules
  - graph, tool, context, and policy modules stay provider-agnostic
- Keep rollout incremental:
  - one shared transport contract
  - then channel-specific implementations behind the same adapter seam
  - then integration and diagnostics coverage

## Channel Integration Design
### Shared Adapter Boundary
- Extend `src/channels/adapters/base.py` with additive shared types for:
  - structured transport send success metadata
  - structured transport failure metadata with retryable classification
  - optional inbound verification and payload translation helpers for provider-backed channels
- Keep the adapter interface narrow:
  - one text-send method
  - one media-send method where supported
  - any additional helpers remain transport-local and do not become new orchestration seams

### Slack
- Replace the current synthetic send implementation with a real Slack transport path.
- Support this slice’s minimum behaviors:
  - inbound event translation into canonical gateway message fields
  - signature verification
  - outbound text send
  - outbound reply threading using existing reply metadata
  - bounded media send where already supported by dispatcher contracts
- Defer rich block-kit layout, slash commands, reactions, and interactive approval UX.

### Telegram
- Replace the current synthetic send implementation with a real Telegram transport path.
- Support this slice’s minimum behaviors:
  - webhook or polling-based inbound message translation into canonical gateway message fields
  - bot-token authenticated outbound send
  - outbound replies
  - bounded media send
  - existing voice-style media routing where the current dispatcher already distinguishes it
- Defer advanced command menus, inline buttons, and streaming updates.

### Webchat
- Replace the current local-only webchat adapter behavior with a real transport contract suitable for production use.
- Keep this slice non-streaming:
  - full-message inbound send
  - durable outbound whole-message delivery
  - reply and media support only where the webchat transport contract can represent them cleanly
- Do not implement token streaming or UI orchestration that belongs to Spec 013.

## Inbound Gateway Design
### Provider-Facing Routes
- Add dedicated gateway routes for channel ingress rather than forcing external providers to call `/inbound/message` directly.
- Each route should:
  - verify or authenticate the provider request
  - normalize provider identities into `channel_account_id`, `sender_id`, `peer_id`, and `group_id`
  - resolve stable `external_message_id`
  - map supported attachments into `CanonicalAttachmentInput`
  - call `SessionService.process_inbound(...)`
- Keep the generic `/inbound/message` route intact for internal tests, manual QA, and local tool-driven ingestion.

### Dedupe Identity
- Reuse `src/gateway/idempotency.py` rather than inventing transport-local dedupe caches.
- If provider event IDs and message IDs differ, define one explicit mapping per channel and keep it documented and test-covered.
- Ensure translated dedupe identity is stable across provider retries and webhook redelivery.

## Outbound Delivery Design
### Dispatcher Responsibilities
- Keep `src/channels/dispatch.py` as the durable orchestration point.
- Additive changes should let it:
  - persist real provider identifiers
  - classify transport failures structurally
  - preserve channel thread or reply metadata in bounded form
  - enforce configured rate-limit or backoff policy per adapter or channel account
- Keep the logical-delivery key as `(outbound_intent_id, chunk_index)`.

### Failure Handling
- Continue creating a durable attempt row before each transport request.
- Adapter code should return structured failure information, but the dispatcher still decides how durable delivery rows transition.
- Map failures into at least:
  - retryable transport unavailable
  - retryable rate-limited
  - terminal auth or verification failure
  - terminal invalid request or unsupported operation

## Persistence Shape
### `src/db/models.py` and `migrations/versions/`
- Prefer additive persistence changes only if transport requirements exceed the current schema.
- Candidate additions:
  - bounded provider metadata fields on outbound deliveries or attempts
  - inbound provider event records if webhook replay visibility needs durable storage
  - delivery receipt or callback records tied back to existing outbound deliveries
- Preserve current append-only audit direction and avoid mutating transcript rows to carry transport state.

### `src/sessions/repository.py`
- Reuse current message, attachment, and delivery helpers where possible.
- Add helper methods only as needed for:
  - provider event identity lookup
  - richer delivery or attempt metadata persistence
  - receipt or callback reconciliation
- Keep repository methods session-scoped and durable-record oriented.

## Settings and Dependency Design
### `src/config/settings.py`
- Add explicit per-channel settings for:
  - channel enablement
  - provider credentials
  - webhook signing secrets or verification tokens
  - outbound base URLs or API hosts when needed
  - rate-limit or retry policy knobs if they belong in configuration
- Keep tests runnable without requiring production credentials.
- Fail clearly when a production channel is explicitly enabled but required credentials are missing.

### Dependencies
- Add any Slack, Telegram, or webchat transport dependencies explicitly in `pyproject.toml` only if they improve maintainability over direct HTTP calls.
- Keep the transport boundary easy to stub in tests.

## Observability and Diagnostics
- Extend `src/observability/failures.py` and `src/observability/logging.py` so transport failures remain structured and redacted.
- Extend `src/observability/diagnostics.py` only as needed so operators can inspect:
  - inbound provider event acceptance
  - delivery attempt history
  - retryability classification
  - provider correlation identifiers in bounded form
- Do not log raw secrets or full webhook payloads.

## Risk Areas
- Provider ingress routes could accidentally bypass the session service and create a second inbound orchestration path.
- Real provider retry behavior could break current dedupe guarantees if the wrong inbound identity is chosen.
- Internal adapter retries could multiply with worker retries and make failure handling nondeterministic.
- Rich provider payloads could leak too much raw metadata into durable tables or logs.
- Webchat scope could drift into streaming or UI concerns that belong to Spec 013.
- Delivery receipt reconciliation could accidentally create a second outbound truth source if not tied back to existing delivery rows.

## Rollback Strategy
- Keep transport integrations behind explicit configuration so stub or fake adapters remain available.
- Land additive gateway routes and persistence changes so disabling a given provider is a configuration rollback first.
- Preserve `/inbound/message` and the current dispatcher contracts so local and CI workflows still function if a production transport integration is disabled.
- If one provider integration regresses, disable that provider-specific adapter or route without removing the shared dispatcher and session-service boundaries.

## Test Strategy
### Unit
- provider payload translation into canonical inbound shape
- request verification and auth failure handling
- adapter send success and structured failure mapping
- dedupe identity selection per provider
- provider reply or thread translation
- bounded provider metadata persistence

### Repository
- additive delivery or provider-event persistence helpers
- callback or receipt reconciliation keyed to existing delivery rows
- idempotent logical-delivery reuse under retry

### Integration
- provider ingress route to session-service acceptance path
- worker execution through existing queue path after provider-originated inbound messages
- outbound delivery through real adapter seams with fakes or stubs
- retry and replay behavior for inbound webhook redelivery and outbound send failure
- diagnostics visibility for real transport attempts and failures

## Rollout Notes
- Start with fake or stubbed transport implementations behind the production adapter seams so the shared contracts are testable before live provider rollout.
- Enable one channel at a time in non-production environments.
- Keep local development centered on `/inbound/message` and fake adapters until transport credentials and callback endpoints are available.
