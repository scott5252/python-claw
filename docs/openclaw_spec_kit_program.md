# OpenClaw-Style Python Alternative — Spec-Kit Program Document

## Purpose

This document converts the architecture review into a **spec-kit execution program** for building an OpenClaw-style system in Python with **FastAPI**, **LangGraph**, **PostgreSQL**, **Redis**, and optional remote node runners.

It is designed for a **multi-spec** workflow rather than a single oversized feature spec. That matches spec-kit’s current constitution → specify → clarify → plan → tasks workflow and keeps each deliverable independently implementable.

## How to Use This Document

1. Start in the project root of the repository you want spec-kit to drive.
2. Run the constitution prompt first.
3. Then execute the specs in dependency order.
4. For each spec, run the phases in this order:
   - `/speckit.specify`
   - `/speckit.clarify`
   - `/speckit.plan`
   - `/speckit.tasks`
5. Implement one spec at a time before opening the next dependent spec.
6. Do not merge later-spec concerns into earlier specs unless the prompt explicitly calls for shared contracts or migrations.

## Program-Level Rules

These rules apply to every spec in this program:

- The gateway is the only execution entrypoint for inbound messages, scheduled jobs, and channel traffic.
- The transcript store is canonical and append-only.
- Memory, summaries, embeddings, and indexes are derived and rebuildable.
- The system must remain useful when semantic retrieval or summary generation fails.
- No tool, script, workflow, or persisted resource may become active without explicit approval.
- Typed actions are preferred over raw shell execution.
- Sensitive execution must be policy-gated, approval-gated, and audited.
- Each spec must be independently testable.
- Each plan must identify the exact files/modules to change.
- Each task list must contain executable acceptance work, not placeholder cleanup tasks.

## Delivery Order

1. Spec 0 — Constitution
2. Spec 1 — Gateway, routing, sessions, and transcript foundation
3. Spec 2 — LangGraph runtime and typed tool registry
4. Spec 3 — User-controlled capability governance
5. Spec 4 — Context continuity, compaction, and recovery
6. Spec 5 — Async execution, scheduler re-entry, and concurrency lanes
7. Spec 6 — Remote node execution and sandbox isolation
8. Spec 7 — Channels, streaming, chunking, and media pipeline
9. Spec 8 — Observability, auth failover, presence, and operational hardening

---

## Spec 0 — Constitution

### Prompt Block: `/speckit.constitution`

```text
Create a constitution for a Python implementation of an OpenClaw-style gateway using FastAPI, LangGraph, PostgreSQL, Redis, and optional remote node runners.

The constitution must enforce these non-negotiable rules:
- gateway-first execution; no channel adapter may invoke the graph directly
- transcript is canonical and append-only
- memory, summaries, embeddings, and indexes are derived and rebuildable
- no tool, script, workflow, schedule, or resource can become active without explicit user approval
- typed actions are preferred over raw shell execution
- shell and remote execution are gated by policy, approval, and audit
- context compaction must be versioned and non-destructive
- derived-state jobs must be post-commit and idempotent
- the system must be observable with structured logging, traces, metrics, and audit records
- specs must preserve service boundaries between gateway, graph runtime, context, memory, tools, scheduler, and node execution
- every spec must define acceptance criteria, runtime invariants, test expectations, and operational considerations
- plans must identify exact modules/files to change and note migration order
- tasks must be dependency-aware and must place high-risk tests before high-risk implementation

Also require the constitution to preserve these engineering principles:
- deterministic session identity and resumability
- failure-mode-first design for context continuity
- explicit policy boundaries before tool binding and before execution
- fail-closed behavior for privileged capabilities
- feature slices must be independently implementable and verifiable
```

### Expected Output Notes

The constitution should become the project-wide guardrail for all later specs. It should be opinionated enough to reject plans that collapse service boundaries or allow unapproved code execution.

---

## Spec 1 — Gateway, Routing, Sessions, and Transcript Foundation

### Objective

Establish the core transport and persistence layer. Nothing else should proceed until inbound message handling, routing, session identity, and append-only transcript durability exist.

### Prompt Block: `/speckit.specify`

