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

### Gap 4: Channel reply intent must stay backend-owned
Options considered:
- Option A: force every channel into one universal reply field and ignore transport-specific threading
- Option B: expose full provider-native thread payloads to graph code
- Option C: keep `reply_to_external_id` as the portable intent and store only bounded provider threading metadata additively where needed
- Option D: defer reply support entirely

Selected option:
- Option C

### Gap 5: Production webchat must not accidentally implement Spec 013
Options considered:
- Option A: require token streaming now
- Option B: leave `webchat` local-only and exclude it from this spec
- Option C: implement production-grade whole-message webchat delivery and ingestion while deferring token streaming
- Option D: fold `webchat` permanently into the generic inbound API only

Selected option:
- Option C

### Gap 6: Canonical routing and dedupe mapping must be explicit per provider
Options considered:
- Option A: define one normative mapping matrix for supported Slack, Telegram, and webchat inbound event shapes
- Option B: leave provider mapping implementation-defined in code
- Option C: create a second provider-specific routing store
- Option D: support only one conversation shape per provider for now

Selected option:
- Option A

### Gap 7: Provider control requests must stay outside transcript ingress
Options considered:
- Option A: treat verification, challenge, and setup callbacks as verified gateway-owned control requests handled outside transcript creation
- Option B: force all provider callbacks through the canonical inbound message contract
- Option C: rely on manual setup and omit runtime challenge handling
- Option D: defer any provider needing challenge callbacks

Selected option:
- Option A

### Gap 8: Production webchat needs one concrete delivery contract
Options considered:
- Option A: define production webchat as HTTP inbound plus durable polling for whole outbound delivery
- Option B: define production webchat as HTTP inbound plus SSE push
- Option C: define production webchat as HTTP inbound plus server callback delivery
- Option D: remove webchat from this slice

Selected option:
- Option A

### Gap 9: Channel account and credential resolution must be registry-backed
Options considered:
- Option A: support only one flat environment-variable account per channel
- Option B: add a settings-backed per-channel account registry keyed by `channel_account_id`
- Option C: create a new database-owned channel account store
- Option D: leave runtime account resolution unspecified

Selected option:
- Option B

### Gap 10: Outbound sends need a durable transport address without replacing canonical routing
Options considered:
- Option A: force every provider to use canonical `peer_id` or `group_id` as the outbound destination
- Option B: resolve the provider destination ad hoc from recent inbound payloads or provider lookups on every send
- Option C: persist one bounded durable transport-address envelope additively at ingress and reuse it for outbound sends while keeping reply or thread metadata additive at the delivery level
- Option D: narrow the slice to only providers whose routing tuple already equals the send target

Selected option:
- Option C

## Tasks

