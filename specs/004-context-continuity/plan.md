# Plan 004: Context Engine Lifecycle, Continuity, Compaction, and Recovery

## Target Modules
- `src/context/engine.py`
- `src/context/service.py`
- `src/context/legacy_engine.py`
- `src/context/compaction.py`
- `src/sessions/repository.py`
- `src/memory/service.py`
- `src/db/models_continuity.py`
- `src/graphs/nodes.py`
- `src/domain/errors.py`
- `tests/`

## Migration Order
1. Create `summary_snapshots`
2. Create `outbox_jobs`
3. Add indexes for session/version lookup and dedupe keys
4. Add optional retrieval metadata tables only if required for this slice

## Implementation Shape
- Wire `ingest -> assemble -> compact -> after_turn` into the runtime explicitly.
- Replace trim-only compaction with snapshot creation over transcript ranges.
- Add repository methods for latest snapshot, snapshot listing, transcript ranges, and snapshot creation.
- Treat memory extraction and indexing as outbox-driven post-commit jobs.
- Implement the reconstruction order as code, not prose.

## Risk Areas
- Foreign-key mismatches between session models and continuity models
- Running after-turn work before transcript commit
- Silent message dropping under token pressure

## Rollback Strategy
- Keep transcript path functional if derived-state tables are rolled back.
- Degrade to transcript + recent history if continuity artifacts are unavailable.

## Test Strategy
- Unit: assembly ordering, compaction range selection, repository summary methods
- Integration: context overflow retry, replay after derived-state deletion, crash-window recovery