```text
Create a feature spec for the gateway/session/transcript foundation of an OpenClaw-style Python system.

Scope:
- FastAPI gateway as the only entrypoint
- inbound message contract
- routing service
- deterministic session-key strategy
- direct-message main-session behavior and group/per-channel session rules
- durable sessions and append-only transcript storage in PostgreSQL
- idempotent inbound handling using external message ids
- basic transcript retrieval and admin/history surface

Non-goals:
- memory extraction
- remote execution
- media pipeline
- multi-agent delegation
- scheduler execution

Required invariants:
- duplicate inbound deliveries do not create duplicate transcript turns
- the same routing inputs always resolve to the same session identity
- direct chat continuity can resume through a stable main-session mapping
- transcripts are append-only and prior assistant messages are never mutated in place

Acceptance criteria must prove duplicate delivery protection, deterministic session reuse, and transcript durability across process restarts.
```

### Prompt Block: `/speckit.clarify`

```text
Clarify the gateway/session/transcript spec with a focus on routing and persistence edge cases.

Resolve and document:
- exact session-key composition rules for direct messages, groups, and per-channel peers
- when a direct conversation maps to a literal main session vs a scoped session
- how external_message_id deduplication is stored and expired
- whether transcript retrieval is cursor-based, time-based, or count-based
- how channel account id, peer id, and group id interact in routing
- which admin/history APIs are read-only in this spec
- which tables and indexes are required now vs deferred to later specs

Do not add memory, tool, or scheduler behavior to this spec.
```

### Prompt Block: `/speckit.plan`

```text
Create the technical implementation plan for the gateway/session/transcript foundation.

Technology and architecture constraints:
- Python 3.11+
- FastAPI gateway
- SQLAlchemy + PostgreSQL
- Redis allowed for dedupe/locks but transcript and session truth must be in PostgreSQL
- all inbound flows must pass through the gateway boundary
- no graph invocation from channel adapters

The plan must include:
- target modules and files to create or change
- exact SQLAlchemy models and migration sequence
- routing service contract
- session repository/service contract
- idempotency guard design
- API contracts for inbound and transcript readback
- unit and integration test strategy
- rollback strategy for schema changes

Mark any synchronous request-path execution as scaffold-only if present.
```

### Prompt Block: `/speckit.tasks`

```text
Break the gateway/session/transcript implementation plan into dependency-aware tasks.

Requirements:
- create schema and migrations before runtime code
- create repository/service tests before or alongside implementation for the highest-risk invariants
- include explicit tasks for idempotency, routing determinism, and transcript append-only behavior
- include API tests for duplicate delivery handling and session reuse
- include docs/update tasks only after code and tests exist
- do not include generic cleanup tasks

The task list must be executable by a coding agent in order.
```

---

## Spec 2 — LangGraph Runtime and Typed Tool Registry

### Objective

Add orchestration without weakening transport boundaries. The graph should consume persisted context and a constrained tool surface, not replace gateway concerns.

### Prompt Block: `/speckit.specify`

```text
Create a feature spec for the LangGraph runtime and typed tool registry.

Scope:
- AssistantState definition
- graph assembly and invocation for one user turn
- runtime dependency injection for repositories/services
- runtime context injection for tools
- policy-aware tool exposure
- outbound message tool
- one safe local example tool
- tool audit logging hooks

Required invariants:
- transport logic stays outside the graph
- tools are exposed through a registry/factory contract, not ad hoc inline wiring
- tool outcomes are never fabricated
- the graph can run without remote execution support

Non-goals:
- capability approvals for tool/resource activation
- remote node execution
- context compaction and recovery jobs

Acceptance criteria must prove tool binding is contextual, graph state is deterministic, and transport concerns remain outside orchestration.
```

### Prompt Block: `/speckit.clarify`

```text
Clarify the LangGraph runtime and tool registry spec.

Resolve and document:
- exact AssistantState fields required now vs deferred
- where dependencies are injected and how test doubles are provided
- whether ToolNode is sufficient or whether a custom execution node is needed now
- the registry contract for policy-aware tool visibility
- how tool calls/results are recorded in transcript or audit storage
- which safe local tool is included in this spec and why
- how outbound replies are represented without leaking channel-specific logic into the graph

Do not add privileged execution or approval workflows in this spec.
```

