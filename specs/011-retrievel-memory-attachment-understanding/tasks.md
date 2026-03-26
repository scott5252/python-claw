# Tasks 011: Retrieval, Memory, and Attachment Understanding

## Alignment Decisions

### Gap 1: Transcript truth must remain authoritative even after durable memory lands
Options considered:
- Option A: replace old transcript with extracted memory once compaction succeeds
- Option B: let summaries and memory rows act as co-equal truth sources
- Option C: keep transcript canonical and treat summary, memory, retrieval, and attachment-derived content as additive derived state only
- Option D: defer durable memory and rely only on summaries

Selected option:
- Option C

### Gap 2: Retrieval needs a bounded first implementation that fits the current repo
Options considered:
- Option A: require an external vector store immediately
- Option B: ship only naive keyword lookup with no durable retrieval records
- Option C: define durable retrieval records plus a retrieval service abstraction that can start with local lexical ranking and grow later
- Option D: skip retrieval and inject all memory rows directly into prompts

Selected option:
- Option C

### Gap 3: Attachment understanding must not make accepted turns synchronous or brittle
Options considered:
- Option A: extract attachment content in the gateway before run creation
- Option B: fully extract every attachment inline during worker normalization
- Option C: keep normalization storage-first and run attachment extraction as idempotent after-turn enrichment, with metadata-only fallback when extraction is unavailable
- Option D: defer attachment understanding entirely

Selected option:
- Option C

### Gap 4: Derived enrichment rows need explicit lifecycle and idempotency
Options considered:
- Option A: leave lifecycle details implicit and rely on generic outbox dedupe only
- Option B: make every enrichment row append-only with freshness inferred heuristically
- Option C: define explicit status transitions and deterministic derivation keys for memory, retrieval, and attachment extraction
- Option D: collapse all enrichment into one generic table

Selected option:
- Option C

### Gap 5: Same-run attachment understanding needs a bounded availability rule
Options considered:
- Option A: make all attachment understanding available only on later turns
- Option B: block every supported attachment on extraction before the turn continues
- Option C: allow a bounded same-run fast path for text files and text-extractable PDFs only, while heavier work remains asynchronous
- Option D: let prompt construction reread normalized files directly

Selected option:
- Option C

### Gap 6: Retrieval selection, budgeting, and deduplication must be deterministic
Options considered:
- Option A: rank everything together and let retrieval use any remaining prompt budget
- Option B: define transcript-first assembly order, explicit per-source caps, and provenance-aware deduplication before rendering
- Option C: include all available sources and rely on downstream truncation
- Option D: choose exactly one non-transcript source type per turn

Selected option:
- Option B

### Gap 7: Durable memory provenance must be structured instead of opaque
Options considered:
- Option A: require every memory row to point to exactly one source message
- Option B: hide provenance inside `payload_json`
- Option C: add an explicit provenance envelope with `source_kind` plus nullable source fields for message- or summary-derived memory
- Option D: split durable memory into separate tables by provenance type

Selected option:
- Option C

### Gap 8: Same-run attachment fast-path ownership must stay worker-owned
Options considered:
- Option A: run bounded fast-path extraction in the worker after normalization and before context assembly
- Option B: let `ContextService` perform same-run extraction during assembly
- Option C: let prompt construction reread normalized files directly when needed
- Option D: remove same-run attachment understanding and make extraction asynchronous-only

Selected option:
- Option A

### Gap 9: Enrichment and indexing identity must be source-specific
Options considered:
- Option A: key retrieval indexing generically by message and let handlers scan sources heuristically
- Option B: key enrichment and indexing by canonical source artifact identity
- Option C: build retrieval rows lazily during reads
- Option D: defer source-aware indexing until a later spec

Selected option:
- Option B

