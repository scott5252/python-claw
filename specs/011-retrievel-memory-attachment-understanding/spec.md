# Spec 011: Retrieval, Memory, and Attachment Understanding

## Purpose
Turn the current continuity scaffolding into a real context system that can preserve long-running conversations, retrieve durable memory, and expose usable attachment-derived content to the model without weakening the existing gateway-first, worker-owned, append-only execution architecture.

## Non-Goals
- Replacing transcript history as the canonical source of truth
- Building production transport-provider integrations or streaming delivery behavior
- Introducing agent-profile, delegation, or multi-session orchestration changes beyond the current session model
- Moving summary generation, retrieval injection, or attachment extraction into synchronous gateway request handling
- Replacing the current media normalization flow with an external document-processing platform
- Shipping a general-purpose vector database dependency if a bounded local retrieval implementation can satisfy this slice

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

## Scope
- Extend `src/context/service.py` so context assembly can combine recent transcript, summary snapshots, retrieved durable memory, and attachment-derived content under one backend-owned budgeted assembly flow
- Add durable memory storage and retrieval records that remain secondary derived state tied back to session and message provenance
- Use worker-owned after-turn jobs to generate summary rollovers, extract durable memory candidates, and build retrieval indexes without blocking the accepted run
- Extend attachment processing so supported stored attachments can expose extracted content and metadata for prompt use
- Record which summaries, memory rows, retrieval rows, and extracted attachment artifacts were used in `context_manifests`
- Preserve safe degradation behavior when retrieval, extraction, or enrichment jobs fail or are unavailable
- Add test coverage for summary rollover, retrieval injection, durable-memory provenance, attachment extraction, degraded assembly, and transcript-only recovery

## Implementation Gap Resolutions
### Gap 1: Authoritative Source of Truth Between Transcript, Summary, and Memory
The roadmap requires durable memory and retrieval, but the current continuity model already treats transcript rows as canonical and summaries as additive. This spec must prevent memory rows from becoming a competing truth source.

Options considered:
- Option A: let durable memory replace older transcript content once extraction succeeds
- Option B: treat summaries and memory rows as equal first-class truth alongside transcript rows
- Option C: keep transcript as canonical truth, with summaries, memory rows, and retrieval chunks as additive derived state only
- Option D: skip durable memory rows and rely only on summary snapshots

Selected option:
- Option C

Decision:
- Transcript rows remain the only canonical conversation record.
- Summary snapshots, durable memory rows, retrieval chunks, and attachment extraction artifacts are derived state with explicit provenance back to session and message ranges.
- If derived state is missing, stale, or invalid, the system must still be able to assemble usable context from transcript plus the latest valid summary alone.

### Gap 2: Retrieval Storage Strategy for This Slice
The roadmap calls for retrieval, but the current codebase has no dedicated retrieval store or vector dependency yet. This spec needs a bounded first implementation that integrates with the existing repo.

Options considered:
- Option A: require an external vector database immediately
- Option B: implement only keyword search and defer embeddings entirely
- Option C: define a retrieval-record abstraction that can start with local lexical and metadata-ranked retrieval, while allowing optional embeddings later without changing assembly contracts
- Option D: store memory only in prompt-ready text blobs with no retrieval layer

Selected option:
- Option C

Decision:
- This slice introduces durable retrieval records and a retrieval service abstraction.
- The initial implementation may use lexical or lightweight local ranking, with optional embedding fields kept additive.
- `ContextService` depends on the retrieval service contract, not on a specific index technology.

### Gap 3: Attachment Understanding Boundary
Current attachment handling normalizes files into stored media records, but does not define whether extraction should happen inline with normalization or asynchronously after the run.

Options considered:
- Option A: extract all attachment content synchronously in the gateway
- Option B: extract content during worker normalization before model execution for every file type
- Option C: keep normalization lightweight and durable first, then run attachment-content extraction through after-turn jobs with optional same-run fast paths for already-available text metadata
- Option D: defer attachment understanding to a later spec

Selected option:
- Option C

Decision:
- Normalization remains the worker-owned ingest step that stores accepted files safely.
- Attachment-content extraction becomes a durable after-turn enrichment job family.
- Context assembly may use extracted attachment content only when it is already available and valid; otherwise it degrades safely to attachment metadata only.

### Gap 4: Lifecycle and Idempotency for Derived Enrichment Records
The draft introduces `session_memories`, `retrieval_records`, and `attachment_extractions`, but it does not yet define terminal states, ownership of transitions, or duplicate-suppression rules strongly enough for worker retries and repair jobs.

