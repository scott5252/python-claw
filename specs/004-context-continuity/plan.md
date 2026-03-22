# Plan 004: Context Engine Lifecycle, Continuity, Compaction, and Recovery

## Target Modules
- `apps/gateway/api/inbound.py`
- `apps/gateway/deps.py`
- `src/db/models.py` or additive continuity-specific models if the slice is split out cleanly
- `src/db/session.py`
- `src/sessions/repository.py`
- `src/sessions/service.py`
- `src/context/service.py`
- `src/graphs/state.py`
- `src/graphs/nodes.py`
- `src/graphs/assistant_graph.py`
- `src/policies/service.py`
- `src/capabilities/activation.py` if governance replay needs activation-state rebuild hooks from Spec 003
- `src/providers/models.py`
- `src/observability/audit.py` or a dedicated continuity observability module if one is introduced
- `migrations/`
- `tests/`

## Migration Order
1. Add additive derived-state tables required by the spec:
   - `summary_snapshots`
   - `outbox_jobs`
   - `context_manifests`
2. Add required indexes after the tables exist:
   - unique `summary_snapshots(session_id, snapshot_version)`
   - lookup `summary_snapshots(session_id, through_message_id)`
   - unique `outbox_jobs(job_dedupe_key)`
   - lookup `outbox_jobs(session_id, status, available_at)`
   - lookup `context_manifests(session_id, created_at)`
   - lookup `context_manifests(message_id)`
3. Add any optional retrieval or chunk-index tables only if they remain explicitly additive, disposable, and rebuildable from canonical transcript state.
4. Extend repository contracts for deterministic continuity reads before graph/runtime changes:
   - transcript range loading
   - latest valid summary lookup
   - summary snapshot creation
   - manifest persistence and bounded retention
   - post-commit `outbox_jobs` enqueue and claim/update flows
5. Wire runtime lifecycle changes behind the existing gateway-owned invocation path only, then add workers/repair flows after canonical reads and writes are stable.
6. Finish with deterministic unit, repository, and integration coverage using `uv run pytest`.

## Implementation Shape
- Preserve the architecture boundary from [docs/architecture.md](/Users/scottcornell/src/projects/python-claw/docs/architecture.md): gateway/service code owns user-visible turn invocation, graph/runtime code owns continuity assembly and compaction behavior, and workers perform post-commit derived-state maintenance only.
- Make the gateway entrypoint explicit in this slice:
  - `apps/gateway/api/inbound.py` owns the user-visible lifecycle handoff after the inbound user message is durably appended
  - no adapter, worker, scheduler, or control-plane component may invoke continuity assembly or resume a user-visible turn outside the gateway path
- Preserve transcript-first durability from the spec and constitution by treating the canonical continuity record as:
  - append-only assistant transcript rows in `messages`
  - append-only tool proposal, tool outcome, and outbound intent artifacts from Spec 002 persistence
  - transcript-linked governance artifacts from Spec 003
- Treat `summary_snapshots`, retrieval indexes, embeddings, `context_manifests`, and `outbox_jobs` as derived artifacts only. No derived artifact may become the source of truth for replay or governance visibility.
- Introduce a dedicated context-service seam in `src/context/service.py`:
  - context assembly, summary selection, compaction decisions, and continuity manifest creation belong to the context service
  - graph modules orchestrate calls into the context service and persist turn outcomes; they do not become the long-term home for continuity policy
- Implement the four-phase lifecycle explicitly and in order:
  - `ingest`: persist the new user turn through the canonical transcript path
  - `assemble`: deterministically load transcript-first context plus the latest valid additive aids
  - `compact`: handle overflow through deterministic retry that prefers additive summaries and older-history elision
  - `after_turn`: enqueue post-commit summary, indexing, and repair work through `outbox_jobs`
- Keep transaction and resume boundaries explicit:
  - `ingest` begins only after the inbound user message commit succeeds
  - model execution runs only after deterministic assembly or bounded degraded fallback completes
  - `after_turn` enqueueing occurs only after the assistant turn commit succeeds
  - resumed approval-wait or repair-driven turns re-enter through the same gateway-owned invocation path