### Prompt Block: `/speckit.plan`

```text
Create the technical implementation plan for the LangGraph runtime and typed tool registry.

Constraints:
- LangGraph for orchestration
- LangChain tool abstractions are allowed
- graph code must remain separate from gateway transport code
- repositories/services must be injectable for tests
- any registry design must support policy-driven exposure later

The plan must cover:
- graph state module
- node modules
- graph factory/assembly
- tool runtime context object
- registry and factory design
- audit/event capture points
- tests for graph routing after tool calls and tool exposure rules

Identify exact files to create/change and note any placeholders that are intentionally scaffold-level.
```

### Prompt Block: `/speckit.tasks`

```text
Break the LangGraph runtime and typed tool registry plan into dependency-aware tasks.

Requirements:
- add graph state and tool context contracts first
- implement registry/factory before graph tool-binding logic
- include tests for contextual tool exposure, successful tool execution, and non-fabricated tool outcomes
- include tests proving channel adapters are not part of the graph runtime
- include transcript/audit persistence tasks only where required by this spec

Do not include approval lifecycle or remote execution tasks.
```

---

## Spec 3 — User-Controlled Capability Governance

### Objective

Ensure the system can propose capabilities without activating them. Approval, activation, and execution must be distinct control-plane stages.

### Prompt Block: `/speckit.specify`

```text
Create a feature spec for user-controlled capability governance.

Scope:
- proposal/approval/activation lifecycle for tools and persisted resources
- approval queue and approval states
- typed action catalog for normal operations
- blocked-by-default policy for raw shell execution and resource activation
- provenance, versioning, and audit requirements
- approval subgraph or equivalent gated runtime flow
- activation controller and execution policy boundary

Required invariants:
- unapproved tools, scripts, jobs, workflows, or integrations cannot become active
- content changes invalidate prior approvals unless explicitly inherited by policy
- the graph may propose but may not self-activate privileged resources
- raw shell execution is treated as privileged and exceptional

Acceptance criteria must make it impossible for an unapproved artifact version to become active.
```

### Prompt Block: `/speckit.clarify`

```text
Clarify the capability governance spec.

Resolve and document:
- the exact lifecycle states and allowed transitions
- what is governed in this spec: tools, jobs, workflows, scripts, prompt bundles, integrations
- how approval scope is represented and what can expire
- whether approval packets are stored separately from resource proposals and versions
- how policy classification occurs before tool binding and before execution
- the minimum typed action catalog needed now vs deferred
- how rejected, expired, and revoked decisions affect runtime availability

Do not implement remote node transport details in this spec.
```

### Prompt Block: `/speckit.plan`

```text
Create the technical implementation plan for capability governance.

Constraints:
- policy must classify requests before sensitive tool binding
- resource proposals, versions, approvals, and active bindings must be durable
- activation must be separated from proposal creation
- privileged execution must fail closed when approval or policy evidence is missing

The plan must include:
- schema and migration order for proposal/version/approval/active-resource tables
- service boundaries for policy, approval queue, activation controller, and execution policy enforcer
- graph/runtime insertion points
- audit model
- tests for blocked activation, expired approvals, and version mismatch handling
```

### Prompt Block: `/speckit.tasks`

```text
Break the capability governance plan into dependency-aware tasks.

Requirements:
- schema and model tasks first
- policy classification contracts before runtime integration
- explicit tasks for activation guards and fail-closed execution checks
- tests before or alongside high-risk implementation for unapproved activation attempts, approval expiry, and content-hash mismatch
- no placeholder task that simply says 'add security'
```

---

## Spec 4 — Context Continuity, Compaction, and Recovery

### Objective

Make continuity resilient to context-window limits and partial post-turn failures, while preserving transcript-first truth.

### Prompt Block: `/speckit.specify`

