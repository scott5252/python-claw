# Plan 011: Retrieval, Memory, and Attachment Understanding

## Target Modules
- `src/context/service.py`
- `src/context/outbox.py`
- `src/graphs/state.py`
- `src/graphs/prompts.py`
- `src/graphs/nodes.py`
- `src/jobs/service.py`
- `src/media/processor.py`
- `src/media/extraction.py` new
- `src/retrieval/service.py` new
- `src/retrieval/indexing.py` new if chunking or ranking helpers need separation
- `src/memory/service.py` new
- `src/sessions/repository.py`
- `src/db/models.py`
- `src/config/settings.py`
- `src/observability/audit.py`
- `src/observability/failures.py`
- `src/observability/logging.py`
- `migrations/versions/`
- `apps/gateway/api/admin.py` only if an additive diagnostics surface is needed in this slice
- `tests/`

## Success Conditions
- Transcript rows remain the only canonical conversation truth; summaries, durable memory rows, retrieval records, and attachment extraction rows remain additive derived state only.
- `src/context/service.py` becomes the only read-only context assembly boundary for this slice and assembles recent transcript, latest valid summary, retrieved memory or retrieval rows, and attachment-derived content under explicit deterministic budgets.
- `ContextAssemblyResult`, `AssistantState`, prompt payload construction, and `context_manifests` all carry explicit structured summary, memory, retrieval, and attachment-derived context instead of encoding them as synthetic transcript messages.
- `session_memories`, `retrieval_records`, and `attachment_extractions` have explicit lifecycle, provenance, and duplicate-suppression behavior aligned with the spec.
- After-turn enrichment remains worker-owned and outbox-driven for summary generation, memory extraction, retrieval indexing, attachment extraction, and continuity repair.
- Newly uploaded text files and text-extractable PDFs may contribute to the same triggering turn only through a bounded worker-owned fast path that persists `attachment_extractions` before assembly; otherwise the turn degrades safely to metadata-only attachment context.
- Retrieval remains session-scoped, deterministic, provenance-aware, and safely degradable when unavailable or empty.
- Durable memory extraction, retrieval indexing, and attachment extraction each carry explicit derivation-strategy identity so strategy changes can rebuild cleanly without silent dedupe collisions.
- After-turn enrichment jobs carry structured source identity rather than relying on `job_dedupe_key` strings alone.
- Same-run attachment fast-path failures are classified explicitly so extraction-class failures degrade safely while canonical-state or persistence failures retry under the normal run contract.
- Durable memory and retrieval inputs remain bounded by an explicit source-eligibility policy that excludes backend-only prompt and audit content by default.
- Derived continuity for one session can be rebuilt from canonical transcript rows and normalized attachment state, never from `context_manifests`.

## Migration Order
1. Add additive persistence models for:
   - `session_memories`
   - `retrieval_records`
   - `attachment_extractions`
2. Add the required indexes and duplicate-suppression identities:
   - `session_memories(session_id, status, created_at)`
   - `session_memories(source_message_id, status)`
   - `session_memories(source_summary_snapshot_id, status)`
   - chosen memory derivation uniqueness such as `(session_id, source_message_id, memory_kind, content_hash)`
   - `retrieval_records(session_id, source_kind, source_id, chunk_index, content_hash)` unique
   - `retrieval_records(session_id, source_kind, created_at)`
   - `attachment_extractions(attachment_id, extractor_kind)` unique
   - `attachment_extractions(session_id, status, created_at)`
   - strategy identity fields or bounded metadata needed so derivation revisions can participate in duplicate suppression and rebuild
3. Keep `messages`, `summary_snapshots`, `message_attachments`, `context_manifests`, and `outbox_jobs` authoritative in their existing roles; extend only payload shapes and repository helpers additively.
4. Define repository and service contracts before wiring graph or prompt changes so deterministic unit tests can run against fake retrieval and extraction implementations.
5. Define the source-eligibility policy and durable job source-envelope shape before retrieval or memory writes are introduced, so indexing and extraction do not begin from ambiguous or unsafe inputs.
6. Add same-run attachment fast-path wiring only after the durable extraction contract exists, because prompt assembly may consume attachment-derived content only from persisted extraction state.
7. Roll out budgeted context assembly after retrieval, memory, and extraction services all have safe empty, pending, unsupported, and failure behavior.

