# Tasks 004: Context Engine Lifecycle, Continuity, Compaction, and Recovery

1. Create migrations for `summary_snapshots` and `outbox_jobs`.
2. Write repository tests for snapshot creation, latest snapshot lookup, and transcript-range reads.
3. Write failure-mode tests for transcript-only recovery and duplicate outbox delivery.
4. Implement context engine interfaces and wire the full lifecycle into runtime execution.
5. Replace trim-only compaction with versioned summary snapshot compaction.
6. Implement outbox-driven post-commit memory extraction and indexing hooks.
7. Implement continuity reconstruction order and compaction/retry handling for context overflow.
8. Add recovery and repair jobs for failed or missing derived artifacts.
9. Add integration tests for crash windows, retrieval outage fallback, and concurrent session turns.
