# Spec 007: Channels, Streaming, Chunking, and Media Pipeline

## Purpose
Make outbound delivery and attachment handling channel-realistic without moving orchestration into channel adapters or weakening the gateway-owned policy and durability model established by earlier specs.

## Non-Goals
- Capability-governance redesign
- Remote execution or sandboxing changes
- Operational presence or WebSocket presence feeds
- Provider-backed OCR, transcription, or speech synthesis
- True token-by-token transport streaming
- Scheduler-driven delivery workflows beyond the existing queued run model

## Upstream Dependencies
- Spec 001
- Spec 002
- Spec 003
- Spec 004
- Spec 005

## Scope
- Canonical inbound attachment contract on the gateway message surface
- Attachment normalization and media-safe persistence before graph context assembly
- Outbound dispatcher abstraction that consumes runtime-owned outbound intents and assistant transcript output
- Reply-directive parsing for bounded supported directives in this slice
- Deterministic channel-aware block chunking before outbound send
- Append-only outbound delivery records for chunked sends and failures
- Thin transport-specific channel adapters for the supported channels in this phase

## Supported Channels In This Phase
- `webchat`
- `slack`
- `telegram`

## Deferred Channels and Behaviors
- Additional transports beyond the three listed above
- Live incremental token streaming over SSE, WebSocket, or provider-native stream fan-out
- Rich provider-native block layout systems beyond plain text, reply references, and bounded media attachments
- Audio transcription, OCR, or media-content understanding beyond normalization and safe storage
- Background media reprocessing pipelines not required for first-pass normalization

## Data Model Changes
- Extend the inbound gateway contract from Spec 001 with optional `attachments`
  - each canonical attachment input includes:
    - `external_attachment_id` nullable
    - `source_url`
    - `mime_type`
    - `filename` nullable
    - `byte_size` nullable
    - `provider_metadata` as bounded JSON for adapter-specific fields that must survive normalization
- Add append-only `inbound_message_attachments` as the durable staging record for canonical attachment inputs accepted on the gateway path
  - `id`
  - `message_id`
  - `session_id`
  - `ordinal`
  - `external_attachment_id` nullable
  - `source_url`
  - `mime_type`
  - `filename` nullable
  - `byte_size` nullable
  - `provider_metadata` as bounded JSON
  - immutable `created_at`
- Add append-only `message_attachments`
  - `id`
  - `inbound_message_attachment_id`
  - `message_id`
  - `session_id`
  - `ordinal`
  - `external_attachment_id` nullable
  - `source_url`
  - `storage_key`
  - `storage_bucket`
  - `mime_type`
  - `media_kind` with values `image`, `audio`, `document`, or `other`
  - `filename` nullable
  - `byte_size` nullable
  - `sha256`
  - `normalization_status` with values `stored`, `rejected`, or `failed`
  - `retention_expires_at`
  - `provider_metadata` as bounded JSON
  - immutable `created_at`
- Add append-only `outbound_deliveries`
  - `id`
  - `session_id`
  - `execution_run_id`
  - `outbound_intent_id`
  - `channel_kind`
  - `channel_account_id`
  - `delivery_kind` with values `text_chunk` or `media`
  - `chunk_index`
  - `chunk_count`
  - `reply_to_external_id` nullable
  - `attachment_id` nullable for media sends referencing `message_attachments`
  - `provider_message_id` nullable
  - `status` with values `pending`, `sent`, or `failed`
  - `error_code` nullable
  - `error_detail` nullable and bounded
  - immutable `created_at`
- Add append-only `outbound_delivery_attempts`
  - `id`
  - `outbound_delivery_id`
  - `attempt_number`
  - optional `provider_idempotency_key`
  - `status` with values `started`, `sent`, or `failed`
  - `provider_message_id` nullable
  - `error_code` nullable
  - `error_detail` nullable and bounded
  - immutable `created_at`
- Required indexes
  - `inbound_message_attachments(message_id, ordinal)`
  - `inbound_message_attachments(session_id, created_at)`
  - `message_attachments(message_id, ordinal)`
  - `message_attachments(session_id, created_at)`
  - `outbound_deliveries(outbound_intent_id, chunk_index)`
  - `outbound_deliveries(session_id, created_at)`
  - unique `(outbound_delivery_id, attempt_number)`
  - unique `(outbound_intent_id, chunk_index)` to keep chunk retries idempotent per intent