```text
Create a feature spec for context continuity, compaction, and recovery.

Scope:
- four-phase context engine lifecycle: ingest, assemble, compact, after_turn
- summary_snapshots and outbox_jobs
- post-commit idempotent memory extraction
- continuity reconstruction order
- transcript-first fallback behavior
- recovery and repair jobs
- compaction and retry on context overflow
- deterministic explainability of why context artifacts were included

Required invariants:
- transcript storage is canonical and append-only
- summaries, memory rows, embeddings, and vector indexes are derived state
- compaction is non-destructive and versioned
- the system can still answer from transcript + summary fallback if semantic retrieval fails
- post-turn derived-state jobs are idempotent and replay-safe

Acceptance criteria must include failure-mode tests proving transcript-only recovery and recovery from failed summary/memory jobs.
```

### Prompt Block: `/speckit.clarify`

```text
Clarify the context continuity spec.

Resolve and document:
- exact triggers for compaction
- summary snapshot schema and versioning rules
- outbox job schema and dedupe rules
- continuity reconstruction order when some artifacts are stale or missing
- what metadata explains why a memory row or summary was included in a prompt
- how context-overflow retries are bounded
- which retrieval paths are required now vs optional later

Do not add channel/media behavior in this spec.
```

### Prompt Block: `/speckit.plan`

```text
Create the technical implementation plan for context continuity, compaction, and recovery.

Constraints:
- transcript remains canonical
- after_turn jobs must run only after assistant response commit succeeds
- all derived-state processing must be replay-safe and idempotent
- context assembly must be inspectable and deterministic

The plan must include:
- schema changes for summary snapshots, outbox jobs, and any continuity metadata
- context service contracts for ingest/assemble/compact/after_turn
- memory extraction interfaces and fallback behavior
- retry/error classification for overflow and post-turn failures
- background worker responsibilities
- tests for transcript-only recovery, compaction safety, and after-turn replay

Call out any repository or API methods that earlier scaffolds referenced but did not yet define.
```

### Prompt Block: `/speckit.tasks`

```text
Break the context continuity plan into dependency-aware tasks.

Requirements:
- add schema and contracts before worker implementation
- include tests for canonical transcript reconstruction, snapshot versioning, and post-commit outbox idempotency
- include bounded retry behavior for context overflow
- include recovery tasks that repair missing derived artifacts from transcript history
- no task may assume semantic retrieval is always available
```

---

## Spec 5 — Async Execution, Scheduler Re-entry, and Concurrency Lanes

### Objective

Move runtime execution off the synchronous inbound path and ensure scheduled work uses the same gateway-owned control path.

### Prompt Block: `/speckit.specify`

```text
Create a feature spec for async execution, scheduler integration, and concurrency lanes.

Scope:
- accept/queue/execute response pattern
- background graph execution
- session-lane locking
- global concurrency cap
- duplicate-work prevention
- retry policy integration for queued runs
- scheduler events that re-enter through the gateway
- run status model and stuck-run handling

Required invariants:
- long graph runs do not block inbound request workers
- work for the same session/lane is serialized according to policy
- scheduled jobs do not bypass gateway routing, policy, or audit
- duplicate enqueue attempts do not create duplicate work

Acceptance criteria must prove queue-based execution, lane serialization, and scheduler re-entry through the same core path as user traffic.
```

### Prompt Block: `/speckit.clarify`

```text
Clarify the async execution and scheduler spec.

Resolve and document:
- queue substrate assumptions for this project phase
- lane identity rules and whether lanes are per-session, per-agent, or configurable
- how run state is stored and surfaced
- retry classifications for transient vs permanent failures
- how scheduler-originated events identify session scope and actor identity
- whether gateway returns accepted/run_id or a richer status envelope

Do not add remote execution details in this spec.
```

### Prompt Block: `/speckit.plan`

```text
Create the technical implementation plan for async execution, scheduler re-entry, and concurrency lanes.

Constraints:
- the inbound API must move toward accepted/queued execution rather than inline graph execution
- scheduler work must re-enter through gateway-owned contracts
- queue processing must survive process restarts in the chosen design

The plan must include:
- queue/run model
- locking strategy
- scheduler service boundaries
- migration or state additions for runs/jobs
- retry/backoff behavior
- tests for duplicate prevention, lane serialization, and stuck-run recovery

Explicitly mark any earlier inline execution path as baseline scaffold only.
```

### Prompt Block: `/speckit.tasks`