## Implementation Shape
- Preserve the existing ownership boundaries from Specs 004, 007, 009, and 010:
  - `src/media/processor.py` owns normalization and storage only
  - the worker owns same-run attachment fast-path extraction timing
  - `src/context/service.py` reads already-persisted state only
  - `src/graphs/prompts.py` renders only already-assembled structured state
  - `src/context/outbox.py` and `src/jobs/service.py` own durable enrichment fan-out and execution
- Keep the first retrieval implementation bounded:
  - session-scoped only
  - lexical or lightweight local ranking allowed
  - optional embedding fields additive only
  - no requirement for an external vector backend
- Make derivation identity explicit:
  - memory extraction, retrieval indexing, and attachment extraction each carry a strategy identifier or version
  - duplicate suppression and rebuild behavior use both canonical source identity and derivation strategy identity where needed
- Keep rebuildability explicit:
  - summaries and memories rebuild from canonical transcript state
  - attachment extractions rebuild from normalized attachment state
  - retrieval records rebuild from canonical source artifacts: transcript rows, summary snapshots, active memory rows, and completed attachment extractions
  - `context_manifests` are diagnostic only and never a rebuild source
- Treat same-run attachment understanding as an exception to the default asynchronous path, not a second extraction architecture:
  - only text files and text-extractable PDFs participate
  - size, page-count, and time limits are explicit settings
  - image extraction is asynchronous-only in this slice
  - prompt assembly never rereads raw files ad hoc
- Keep failure classification explicit:
  - extraction-class fast-path failures degrade to metadata-only prompt input after durable status persistence
  - canonical-state or persistence failures follow the normal retryable run-failure path
- Keep durable source eligibility explicit:
  - allow only approved canonical source classes into memory and retrieval indexing
  - exclude backend-only prompt scaffolding, raw provider payloads, approval packets, and raw audit blobs by default

## Assembly Strategy
- Keep assembly deterministic and transcript-first:
  - reserve budget for recent transcript needed for immediate conversational continuity
  - include the latest valid summary snapshot only when transcript exceeds the configured window or rollover budget
  - apply one explicit total budget for retrieved non-transcript context
  - apply explicit per-source caps for active memory rows, attachment-derived records, and other retrieval records
- Enforce provenance-aware deduplication before prompt rendering:
  - skip retrieval candidates whose canonical source range is already covered by directly included transcript
  - skip retrieval candidates whose content is already represented by the selected summary snapshot unless they add distinct active memory or attachment-derived content
  - collapse duplicate candidates sharing canonical source identity or `content_hash` deterministically
- Preserve explainability:
  - `context_manifests` record what was used, what was skipped, the retrieval strategy identifier, assembly budget, trimming, and bounded degraded reasons
  - healthy empty retrieval is distinct from degraded retrieval failure
  - pending or failed attachment extraction is distinct from unsupported attachment extraction

## Service and Module Boundaries
### `src/context/service.py`
- Extend `ContextAssemblyResult` to carry:
  - transcript selection metadata
  - selected summary snapshot ids and rendered summary context
  - selected active memory items
  - selected non-memory retrieval items
  - selected attachment-derived items and metadata-only fallback items
  - assembly budget, retrieval strategy, trimming, and degraded reasons
- Keep the service read-only in this slice:
  - no inline attachment extraction
  - no inline memory writes
  - no inline retrieval indexing
- Own manifest creation and persistence so one module remains authoritative for the turn’s continuity explanation.

### `src/context/outbox.py`
- Extend job execution beyond `summary_generation` to support:
  - `memory_extraction`
  - `retrieval_index`
  - `attachment_extraction`
  - `continuity_repair`
- Implement source-specific idempotent job handling:
  - transcript-source indexing keyed by source message identity
  - summary-source indexing keyed by summary snapshot identity
  - memory-source indexing keyed by active memory identity
  - attachment-source extraction keyed by `(attachment_id, extractor_kind)`
  - attachment-source indexing keyed by completed attachment extraction identity
- Keep retries additive and deterministic; failed enrichment must not corrupt accepted-run transcript or manifest state.
- Carry structured source identity for each enrichment job so workers do not rely on free-form `job_dedupe_key` parsing as the only source of truth.