Options considered:
- Option A: keep lifecycle details implementation-defined and rely on `outbox_jobs` dedupe alone
- Option B: make every enrichment table append-only with no status transitions and let consumers infer freshness heuristically
- Option C: define explicit per-table lifecycle and idempotency contracts so retries, supersession, and repair can be deterministic
- Option D: collapse memory, retrieval, and attachment extraction into one generic enrichment table

Selected option:
- Option C

Decision:
- `session_memories`, `retrieval_records`, and `attachment_extractions` keep separate responsibilities, but each gets an explicit idempotent production contract.
- `session_memories.status` is restricted in this slice to `active`, `superseded`, `expired`, or `rejected`.
- `attachment_extractions.status` is restricted in this slice to `pending`, `completed`, `failed`, or `unsupported`.
- `retrieval_records` remain immutable derived index rows rather than mutable work-state rows; duplicate suppression is by deterministic source identity and chunk identity.
- Worker retries and repair jobs must use stable derivation keys so the same source input and extractor or chunking strategy do not create conflicting duplicate derived state.

### Gap 5: Same-Run Availability of Attachment Understanding
The draft says attachment extraction is after-turn work, but it does not resolve whether the model can understand newly uploaded attachments in the same triggering run, which is a planning blocker for user experience and worker timing.

Options considered:
- Option A: no same-run attachment understanding; all extraction is available only to later turns
- Option B: block every supported attachment type on extraction before the current run continues
- Option C: allow a bounded same-run fast path for text-native attachments and text-extractable PDFs within configured limits, while keeping heavier extraction asynchronous
- Option D: let prompt construction reread normalized files directly when needed

Selected option:
- Option C

Decision:
- The default path remains asynchronous after-turn extraction.
- This slice also allows one bounded same-run fast path for text files and text-extractable PDFs when extraction can complete within configured size, page-count, and time limits on the owning worker attempt.
- Image understanding remains asynchronous in this slice unless a later spec extends the contract explicitly.
- Prompt construction may use same-run extracted content only through the same durable extraction contract used by later turns; it may not bypass extraction records by reading raw files ad hoc.

### Gap 6: Deterministic Retrieval Selection, Budgeting, and Deduplication
The draft says context assembly is budget-aware, but it does not yet define how transcript, summaries, memories, retrieval chunks, and attachment-derived content compete for prompt budget or how overlapping provenance is deduplicated.

Options considered:
- Option A: rely on rank score alone and let any source consume the remaining prompt budget
- Option B: define deterministic per-source assembly order, per-source caps, and provenance-aware deduplication before final prompt rendering
- Option C: include all available sources and rely on model truncation or provider limits
- Option D: choose exactly one non-transcript source type per turn and ignore the rest

Selected option:
- Option B

Decision:
- Context assembly remains transcript-first and summary-aware, then applies retrieval under explicit per-source and total budget caps.
- Retrieval candidates whose provenance is already fully covered by directly included recent transcript or the selected summary snapshot must be dropped unless they add non-duplicative memory or attachment-extraction content.
- The manifest must record not only what was included, but also the retrieval strategy identifier, the per-source caps applied, and whether candidates were skipped due to overlap, budget, or degraded dependency state.
- Rebuildability in this slice is source-aware: summaries and memories rebuild from canonical transcript state, while attachment extractions rebuild from normalized attachment state and retrieval records rebuild from their canonical source artifacts rather than from manifests.

### Gap 7: Durable Memory Provenance Shape
The spec requires durable memory rows to retain provenance, but the current draft does not cleanly resolve how one memory row can be derived either from a specific message or from a covered summary range without pushing the authoritative provenance into opaque JSON.

Options considered:
- Option A: require every memory row to point to exactly one `source_message_id`
- Option B: make provenance implementation-defined inside `payload_json`
- Option C: add an explicit provenance envelope with `source_kind` plus nullable source fields for message- or summary-derived memory
- Option D: split durable memory into separate tables for message-derived and summary-derived rows

Selected option:
- Option C

Decision:
- `session_memories` must carry explicit structured provenance rather than hiding provenance only inside `payload_json`.
- This slice adds `source_kind` with values `message` or `summary_snapshot`.
- For `source_kind=message`, `source_message_id` is required and `source_summary_snapshot_id` is null.
- For `source_kind=summary_snapshot`, `source_summary_snapshot_id` is required, and the row must also persist the covered canonical transcript range through `source_base_message_id` and `source_through_message_id`.
- Exactly one provenance form is valid for any `session_memories` row, and retrieval or diagnostics must rely on those structured fields rather than parsing opaque payload content.

