# Plan 007: Channels, Streaming, Chunking, and Media Pipeline

## Target Modules
- `apps/gateway/api/inbound.py`
- `apps/gateway/deps.py`
- `src/config/settings.py`
- `src/domain/schemas.py`
- `src/db/models.py`
- `src/sessions/repository.py`
- `src/sessions/service.py`
- `src/context/service.py`
- `src/graphs/state.py`
- `src/tools/messaging.py`
- `src/jobs/service.py`
- `src/channels/dispatch.py`
- `src/channels/adapters/base.py`
- `src/channels/adapters/webchat.py`
- `src/channels/adapters/slack.py`
- `src/channels/adapters/telegram.py`
- `src/domain/reply_directives.py`
- `src/domain/block_chunker.py`
- `src/media/processor.py`
- `migrations/versions/`
- `tests/`

## Migration Order
1. Add additive persistence for attachment normalization and outbound delivery auditing:
   - `message_attachments`
   - `outbound_deliveries`
2. Add required enums, retention fields, and indexes with idempotency-safe lookup paths:
   - `message_attachments(message_id, ordinal)`
   - `message_attachments(session_id, created_at)`
   - `outbound_deliveries(outbound_intent_id, chunk_index)`
   - `outbound_deliveries(session_id, created_at)`
   - unique `(outbound_intent_id, chunk_index)`
3. Extend the canonical inbound contract before worker-path changes:
   - optional `attachments` on `POST /inbound/message`
   - bounded canonical attachment input shape on the gateway surface
4. Introduce attachment normalization contracts before context assembly changes:
   - worker-owned first-pass normalization after the queued run is claimed
   - append-only terminal attachment rows with `stored`, `rejected`, or `failed`
   - idempotent retry behavior for resumed Spec 005 runs
5. Extend runtime-owned outbound intent contracts before adapter wiring:
   - preserve Spec 002 runtime ownership of outbound intents
   - enrich intent payloads and state so the dispatcher can combine assistant text, reply directives, and media work deterministically
6. Add shared dispatcher, directive parsing, chunking, and capability-gating services before any transport-specific adapter send logic.
7. Finish by wiring the supported adapters for `webchat`, `slack`, and `telegram`, then add integration and failure-mode coverage.

## Implementation Shape
- Preserve the gateway-first execution model from Specs 001 through 006 and the current README:
  - `POST /inbound/message` still durably persists the inbound transcript row, creates or reuses the queued `execution_runs` row, finalizes dedupe, and returns `202 Accepted`
  - attachment normalization is explicitly deferred to the worker-owned run path
- Keep attachment processing aligned with the existing Spec 005 execution lifecycle:
  - the worker claims the run
  - attachment normalization runs as the first pre-context stage for inbound-triggered runs
  - only after normalization reaches terminal states for the triggering message may normal context assembly proceed
- Preserve transcript-first and append-only durability:
  - canonical inbound message remains the source event
  - attachment rows are append-only audit records, not mutable transport blobs
  - outbound sends are recorded in durable `outbound_deliveries` rows rather than inferred from adapter logs
- Reuse the existing runtime-owned outbound-intent direction from Spec 002 instead of pushing send behavior into graph nodes or adapters:
  - tools may still prepare outbound intent data
  - the dispatcher combines persisted assistant output and runtime-owned intent data after the assistant turn completes
  - adapters only deliver one chunk or one media instruction at a time
- Treat "streaming" in this slice as deterministic post-turn chunk dispatch only:
  - no SSE fan-out
  - no token-by-token provider streaming
  - no adapter-owned buffering logic
- Keep policy and capability checks centralized and fail closed:
  - directive parsing happens once in shared dispatcher code
  - reply, media, and voice metadata must pass policy and adapter capability checks before send
  - unsupported directives never leak through as literal user-visible command text
- Keep media handling bounded for this phase:
  - normalize and store safe references
  - classify `media_kind`
  - enforce URL scheme, MIME, and byte-size limits
  - defer OCR, transcription, and semantic media understanding

## Service and Module Boundaries
### Gateway and Inbound Contracts
- `src/domain/schemas.py`
  - extend `InboundMessageRequest` with optional canonical `attachments`
  - keep the existing direct-vs-group routing validation intact
- `apps/gateway/api/inbound.py`
  - continue returning Spec 005 `202 Accepted` semantics
  - validate the attachment payload shape at the gateway boundary without performing normalization inline
- `src/sessions/service.py`
  - continue to orchestrate dedupe claim, session resolution, transcript persistence, run creation, and dedupe finalization
  - pass canonical attachment inputs into persistence for later worker-owned normalization without elongating the accept path

### Persistence and Repository Contracts
- `src/db/models.py` and `migrations/versions/`
  - add append-only `message_attachments`
  - add append-only `outbound_deliveries`
  - add any required enums and bounded error-detail columns
