# Python Claw Constitution

## Core Principles

### I. Gateway-First Execution
All inbound work enters through the gateway boundary. Channel adapters, schedulers, workers, and control-plane clients may submit events to the gateway, but they may not invoke the graph runtime directly. Routing, idempotency, session lifecycle, approval enforcement, and audit correlation belong to the gateway path.

### II. Transcript-First Durability
The append-only transcript store is the canonical record of conversational state. Sessions must be resumable through deterministic identity rules. Summaries, memory rows, embeddings, indexes, and retrieval caches are derived artifacts that must be rebuildable from durable transcript history.

### III. Approval Before Activation
Agents may propose tools, scripts, workflows, jobs, and integrations, but they may not activate or execute privileged capabilities without explicit approval tied to the exact artifact version and action parameters. Normal automation uses typed actions. Raw shell and remote execution are exceptional, fail-closed, policy-gated, approval-gated, and fully audited.

### IV. Versioned Continuity
Context compaction must be additive and versioned. The system may reduce prompt size, but it may not destroy the ability to reconstruct continuity. Summary snapshots never replace transcript history. Derived-state jobs run only after transcript commit and must be idempotent.

### V. Observable, Bounded Delivery
Every feature must preserve service boundaries between gateway, graph runtime, context, memory, tools, scheduler, policy, and node execution. Critical flows must emit structured logs, traces, metrics, and audit events. Specs must remain bounded vertical slices with executable acceptance criteria, explicit invariants, operational considerations, and test expectations.

## Architecture Constraints

- Python 3.11+ is required.
- FastAPI is the gateway surface.
- PostgreSQL is the source of truth for sessions, messages, approvals, jobs, and derived-state bookkeeping.
- Redis may be used for locks, idempotency windows, rate limiting, and ephemeral caches, but not as transcript truth.
- LangGraph owns orchestration. LangChain abstractions may be used for models, tools, and retrievers.
- Deterministic session identity and resumability are mandatory.
- Failure-mode-first design is required for context continuity, including replay and recovery paths.
- Policy boundaries must exist before tool binding and before execution.
- Privileged capabilities must fail closed.

## Delivery Workflow

- Work proceeds through bounded specs under `specs/` in dependency order.
- Each `spec.md` must define purpose, non-goals, dependencies, data-model changes, contracts, invariants, security constraints, operational considerations, acceptance criteria, and explicit test expectations.
- Each `plan.md` must name exact files or modules to change, migration order, risk areas, rollback strategy where appropriate, and unit/integration test strategy.
- Each `tasks.md` must be dependency-aware, avoid placeholder cleanup items, and place high-risk tests before high-risk implementation.
- No spec may silently collapse service boundaries established by an earlier spec. Later specs may extend contracts, not erase them.
- Placeholder scaffolds must be marked clearly as stub-only or sample-only.

## Governance

This constitution overrides local convenience when the two conflict. Plans, tasks, and implementations must explicitly verify compliance with these principles. Amendments require a documented reason, a migration path for affected specs, and an update to all impacted acceptance criteria.

**Version**: 1.0.0 | **Ratified**: 2026-03-22 | **Last Amended**: 2026-03-22