### `src/jobs/service.py`
- Enqueue additive after-turn jobs for:
  - summary generation
  - memory extraction
  - retrieval indexing
  - attachment extraction for new stored attachments
  - continuity repair when assembly degraded or enrichment failed
- Distinguish trigger-time fan-out from durable job identity:
  - a turn may enqueue from `(session_id, message_id)`
  - durable dedupe identities must be the canonical source artifacts being processed
- Ensure fan-out produces structured source envelopes for derived work so later outbox workers can process one canonical source artifact at a time without rescanning unrelated session state.
- Keep run completion independent from enrichment completion so accepted runs do not block on indexing or extraction.

### `src/media/processor.py`
- Keep scope limited to safe normalization, storage, and metadata for supported attachments.
- Expose enough normalized metadata and storage references for later extraction and diagnostics.
- Do not perform OCR, PDF parsing, or prompt-time content reading in this module.

### `src/media/extraction.py`
- Introduce one durable extraction boundary for stored attachments only.
- Support this slice’s attachment kinds:
  - text files
  - PDFs
  - images
- Standardize extraction output on:
  - `status`
  - `content_text`
  - `content_metadata_json`
  - `extractor_kind`
  - bounded `error_detail`
- Respect transition ownership:
  - `pending`
  - `completed`
  - `failed`
  - `unsupported`
- Ensure repair retries reuse the same `(attachment_id, extractor_kind)` identity instead of creating competing active rows.
- Persist extractor strategy identity so revised extraction logic can rebuild without colliding with earlier derived rows for the same attachment.
- Classify same-run fast-path failures so timeout, unsupported parsing, and bounded parsing failures degrade safely while durable-persistence failures retry the run.

### `src/memory/service.py`
- Extract durable memory only from canonical transcript inputs or summary snapshot inputs after transcript commit.
- Persist explicit structured provenance:
  - `source_kind=message`
  - `source_kind=summary_snapshot`
  - required source fields per provenance form
- Keep memory lifecycle explicit:
  - extraction creates `active` or `rejected`
  - later extraction or maintenance may move `active -> superseded`
  - lifecycle policy may move `active -> expired` or `superseded -> expired`
- Normalize bounded memory rows with stable content hashes, confidence, memory kind, and session provenance.
- Include derivation strategy identity in memory dedupe and rebuild behavior.
- Apply the slice's source-eligibility and secret-safety rules before any durable memory write occurs.

### `src/retrieval/service.py`
- Define a storage-agnostic retrieval boundary that:
  - indexes transcript, summary, active memory, and completed attachment-extraction content
  - retrieves bounded relevant records for one turn
  - returns provenance-rich ranking metadata to `ContextService`
- Keep retrieval deterministic from backend-owned turn inputs:
  - current user message text
  - triggering message attachment metadata
  - bounded recent transcript context
- Do not allow cross-session retrieval in this slice.
- Include derivation strategy identity in retrieval indexing where chunking or ranking revisions would otherwise collide with older rows.
- Enforce the source-eligibility boundary before indexing so backend-only content does not become durable retrieval input.

### `src/retrieval/indexing.py`
- Add chunking, ranking, or canonical source-to-record helpers only if separating them keeps `src/retrieval/service.py` small and testable.
- Ensure chunk identity is deterministic from canonical source artifact plus `chunk_index` and bounded content hashing.

### `src/graphs/state.py`
- Extend `AssistantState` additively with explicit structured continuity carriers for:
  - selected summary context
  - selected memory items
  - selected non-memory retrieval items
  - selected attachment-derived prompt items
  - assembly metadata needed by prompt rendering and diagnostics
- Keep `context_manifest` as the durable inspectable record, but make `AssistantState` the authoritative in-turn carrier.
- Define minimal typed carriers rather than raw untyped dictionaries so prompt rendering and tests can rely on stable structured fields.

### `src/graphs/prompts.py`
- Add explicit prompt sections for:
  - selected summary context
  - retrieved memory
  - retrieved non-memory context
  - attachment-derived content already available
  - metadata-only attachment fallback when extraction is pending, failed, unsupported, or skipped
- Keep prompt construction pure:
  - no repository reads
  - no raw-file rereads
  - no retrieval heuristics outside assembled state