- Keep context assembly deterministic and inspectable:
  - the same canonical session state plus the same valid derived inputs must produce the same manifest content
  - manifest content must record transcript ranges, summary ids, retrieval/chunk ids, governance artifacts, and degraded/compacted status
- Persist one `context_manifests` record per turn and emit the same manifest payload to structured logs for debugging and replay analysis.
- Make transcript-first assembly the default failure behavior:
  - retrieval, memory, or summary loading failure must not fail the user turn by itself
  - only canonical transcript unavailability may fail the turn immediately
  - if transcript-first assembly still cannot fit, retry deterministically with additive aids
  - if the prompt still cannot fit and no valid aid is available, return a bounded degraded failure and enqueue repair rather than silently truncating history
- Keep summary snapshots additive, versioned, and range-bounded:
  - snapshots never overwrite transcript history
  - later snapshots may supersede earlier ones for assembly
  - version allocation and “latest valid” selection must remain deterministic under concurrent post-commit workers
- Use Spec 003 dual durability for governance-aware continuity:
  - normalized governance tables may be consulted while healthy for runtime reads and enforcement
  - transcript-linked governance artifacts remain the canonical rebuild source after drift, restart, or repair
  - repair flows must be able to rebuild normalized governance visibility state from those transcript-linked artifacts
- Keep resume and repair fail-closed:
  - workers may repair derived state and normalized governance state
  - only the gateway-owned runtime invocation path may resume a user-visible turn after approval waits, revocations, or continuity repair

## Contracts to Implement
### Persistence and Repository Contracts
- `src/db/models.py` and `migrations/`
  - define additive persistence for `summary_snapshots`, `outbox_jobs`, and `context_manifests`
  - encode snapshot range bounds, snapshot versioning, source watermark tracking, dedupe keys, retry metadata, degraded flags, and required indexes
- `src/sessions/repository.py`
  - expose transcript-range reads over canonical transcript history and transcript-linked tool/governance artifacts
  - expose latest-valid summary lookup and versioned snapshot creation
  - expose post-commit `outbox_jobs` enqueue, claim, completion, retry, and dedupe-safe update methods
  - expose context manifest persistence plus bounded-retention cleanup that preserves the latest manifest and message-triggered lookup within the retention window

### Runtime and Assembly Contracts
- `apps/gateway/api/inbound.py`
  - invoke the continuity lifecycle through the gateway-owned path after durable inbound persistence
  - preserve the gateway as the only user-visible resume entrypoint for approval waits, repairs, and recovery
- `src/context/service.py`
  - own deterministic transcript-first assembly, additive aid selection, compaction decisions, and manifest creation
  - expose a stable service contract that graph/runtime code can call without embedding continuity policy in node glue
- `src/graphs/state.py`
  - define the continuity assembly inputs and manifest structure used by runtime code and tests
  - represent degraded outcomes and overflow/repair metadata explicitly rather than inferring them from missing context
- `src/graphs/nodes.py`
  - consume the context-service contract for transcript-first context, additive aid selection, and manifest creation
  - persist or hand off the final context manifest for each turn
  - record overflow mode and trigger deterministic compaction/retry behavior without becoming the long-term continuity policy layer
- `src/graphs/assistant_graph.py`
  - keep lifecycle sequencing explicit so ingest, assemble, compact/retry, model execution, and after-turn enqueueing happen in a defined order
  - keep repaired or resumed turns on the gateway-owned runtime path only
- `src/providers/models.py`
  - expose the context-window overflow signal needed to distinguish normal execution failure from compaction-triggered retry

### Governance and Repair Contracts
- `src/policies/service.py`
  - expose governance visibility reads that can operate from normalized state while healthy and remain compatible with transcript-driven rebuild after repair
- `src/capabilities/activation.py` if needed by the existing governance model
  - preserve approval and revocation effects when normalized governance state is rebuilt from transcript-linked artifacts
