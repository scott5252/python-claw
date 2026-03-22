# Spec 004: Context Engine Lifecycle, Continuity, Compaction, and Recovery

## Purpose
Harden continuity so context-window pressure, partial failures, or loss of derived state do not destroy the assistant's ability to reconstruct conversation state from the canonical append-only record.

## Non-Goals
- Remote node execution
- Media delivery
- Presence and auth failover
- New approval or activation semantics beyond replaying already-persisted governance state

## Upstream Dependencies
- Specs 001, 002, and 003

## Scope
- Four-phase context lifecycle: ingest, assemble, compact, after-turn
- Deterministic context assembly from canonical transcript plus approved additive artifacts
- Versioned `summary_snapshots`
- Post-commit idempotent `outbox_jobs` for summaries, retrieval indexes, and continuity repair
- Continuity reconstruction algorithm for sessions with assistant, tool, and governance artifacts
- Recovery and repair services/jobs
- Compaction and retry flow for context overflow
- Persisted inspectable context manifests for debugging and replay analysis

## Data Model Changes
- `summary_snapshots`
  - `id`
  - `session_id`
  - `snapshot_version`
  - `base_message_id`
  - `through_message_id`
  - `source_watermark_message_id`
  - `summary_text`
  - optional `summary_metadata_json`
  - `created_at`
- `outbox_jobs`
  - `id`
  - `session_id`
  - `message_id`
  - `job_kind`
  - `job_dedupe_key`
  - `status` with values `pending`, `running`, `completed`, `failed`
  - optional `attempt_count`
  - optional `available_at`
  - optional `last_error`
  - timestamps for creation and last update
- Optional transcript or retrieval chunk index for older-history retrieval, if implemented as additive lookup state only
- `context_manifests`
  - `id`
  - `session_id`
  - `message_id`
  - `manifest_json`
  - `degraded` flag
  - `created_at`
- Required indexes
  - unique index on `summary_snapshots(session_id, snapshot_version)`
  - lookup index on `summary_snapshots(session_id, through_message_id)`
  - unique index on `outbox_jobs(job_dedupe_key)`
  - lookup index on `outbox_jobs(session_id, status, available_at)`
  - lookup index on `context_manifests(session_id, created_at)`
  - lookup index on `context_manifests(message_id)`

## Contracts
- The canonical continuity record is the append-only transcript plus transcript-linked governance artifacts from Spec 003, plus explicitly named append-only assistant and tool artifacts required to reconstruct prior tool outcomes and outbound intent history.
- For this spec, canonical assistant and tool continuity inputs are:
  - append-only assistant transcript rows in `messages`
  - append-only tool proposal, tool outcome, and outbound intent artifacts from the Spec 002 persistence contract
- Summary snapshots, retrieval indexes, embeddings, caches, context manifests, and `outbox_jobs` are derived artifacts only.
- Context assembly consumes canonical transcript history first and may add the latest valid summary snapshot, retrieval results, and governance visibility state as deterministic derived inputs.
- Summary snapshots are additive, versioned, and range-bounded:
  - each snapshot covers an inclusive transcript range from `base_message_id` through `through_message_id`
  - snapshots never replace or delete transcript history
  - later snapshots may supersede earlier summaries for assembly purposes, but earlier snapshots remain auditable until explicit retention cleanup allowed by policy
- `outbox_jobs` are created only after the canonical transcript transaction commits. No pre-commit summary, retrieval, repair, or indexing side effect may become the source of truth.
- Recovery and repair jobs operate from durable session state and canonical continuity inputs alone. They must not require in-memory graph state from the failed turn.
- Context assembly must produce an inspectable manifest for each turn that identifies:
  - transcript range included directly
  - summary snapshot identifiers used
  - retrieval or chunk identifiers used
  - governance state artifacts included for approval-aware continuity
  - whether compaction or degraded transcript-only fallback was used
- Context manifests must be persisted durably through a bounded-retention store and also emitted to structured logs for debugging and replay analysis.
- When retrieval, memory, or summary loading fails, the runtime must continue with transcript-first assembly rather than failing the entire user turn, unless the canonical transcript itself is unavailable.
- Compaction retry must be deterministic:
  - first attempt uses normal assembly
  - overflow handling records the failure mode
  - retry assembly reduces prompt size through additive summary use and older-history elision without dropping the ability to reconstruct continuity from durable state