### Gap 8: Same-Run Attachment Fast-Path Ownership and Timing
The draft allows same-run attachment understanding, but it does not yet define where that bounded fast path runs relative to the existing worker flow of normalization, context assembly, and prompt construction.

Options considered:
- Option A: run bounded fast-path extraction in the worker after normalization and before `ContextService` assembles prompt inputs
- Option B: let `ContextService` perform same-run extraction during assembly
- Option C: let prompt construction reread normalized files directly when needed
- Option D: remove same-run attachment understanding and make extraction asynchronous-only

Selected option:
- Option A

Decision:
- Same-run fast-path extraction is worker-owned.
- For supported text files and text-extractable PDFs that meet configured size, page-count, and time limits, the worker may perform bounded extraction after `src/media/processor.py` finishes normalization and before `src/context/service.py` assembles turn context.
- Any same-run fast-path result must be persisted through `attachment_extractions` using the same durable contract used by asynchronous extraction before prompt assembly may consume it.
- `ContextService` remains a read-only assembler of already-persisted transcript, summary, retrieval, memory, and attachment-extraction state.
- `src/graphs/prompts.py` remains a pure prompt-construction layer and may not reread raw files or perform extraction work.

### Gap 9: Source-Specific Enrichment Job Identity and Rebuild
The draft requires after-turn enrichment jobs, but it does not yet define whether retrieval indexing is keyed by message, by canonical source artifact, or by one monolithic session scan, which would make retries and rebuild behavior ambiguous.

Options considered:
- Option A: keep one generic `retrieval_index` job per message and let it scan all candidate sources heuristically
- Option B: make indexing source-specific and keyed by canonical source artifact identity
- Option C: build retrieval rows lazily at read time instead of through jobs
- Option D: defer source-specific indexing until a later spec

Selected option:
- Option B

Decision:
- Enrichment job identities in this slice are source-specific and artifact-keyed.
- Summary generation remains keyed by the triggering `(session_id, message_id)`.
- Memory extraction jobs are keyed by the canonical transcript or summary source they derive from.
- Attachment extraction jobs are keyed by `(attachment_id, extractor_kind)`.
- Retrieval indexing jobs are keyed by canonical source artifact identity, specifically one of:
  - transcript message
  - summary snapshot
  - active memory row
  - completed attachment extraction
- A generic message-triggered after-turn step may fan out those source-specific jobs, but the durable dedupe and retry identity for indexing must remain the source artifact rather than the enqueueing message alone.

### Gap 10: Structured Runtime Carrier for Retrieved Context
The draft requires prompt-visible summary, retrieval, memory, and attachment-derived sections, but it does not yet define how that structured context moves from `ContextService` into `AssistantState` and then into prompt construction without overloading transcript messages or pushing database reads into prompt builders.

Options considered:
- Option A: encode retrieved items as synthetic conversation messages
- Option B: let prompt construction query repositories directly
- Option C: extend the context-assembly and runtime state contracts with explicit structured fields for summary, retrieval, memory, and attachment-derived items
- Option D: keep only identifiers in manifests and let later layers reconstruct content ad hoc

Selected option:
- Option C

Decision:
- This slice adds explicit structured context carriers rather than encoding retrieved context as fake transcript messages.
- `ContextAssemblyResult`, `AssistantState`, and prompt payload construction must be extended so prompt-visible summary context, retrieved memory items, retrieved non-memory records, and attachment-derived content are carried as backend-owned structured state.
- `src/context/service.py` remains responsible for populating those structures from already-persisted state.
- `src/graphs/prompts.py` must consume those structures without querying the database directly.
- `context_manifests` remain the diagnostic explanation of what was used, while `AssistantState` is the authoritative in-turn carrier of the already-selected prompt inputs.

### Gap 11: Derivation Strategy Identity for Memory, Retrieval, and Extraction
The draft defines source-aware idempotency, but it does not yet resolve how strategy changes such as new chunking, ranking, OCR, PDF parsing, or memory-extraction logic participate in duplicate suppression and rebuild behavior.

Options considered:
- Option A: key all derived rows by source identity and content hash only
- Option B: store strategy version in metadata only and keep dedupe identity unchanged
- Option C: add explicit derivation strategy identity that participates in duplicate suppression and rebuild decisions
- Option D: split each derivation strategy into separate tables

Selected option:
- Option C