```text
Break the async execution and scheduler plan into dependency-aware tasks.

Requirements:
- create run/job schema and contracts before worker integration
- include tests for accepted/queued behavior, lane locking, duplicate prevention, and scheduler re-entry
- include operational tasks for stuck-run detection and safe retries
- do not add media or remote-node tasks here
```

---

## Spec 6 — Remote Node Execution and Sandbox Isolation

### Objective

Add controlled remote execution without weakening policy or approval guarantees.

### Prompt Block: `/speckit.specify`

```text
Create a feature spec for remote node execution and per-agent sandbox isolation.

Scope:
- node-runner service
- signed gateway-to-node requests
- per-agent sandbox modes
- allowlists and denial behavior
- execution audit logging
- approval requirements for privileged actions
- failure handling for unavailable or unauthorized nodes

Required invariants:
- unauthorized or unsigned execution requests fail closed
- unapproved privileged actions cannot run
- sandbox selection is explicit and auditable
- gateway policy and node-side enforcement both exist

Acceptance criteria must prove signed request validation, deny-by-default execution, and auditable privileged-action handling.
```

### Prompt Block: `/speckit.clarify`

```text
Clarify the remote node execution and sandbox isolation spec.

Resolve and document:
- minimum request/response contract between gateway and node runner
- what is signed and how replay protection is handled
- sandbox mode taxonomy required now vs later
- where allowlists are stored and enforced
- what execution metadata is written to audit logs
- how node health/unavailability is surfaced to operators and to the user

Do not add general channel/media concerns in this spec.
```

### Prompt Block: `/speckit.plan`

```text
Create the technical implementation plan for remote node execution and sandbox isolation.

Constraints:
- gateway and node runner are separate services
- approvals and policies must be checked before dispatch and again at execution time where relevant
- raw shell execution is privileged and exceptional
- the design must support fail-closed behavior

The plan must include:
- service/module boundaries
- signed request design
- sandbox selection and enforcement path
- audit schema or event design
- tests for unsigned requests, stale signatures, denied commands, and unavailable nodes
```

### Prompt Block: `/speckit.tasks`

```text
Break the remote node execution and sandbox isolation plan into dependency-aware tasks.

Requirements:
- define contracts and signature validation before execution handlers
- include tests for deny-by-default behavior, replay protection, and approval enforcement
- include node health/error handling tasks
- do not mix unrelated scheduler or media work into this task list
```

---

## Spec 7 — Channels, Streaming, Chunking, and Media Pipeline

### Objective

Expand transport features while keeping adapters transport-specific and orchestration centralized.

### Prompt Block: `/speckit.specify`

```text
Create a feature spec for channels, streaming, chunking, and media handling.

Scope:
- outbound dispatcher
- block chunking for long responses
- reply directive parsing
- inbound attachment normalization
- media-safe storage path and metadata model
- transport-specific adapter boundaries for supported channels

Required invariants:
- channel adapters remain transport-specific and do not own orchestration logic
- outbound chunking is deterministic and channel-aware
- attachment normalization preserves source metadata and storage safety requirements
- reply directives do not bypass gateway policy boundaries

Acceptance criteria must prove adapter boundary discipline, chunking correctness, and normalized media ingestion.
```

### Prompt Block: `/speckit.clarify`

```text
Clarify the channels, streaming, chunking, and media spec.

Resolve and document:
- which channels are included now vs deferred
- canonical attachment metadata contract
- how long responses are chunked and reassembled per transport
- which reply directives are supported in this phase
- storage and retention assumptions for media artifacts
- whether streaming is true incremental transport streaming or chunked message dispatch only

Do not move graph orchestration into channel adapters.
```

### Prompt Block: `/speckit.plan`

```text
Create the technical implementation plan for channels, streaming, chunking, and media handling.

Constraints:
- gateway remains the single orchestration entrypoint
- adapters translate transport details only
- storage paths and attachment metadata must be safe and auditable

The plan must include:
- adapter contracts
- outbound dispatcher design
- chunking utility/module design
- media normalization and storage components
- tests for chunking, attachment normalization, and adapter boundary enforcement
```

### Prompt Block: `/speckit.tasks`