## Contracts
### Canonical Inbound Attachment Contract
- The gateway-owned inbound message contract in this slice accepts optional `attachments`.
- Channel adapters translate provider-native attachment payloads into the canonical attachment input contract before calling the gateway.
- Each attachment must include:
  - a non-empty `source_url`
  - a non-empty `mime_type`
- `external_attachment_id`, `filename`, and `byte_size` are optional because not every transport provides them.
- `provider_metadata` must remain bounded, transport-specific, and non-authoritative for security-sensitive decisions.
- Unsupported attachment payloads fail closed at the gateway boundary with a validation error rather than entering the graph as partially normalized media.
- Accepted canonical attachment inputs must be durably persisted on the gateway path in `inbound_message_attachments` in the same bounded acceptance lifecycle as the inbound message and queued run so worker-owned normalization never depends on ephemeral request state.

### Attachment Normalization Contract
- Attachment normalization occurs after the inbound message is durably persisted and before context assembly consumes attachment metadata for the run.
- Attachment normalization is not part of the synchronous `POST /inbound/message` acceptance path:
  - the gateway must still follow Spec 005 by durably committing the canonical inbound message, the initial queued `execution_runs` row, and dedupe finalization before returning `202 Accepted`
  - attachment normalization then occurs on the worker-owned execution path as the first pre-context stage for that queued run
- Normalization responsibilities in this slice are:
  - validate scheme, MIME allowlist, and byte-size limits
  - classify `media_kind`
  - fetch or stage the attachment into a media-safe storage path
  - compute `sha256`
  - persist one append-only `message_attachments` row per accepted staged attachment
- The normalized storage path must be runtime-owned and derived from canonical scope data rather than provider filenames alone.
- In this slice, normalized attachments expose metadata and safe stored references to later context assembly. They do not require OCR, transcription, or semantic extraction.
- If normalization fails for one attachment, the failure must be recorded on that attachment row without deleting the canonical inbound message.
- Context assembly for a run may consume only attachment rows that have reached a terminal normalization state for that run's inbound message:
  - `stored` rows are eligible for context assembly
  - `rejected` rows are terminal and remain audit-visible but are not exposed as usable media inputs
  - `failed` rows are terminal for the current attempt and remain audit-visible but are not exposed as usable media inputs
- The worker must complete first-pass normalization for all attachments on the triggering inbound message before normal context assembly begins for that run.
- Retry behavior is explicit:
  - transient fetch, storage, or dependency failures during normalization are retryable run failures under the Spec 005 worker retry contract
  - deterministic validation failures such as disallowed scheme, MIME, or byte-size are terminal attachment rejections and must not cause infinite run retry
  - when a later retry resumes the run, normalization must be idempotent for attachments already recorded in a terminal state
- The replay and continuity contract for attachments in this slice is:
  - `inbound_message_attachments` is the canonical accepted-input record for attachment replay and re-normalization
  - `message_attachments` is the canonical normalized metadata record consumed by context assembly
  - normalized attachment metadata and identifiers used for a turn must be included in the persisted context manifest from Spec 004
  - stored media objects may expire by retention policy, but expiry must remain explicit and must not silently erase the canonical audit trail or manifest-visible attachment usage for prior turns

### Outbound Dispatcher Contract
- The outbound dispatcher is the only component in this slice that translates runtime-owned outbound intents plus assistant output into transport sends.
- The dispatcher consumes:
  - the Spec 002 outbound intent or outbound reference
  - the assistant display text already persisted through the append-only runtime contract
  - adapter capability metadata for the destination channel
- The dispatcher performs, in order:
  1. reply-directive parsing
  2. policy and capability checks for requested outbound behaviors
  3. channel-aware text chunking
  4. append-only outbound delivery record creation
  5. append-only delivery-attempt record creation for the current send attempt
  6. adapter send calls
  7. terminal delivery-attempt and logical-delivery status update
- The dispatcher must be callable from the existing Spec 005 worker-owned execution path and may not be invoked directly by channel adapters.
- The dispatcher owns resend and recovery behavior for outbound work:
  - `outbound_deliveries` is the single logical-delivery record keyed by `(outbound_intent_id, chunk_index)`
  - `outbound_delivery_attempts` records bounded send attempts for that logical delivery
  - a resumed worker may create a new attempt only after observing that the prior attempt did not reach a terminal successful state in durable storage
  - providers that support idempotency keys should receive a stable provider idempotency key derived from `(outbound_intent_id, chunk_index, attempt_number)` or a stricter provider-safe equivalent
  - duplicate worker replay must not create a second logical delivery row for the same chunk, even when a new bounded attempt is required