### Gap 10: Retrieved context needs an explicit structured runtime carrier
Options considered:
- Option A: encode summaries and retrieval as synthetic conversation messages
- Option B: let prompt construction query repositories directly
- Option C: extend context assembly and runtime state with explicit structured summary, memory, retrieval, and attachment-derived fields
- Option D: carry only identifiers and reconstruct later

Selected option:
- Option C

### Gap 11: Derived rows need explicit strategy identity
Options considered:
- Option A: key derived rows by source identity and content hash only
- Option B: store strategy version in metadata only
- Option C: add explicit derivation strategy identity for memory, retrieval, and extraction work
- Option D: split each strategy into separate tables

Selected option:
- Option C

### Gap 12: Enrichment jobs need a structured source envelope
Options considered:
- Option A: rely on `job_dedupe_key` strings only
- Option B: rescan sessions heuristically during outbox execution
- Option C: add a structured source envelope for durable enrichment jobs
- Option D: create separate queue tables per enrichment family

Selected option:
- Option C

### Gap 13: Same-run fast-path failures need explicit classification
Options considered:
- Option A: retry the whole run for any fast-path failure
- Option B: degrade all fast-path failures to metadata-only
- Option C: retry canonical-state or persistence failures, but degrade extraction-class failures after durable status recording
- Option D: remove same-run fast path

Selected option:
- Option C

### Gap 14: Retrieved context carriers need minimum typed shapes
Options considered:
- Option A: use raw dictionaries everywhere
- Option B: carry only identifiers
- Option C: define explicit typed carriers for summary, memory, retrieval, attachment-derived, and budget metadata
- Option D: encode retrieved context as synthetic transcript messages

Selected option:
- Option C

### Gap 15: Memory and retrieval inputs need an explicit source-eligibility policy
Options considered:
- Option A: allow all transcript-linked text and artifacts
- Option B: rely on best-effort redaction only
- Option C: define an explicit allowlist plus rejection or redaction rules
- Option D: allow only user transcript rows

Selected option:
- Option C

## Tasks