- If transcript-first assembly still exceeds the model context window and no valid summary snapshot or retrieval aid is available, the runtime may return a bounded degraded failure for the turn and enqueue repair work; it must not silently truncate canonical continuity state with an undefined rule.
- Governance-aware continuity uses Spec 003 dual durability:
  - normalized governance tables may be used for runtime reads and enforcement while healthy
  - transcript-linked governance artifacts are the canonical rebuild source after loss, drift, restart, or repair
  - repair flows must be able to rebuild normalized governance state from transcript-linked governance artifacts
- Repair flows may enqueue or execute post-commit workers, but control-plane clients, adapters, schedulers, and workers may not bypass gateway-owned session and transcript contracts when resuming user-visible turns.

## Runtime Invariants
- No durable context is destroyed during compaction.
- Context assembly is deterministic and inspectable for the same session state, transcript history, governance artifacts, and derived inputs.
- Retrieval or summary failure does not block transcript-first assembly; if the resulting prompt still cannot fit, the runtime fails in a bounded, inspectable way and enqueues repair rather than silently truncating continuity state.
- Replaying canonical continuity inputs can rebuild continuity after derived-artifact loss.
- `outbox_jobs` workers never mutate prior canonical transcript or governance artifacts in place.
- Duplicate `outbox_jobs` delivery does not create conflicting summary or repair state.
- Gateway-owned runtime invocation remains the only path that resumes a user-visible turn after continuity repair or approval wait recovery.

## Security Constraints
- `outbox_jobs` workers must not mutate canonical transcript history or governance artifacts.
- Recovery jobs must be idempotent, traceable, and bounded to additive repairs.
- Context assembly must preserve approval and revocation effects from Spec 003; replay may restore visibility state only from persisted governance records, never from stale cached bindings.
- Compaction must fail closed with respect to privileged capability visibility: omitted governance state may not be inferred or widened during retry.

## Operational Considerations
- Need repair jobs for missing summaries, failed `outbox_jobs`, and stale continuity gaps after crash recovery.
- Need metrics and structured logs for compaction failures, replay latency, summary staleness, degraded transcript-only invocations, empty-memory retrieval on long sessions, and repair-job outcomes.
- Need operational inspection of the latest valid summary snapshot and bounded recent context manifests for a session.
- Context manifest retention may be bounded by count, age, or both, but the latest manifest for a session and manifest lookup by triggering `message_id` must remain available within the configured retention window.
- If retrieval chunk indexes are implemented, they must be rebuildable from canonical transcript state and treated as disposable lookup acceleration only.

## Acceptance Criteria
- Graph can compact and retry after context overflow without losing the ability to reconstruct continuity from canonical records.
- Recovery works after deleting summary snapshots, retrieval indexes, context manifests, and other derived artifacts, as long as canonical continuity inputs remain intact.
- Duplicate `outbox_jobs` delivery does not duplicate summary or repair state.
- Latest valid summary snapshot can be retrieved and inspected with its covered transcript range and source watermark.
- Context assembly exposes a persisted inspectable manifest showing which transcript ranges, summaries, retrieval artifacts, assistant/tool continuity artifacts, and governance artifacts were used.
- Retrieval or summary outage degrades to transcript-first assembly rather than failing the turn when canonical transcript storage is healthy, unless transcript-first assembly still exceeds the model window and triggers bounded degraded failure plus repair.
- Replay after an approval wait or revocation rebuilds continuity from persisted governance artifacts without reusing stale in-memory policy state.

## Test Expectations
- Failure-mode tests for crash points, duplicate `outbox_jobs` delivery, concurrent inbound turns, retrieval outage, replay, and compaction/retry
- Unit tests for deterministic context assembly manifests and summary range selection
- Repository or contract tests for additive versioned `summary_snapshots` and idempotent `outbox_jobs`
- Integration tests proving canonical continuity replay rebuilds continuity after deleting derived artifacts
- Integration tests proving revocation and approval-wait continuity survive restart and replay without stale tool visibility