Decision:
- This slice adds explicit derivation strategy identity for durable memory extraction, retrieval indexing, and attachment extraction.
- The chosen strategy identifier or version must participate in duplicate suppression wherever a strategy change could otherwise silently reuse stale derived rows.
- Strategy identity may be stored as dedicated columns or as bounded structured metadata, but it must be authoritative for rebuild, diagnostics, and idempotent retries.
- A strategy change must be able to rebuild derived state without mutating transcript truth or creating ambiguous duplicate ownership.

### Gap 12: Durable Job Payload Shape for Source-Specific Enrichment
The draft says enrichment identity must be source-specific, but it does not yet define how that source identity moves through `outbox_jobs` without relying on fragile string parsing or full-session rescans.

Options considered:
- Option A: encode all source identity only inside `job_dedupe_key`
- Option B: rescan the full session on each enrichment job and infer the source artifact heuristically
- Option C: add an explicit structured source envelope for enrichment jobs
- Option D: create a separate durable queue table for every enrichment family

Selected option:
- Option C

Decision:
- Enrichment jobs in this slice must carry a structured source envelope identifying at minimum `job_kind`, `source_kind`, `source_id`, and the relevant strategy identifier.
- `job_dedupe_key` remains useful for uniqueness, but it must be a projection of the structured source identity rather than the only authoritative carrier.
- Outbox execution may fan out from a triggering message, but each durable enrichment job must resolve to one canonical source artifact without rescanning unrelated session state.
- The implementation may store the structured source envelope in additive outbox payload fields or bounded JSON, but workers must not rely on parsing free-form strings as the sole source of truth.

### Gap 13: Same-Run Fast-Path Failure Classification
The draft allows same-run attachment fast paths, but it does not yet distinguish which fast-path failures should retry the run versus degrade to metadata-only attachment context and continue safely.

Options considered:
- Option A: any same-run fast-path failure retries the whole run
- Option B: all same-run fast-path failures degrade to metadata-only behavior
- Option C: classify canonical-state or storage failures as retryable run failures, while extraction-class failures persist durable extraction state and degrade to metadata-only prompt input
- Option D: remove same-run fast-path behavior entirely

Selected option:
- Option C

Decision:
- Same-run fast-path failures are classified explicitly in this slice.
- Failures that threaten canonical run prerequisites, such as missing normalized attachment state or durable persistence failure for a completed fast-path result, remain retryable run failures under Spec 005 rules.
- Extraction-class failures such as timeout, unsupported parser behavior, bounded PDF parsing failure, or OCR failure must persist durable extraction state where applicable and then degrade the current turn to metadata-only attachment context.
- The worker must not silently consume raw files after a failed fast path, and prompt assembly must continue to read only durable attachment and extraction records.

### Gap 14: Minimum Typed Shape for Retrieved Context Carriers
The draft says structured context must move through `ContextService`, `AssistantState`, and prompt construction, but it does not yet define the minimum typed shapes needed to keep those interfaces stable and testable.

Options considered:
- Option A: use untyped dictionaries everywhere
- Option B: carry only identifiers and let later layers reconstruct content ad hoc
- Option C: define explicit typed carriers for summary, memory, retrieval, attachment-derived, and budget metadata
- Option D: encode all retrieved context as synthetic transcript messages

Selected option:
- Option C

Decision:
- This slice defines minimum typed context carriers for:
  - selected summary context
  - selected memory items
  - selected non-memory retrieval items
  - selected attachment-derived prompt items
  - metadata-only attachment fallback items
  - assembly budget and trimming metadata
- These typed carriers must be authoritative for in-turn prompt rendering and tests, while `context_manifests` remain the durable diagnostic explanation.
- Prompt construction must consume those typed carriers directly and must not reconstruct them from raw manifest JSON.

### Gap 15: Source Eligibility and Secret-Safe Memory Boundaries
The draft says secret-bearing prompt or provider payloads must not be written into memory, retrieval, or extraction stores by default, but it does not yet define a concrete eligibility boundary for what source content may be indexed or remembered.

Options considered:
- Option A: allow all transcript-linked text and artifacts to become memory or retrieval inputs
- Option B: rely on best-effort redaction heuristics only
- Option C: define an explicit allowlist of eligible sources plus bounded rejection or redaction rules
- Option D: allow only user transcript rows and defer all other source classes

Selected option:
- Option C

Decision:
- This slice defines an explicit source-eligibility policy for durable memory and retrieval indexing.
- Eligible inputs may include canonical user-visible transcript rows, latest valid summary snapshots, active memory rows, and completed attachment extractions, subject to bounded redaction or rejection rules.
- Ineligible inputs in this slice include raw provider payloads, hidden prompt scaffolding, raw tool-audit payloads, approval packets, and other backend-only content unless a later spec authorizes them explicitly.
- Rejection or redaction decisions must happen before durable memory or retrieval writes so the system does not store sensitive backend-only content and then attempt to filter it later.