### Reply Directive Contract
- Supported directives in this phase are:
  - `[[reply:{external_message_id}]]`
  - `[[media:{media_ref}]]`
  - `[[voice:{media_ref}]]`
- Directive parsing is a post-processing step on assistant output before outbound dispatch.
- Parsed directives must be stripped from the user-visible text before chunking or send.
- The parser returns a typed result containing:
  - cleaned display text
  - optional `reply_to_external_id`
  - ordered `media_refs`
  - `voice_media_ref` nullable
- Unsupported or malformed directives must not be passed through to adapters as raw text commands.
- Reply directives may not bypass existing gateway policy boundaries:
  - `reply` only sets outbound metadata for adapters that support reply targeting
  - `media` may only reference runtime-owned media identifiers that resolve to durably known normalized attachments or other runtime-owned media assets; arbitrary assistant-authored external URLs are not a valid directive payload in this slice
  - `voice` may only reference a runtime-owned media identifier that resolves to an audio-compatible asset and may only set outbound metadata for adapters that support voice-style delivery; it does not synthesize audio in this slice
- If a directive is unsupported for the destination adapter or denied by policy, the dispatcher must fail that outbound delivery attempt explicitly rather than silently inventing an alternative send path.

### Chunking and Streaming Contract
- In this spec, "streaming" means chunked outbound message dispatch after the assistant turn completes. It does not mean token-level incremental transport streaming.
- Chunking is deterministic and channel-aware:
  - each adapter provides a `max_text_chars` limit and any stricter transport formatting constraints
  - the shared chunker prefers paragraph boundaries first
  - if a paragraph exceeds the limit, the chunker performs a deterministic hard split
  - no empty chunks may be produced
- Chunk order must be stable and preserved in `outbound_deliveries.chunk_index`.
- Chunking occurs after directive stripping so directives do not count against display-text chunk budgets.
- Reassembling display text on the receiving side is transport-defined and out of scope; this spec only guarantees stable ordered dispatch.

### Channel Adapter Contract
- Supported adapters in this phase are transport-specific implementations for `webchat`, `slack`, and `telegram`.
- Adapters may:
  - translate inbound provider payloads into the canonical gateway contract
  - expose channel capability metadata used by the dispatcher
  - deliver one text chunk or one media send instruction at a time
- Adapters may not:
  - invoke the graph directly
  - parse assistant directives on their own
  - own chunking behavior
  - bypass the dispatcher to send ad hoc assistant output
- Adapter capability metadata must explicitly declare at least:
  - `max_text_chars`
  - supports reply targeting yes or no
  - supports media yes or no
  - supports voice-style media flag yes or no

### Repository and Service Contracts
- The media processor service must support:
  - read a staged canonical attachment input from `inbound_message_attachments`
  - validate and classify a canonical attachment input
  - persist a safe stored object and attachment metadata
  - return a normalized attachment record suitable for context assembly
- The outbound delivery repository must support:
  - insert one pending row per chunk or media send before adapter dispatch
  - insert one bounded attempt row per send attempt before adapter dispatch
  - transition rows to `sent` or `failed`
  - idempotent lookup by `(outbound_intent_id, chunk_index)`
  - ordered lookup of attempts by `outbound_delivery_id`
- The dispatcher service must support:
  - compute the channel capability profile for the outbound destination
  - parse directives
  - create deterministic chunks
  - call the correct adapter send method
  - persist append-only delivery records and terminal status
- Context assembly in later execution steps may read normalized attachment metadata and storage references, but it must not read raw provider payloads directly once normalization has completed.

## Runtime Invariants
- The gateway remains the sole orchestration entrypoint for inbound and outbound assistant work.
- Channel adapters remain transport-specific and do not own orchestration logic.
- Reply directives are parsed before outbound send and stripped from display text.
- Outbound chunking is deterministic for the same cleaned text and adapter capability profile.
- Attachments enter a normalized processing pipeline before graph context assembly consumes them.
- Accepted attachment inputs are durable before worker normalization begins and do not depend on in-memory request objects after `202 Accepted`.
- The inbound acceptance path is still bounded to transcript persistence, queued-run creation, and dedupe finalization; attachment normalization does not delay the Spec 005 `202 Accepted` response.
- Attachment normalization preserves source metadata needed for audit while treating normalized storage state as the security-sensitive source of truth.
- Outbound delivery attempts are durably recorded per chunk or media send and do not depend on adapter logs alone.
- Duplicate replay or worker resume does not create a second logical outbound delivery for the same `(outbound_intent_id, chunk_index)`, even if a bounded retry attempt is required.