- worker or service modules introduced by this slice
  - implement idempotent post-commit jobs for summary generation, retrieval indexing, continuity repair, and governance-state rebuild
  - guarantee duplicate `outbox_jobs` delivery does not create conflicting snapshot, manifest, repair, or governance state

### Observability Contracts
- `src/observability/audit.py` or a dedicated continuity module
  - emit structured events for assembly mode, overflow retry, degraded transcript-only operation, summary staleness, replay latency, repair outcomes, and empty-memory retrieval on long sessions
  - expose enough metadata to inspect the latest valid summary snapshot and recent manifests for a session without treating logs as the source of truth

## Risk Areas
- Drift between canonical transcript continuity inputs and any derived lookup state if repository methods accidentally privilege summaries, retrieval indexes, or normalized governance rows over canonical records.
- Silent truncation under context pressure if overflow handling is implemented as ad hoc message dropping rather than deterministic retry plus bounded degraded failure.
- Snapshot version races or dedupe gaps causing multiple workers to claim “latest valid” status inconsistently.
- Governance replay using stale normalized state after approval or revocation changes instead of rebuilding from transcript-linked artifacts.
- Repair workers accidentally mutating canonical transcript or governance history in place instead of performing additive repair only.
- Context manifests becoming log-only or best-effort data even though the spec requires durable inspection per turn.

## Rollback Strategy
- Keep all schema changes additive and preserve the canonical transcript path even if derived continuity tables must be rolled back.
- Fail back to transcript-first assembly when summary, retrieval, or manifest reads fail, and surface bounded degraded failure if the prompt still cannot fit.
- Keep repair and indexing work post-commit and idempotent so workers can be disabled without corrupting canonical continuity state.
- Default to fail-closed governance visibility if rebuild or normalized reads are unavailable; do not widen tool visibility during partial rollback.

## Test Strategy
- Unit:
  - deterministic context assembly manifest generation for the same transcript, tool artifacts, governance artifacts, and derived inputs
  - summary snapshot range selection, latest-valid snapshot selection, and version allocation behavior
  - overflow classification and deterministic compaction/retry sequencing
  - degraded-failure behavior when transcript-first assembly still exceeds the model window with no valid additive aid
  - governance replay and visibility restoration after approval waits and revocations
- Repository or persistence:
  - additive versioned `summary_snapshots`
  - idempotent `outbox_jobs` enqueue and duplicate delivery handling
  - durable `context_manifests` persistence, recent-session lookup, and lookup by triggering `message_id`
  - canonical continuity reads that include Spec 002 assistant/tool artifacts and Spec 003 governance artifacts
- Integration:
  - gateway-owned lifecycle sequencing through `apps/gateway/api/inbound.py`, including user-turn ingest, assemble, compact/retry, and after-turn enqueue boundaries
  - context overflow followed by deterministic compact/retry without loss of reconstructability
  - deletion of summaries, retrieval indexes, manifests, and other derived artifacts followed by replay from canonical continuity inputs alone
  - retrieval or summary outage degrading to transcript-first assembly instead of immediate turn failure
  - long-session hard overflow producing bounded degraded failure plus queued repair rather than silent truncation
  - approval-wait and revocation continuity surviving restart and replay without stale tool visibility
  - crash-window recovery and concurrent inbound turns with no conflicting derived-state results
- Implementation notes:
  - use `uv sync` for environment setup
  - run targeted checks with `uv run pytest tests`

## Constitution Check
- Gateway-first execution preserved: user-visible resume after continuity repair, approval wait, or revocation stays on the gateway-owned runtime path.
- Transcript-first durability preserved: assistant/tool/governance continuity is rebuilt from canonical append-only records, not from summaries or caches.
- Approval and revocation continuity preserved: governance visibility remains fail-closed and rebuildable from persisted governance artifacts.
- Observable, bounded delivery preserved: manifests, structured logs, retry metadata, and degraded-failure paths are explicit parts of the implementation contract.