## Data Model Changes
- Add one durable memory table for extracted memory facts or notes tied to session and provenance:
  - `session_memories`
  - minimum fields:
    - `id`
    - `session_id`
    - `source_kind` with values `message` or `summary_snapshot`
    - `source_message_id` nullable
    - `source_summary_snapshot_id` nullable
    - `source_base_message_id` nullable
    - `source_through_message_id` nullable
    - `memory_kind`
    - `status` with values `active`, `superseded`, `expired`, or `rejected`
    - `confidence`
    - `title` nullable
    - `content_text`
    - `payload_json`
    - `content_hash`
    - `derivation_strategy_id`
    - `expires_at` nullable
    - `superseded_at` nullable
    - `created_at`
- Add one durable retrieval-source table that stores searchable chunks derived from transcript, summaries, memory rows, and extracted attachment content:
  - `retrieval_records`
  - minimum fields:
    - `id`
    - `session_id`
    - `source_kind` with values `message`, `summary_snapshot`, `memory`, or `attachment_extraction`
    - `source_id`
    - `message_id` nullable
    - `attachment_id` nullable
    - `memory_id` nullable
    - `summary_snapshot_id` nullable
    - `chunk_index`
    - `content_text`
    - `content_hash`
    - `metadata_json`
    - `embedding_vector_json` nullable
    - `derivation_strategy_id`
    - `created_at`
- Add one attachment-extraction table or equivalent additive record for content derived from stored attachments:
  - `attachment_extractions`
  - minimum fields:
    - `id`
    - `attachment_id`
    - `session_id`
    - `message_id`
    - `extractor_kind`
    - `derivation_strategy_id`
    - `status` with values `pending`, `completed`, `failed`, or `unsupported`
    - `content_text` nullable
    - `content_metadata_json`
    - `error_detail` nullable
    - `created_at`
- Existing tables remain authoritative for:
  - transcript truth: `messages`
  - summary continuity: `summary_snapshots`
  - turn inspectability: `context_manifests`
  - background work: `outbox_jobs`
  - raw normalized media: `message_attachments`
- `context_manifests.manifest_json` may grow additively to persist:
  - `memory_ids`
  - `retrieval_ids`
  - `attachment_extraction_ids`
  - `assembly_budget`
  - `retrieval_strategy`
  - `degraded_reasons`
- This spec must not introduce any data path where derived memory is stored without source session or message provenance.
- Required indexes
  - lookup index on `session_memories(session_id, status, created_at)`
  - lookup index on `session_memories(source_message_id, status)`
  - lookup index on `session_memories(source_summary_snapshot_id, status)`
  - unique or duplicate-suppression index on the chosen memory-derivation identity, such as `(session_id, source_message_id, memory_kind, content_hash)`, so repeat extraction attempts stay idempotent
  - unique index on `retrieval_records(session_id, source_kind, source_id, chunk_index, content_hash)`
  - lookup index on `retrieval_records(session_id, source_kind, created_at)`
  - unique index on `attachment_extractions(attachment_id, extractor_kind)`
  - lookup index on `attachment_extractions(session_id, status, created_at)`

## Contracts
### Context Assembly Contract
- `src/context/service.py` remains the only runtime component that assembles transcript, summary, retrieval, and attachment-derived context for a turn.
- Context assembly must remain backend-owned and complete before provider invocation.
- `ContextService` reads already-persisted state only in this slice; it does not perform attachment extraction, retrieval indexing, or durable memory writes inline during prompt assembly.
- Assembly order in this slice is:
  - recent transcript needed for immediate conversational continuity
  - latest valid summary snapshot when transcript exceeds the window budget
  - retrieved durable memory and other retrieval records ranked for the current turn
  - attachment-derived content already available for attachments relevant to the triggering message or recently referenced context
- The assembly algorithm must be budget-aware rather than append-everything.
- The assembly algorithm must also be deterministic for the same session state, retrieval index state, configuration, and triggering turn inputs.
- `ContextAssemblyResult.manifest` must record which derived continuity sources were used, skipped, degraded, or unavailable.
- If retrieval fails, context assembly must still succeed using transcript plus summary behavior already supported by Spec 004.
- If attachment extraction is unavailable, the prompt may still include normalized attachment metadata from `message_attachments`.