## Security Constraints
- Attachment inputs must use approved URL schemes only, with HTTPS required unless a stricter platform rule applies.
- MIME type and byte-size allowlists are gateway-owned configuration, not adapter-authored policy.
- Stored media keys must be runtime-owned, sanitized, and not derived solely from provider-supplied filenames.
- Media retention must be bounded by `retention_expires_at`; indefinite artifact retention is out of scope.
- Reply-directive media references must resolve to runtime-owned media only; arbitrary assistant-authored external URLs are out of scope for this slice.
- Reply directives do not authorize new capabilities; they only request bounded outbound behaviors already permitted by existing runtime policy and adapter capability checks.
- Attachment normalization and outbound media handling must fail closed when validation, storage, or capability checks fail.

## Operational Considerations
- Per-channel chunk limits must be configuration-backed so adapters can evolve without changing graph behavior.
- Text-only outbound delivery remains available when media handling is disabled or a channel lacks media capability.
- Attachment processing failures should degrade gracefully by preserving the canonical inbound message and recording attachment-level failure state.
- Attachment normalization must compose cleanly with the Spec 005 run lifecycle:
  - transient normalization failures should surface as retryable run outcomes
  - deterministic attachment validation failures should be recorded without poisoning the session with endless run retries
- Delivery records must make multi-chunk failures diagnosable without relying on transport-provider dashboards.
- The implementation should use bounded previews and bounded error details in delivery records rather than unbounded provider payload dumps.
- Media object cleanup may be asynchronous, but retention deadlines must be durably recorded at normalization time.
- Context manifests and replay tooling should remain able to explain which normalized attachment metadata was used for a turn even after a retained media object itself has expired.

## Acceptance Criteria
- Long assistant responses are split into deterministic ordered chunks before outbound send for channels whose limits require it.
- Reply directives are parsed and removed from display text before outbound send.
- Supported reply directives produce the correct bounded outbound metadata without bypassing policy or adapter capability checks.
- Inbound attachments are translated into the canonical attachment contract, durably staged on the gateway path, normalized into safe storage on the worker path, and persisted in append-only attachment records before graph use.
- `POST /inbound/message` still returns Spec 005 `202 Accepted` semantics after durable transcript and queued-run creation; attachment normalization occurs later on the worker-owned run path before context assembly.
- Channel adapters remain transport-specific and do not invoke the graph, own chunking, or parse directives.
- Outbound chunk and media delivery attempts are durably recorded with terminal `sent` or `failed` outcomes, and duplicate replay never creates a second logical delivery row for the same chunk.
- This slice supports `webchat`, `slack`, and `telegram`, and it explicitly treats true incremental transport streaming as deferred.

## Test Expectations
- Unit tests for reply-directive parsing, including malformed and unsupported directive handling
- Unit tests for deterministic chunking across channel capability profiles and overlong-paragraph fallback
- Unit tests for adapter capability gating of reply, media, and voice metadata
- Unit tests for attachment MIME and size allowlist enforcement
- Unit tests for media-kind classification and safe storage-key derivation
- Repository tests for append-only `inbound_message_attachments`, append-only `message_attachments`, and idempotent `outbound_deliveries` logical chunk records plus bounded attempt records
- Integration tests proving `POST /inbound/message` preserves Spec 005 durable accept-and-queue semantics while attachment normalization is deferred to worker execution
- Integration tests proving inbound attachments are normalized before context assembly reads them
- Integration tests proving replay and manifests preserve attachment continuity metadata even when retained stored objects later expire
- Integration tests proving transient normalization failures retry safely and deterministic attachment rejections do not cause unbounded run retries
- Integration tests proving outbound dispatcher, not adapters, performs directive parsing and chunking
- Integration tests for chunked outbound delivery success, partial-failure recording, and bounded resend attempts without duplicate logical delivery rows
- Contract tests proving adapters cannot invoke graph orchestration directly in this slice