### `src/graphs/nodes.py`
- Keep graph orchestration responsible for sequencing:
  - worker normalization
  - optional bounded same-run attachment fast-path extraction
  - context assembly
  - model execution
  - after-turn job enqueue
- Do not move long-term continuity policy or storage logic into graph nodes.

### `src/sessions/repository.py`
- Add repository helpers for:
  - durable memory creation, lookup, and lifecycle transitions
  - retrieval-record insertion, dedupe-safe upsert behavior, and source lookups
  - attachment-extraction creation, lookup, completion, failure, unsupported state, and fast-path persistence
  - source-aware rebuild reads for transcript rows, summary snapshots, active memories, completed attachment extractions, and normalized attachments
- Keep methods session-scoped and provenance-aware; no helper should make manifests the rebuild source.

### `src/db/models.py`
- Add additive models and indexes for:
  - `session_memories`
  - `retrieval_records`
  - `attachment_extractions`
- Grow `context_manifests.manifest_json` additively to persist:
  - `memory_ids`
  - `retrieval_ids`
  - `attachment_extraction_ids`
  - `assembly_budget`
  - `retrieval_strategy`
  - `degraded_reasons`
- Avoid mutating transcript truth or existing governance durability contracts.

### `src/config/settings.py`
- Add explicit bounded settings for:
  - retrieval enable or disable
  - retrieval ranking strategy identifier
  - retrieval result thresholds and total retrieved-context budget
  - per-source caps for memory, attachment-derived, and other retrieval items
  - retrieval chunk sizing and indexing limits
  - memory extraction enable or disable
  - attachment extraction enable or disable
  - same-run fast-path enable or disable
  - same-run text and PDF size, page-count, and time limits
  - derivation strategy identifiers or versions where they are configurable in this slice
  - source-eligibility toggles only if they stay fail-closed by default
  - optional embedding configuration only if an additive local implementation actually uses it

### `src/observability/*`
- Emit structured events and failure classes for:
  - retrieval unavailable
  - retrieval empty but healthy
  - memory extraction failed
  - attachment extraction pending
  - attachment extraction failed
  - attachment extraction unsupported
  - summary rollover skipped because thresholds were not met
  - same-run fast-path success, timeout, or fallback to metadata-only behavior
- Keep degraded continuity separate from hard accepted-run failure.

## Contracts to Implement
### Persistence Contracts
- `session_memories`
  - explicit provenance envelope with `source_kind`
  - exactly one valid provenance form per row
  - status values restricted to `active`, `superseded`, `expired`, or `rejected`
- `retrieval_records`
  - immutable derived rows keyed by canonical source artifact and chunk identity
  - `source_kind` restricted to `message`, `summary_snapshot`, `memory`, or `attachment_extraction`
- `attachment_extractions`
  - one durable logical extraction identity per `(attachment_id, extractor_kind)`
  - status values restricted to `pending`, `completed`, `failed`, or `unsupported`
- Repository helpers must support:
  - session-scoped lookups
  - provenance-aware lookups by source message, summary snapshot, memory, and attachment extraction
  - deterministic duplicate suppression
  - source-aware rebuild reads

### Runtime Contracts
- `ContextService.assemble(...)`
  - reads already-persisted state only
  - returns transcript selections plus explicit structured summary, memory, retrieval, and attachment-derived context
  - applies deterministic budgets and provenance-aware deduplication
  - succeeds with transcript-plus-summary behavior when retrieval is unavailable
- Same-run attachment fast path
  - runs on the owning worker after normalization and before context assembly
  - may persist only bounded text-file and text-extractable-PDF extraction results
  - must persist `attachment_extractions` before assembly consumes the result
  - degrades cleanly to metadata-only attachment context when limits are exceeded or the fast path does not finish in time
- Prompt payload
  - renders only already-assembled state from `AssistantState`
  - never queries the database directly

### Enrichment Contracts
- Summary generation
  - remains additive, versioned, and range-bounded
- Memory extraction
  - runs post-commit only
  - is idempotent per canonical source and extraction strategy
  - may write only `active` or `rejected` on initial extraction
- Retrieval indexing
  - indexes only bounded canonical source artifacts
  - is idempotent per source artifact and chunk identity
  - may index attachment-derived content only from completed extraction rows
- Attachment extraction
  - runs only against normalized stored attachments
  - persists durable failure or unsupported state without failing the accepted turn