### Retrieval Selection and Deduplication Contract
- Retrieval query construction in this slice is backend-owned and must be deterministic from the current turn inputs already available to `ContextService`.
- The retrieval query may use the current user message text, the triggering message's normalized attachment metadata, and bounded recent transcript context, but it must not query raw provider payloads or re-open arbitrary remote files.
- Budgeting must be explicit:
  - reserve prompt budget for recent transcript first
  - reserve summary budget only when needed for overflow or continuity rollover
  - apply one configured total budget for retrieved non-transcript context
  - apply bounded per-source caps for memory rows, attachment-derived records, and other retrieval records
- Deduplication must be provenance-aware:
  - retrieval candidates whose source message range is already directly included in transcript context must be skipped
  - retrieval candidates whose source content is already represented by the selected summary snapshot should be skipped unless they contribute distinct durable memory or attachment-derived content
  - duplicate retrieval candidates with the same canonical source identity or `content_hash` must collapse deterministically to one included item
- If the retrieval subsystem is healthy but returns no candidates above threshold, the manifest must record that state as empty retrieval rather than degraded retrieval failure.

### Durable Memory Contract
- Durable memory rows are derived facts, preferences, commitments, or other reusable continuity items extracted from transcript and summary state after the turn.
- Durable memory rows must carry explicit structured source provenance back to at least one session and one source message or covered summary range.
- Provenance shape in this slice is:
  - `source_kind=message`: requires `source_message_id`, forbids `source_summary_snapshot_id`, and leaves `source_base_message_id` and `source_through_message_id` null
  - `source_kind=summary_snapshot`: requires `source_summary_snapshot_id`, requires `source_base_message_id` and `source_through_message_id`, and may leave `source_message_id` null
- Exactly one provenance form is valid per memory row.
- Memory extraction must be idempotent per source input and extraction strategy.
- Durable memory derivation identity must include the extraction strategy identifier so revised extraction rules can rebuild cleanly without silently colliding with older rows.
- Durable memory records may be superseded or expired, but must not mutate prior transcript rows.
- Retrieval and prompt assembly may down-rank or exclude stale or superseded memory without deleting the canonical record immediately.
- Memory writes in this slice must happen only after transcript persistence has already committed.
- Transition ownership in this slice is:
  - extraction jobs create `active` or `rejected`
  - memory maintenance or later extraction jobs may move `active -> superseded`
  - lifecycle policy may move `active -> expired` or `superseded -> expired`
- Prompt assembly and retrieval may use only `active` memory rows in this slice unless an explicit repair or diagnostics path is reading older states.

### Retrieval Contract
- This slice defines one retrieval service boundary, such as `src/retrieval/service.py`, responsible for:
  - indexing eligible transcript, summary, memory, and attachment-derived content
  - retrieving bounded relevant records for one turn
  - exposing safe provenance-rich retrieval results back to `ContextService`
- Retrieval results must include at minimum:
  - `retrieval_record_id`
  - `source_kind`
  - `source_id`
  - `content_text`
  - `score` or equivalent rank metadata
  - bounded provenance metadata suitable for manifests and diagnostics
- Retrieval must be scoped by session in this slice.
- This spec may allow optional future cross-session retrieval only if explicitly disabled by default and separately authorized later.
- Retrieval failure must degrade safely and observably rather than failing the whole turn by default.
- Retrieval indexing must be idempotent per canonical source artifact and chunk identity.
- Retrieval indexing identity must also include the chunking or ranking strategy identifier whenever a strategy revision would otherwise collide with an older derived row for the same source artifact and `chunk_index`.
- Retrieval records sourced from attachment content may be produced only from completed extraction records, not from raw files or pending extraction attempts.

### Attachment Extraction Contract
- `src/media/processor.py` remains responsible for safe file normalization and storage.
- This spec introduces one extraction boundary, such as `src/media/extraction.py`, for supported attachment-content extraction after storage.
- Supported attachment kinds in this slice are:
  - text files
  - PDFs
  - images
- Minimum extraction outputs are:
  - extracted text when available
  - bounded metadata describing what was extracted
  - failure status and safe error detail when extraction fails