```text
Break the channels, streaming, chunking, and media plan into dependency-aware tasks.

Requirements:
- add canonical contracts first
- implement shared dispatcher/chunking behavior before transport-specific adapters that depend on it
- include tests for deterministic chunking and media normalization
- include adapter conformance tests proving they do not invoke graph runtime directly
```

---

## Spec 8 — Observability, Auth Failover, Presence, and Operational Hardening

### Objective

Make the system operable and diagnosable without direct database inspection or ad hoc shell access.

### Prompt Block: `/speckit.specify`

```text
Create a feature spec for observability, auth failover, presence, and operational hardening.

Scope:
- structured logs and trace propagation
- metrics for runs, queueing, retries, and recovery paths
- presence endpoint and/or websocket presence events
- multi-auth profile rotation and failover
- admin diagnostics for sessions, jobs, approvals, and stuck runs
- alertable failure conditions for continuity and execution systems

Required invariants:
- operator-visible failures are diagnosable without direct database inspection
- auth/profile failover behavior is explicit and observable
- trace identifiers propagate across gateway, workers, and node execution boundaries where applicable
- diagnostics remain read-only unless a later spec explicitly authorizes mutations

Acceptance criteria must prove traceability, diagnostics coverage, and observable auth failover behavior.
```

### Prompt Block: `/speckit.clarify`

```text
Clarify the observability, auth failover, presence, and hardening spec.

Resolve and document:
- minimum structured log fields
- required metric families and labels
- how presence is computed and exposed
- auth profile rotation order and fallback rules
- which admin diagnostics are mandatory in this phase
- what stuck-run and continuity failures must alert operators

Do not broaden the scope into new execution capabilities.
```

### Prompt Block: `/speckit.plan`

```text
Create the technical implementation plan for observability, auth failover, presence, and operational hardening.

Constraints:
- observability must cover gateway, background workers, and remote execution paths where implemented
- diagnostics should expose system health without requiring direct data-store inspection
- auth failover logic must be explicit, bounded, and testable

The plan must include:
- logging/tracing module boundaries
- metrics emission points
- presence model and endpoint/event design
- auth profile rotation logic
- admin diagnostics endpoints or services
- tests for trace propagation, failover behavior, and stuck-run visibility
```

### Prompt Block: `/speckit.tasks`

```text
Break the observability, auth failover, presence, and hardening plan into dependency-aware tasks.

Requirements:
- shared telemetry contracts before broad instrumentation
- include tests for trace propagation, auth failover, diagnostics visibility, and stuck-run reporting
- include documentation tasks for operator runbooks only after code and tests exist
- do not add unrelated feature work in this final hardening spec
```

---

## Cross-Spec Guardrails

Use these checks during every clarify, plan, and tasks phase:

### Required architecture checks

- Does the spec preserve gateway-first execution?
- Does the spec keep transcript truth separate from derived memory/summary state?
- Does the spec avoid allowing the graph to self-activate privileged capabilities?
- Are service boundaries still explicit?
- Are any migrations introduced in the earliest spec that needs them?
- Are acceptance criteria executable and testable?

### Required code-accuracy checks

- Session foreign keys must consistently reference `sessions.session_id` if that remains the primary key.
- Repository methods referenced by graph code must exist in the owning spec before implementation is considered complete.
- Any inline request-path graph execution must be labeled scaffold-only once async execution is introduced.
- Direct-chat continuity should preserve a stable `main` session concept rather than relying only on arbitrary free-form keys.

## Recommended Branching / Delivery Pattern

Use one feature branch per spec or per tightly coupled spec pair. Keep merges small.

Recommended pattern:

- `001-gateway-session-transcript`
- `002-langgraph-tool-registry`
- `003-capability-governance`
- `004-context-continuity`
- `005-async-scheduler-lanes`
- `006-remote-node-sandbox`
- `007-channels-streaming-media`
- `008-observability-hardening`

## Final Note

This program is intentionally sequenced so that spec-kit can generate implementation artifacts with low ambiguity and low architectural drift. It separates foundational transport/persistence work from orchestration, then layers governance, continuity, async execution, remote execution, transport expansion, and operational hardening in a build order that supports reliable implementation.