### Manifest and Diagnostics Contracts
- `context_manifests`
  - remain the inspectable explanation of one turn’s assembled continuity
  - must record transcript range, summary ids, memory ids, retrieval ids, attachment ids, attachment extraction ids, retrieval strategy, assembly budget, trimming, and degraded reasons
- Diagnostics and observability
  - must distinguish degraded dependency state from healthy empty results
  - must support source-aware rebuild and failure analysis without relying on logs as the source of truth

## Risk Areas
- Durable memory drifting into a competing source of truth instead of remaining derived, provenance-backed continuity.
- `ContextService` growing hidden write paths or prompt-time extraction logic and weakening the spec’s read-only assembly boundary.
- Same-run attachment fast-path logic bypassing durable extraction persistence or rereading raw files directly.
- Retrieval candidates crowding out recent transcript because total budgets and per-source caps are not enforced deterministically.
- Retrieval deduplication missing transcript or summary overlap and injecting redundant context.
- Source-specific outbox dedupe being implemented as message-generic fan-out and creating duplicate rows on retry.
- `context_manifests` accidentally becoming the rebuild source for memories, retrieval records, or attachment extractions.
- Image or PDF extraction adding heavyweight dependencies or unbounded runtime to the accepted-turn path.
- Session scoping being implemented loosely and allowing retrieval or derived artifacts to bleed across sessions.

## Rollback Strategy
- Keep all new schema and manifest changes additive.
- Preserve transcript-plus-summary continuity from Spec 004 as the minimum safe path if retrieval, memory extraction, or attachment extraction is disabled.
- Disable retrieval injection separately from retrieval indexing if ranking quality is poor.
- Disable same-run attachment fast-path extraction separately from asynchronous extraction if worker latency regresses.
- Fall back to metadata-only attachment context when extraction is pending, failed, unsupported, or feature-disabled.

## Test Strategy
- Unit:
  - deterministic context assembly ordering and budgeting across transcript, summary, memory, retrieval, and attachment-derived content
  - provenance-aware deduplication against directly included transcript and selected summary coverage
  - manifest payload consistency for `memory_ids`, `retrieval_ids`, `attachment_extraction_ids`, retrieval strategy, assembly budget, trimming, and degraded reasons
  - durable memory provenance, idempotency, supersession, expiry, and transcript-truth preservation
  - retrieval ranking, chunk identity, session scoping, thresholding, and healthy-empty-result behavior
  - attachment extraction contracts for text, PDF, and image inputs, including unsupported and failed states
  - same-run fast-path limits and metadata-only fallback behavior
- Repository or persistence:
  - additive models and required indexes for `session_memories`, `retrieval_records`, and `attachment_extractions`
  - duplicate-suppression identities for memory derivation, retrieval chunks, and `(attachment_id, extractor_kind)`
  - source-aware lookup and rebuild reads
  - additive manifest payload persistence
- Runtime:
  - after-turn job enqueueing for summary generation, memory extraction, retrieval indexing, attachment extraction, and continuity repair
  - idempotent outbox execution with source-specific dedupe identities
  - accepted turns completing safely while retrieval or extraction jobs are pending or failed
  - retrieval-unavailable degradation versus retrieval-empty-but-healthy behavior
  - same-run fast-path extraction persisting durable extraction state before prompt use or degrading cleanly to metadata-only attachment context
- Integration:
  - long-running session continuity using recent transcript plus latest valid summary plus bounded retrieval
  - later turns consuming memory or attachment-derived content generated from earlier transcript or attachments
  - attachment upload followed by same-run text or PDF fast-path success when within limits
  - attachment upload followed by asynchronous-only improvement on later turns when same-run fast path times out or is not eligible
  - unsupported or failed attachment extraction remaining metadata-only and observable
  - source-aware rebuild of summaries, memories, retrieval rows, and attachment extraction state from canonical transcript and normalized attachments after simulated failure

## Constitution Check
- Gateway-first ingestion remains unchanged.
- Worker-owned execution, enrichment, and repair ownership remain unchanged.
- Transcript remains the only canonical source of conversational truth.
- Prompt construction remains backend-authored and explainable through structured state plus manifests.
- Retrieval, durable memory, and attachment understanding enrich continuity without weakening approval, audit, durability, or session-scoping boundaries.