1. Confirm the current gateway, dependency, routing, idempotency, session-service, repository, dispatcher, adapter, diagnostics, admin-read, and README seams in `apps/gateway/api/inbound.py`, `apps/gateway/api/admin.py`, `apps/gateway/deps.py`, `src/routing/service.py`, `src/gateway/idempotency.py`, `src/sessions/service.py`, `src/sessions/repository.py`, `src/channels/dispatch.py`, `src/channels/dispatch_registry.py`, `src/channels/adapters/*.py`, and `README.md` so Spec 012 extends the existing gateway-first architecture instead of creating a second transport path.
2. Add high-risk contract tests first for one explicit per-provider canonical mapping matrix, proving each supported Slack, Telegram, and webchat inbound event shape maps deterministically into the canonical inbound fields, uses the correct stable `external_message_id`, sets `sender_id`, `peer_id`, and `group_id` correctly, derives the correct durable transport address, and ignores unsupported event shapes cleanly.
3. Add high-risk provider control-request tests first proving challenge, verification, and setup callbacks return the required provider-facing success semantics without creating dedupe rows, transcript messages, sessions, or execution runs.
4. Add high-risk request-verification tests first for provider-facing ingress routes, covering missing or invalid signatures, invalid verification tokens, malformed payloads, unsupported event types, and the guarantee that unverified requests fail closed before any transcript or idempotency write.
5. Add high-risk dedupe tests first proving provider retries, webhook redelivery, and repeated canonical webchat submissions collapse onto the existing gateway idempotency model keyed by `(channel_kind, channel_account_id, external_message_id)` and do not create duplicate transcript rows.
6. Add high-risk adapter-contract tests first for `src/channels/adapters/base.py` proving the shared seam can represent durable transport-address inputs, structured send success, structured retryable and terminal failures, bounded provider correlation metadata, and reply-thread translation inputs without leaking provider-native clients or SDK payloads outside the adapter boundary.
7. Add high-risk dispatcher tests first proving `src/channels/dispatch.py` preserves `(outbound_intent_id, chunk_index)` logical-delivery idempotency, records durable attempts before each transport request, resolves the durable transport address without inferring it from `session_id` alone, derives provider idempotency keys from durable identities where supported, classifies retryable versus terminal failures centrally, and persists bounded provider correlation and threading metadata.
8. Add high-risk channel-account registry tests first proving a typed settings-backed registry keyed by canonical `channel_account_id` can resolve `channel_kind`, fake versus real adapter mode, outbound credentials, inbound verification settings, bounded base-URL overrides, and bounded per-account transport policy identifiers while failing closed on incomplete real-account configuration.
9. Add high-risk production webchat polling tests first proving the chosen contract is canonical HTTP inbound plus dedicated client-authenticated durable polling for already-persisted whole outbound delivery results only, with replay-safe cursoring, no token streaming, no SSE, no partial transcript state, and no provider-owned orchestration.
10. Extend `src/config/settings.py` with one typed settings-backed per-channel account registry keyed by canonical `channel_account_id`, sufficient to resolve `channel_kind`, fake versus real adapter mode, outbound credentials, inbound verification settings, bounded base-URL overrides, and bounded per-account transport policy identifiers, while keeping secrets settings-only and excluded from diagnostics payloads.
11. Update `.env.example` with the new typed channel-account registry shape, fake-versus-real transport examples, inbound verification settings, and any bounded per-account transport policy settings required to configure Slack, Telegram, and production webchat safely.
12. Add or update gateway dependencies in `apps/gateway/deps.py` and app wiring in `apps/gateway/main.py` so the application can build the shared channel-account registry, transport-aware adapters, provider verification helpers, and production webchat polling dependencies without hidden globals.
13. Add provider-facing gateway ingress modules under `apps/gateway/api/` for Slack, Telegram, and webchat so each route verifies the inbound request, distinguishes provider control requests from canonical message ingress, translates supported payloads into the canonical inbound contract, resolves the durable transport address, and calls `SessionService.process_inbound(...)` instead of persisting transcript rows directly.
14. Extend `src/domain/schemas.py` only as needed with additive typed request and response models for provider translation helpers, durable transport-address envelopes, provider control-request responses, and production webchat polling, while keeping `InboundMessageRequest` as the canonical backend-owned message-ingress envelope.
15. Refine `src/routing/service.py` only if needed with additive normalization helpers that preserve the Spec 001 routing tuple invariants for supported provider mappings without introducing provider-specific session caches or second routing state.
16. Refine `src/gateway/idempotency.py` only as needed so translated provider identities and repeated webchat submissions remain stable under retries and redelivery without changing the existing gateway-owned dedupe boundary or adding provider-local dedupe caches.
17. Extend `src/sessions/service.py` and `src/sessions/repository.py` only as needed so translated provider messages, canonicalized provider attachments, durable transport-address metadata, bounded provider event identity or replay-visibility metadata, and production webchat polling reads all flow through the existing append-only session, message, attachment, run, delivery, and attempt model without creating a second transcript or outbound truth source.
18. Replace the synthetic outbound behavior in `src/channels/adapters/slack.py` with a real Slack transport seam that supports verified inbound translation inputs, outbound text send, reply-thread translation, bounded media send, structured error mapping, and provider-safe result metadata, while keeping Slack challenge handling outside transcript creation.
19. Replace the synthetic outbound behavior in `src/channels/adapters/telegram.py` with a real Telegram transport seam that supports verified inbound translation inputs, outbound text send, reply behavior, bounded media send, voice-safe media handling where supported, and structured error mapping with provider-safe result metadata.
20. Replace the local-only synthetic behavior in `src/channels/adapters/webchat.py` with a production webchat transport seam that supports canonical HTTP inbound submission plus durable whole-message polling for outbound delivery visibility, explicitly keeping token streaming, SSE, and browser-session orchestration out of scope for this slice.
21. Update `src/channels/dispatch.py` so real provider sends resolve and use the durable transport address, persist bounded provider message identifiers, bounded reply or thread metadata, structured retryability classification, and any bounded per-account backoff or rate-limit policy results, while keeping directive parsing, chunking, attempt creation, and durable state reconciliation owned by the dispatcher.
22. Extend `src/channels/dispatch_registry.py` so adapter selection resolves through the shared channel-account registry rather than a hard-coded one-adapter-per-channel map, allowing tests and local development to use fake adapters through the same runtime contract as production.
23. Add additive persistence in `src/db/models.py`, `migrations/versions/`, and `src/sessions/repository.py` only where real transport requirements demand it, such as bounded durable transport-address metadata, bounded provider event identity for replay visibility, richer delivery or attempt metadata, receipt or callback correlation keyed back to existing deliveries, or bounded durable polling reads for production webchat.
24. Extend `src/observability/failures.py`, `src/observability/logging.py`, and `src/observability/diagnostics.py` so provider verification failures, control-request handling, auth failures, rate limits, invalid-request failures, transport-unavailable failures, callback replay states, and bounded provider correlation identifiers are visible in redacted bounded form without logging secrets or full raw webhook payloads.
25. Add repository tests for any additive provider-event persistence, richer delivery or attempt metadata persistence, receipt or callback reconciliation keyed to existing deliveries, idempotent logical-delivery reuse under retry, and bounded production webchat polling reads over persisted outbound deliveries.
26. Add API tests proving provider-facing ingress routes preserve the current `202 Accepted` semantics for accepted canonical messages, route through the same session-processing path as `/inbound/message`, and produce the same dedupe, session reuse, attachment staging, and queued-run behavior for accepted messages.
27. Add API tests proving provider control or challenge routes return the correct provider-specific success semantics, remain distinguishable from canonical message acceptance in logs and diagnostics, and never create transcript, dedupe, session, or run state.
28. Add API tests proving production webchat polling returns already-persisted whole-message delivery state only, enforces the dedicated webchat client-auth boundary, uses replay-safe cursor semantics, and does not expose partial tokens, provider secrets, or unbounded raw metadata.
29. Add dispatcher and adapter integration tests proving real transport seams can send chunked text and supported media, preserve logical-delivery idempotency under retry, map reply or thread behavior correctly, and keep one transport request per durable attempt without adapter-local retry loops.
30. Add failure-path integration tests proving provider verification failures do not write transcript state, retryable transport failures create failed delivery attempts that can be retried safely, terminal transport failures remain bounded and diagnosable, control requests stay outside transcript ingress, and worker replay does not create duplicate logical deliveries.
31. Add diagnostics coverage proving operators can inspect inbound provider acceptance, control-request handling, outbound delivery attempts, retryability classification, bounded provider event identity, bounded reply or thread metadata, and transport failure reasons through existing read-only diagnostics surfaces.
32. Update `README.md` so the documented channel architecture, supported transport behavior, provider-facing ingress routes, production webchat polling contract, fake-versus-real account configuration model, and current non-goals match the implemented Spec 012 behavior instead of the older local-only channel description.
33. Finish with verification that Slack, Telegram, and production webchat all enter through gateway-owned verified ingress, preserve Spec 001 routing and idempotency guarantees, keep session routing distinct from the additive durable transport-address contract, keep dispatcher-owned outbound delivery semantics, remain testable without live provider access in the default suite, do not create a second transcript or outbound truth source, and do not accidentally introduce streaming, human-handoff, or UI-surface behavior that belongs to later specs.