- `src/sessions/repository.py`
  - persist canonical inbound attachment references linked to the inbound message and session
  - expose idempotent attachment lookup and insert helpers for worker normalization
  - expose pending and terminal outbound-delivery persistence helpers keyed by `(outbound_intent_id, chunk_index)`
  - preserve append-only transcript and artifact behavior from earlier specs

### Worker and Runtime Contracts
- `src/jobs/service.py`
  - keep the worker as the execution owner for this slice
  - add a pre-context normalization stage for inbound-triggered runs before `ContextService.assemble`
  - invoke outbound dispatch after the assistant turn has completed and persisted its results
- `src/context/service.py`
  - read normalized attachment metadata and storage references only after terminal normalization
  - never consume raw provider attachment payloads directly once normalized state exists
- `src/graphs/state.py`
  - extend outbound-intent structures only as needed to support dispatcher-owned delivery metadata without moving transport logic into the graph
- `src/tools/messaging.py`
  - continue producing runtime-owned outbound intent data only
  - never call transport adapters directly

### Shared Dispatcher, Chunking, and Directive Contracts
- `src/channels/dispatch.py`
  - own the outbound dispatch flow
  - combine persisted assistant display text, outbound intent metadata, and adapter capability profiles
  - perform reply-directive parsing, policy checks, deterministic chunking, delivery-row creation, adapter send calls, and terminal status updates in one shared path
- `src/domain/reply_directives.py`
  - parse supported directives for this slice:
    - `[[reply:{external_message_id}]]`
    - `[[media:{url}]]`
    - `[[voice]]`
  - return cleaned display text plus typed metadata
  - reject malformed or unsupported directives without passing raw directive text to adapters
- `src/domain/block_chunker.py`
  - implement deterministic channel-aware text chunking
  - prefer paragraph boundaries first
  - hard-split only when a paragraph exceeds the adapter limit
  - never emit empty chunks

### Media and Adapter Contracts
- `src/media/processor.py`
  - validate scheme, MIME, and byte-size allowlists
  - classify `media_kind`
  - fetch or stage the object into runtime-owned storage
  - compute `sha256`
  - persist one terminal attachment row per canonical input
- `src/channels/adapters/base.py`
  - define adapter capability metadata and one-chunk or one-media send interfaces
- `src/channels/adapters/webchat.py`
- `src/channels/adapters/slack.py`
- `src/channels/adapters/telegram.py`
  - translate inbound provider payloads into the canonical gateway contract where applicable
  - expose capability metadata
  - send one text chunk or one media instruction at a time
  - never invoke graph orchestration, parse directives, or own chunking logic

## Risk Areas
- Attachment normalization accidentally extending the synchronous inbound acceptance path and breaking Spec 005 `202 Accepted` behavior.
- Duplicate or resumed runs re-normalizing or re-sending work non-idempotently if terminal attachment rows and outbound delivery keys are not used correctly.
- Channel-specific formatting logic leaking into graph nodes, tools, or gateway handlers instead of staying in shared dispatcher and thin adapters.
- Directive parsing becoming a hidden policy bypass if `reply`, `media`, or `voice` metadata is not checked against both runtime policy and adapter capability.
- Partial multi-chunk failures becoming hard to diagnose if delivery rows are created after send instead of before send.
- Unbounded media fetch, storage-key derivation, or provider metadata persistence creating security and retention problems.
- Context assembly reading raw or non-terminal attachment state and producing nondeterministic assistant inputs across retries.

## Rollback Strategy
- Keep schema changes additive.
- Preserve text-only outbound behavior as the minimum safe path if media normalization or media send wiring is disabled.
- Ensure the worker can skip dispatcher media paths cleanly when adapter capability, policy, or feature configuration disables them.
- Roll back transport-specific adapters before removing shared dispatcher contracts so existing runtime-owned outbound intent persistence remains valid.
- If attachment normalization must be disabled, inbound transcript persistence and queued-run creation must continue to work without deleting canonical inbound message state.

## Test Strategy
- Unit:
  - canonical inbound attachment validation
  - reply-directive parsing, stripping, and malformed-directive handling
  - deterministic chunking across capability profiles and overlong-paragraph fallback
  - adapter capability gating for reply, media, and voice metadata
  - MIME, scheme, and byte-size enforcement
  - media-kind classification and safe storage-key derivation
- Repository:
  - append-only `message_attachments` inserts and terminal-state idempotency
  - append-only `outbound_deliveries` inserts, updates, and unique chunk-key enforcement
- Integration:
  - `POST /inbound/message` still returns durable Spec 005 accept-and-queue semantics while attachments are deferred
  - worker normalization completes before context assembly consumes attachment metadata
  - transient normalization failures retry safely through the existing run retry contract
  - deterministic attachment validation failures do not cause unbounded run retries
  - outbound dispatcher, not adapters, performs directive parsing and chunking
  - chunked outbound delivery records success, partial failure, and retry-safe idempotent chunk identity
  - adapters cannot invoke graph orchestration directly in this slice
