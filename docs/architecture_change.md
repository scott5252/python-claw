# Architecture Change: Approval Continuation Fix

## Problem

When a child agent paused for human approval (e.g., before executing a destructive deployment), the system correctly queued the approval prompt and waited. But after the user approved and the child agent completed its work, the parent agent never received the final result. The conversation stalled permanently.

### Root Cause: Trigger Deduplication Collision

The `create_or_get_execution_run` method in `JobsRepository` deduplicates execution runs by `(trigger_kind, trigger_ref)`. For delegation results, both possible parent runs used:

```
trigger_kind = "delegation_result"
trigger_ref  = delegation.id
```

This pair is unique-constrained. Here is what happened in the broken lifecycle:

1. **Child run completes (paused state)** → `handle_child_run_completed` called → `delegation.status = COMPLETED` → parent result run created with `("delegation_result", delegation.id)`
2. **User approves** → continuation child run queued → delegation requeued
3. **Continuation run completes (final state)** → `handle_child_run_completed` called again → attempts to create parent result run with `("delegation_result", delegation.id)` → **deduplication returns the already-finished run from step 1** → no new run is queued → parent never processes the actual result

The approval step created an illusion of progress while silently discarding the final result.

---

## Fix

The fix separates the two conceptually different events into two distinct trigger kinds, eliminating any possibility of deduplication collision.

### New Delegation Lifecycle

```
QUEUED → RUNNING → AWAITING_APPROVAL → QUEUED → RUNNING → COMPLETED
```

The key insight: a child run pausing for approval is **not** a completion. It is a pause. The delegation must not be marked `COMPLETED` until the child actually finishes its work.

### Changes

#### 1. `src/db/models.py` — New `DelegationStatus` value

Added `AWAITING_APPROVAL = "awaiting_approval"` to the `DelegationStatus` enum.

```python
class DelegationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"   # NEW
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

#### 2. `src/delegations/repository.py` — New method and updated active counts

Added `mark_awaiting_approval()` to transition the delegation to the pause state:

```python
def mark_awaiting_approval(self, db, *, delegation_id, awaiting_at=None):
    record.status = DelegationStatus.AWAITING_APPROVAL.value
    record.updated_at = awaiting_at or utc_now()
```

Updated `count_active_for_parent_run` and `count_active_for_parent_session` to include `AWAITING_APPROVAL` in their active-status checks. A delegation paused for approval is still active — it is not done.

#### 3. `src/delegations/service.py` — New `handle_child_run_paused_for_approval` method

When a child run completes with `state.awaiting_approval = True`, this new method is called instead of `handle_child_run_completed`. It:

1. Fetches the delegation for the child run
2. Fetches pending approval items from the child session
3. Creates a **notification message** in the parent session describing the paused state
4. Queues a parent run with `trigger_kind="delegation_approval_prompt"` and `trigger_ref="{delegation_id}:{child_run_id}"` — this is unique per pause event and does not collide with the eventual result run
5. Marks the delegation `AWAITING_APPROVAL`
6. Appends a delegation event recording the pause

The `handle_child_run_completed` method is unchanged. It is now called **only once** — when the child agent actually finishes all its work.

#### 4. `src/jobs/service.py` — Routing based on `state.awaiting_approval`

The worker's post-run handler now routes on the `awaiting_approval` flag from `AssistantState`:

```python
if self.delegation_service is not None and run.trigger_kind == "delegation_child":
    if state.awaiting_approval:
        self.delegation_service.handle_child_run_paused_for_approval(db, child_run_id=run.id)
    else:
        self.delegation_service.handle_child_run_completed(db, child_run_id=run.id)
```

#### 5. `src/observability/diagnostics.py` — Diagnostics support for new trigger kind

Added a handler for `delegation_approval_prompt` in the run detail diagnostic so the delegation can be looked up and correlated when inspecting runs with this trigger kind.

---

## Why This Works

After the fix, the two parent runs that get created during a full approval lifecycle use **different trigger kinds**:

| Event | `trigger_kind` | `trigger_ref` |
|-------|---------------|---------------|
| Child pauses for approval | `delegation_approval_prompt` | `{delegation_id}:{child_run_id}` |
| Child completes final work | `delegation_result` | `{delegation_id}` |

These are different keys. The deduplication constraint is never hit. The parent agent receives the approval notification, displays the pending approvals to the user, and later (after approval and child completion) receives the final result in a separate run and resumes normally.

---

## Test Coverage

`tests/test_approval_continuation.py` contains three tests covering the new lifecycle:

1. **`test_paused_for_approval_marks_delegation_awaiting_and_queues_notification`** — Verifies that calling `handle_child_run_paused_for_approval` transitions the delegation to `AWAITING_APPROVAL` and creates a parent notification run with `trigger_kind="delegation_approval_prompt"`.

2. **`test_awaiting_approval_delegation_counts_as_active`** — Verifies that a delegation in `AWAITING_APPROVAL` state is counted by both `count_active_for_parent_run` and `count_active_for_parent_session`, ensuring downstream logic that guards against over-delegation sees the paused delegation as still active.

3. **`test_approval_continuation_completes_without_deduplication_collision`** — End-to-end five-phase lifecycle test:
   - Phase 1: Setup — parent session, child session, delegation
   - Phase 2: Child pauses — `handle_child_run_paused_for_approval` called, delegation enters `AWAITING_APPROVAL`, notification run created
   - Phase 3: Approval — delegation requeued with new child run IDs
   - Phase 4: Child completes — `handle_child_run_completed` called (first and only time), delegation enters `COMPLETED`, result run created with `trigger_kind="delegation_result"`
   - Phase 5: Verification — notification run and result run exist with distinct IDs and distinct trigger kinds; no deduplication collision