- Image extraction may be limited to OCR or coarse description only if bounded and explicit.
- Unsupported attachment types must not fail the turn; they remain normalized media with metadata only.
- Prompt-visible attachment content must come from extracted durable records, not from ad hoc rereads of raw files inside prompt construction.
- Attachment extraction identity in this slice includes the extractor or parser strategy identifier so retries and rebuilds can distinguish revised extraction logic from prior attempts.
- Same-run availability rules in this slice are:
  - text files and text-extractable PDFs may use a bounded same-run extraction fast path when configured limits are met
  - same-run fast-path extraction runs on the owning worker after normalization and before `ContextService` assembles prompt inputs for that run
  - same-run fast-path work must still persist through `attachment_extractions` before prompt assembly consumes it
  - if the fast path does not complete within configured bounds, the run degrades to metadata-only attachment context and leaves extraction to after-turn jobs
  - image extraction is asynchronous-only in this slice
- Transition ownership in this slice is:
  - normalization completion or job enqueue creates `pending` extraction intent when the attachment type is supported
  - extraction workers move `pending -> completed`, `pending -> failed`, or `pending -> unsupported`
  - repair jobs may retry by replacing a prior failed logical attempt only through the same idempotent `(attachment_id, extractor_kind)` identity rather than creating competing active extraction rows
- Same-run fast-path failure classification in this slice is:
  - canonical-state or durable-persistence failures remain retryable run failures when they prevent the worker from safely relying on persisted normalized or extracted state
  - extraction-class failures such as timeout, unsupported parsing behavior, or bounded parsing failure must degrade the current turn to metadata-only attachment context after persisting durable extraction status where applicable

### After-Turn Job Contract
- After-turn enrichment remains worker-owned and outbox-driven.
- `src/jobs/service.py` must enqueue additive jobs for:
  - summary generation
  - memory extraction
  - retrieval indexing
  - attachment extraction for new stored attachments
  - continuity repair when degraded assembly or failed enrichment requires retry
- `src/context/outbox.py` or a successor service must claim and execute those jobs idempotently.
- A failed enrichment job must not corrupt transcript or manifest state for the accepted run that already completed.
- Job dedupe keys must be stable per session, message, source attachment, canonical source artifact, and job kind as applicable.
- Enrichment jobs in this slice must also carry a structured source envelope identifying the canonical source artifact being processed; workers must not rely on `job_dedupe_key` string parsing as the sole source of truth.
- This slice distinguishes trigger-time fan-out from durable job identity:
  - a completed turn may enqueue follow-up enrichment work based on the triggering `(session_id, message_id)`
  - the durable dedupe identity for memory extraction, attachment extraction, and retrieval indexing must be the canonical source artifact being processed
- Retrieval indexing dedupe in particular must be source-specific, not message-generic:
  - transcript-source indexing is keyed by source message identity
  - summary-source indexing is keyed by summary snapshot identity
  - memory-source indexing is keyed by active memory identity
  - attachment-source indexing is keyed by completed attachment extraction identity
- Rebuild and repair ownership in this slice is:
  - summary and memory rebuild jobs derive only from canonical transcript and existing governance continuity inputs
  - attachment extraction rebuild derives from normalized attachment state in `message_attachments`
  - retrieval-record rebuild derives from the canonical source artifact for each source kind: transcript rows, summary snapshots, active memory rows, or completed attachment extractions
- `context_manifests` are diagnostic records only and must never be treated as the rebuild source for summaries, memories, retrieval records, or attachment extractions

### Manifest and Observability Contract
- `context_manifests` remain the inspectable source for how one turn’s prompt context was assembled.
- For this slice, manifest payloads must be able to show:
  - transcript range used
  - summary snapshot ids used
  - memory ids used
  - retrieval record ids used
  - attachment ids and attachment extraction ids used
  - retrieval strategy identifier
  - assembly budget and whether trimming occurred
  - degraded flags and bounded degraded reasons
- Structured observability should distinguish:
  - retrieval unavailable
  - retrieval empty but healthy
  - attachment extraction pending
  - attachment extraction failed
  - memory extraction failed
  - summary rollover skipped because thresholds were not met

### Prompt Construction Contract
- `src/graphs/prompts.py` remains the prompt-construction entry point.
- Prompt payloads in this slice must gain explicit sections or metadata for:
  - summary context already selected
  - retrieved memory and retrieval items
  - attachment-derived content already available
- The minimum prompt-visible structured carriers in this slice are:
  - selected summary context
  - selected memory items
  - selected non-memory retrieval items
  - selected attachment-derived items
  - metadata-only attachment fallback items
  - assembly budget and trimming metadata
- Prompt rendering must not query the database directly.
- Prompt construction must consume only backend-owned state already assembled into `AssistantState` and `context_manifest`.
- This slice extends the runtime state contract so selected summary context, retrieved memory items, retrieved non-memory records, and attachment-derived prompt items are carried explicitly on the assembled turn state rather than encoded as synthetic conversation messages.
- Prompt-visible retrieval and attachment content must stay bounded and provenance-aware so diagnostics can explain why the model saw a given memory or extracted snippet.

