# Tasks 012: Production Channel Integration

## Alignment Decisions

### Gap 1: Provider ingress must not become a second orchestration path
Options considered:
- Option A: let provider routes persist sessions and messages directly
- Option B: proxy every provider request to `/inbound/message` over HTTP
- Option C: add provider-specific gateway routes that authenticate and translate payloads, then call the same `SessionService.process_inbound(...)` path in-process
- Option D: move provider ingress handling into worker code

Selected option:
- Option C

### Gap 2: Real provider delivery metadata must fit the current append-only delivery model
Options considered:
- Option A: keep only `provider_message_id` and ignore all other provider delivery identity
- Option B: mutate transcript rows to carry transport state
- Option C: extend delivery and attempt persistence additively with bounded provider metadata while keeping `outbound_deliveries` authoritative
- Option D: store provider state outside the main database

Selected option:
- Option C

### Gap 3: Transport retries must compose with worker retries safely
Options considered:
- Option A: let adapters retry internally until success
- Option B: push all retry behavior to providers
- Option C: keep one transport request per durable dispatcher attempt and let worker replay remain the outer retry owner
- Option D: retry synchronously inside dispatcher loops

Selected option:
- Option C

### Gap 4: Production webchat must not accidentally implement Spec 013
Options considered:
- Option A: require token streaming now
- Option B: leave `webchat` local-only and exclude it from this spec
- Option C: implement production-grade whole-message webchat delivery and ingestion while deferring token streaming
- Option D: fold `webchat` permanently into the generic inbound API only

Selected option:
- Option C

## Tasks

1. Confirm the current channel, gateway, session-service, idempotency, dispatcher, repository, diagnostics, and README seams in `apps/gateway/api/inbound.py`, `src/sessions/service.py`, `src/gateway/idempotency.py`, `src/channels/dispatch.py`, `src/channels/adapters/*.py`, and `README.md` so Spec 012 extends the existing architecture instead of creating a parallel transport path.
2. Add high-risk contract tests first for provider-facing inbound translation, proving Slack, Telegram, and webchat payloads map into the canonical inbound message shape with stable `external_message_id`, correct routing fields, bounded provider metadata, and canonical attachments where present.
3. Add high-risk request-verification tests first for provider-facing ingress routes, covering missing or invalid signatures, invalid tokens, malformed payloads, unsupported event types, and the guarantee that unverified requests never create dedupe, message, or run state.
4. Add high-risk dedupe tests first proving provider retries and webhook redelivery collapse onto the existing gateway idempotency model and do not create duplicate transcript messages when the translated provider identity is the same.
5. Add high-risk adapter-contract tests first for `src/channels/adapters/base.py` proving the shared channel adapter seam can represent structured send success, structured retryable and terminal failures, reply-thread metadata, and bounded provider identifiers without leaking provider-native SDK objects outside the adapter boundary.
6. Add high-risk dispatcher tests first proving `src/channels/dispatch.py` preserves `(outbound_intent_id, chunk_index)` logical-delivery idempotency, records durable attempts before each transport request, classifies retryable versus terminal transport failures, and stores bounded provider correlation metadata from real adapters.
7. Add high-risk reply-threading tests first proving the existing `reply_to_external_id` abstraction remains backend-owned while adapters translate it into channel-specific thread or reply behavior for Slack, Telegram, and webchat without exposing provider threading logic to graph code.
8. Extend `src/config/settings.py` with explicit per-channel settings for production enablement, credentials, webhook verification, and any bounded channel retry or rate-limit knobs required by the spec, while keeping tests runnable without live credentials and failing clearly when a production channel is enabled with missing required secrets.
9. Add or update gateway dependencies in `apps/gateway/deps.py` and app wiring in `apps/gateway/main.py` so the application can construct provider-backed channel adapters, channel ingress translators, and any required verification helpers under explicit configuration.
10. Add provider-facing gateway ingress modules under `apps/gateway/api/` for Slack, Telegram, and webchat so each route authenticates the inbound request, translates provider payloads into the canonical inbound contract, and calls `SessionService.process_inbound(...)` instead of persisting transcript rows directly.
11. Extend `src/domain/schemas.py` only as needed with additive typed request or translation helpers for provider ingress while keeping `InboundMessageRequest` as the canonical internal contract shared by direct API calls and translated provider traffic.
12. Refine `src/gateway/idempotency.py` only as needed so translated provider identities remain stable under retries or redelivery, without changing the current gateway-owned dedupe boundary or introducing provider-local dedupe caches.
13. Extend `src/sessions/service.py` and `src/sessions/repository.py` only as needed so provider-translated inbound messages, provider attachments, and any additive provider event correlation data can be persisted through the existing append-only message and attachment path without creating a second transcript store.
14. Replace the synthetic outbound behavior in `src/channels/adapters/slack.py` with a real Slack transport implementation or seam that supports verified inbound translation, outbound text send, reply threading, bounded media send, structured error mapping, and provider-safe result metadata.
15. Replace the synthetic outbound behavior in `src/channels/adapters/telegram.py` with a real Telegram transport implementation or seam that supports inbound translation, outbound text send, reply behavior, bounded media send, voice-style media routing where already supported, structured error mapping, and provider-safe result metadata.
16. Replace the local-only synthetic behavior in `src/channels/adapters/webchat.py` with a production-grade webchat transport implementation or seam for whole-message inbound and outbound delivery, explicitly keeping token streaming out of scope for this slice.
17. Update `src/channels/dispatch.py` so real provider sends persist bounded provider identifiers, thread or reply metadata, and structured failure classifications, while keeping directive parsing, chunking, attempt creation, and durable state transitions owned by the dispatcher rather than by adapters.
18. Extend `src/channels/dispatch_registry.py` so adapter selection is configuration-aware and can switch between fake local adapters for tests and provider-backed adapters for production-enabled channels without changing caller contracts.
19. Add additive persistence in `src/db/models.py`, `migrations/versions/`, and `src/sessions/repository.py` only where real transport requirements demand it, such as bounded provider event identity, delivery receipt correlation, richer attempt metadata, or callback reconciliation tied back to existing delivery rows.
20. Extend `src/observability/failures.py`, `src/observability/logging.py`, and `src/observability/diagnostics.py` so inbound verification failures, provider auth failures, rate limits, transport unavailability, invalid-request failures, and callback replay states are visible in bounded redacted form without logging secrets or full raw webhook payloads.
21. Add API tests proving provider-facing ingress routes preserve the current `202 Accepted` semantics, route through the same session-processing path as `/inbound/message`, and produce the same dedupe, session reuse, attachment staging, and queued-run behavior for accepted messages.
22. Add dispatcher and adapter integration tests proving real transport adapters can send chunked text and supported media, preserve logical-delivery idempotency under retry, and map provider reply or thread behavior correctly without bypassing shared dispatcher logic.
23. Add failure-path integration tests proving provider verification failures do not write transcript state, retryable transport failures create failed delivery attempts that can be retried safely, terminal transport failures remain bounded and diagnosable, and worker replay does not create duplicate logical deliveries.
24. Add diagnostics coverage proving operators can inspect inbound provider acceptance, outbound delivery attempts, retryability classification, bounded provider correlation identifiers, and transport failure reasons through existing read-only diagnostics surfaces.
25. Finish with verification that Slack, Telegram, and production webchat all enter through gateway-owned ingress, preserve current session routing and idempotency guarantees, keep dispatcher-owned outbound delivery semantics, remain testable without live provider dependencies in the default suite, and do not accidentally introduce streaming, human-handoff, or UI-surface behavior that belongs to later specs.