1. Confirm the current continuity, outbox, worker, media, graph-state, prompt, provider, repository, and manifest seams in `src/context/service.py`, `src/context/outbox.py`, `src/jobs/service.py`, `src/media/processor.py`, `src/graphs/state.py`, `src/graphs/prompts.py`, `src/graphs/nodes.py`, `src/sessions/repository.py`, and `src/db/models.py` so Spec 011 extends the existing gateway-first architecture instead of creating a second continuity path.
2. Add high-risk contract tests first for transcript-authority preservation, proving summaries, durable memories, retrieval rows, and attachment-extraction rows remain derived state only and that transcript-plus-summary continuity still works when all new enrichment is absent, stale, or disabled.
3. Add high-risk persistence tests first for the new provenance and lifecycle rules, covering valid and invalid `session_memories` provenance envelopes, allowed memory statuses, immutable `retrieval_records` source identities, unique chunk identity, unique `(attachment_id, extractor_kind)` extraction identity, and deterministic duplicate suppression across retries.
4. Add additive migrations for `session_memories`, `retrieval_records`, and `attachment_extractions`, including all required fields, indexes, unique constraints, lifecycle columns, structured provenance columns, and additive `context_manifests.manifest_json` payload growth for `memory_ids`, `retrieval_ids`, `attachment_extraction_ids`, `assembly_budget`, `retrieval_strategy`, and `degraded_reasons`.
5. Extend those additive persistence contracts with explicit derivation-strategy identity for memory extraction, retrieval indexing, and attachment extraction wherever strategy revision must participate in duplicate suppression and rebuild behavior.
6. Extend `src/db/models.py` with additive SQLAlchemy models for `session_memories`, `retrieval_records`, and `attachment_extractions`, preserving transcript, summaries, normalized attachments, outbox jobs, and manifests in their existing authoritative roles.
7. Add repository helpers and repository tests in `src/sessions/repository.py` for durable memory creation, lookup, dedupe-safe transitions, retrieval-record insertion and source-aware lookups, attachment-extraction creation and terminal-state transitions, structured outbox source envelopes, and rebuild reads over transcript rows, summary snapshots, active memory rows, completed attachment extractions, and normalized attachments.
8. Extend `src/config/settings.py` with explicit bounded settings for retrieval enablement, retrieval strategy identifier, ranking thresholds, total retrieved-context budget, per-source caps, chunk sizing limits, memory extraction enablement, attachment extraction enablement, same-run fast-path enablement, same-run text or PDF size, page-count, and time ceilings, and any explicit source-eligibility or derivation-version settings kept fail-closed by default.
9. Add settings tests first proving invalid budgets, invalid per-source caps, invalid same-run fast-path limits, invalid derivation-strategy settings, and contradictory feature toggles fail closed instead of enabling unbounded enrichment behavior.
10. Add high-risk context-assembly tests first for `src/context/service.py`, proving transcript-first budgeting, summary inclusion only when needed, explicit total and per-source retrieval caps, provenance-aware deduplication against included transcript and selected summary coverage, deterministic trimming, healthy-empty retrieval handling, and degraded retrieval-unavailable handling.
11. Add manifest-shape tests first proving `ContextAssemblyResult` and persisted manifest payloads record transcript range, summary ids, memory ids, retrieval ids, attachment ids, attachment-extraction ids, retrieval strategy, assembly budget, trimming decisions, skipped-candidate reasons, and degraded reasons without making manifests a rebuild source.
12. Introduce `src/memory/service.py` with one bounded durable-memory extraction contract that derives memory only from canonical transcript rows or summary snapshots after transcript commit, assigns stable content hashes and memory kinds, records confidence, remains idempotent per source input and extraction strategy, and applies the explicit source-eligibility boundary before any durable write.
13. Add high-risk memory-service tests proving valid structured provenance for `source_kind=message` and `source_kind=summary_snapshot`, rejection of invalid provenance combinations, idempotent extraction, derivation-strategy-aware duplicate suppression, `active` or `rejected` initial writes only, and later `active -> superseded` or `expired` transitions without transcript mutation.
14. Introduce `src/retrieval/service.py` with one storage-agnostic retrieval boundary for indexing transcript, summary, active-memory, and completed attachment-extraction content and for returning bounded, session-scoped, provenance-rich ranked results to `ContextService`.
15. Add `src/retrieval/indexing.py` only if needed to keep retrieval chunking, chunk identity, and ranking helpers small and testable, ensuring chunk identity stays deterministic from canonical source artifact plus `chunk_index`, bounded content hashing, and derivation strategy identity where required.
16. Add high-risk retrieval tests proving session scoping, deterministic chunk identity, immutable source-specific retrieval rows, lexical or lightweight local ranking behavior, result thresholding, bounded result counts, duplicate collapse by source identity or `content_hash`, healthy empty-result behavior distinct from degraded failure, and exclusion of ineligible backend-only sources.
17. Introduce `src/media/extraction.py` with one durable extraction contract for normalized stored attachments only, standardizing `status`, `content_text`, `content_metadata_json`, `extractor_kind`, derivation strategy identity, and bounded `error_detail` across text files, PDFs, and images.
18. Add high-risk attachment-extraction tests proving text extraction for supported text files, bounded PDF extraction, image extraction status handling, unsupported-type handling, `pending -> completed|failed|unsupported` transitions, explicit fast-path failure classification, and deterministic reuse of the same canonical extraction identity during retries or repairs.
19. Refactor `src/context/service.py` so `ContextAssemblyResult` carries explicit structured transcript-selection metadata, selected summary context, selected active-memory items, selected non-memory retrieval items, selected attachment-derived items, metadata-only attachment fallback items, assembly budgets, retrieval strategy, trimming metadata, and degraded reasons while remaining read-only.
20. Extend `src/graphs/state.py` with the smallest additive typed runtime carriers needed for selected summary context, selected memory items, selected retrieval items, selected attachment-derived items, metadata-only attachment fallback, and assembly metadata so prompt construction never queries repositories directly and does not rely on synthetic transcript messages.
21. Update `src/graphs/prompts.py` so prompt payload construction renders explicit sections for summary context, retrieved memory, retrieved non-memory context, attachment-derived content already available, and metadata-only attachment fallback, while remaining pure and consuming only assembled state.
22. Update `src/graphs/nodes.py` so worker-owned orchestration explicitly sequences normalization, optional same-run attachment fast-path extraction, read-only context assembly, model execution, and after-turn enrichment enqueueing without moving storage or continuity policy into prompt builders.
23. Add same-run fast-path tests first proving only configured text files and text-extractable PDFs can participate, the worker performs extraction after normalization and before assembly, `attachment_extractions` are persisted before prompt consumption, extraction-class timeout or over-limit cases degrade to metadata-only context, canonical-state or persistence failures retry the run, and images remain asynchronous-only in this slice.
24. Extend `src/context/outbox.py` so it can claim and execute `summary_generation`, `memory_extraction`, `retrieval_index`, `attachment_extraction`, and `continuity_repair` jobs with deterministic source-specific identity, structured source envelopes, idempotent retries, and bounded failure recording.
25. Extend `src/jobs/service.py` so accepted runs enqueue additive after-turn jobs for summary rollover, memory extraction, retrieval indexing, attachment extraction for new supported normalized attachments, and continuity repair when assembly degraded or enrichment failed, while keeping run completion independent from enrichment completion.
26. Add runtime and outbox tests proving trigger-time fan-out can start from `(session_id, message_id)` while durable dedupe identity remains source-specific for transcript messages, summary snapshots, active memory rows, completed attachment extractions, and `(attachment_id, extractor_kind)` extraction work, with structured source envelopes preserved end to end.
27. Extend manifest persistence so `context_manifests` remain the inspectable explanation of one turn’s continuity, recording used and skipped derived sources, retrieval strategy, assembly budget, trimming, and degraded dependency state without becoming a rebuild or replay source of truth.
28. Extend observability in `src/observability/audit.py`, `src/observability/failures.py`, and `src/observability/logging.py` so operators can distinguish retrieval unavailable vs retrieval empty, memory extraction failure, attachment extraction pending vs failed vs unsupported, summary rollover skipped, and same-run fast-path success vs timeout vs metadata-only fallback.
29. Add diagnostics coverage only as needed so existing read-only operator surfaces can inspect attachment extraction, retrieval, and continuity degradation state without introducing a second source of truth or a write surface.
30. Add runtime tests proving accepted turns still complete when retrieval, memory extraction, or attachment extraction jobs are pending, failed, unsupported, or disabled, and that transcript-plus-summary continuity remains the minimum safe path.
31. Add integration tests proving long-running sessions can move from transcript replay to latest-valid summary plus bounded retrieval plus active-memory continuity, while manifests remain inspectable and transcript remains authoritative.
32. Add integration tests proving normalized attachments can contribute same-run text or PDF understanding when within fast-path limits, can contribute later-turn context through asynchronous extraction when fast-path limits are exceeded or disabled, and remain metadata-only when extraction is unsupported or failed.
33. Add rebuild and recovery tests proving summaries, durable memories, retrieval records, and attachment extractions can all be rebuilt from canonical transcript rows and normalized attachment state after simulated outbox or worker failure, with manifests treated as diagnostic only.
34. Finish with verification that retrieval stays session-scoped, memory provenance remains explicit and structured, derivation-strategy identity is honored, source eligibility remains fail-closed, `ContextService` stays read-only, prompt construction stays backend-owned, accepted turns never depend on synchronous enrichment beyond the bounded same-run fast path, and the final implementation satisfies Specs 001 through 010 without weakening existing execution, approval, durability, or observability boundaries.