## Runtime Invariants
- The gateway still persists canonical transcript and run state before any derived memory or retrieval job executes.
- Transcript rows remain the only canonical conversation truth.
- `ContextService` remains the only context-assembly boundary for provider-backed turns.
- Retrieval and memory failures must not silently invent assistant-visible facts.
- Attachment-derived content must come only from normalized stored attachments, never from arbitrary remote URLs at prompt-build time.
- The worker and outbox system remain the only owners of after-turn enrichment and repair.
- Degraded continuity must remain observable in manifests and diagnostics.

## Security Constraints
- Attachment extraction must operate only on already-normalized stored content within configured size and type boundaries.
- Extracted attachment text, memory rows, and retrieval rows must inherit the same session scoping and audit expectations as the transcript they derive from.
- No secret-bearing prompt or provider payload may be written into memory, retrieval, or extraction stores by default.
- Durable memory and retrieval indexing in this slice must follow an explicit source-eligibility allowlist so backend-only prompt scaffolding, raw provider payloads, raw audit payloads, and approval packets do not become durable retrieval inputs by accident.
- Retrieval must not cross session boundaries in this slice.
- Image or PDF extraction must fail closed on unsupported or oversized inputs rather than bypassing storage or size policies.

## Operational Considerations
- The system should prefer transcript-first resilience over enrichment completeness: accepted runs must stay successful even when indexing or extraction is behind.
- Enrichment jobs should be independently retryable and idempotent.
- Summary rollover, memory extraction, retrieval indexing, and attachment extraction should each have bounded failure classification and diagnostics visibility.
- The implementation should support source-aware rebuild of derived state for one session:
  - summaries and memories rebuild from canonical transcript state
  - attachment extraction state rebuilds from normalized attachment state
  - retrieval rows rebuild from their canonical source artifacts
- Retrieval scoring, chunk sizing, and assembly budgets should be explicit configuration rather than hidden constants where practical.
- The initial implementation should keep dependencies modest and local-testable; any heavy external retrieval backend should remain optional.

## Acceptance Criteria
- A long-running session can exceed the raw transcript window and still assemble context using recent transcript plus the latest valid summary snapshot, with manifest visibility into the chosen ranges.
- After-turn jobs can persist durable memory rows with source provenance and retrieval records without blocking the accepted run.
- `ContextService` can inject bounded relevant retrieval results into a later turn, and `context_manifests` record exactly which retrieval records and memory rows were used.
- Supported attachments can be normalized first and later expose extracted content for prompt use when extraction succeeds, while still degrading safely to metadata-only behavior when extraction is pending, unsupported, or failed.
- Newly uploaded supported text files and text-extractable PDFs may contribute extracted content to the same triggering turn only when the bounded same-run fast path completes durably; otherwise that turn degrades to metadata-only attachment context and later turns may benefit after asynchronous extraction completes.
- Retrieval, memory extraction, and attachment extraction failures do not corrupt transcript truth and do not prevent a safe assistant turn from completing when transcript or summary context is sufficient.
- The repository test suite can exercise summary rollover, memory extraction, retrieval indexing, attachment extraction, degraded assembly, and transcript-only recovery without requiring live external retrieval services.

## Test Expectations
- Unit tests for context assembly ordering and budgeting across transcript, summary, retrieval, and attachment-derived content
- Unit tests for manifest payloads proving retrieval ids, memory ids, attachment extraction ids, and degraded reasons are recorded consistently
- Unit tests for durable memory extraction proving provenance, idempotency, supersession, and transcript-truth preservation
- Unit tests for retrieval ranking and scoping proving retrieval is bounded, session-scoped, and safe when no results are found
- Unit tests for text, PDF, and image attachment extraction contracts proving supported outputs, bounded metadata, and failure handling
- Runtime tests proving after-turn jobs enqueue and execute summary generation, memory extraction, retrieval indexing, and attachment extraction idempotently
- Runtime tests proving context assembly degrades safely when retrieval is unavailable or attachment extraction is still pending
- Integration-style tests proving a later turn can use memory or attachment-derived context generated from earlier transcript and attachments
- Integration-style tests proving same-run bounded attachment fast-path extraction either produces durable extraction state before prompt use or degrades cleanly to metadata-only behavior
- Recovery tests proving summaries, memory rows, retrieval rows, and attachment extraction state can be rebuilt from canonical transcript and normalized attachment state after simulated failure
