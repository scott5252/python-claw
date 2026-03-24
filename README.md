# python-claw

`python-claw` is the foundation for a gateway-first assistant runtime inspired by the `001-gateway-sessions`, `002-runtime-tools`, `003-capability-governance`, `004-context-continuity`, `005-async-queueing`, and `006-node-sandbox` specs in [`/specs/001-gateway-sessions/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/001-gateway-sessions/spec.md), [`/specs/002-runtime-tools/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/002-runtime-tools/spec.md), [`/specs/003-capability-governance/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/003-capability-governance/spec.md), [`/specs/004-context-continuity/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/004-context-continuity/spec.md), [`/specs/005-async-queueing/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/005-async-queueing/spec.md), and [`/specs/006-node-sandbox/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md). The current implementation focuses on these things:

- a single FastAPI gateway entrypoint
- deterministic routing into durable sessions
- append-only transcript persistence
- PostgreSQL-safe idempotency semantics for inbound messages
- a gateway-owned single-turn assistant runtime
- a typed, policy-aware local tool registry
- append-only storage for tool artifacts and audit events
- exact-match capability approvals for governed actions
- transcript-linked governance events plus normalized approval and activation state
- transcript-first context assembly with additive summary snapshots
- per-turn persisted context manifests for inspection and replay analysis
- post-turn outbox enqueueing for summaries, retrieval indexing, and continuity repair
- durable queued execution runs, worker leasing, and run diagnostics
- a separate internal node-runner service boundary for signed remote execution
- per-agent sandbox profile resolution and durable node execution audits

This README is written for a developer who needs to understand what was implemented, how to run it, and how to test it locally.

## Current Implementation At A Glance

The application exposes:

- `GET /health`
- `POST /inbound/message`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/governance/pending`
- `GET /runs/{run_id}`
- `GET /sessions/{session_id}/runs`

The implemented flow for `POST /inbound/message` is:

1. validate and normalize routing input
2. claim the dedupe identity for `(channel_kind, channel_account_id, external_message_id)`
3. resolve or create the canonical session
4. append one inbound `user` message
5. finalize the dedupe record with the resulting `session_id` and `message_id`
6. create or reuse one durable `execution_runs` row for the turn
7. return `202 Accepted` with `run_id` and queued status
8. let a worker claim and execute the queued run through the gateway-owned runtime
9. append the assistant transcript message plus runtime artifacts, manifests, and post-turn jobs during worker execution

That behavior is implemented across:

- gateway app bootstrap: [`apps/gateway/main.py`](/Users/scottcornell/src/projects/python-claw/apps/gateway/main.py)
- inbound/admin endpoints: [`apps/gateway/api/inbound.py`](/Users/scottcornell/src/projects/python-claw/apps/gateway/api/inbound.py), [`apps/gateway/api/admin.py`](/Users/scottcornell/src/projects/python-claw/apps/gateway/api/admin.py)
- routing rules: [`src/routing/service.py`](/Users/scottcornell/src/projects/python-claw/src/routing/service.py)
- orchestration service: [`src/sessions/service.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/service.py)
- graph runtime: [`src/graphs/state.py`](/Users/scottcornell/src/projects/python-claw/src/graphs/state.py), [`src/graphs/nodes.py`](/Users/scottcornell/src/projects/python-claw/src/graphs/nodes.py), [`src/graphs/assistant_graph.py`](/Users/scottcornell/src/projects/python-claw/src/graphs/assistant_graph.py)
- continuity assembly and outbox worker: [`src/context/service.py`](/Users/scottcornell/src/projects/python-claw/src/context/service.py), [`src/context/outbox.py`](/Users/scottcornell/src/projects/python-claw/src/context/outbox.py)
- tool and policy wiring: [`src/tools/registry.py`](/Users/scottcornell/src/projects/python-claw/src/tools/registry.py), [`src/tools/local_safe.py`](/Users/scottcornell/src/projects/python-claw/src/tools/local_safe.py), [`src/tools/messaging.py`](/Users/scottcornell/src/projects/python-claw/src/tools/messaging.py), [`src/policies/service.py`](/Users/scottcornell/src/projects/python-claw/src/policies/service.py)
- typed capability governance: [`src/tools/typed_actions.py`](/Users/scottcornell/src/projects/python-claw/src/tools/typed_actions.py), [`src/capabilities/activation.py`](/Users/scottcornell/src/projects/python-claw/src/capabilities/activation.py)
- model adapter contract: [`src/providers/models.py`](/Users/scottcornell/src/projects/python-claw/src/providers/models.py)
- audit sink: [`src/observability/audit.py`](/Users/scottcornell/src/projects/python-claw/src/observability/audit.py)
- persistence layer: [`src/sessions/repository.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/repository.py)
- queueing and worker orchestration: [`src/jobs/repository.py`](/Users/scottcornell/src/projects/python-claw/src/jobs/repository.py), [`src/jobs/service.py`](/Users/scottcornell/src/projects/python-claw/src/jobs/service.py), [`apps/worker/jobs.py`](/Users/scottcornell/src/projects/python-claw/apps/worker/jobs.py)
- remote execution contracts and runtime: [`src/execution/contracts.py`](/Users/scottcornell/src/projects/python-claw/src/execution/contracts.py), [`src/execution/runtime.py`](/Users/scottcornell/src/projects/python-claw/src/execution/runtime.py), [`src/tools/remote_exec.py`](/Users/scottcornell/src/projects/python-claw/src/tools/remote_exec.py)
- node runner and sandbox resolution: [`apps/node_runner/main.py`](/Users/scottcornell/src/projects/python-claw/apps/node_runner/main.py), [`apps/node_runner/api/internal.py`](/Users/scottcornell/src/projects/python-claw/apps/node_runner/api/internal.py), [`apps/node_runner/policy.py`](/Users/scottcornell/src/projects/python-claw/apps/node_runner/policy.py), [`apps/node_runner/executor.py`](/Users/scottcornell/src/projects/python-claw/apps/node_runner/executor.py), [`src/sandbox/service.py`](/Users/scottcornell/src/projects/python-claw/src/sandbox/service.py), [`src/security/signing.py`](/Users/scottcornell/src/projects/python-claw/src/security/signing.py)
- idempotency lifecycle: [`src/gateway/idempotency.py`](/Users/scottcornell/src/projects/python-claw/src/gateway/idempotency.py)
- database schema: [`src/db/models.py`](/Users/scottcornell/src/projects/python-claw/src/db/models.py)
- migrations: [`migrations/versions/20260322_001_gateway_sessions.py`](/Users/scottcornell/src/projects/python-claw/migrations/versions/20260322_001_gateway_sessions.py), [`migrations/versions/20260322_002_runtime_tools.py`](/Users/scottcornell/src/projects/python-claw/migrations/versions/20260322_002_runtime_tools.py), [`migrations/versions/20260322_003_capability_governance.py`](/Users/scottcornell/src/projects/python-claw/migrations/versions/20260322_003_capability_governance.py), [`migrations/versions/20260323_005_async_queueing.py`](/Users/scottcornell/src/projects/python-claw/migrations/versions/20260323_005_async_queueing.py), [`migrations/versions/20260324_006_node_sandbox.py`](/Users/scottcornell/src/projects/python-claw/migrations/versions/20260324_006_node_sandbox.py)

## Spec 002 Runtime Tools

Spec 002 adds the first assistant execution path to the project. The key idea is that the gateway still owns the request lifecycle, but after the inbound user message is stored it now invokes a single-turn runtime that can either:

- return plain assistant text
- call a safe local tool
- prepare a runtime-owned outbound intent without calling a transport directly

The runtime is intentionally narrow in this spec:

- one turn only
- local tools only
- no background workflows
- no remote execution
- no transport dispatch from the graph

### What A Developer Needs To Know

The important implementation boundary is:

- `SessionService` is still the entry point for inbound work
- `AssistantGraph` is invoked from the service layer, not from FastAPI routes directly
- `ModelAdapter` returns a typed `ModelTurnResult`
- `ToolRegistry` binds tools per turn using `ToolRuntimeContext`
- `SessionRepository` persists assistant messages plus append-only runtime artifacts
- `ToolAuditSink` records execution attempts and outcomes separately from transcript rows

In the current workspace, the default runtime behavior is intentionally simple:

- `echo <text>` invokes `echo_text`
- `send <text>` invokes `send_message`
- anything else returns `Received: <text>`

That behavior lives in [`src/providers/models.py`](/Users/scottcornell/src/projects/python-claw/src/providers/models.py). It is a local rule-based adapter used to prove the runtime contracts and test paths before a real provider is introduced.

### Runtime Flow

For each accepted inbound message, the application now does this:

1. normalize routing and claim dedupe
2. reuse or create the session
3. append the inbound `user` message
4. finalize the dedupe record
5. build `AssistantState` from the current turn and recent transcript history
6. bind policy-allowed tools for this runtime context
7. execute any requested tools and record append-only artifacts
8. append the final `assistant` message

The append-only runtime records introduced by Spec 002 are:

- `session_artifacts` for `tool_proposal`, `tool_result`, and `outbound_intent`
- `tool_audit_events` for execution attempt and result auditing

### Files To Read First

If you want the shortest path to understanding Spec 002, read:

1. [`specs/002-runtime-tools/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/002-runtime-tools/spec.md)
2. [`src/sessions/service.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/service.py)
3. [`src/graphs/nodes.py`](/Users/scottcornell/src/projects/python-claw/src/graphs/nodes.py)
4. [`src/tools/registry.py`](/Users/scottcornell/src/projects/python-claw/src/tools/registry.py)
5. [`src/sessions/repository.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/repository.py)
6. [`tests/test_runtime.py`](/Users/scottcornell/src/projects/python-claw/tests/test_runtime.py) and [`tests/test_integration.py`](/Users/scottcornell/src/projects/python-claw/tests/test_integration.py)

## Spec 003 Capability Governance

Spec 003 adds a capability-governance layer on top of the single-turn runtime from Spec 002. The key idea is that the gateway still owns the turn lifecycle, but some capabilities are now treated as governed typed actions that cannot be exposed or executed until the user has approved the exact action and parameter payload.

The runtime is still intentionally narrow in this spec:

- approval is exact-match only
- approval scope is session-and-agent scoped
- activation stays on the gateway-owned path
- governed waits are persisted before the turn exits
- revocation affects future visibility and future execution

### What A Developer Needs To Know

The important implementation boundary is:

- `PolicyService` now classifies turns before gated tool exposure
- `typed_actions.py` defines which capabilities are governed typed actions
- `SessionRepository` persists proposals, versions, approvals, active resources, and governance transcript events
- `ActivationController` is the sole activation path for approved capabilities
- `AssistantGraph` and graph nodes exit into persisted approval wait when governance blocks execution
- tool visibility is rebuilt from current approval state on each turn
- execution still re-checks approval even when a governed tool is visible

In the current workspace, the governance behavior is intentionally concrete:

- `echo_text` remains a safe, always-available local action
- `send_message` is the governed action used to prove the approval flow
- `send <text>` creates a proposal when no matching approval exists
- `approve <proposal_id>` approves and activates that exact proposal
- `revoke <proposal_id>` revokes it for later turns

### Runtime Flow

For a governed request without approval, the application now does this:

1. normalize routing and claim dedupe
2. reuse or create the session
3. append the inbound `user` message
4. finalize the dedupe record
5. classify the turn before gated tool exposure
6. persist a resource proposal, immutable version, and governance transcript events
7. append an `assistant` message explaining that approval is required

For a later approval turn, the application now does this:

1. classify `approve <proposal_id>` as an approval decision
2. persist the exact approval record
3. activate the approved resource through `ActivationController`
4. append governance transcript events for approval and activation
5. append an `assistant` message confirming approval and activation

For a later retry of the original request, the application now does this:

1. rebuild policy context from active approvals
2. expose the governed tool only if the exact approval matches
3. re-check the approval at execution time
4. persist normal runtime artifacts such as `tool_proposal`, `outbound_intent`, and `tool_result`

The governance records introduced by Spec 003 are:

- `governance_transcript_events` for proposal creation, approval request, approval decision, activation result, and revocation result
- `resource_proposals` for proposal state
- `resource_versions` for immutable proposed content versions
- `resource_approvals` for exact approval matching and revocation state
- `active_resources` for activation and revocation state

### Files To Read First

If you want the shortest path to understanding Spec 003, read:

1. [`specs/003-capability-governance/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/003-capability-governance/spec.md)
2. [`src/tools/typed_actions.py`](/Users/scottcornell/src/projects/python-claw/src/tools/typed_actions.py)
3. [`src/policies/service.py`](/Users/scottcornell/src/projects/python-claw/src/policies/service.py)
4. [`src/sessions/repository.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/repository.py)
5. [`src/graphs/nodes.py`](/Users/scottcornell/src/projects/python-claw/src/graphs/nodes.py)
6. [`tests/test_runtime.py`](/Users/scottcornell/src/projects/python-claw/tests/test_runtime.py) and [`tests/test_integration.py`](/Users/scottcornell/src/projects/python-claw/tests/test_integration.py)

## Spec 004 Context Continuity

Spec 004 adds a continuity layer around the gateway-owned runtime from Specs 001 to 003. The key idea is that the canonical source of conversation continuity remains the append-only transcript plus transcript-linked tool and governance artifacts, while summaries, manifests, and outbox jobs are treated as additive derived state.

The runtime shape is still intentionally narrow in this workspace:

- assembly is transcript-first
- compaction retries are deterministic but simple
- summary generation is implemented as a local worker-side heuristic
- retrieval indexing is queued but not yet implemented
- degraded overflow produces a bounded assistant failure rather than silent truncation

### What A Developer Needs To Know

The important implementation boundary is:

- `ContextService` owns context assembly, overflow retry, and manifest construction
- `AssistantGraph` still runs only on the gateway-owned invocation path
- `SessionRepository` exposes additive continuity reads and writes for summaries, manifests, outbox jobs, and governance replay
- `SessionService` enqueues post-turn jobs only after the assistant turn commits
- `PolicyService` can replay active approvals from transcript-linked governance events when normalized state is missing
- `OutboxWorker` currently implements `summary_generation` and leaves other queued job kinds as no-ops

In the current workspace, continuity behavior is intentionally concrete:

- a turn first loads transcript history, all persisted tool artifacts, all governance events, and the latest valid summary snapshot
- if the transcript fits within `runtime_transcript_context_limit`, the full transcript is used
- if it overflows and a summary exists, the runtime retries with one synthetic summary message plus the newest tail messages
- if retry still cannot fit, or no usable summary exists, the turn degrades safely and returns a continuity-repair response
- every turn persists a `context_manifests` row recording transcript ranges, summary ids, tool artifact ids, governance artifact ids, and overflow metadata
- after the assistant turn commits, the service enqueues `summary_generation` and `retrieval_index` jobs, plus `continuity_repair` when the turn degraded

### Runtime Flow

For each accepted inbound message, the application now does this:

1. persist the inbound `user` message through the canonical transcript path
2. assemble transcript-first context from messages plus additive aids
3. build an inspectable manifest for the chosen assembly mode
4. execute the governed runtime turn, or return a bounded degraded response on hard overflow
5. append the final `assistant` message
6. persist the turn manifest
7. enqueue post-turn outbox jobs for summaries, retrieval indexing, and continuity repair when needed

The additive continuity records introduced by Spec 004 are:

- `summary_snapshots` for versioned, range-bounded summaries
- `context_manifests` for durable per-turn assembly inspection
- `outbox_jobs` for post-commit summary, retrieval, and repair work

### Files To Read First

If you want the shortest path to understanding Spec 004, read:

1. [`specs/004-context-continuity/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/004-context-continuity/spec.md)
2. [`src/context/service.py`](/Users/scottcornell/src/projects/python-claw/src/context/service.py)
3. [`src/sessions/service.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/service.py)
4. [`src/sessions/repository.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/repository.py)
5. [`src/context/outbox.py`](/Users/scottcornell/src/projects/python-claw/src/context/outbox.py)
6. [`tests/test_repository.py`](/Users/scottcornell/src/projects/python-claw/tests/test_repository.py) and [`tests/test_integration.py`](/Users/scottcornell/src/projects/python-claw/tests/test_integration.py)

## Spec 005 Async Queueing

Spec 005 moves assistant execution out of the request thread and into durable `execution_runs` rows processed by a worker. The key idea is that the gateway still owns intake, routing, transcript persistence, and idempotency, but user-visible turn execution now happens asynchronously under lease-controlled worker ownership.

The runtime shape is still intentionally narrow in this spec:

- inbound acceptance and graph execution are split
- one durable run is created per trigger identity
- same-session work is serialized by lane leases
- global concurrency is bounded by explicit global lease slots
- scheduler fires reuse the same execution-run system

### What A Developer Needs To Know

The important implementation boundary is:

- `SessionService` accepts inbound work and creates durable `execution_runs`
- `RunExecutionService` is the worker-side owner of claiming, running, retrying, and completing runs
- `JobsRepository` owns run state transitions, lease acquisition, and replay-safe trigger identity
- `SessionConcurrencyService` wraps the lane and global lease rules introduced by this spec
- `apps/worker/jobs.py` is the narrow entry point for processing one eligible run
- the graph runtime still runs through the same `AssistantGraph`, but only after a worker claims the run

In the current workspace, queueing behavior is intentionally concrete:

- `POST /inbound/message` returns `202 Accepted`
- the response includes `run_id` and the run's initial `queued` status
- transcript shows the inbound `user` message before the worker runs
- assistant output appears only after a worker claims and completes the queued run
- scheduler submissions create canonical user-role trigger messages and then reuse the same run pipeline

### Runtime Flow

For each accepted inbound message, the application now does this:

1. normalize routing, claim dedupe, and append the inbound `user` message
2. create or reuse one durable `execution_runs` row keyed by the trigger identity
3. return `202 Accepted` with the run metadata
4. let a worker claim the next eligible run subject to lane and global lease rules
5. execute the assistant graph for the canonical transcript message
6. persist terminal run state plus any runtime artifacts and post-turn jobs

The queueing records introduced by Spec 005 are:

- `execution_runs` for durable queued and terminal run state
- `session_run_leases` for same-session FIFO ownership
- `global_run_leases` for bounded global concurrency
- `scheduled_jobs` and `scheduled_job_fires` for replay-safe scheduler submission

### Files To Read First

If you want the shortest path to understanding Spec 005, read:

1. [`specs/005-async-queueing/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/005-async-queueing/spec.md)
2. [`src/sessions/service.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/service.py)
3. [`src/jobs/repository.py`](/Users/scottcornell/src/projects/python-claw/src/jobs/repository.py)
4. [`src/jobs/service.py`](/Users/scottcornell/src/projects/python-claw/src/jobs/service.py)
5. [`src/sessions/concurrency.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/concurrency.py)
6. [`apps/worker/jobs.py`](/Users/scottcornell/src/projects/python-claw/apps/worker/jobs.py), [`apps/worker/scheduler.py`](/Users/scottcornell/src/projects/python-claw/apps/worker/scheduler.py), and [`tests/test_async_queueing_coverage.py`](/Users/scottcornell/src/projects/python-claw/tests/test_async_queueing_coverage.py)

## Spec 006 Remote Node Runner And Per-Agent Sandboxing

Spec 006 separates orchestration from privileged execution by introducing a fail-closed node-runner boundary. The key idea is that the gateway and workers still own policy, approval refresh, and request construction, but host execution now happens through one signed internal request contract with deterministic sandbox resolution and durable node execution audits.

The runtime shape is still intentionally narrow in this spec:

- remote execution remains approval-gated and typed
- requests use argv semantics only
- request signing and replay protection are mandatory
- duplicate delivery reuses one logical execution attempt keyed by `request_id`
- sandbox isolation is scaffolded, but container-backed enforcement is not fully implemented yet in this workspace

### What A Developer Needs To Know

The important implementation boundary is:

- `TypedAction` now includes `remote_exec` as a governed `node_command_template` capability
- `RemoteExecutionRuntime` constructs one canonical signed `NodeExecRequest` from approved template data, exact invocation parameters, and sandbox resolution
- `ToolRegistry` can bind the remote-exec tool, but only when remote execution is enabled and an exact active approval exists
- `NodeRunnerPolicy` independently verifies signatures, freshness, argv derivation, executable allowlists, and sandbox consistency before execution
- `NodeRunnerExecutor` is execution-only and records terminal state through `node_execution_audits`
- `SandboxService` resolves deterministic `off`, `shared`, or `agent` mode metadata plus one canonical workspace root

In the current workspace, remote-execution behavior is intentionally concrete:

- `/bin/echo` is the main allowlisted example executable used in tests and manual QA
- the gateway runtime can sign and dispatch a request directly to the node-runner policy and executor path
- duplicate delivery of the same signed request returns the existing persisted state
- tampered requests fail closed before execution
- container-backed sandbox metadata exists, but the actual container backend is only scaffolded so current execution still focuses on signed request, audit, and resolution contracts

### Runtime Flow

For one approved remote-execution attempt, the application now does this:

1. refresh execution-time approval and policy state on the worker-owned path
2. load the immutable approved `node_command_template`
3. derive the canonical invocation parameters, final argv, sandbox mode, sandbox key, workspace root, and workspace mount mode
4. derive one stable `request_id` from `(execution_run_id, tool_call_id, execution_attempt_number)`
5. sign the canonical request and dispatch it to the node runner
6. let the node runner insert-or-reuse the audit row, verify policy, execute if allowed, and return the persisted state

The records introduced by Spec 006 are:

- `node_execution_audits` for replay-safe execution attempts and terminal diagnostics
- `agent_sandbox_profiles` for per-agent default mode, shared profile key, and timeout ceilings

### Files To Read First

If you want the shortest path to understanding Spec 006, read:

1. [`specs/006-node-sandbox/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/006-node-sandbox/spec.md)
2. [`src/execution/contracts.py`](/Users/scottcornell/src/projects/python-claw/src/execution/contracts.py)
3. [`src/execution/runtime.py`](/Users/scottcornell/src/projects/python-claw/src/execution/runtime.py)
4. [`apps/node_runner/policy.py`](/Users/scottcornell/src/projects/python-claw/apps/node_runner/policy.py)
5. [`apps/node_runner/executor.py`](/Users/scottcornell/src/projects/python-claw/apps/node_runner/executor.py)
6. [`src/execution/audit.py`](/Users/scottcornell/src/projects/python-claw/src/execution/audit.py), [`src/sandbox/service.py`](/Users/scottcornell/src/projects/python-claw/src/sandbox/service.py), and [`tests/test_node_sandbox.py`](/Users/scottcornell/src/projects/python-claw/tests/test_node_sandbox.py)

## How To Read The Code

If you want the fastest path through the codebase, read it in this order:

1. [`specs/001-gateway-sessions/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/001-gateway-sessions/spec.md) for the intended contract.
2. [`apps/gateway/main.py`](/Users/scottcornell/src/projects/python-claw/apps/gateway/main.py) to see how the FastAPI app is assembled.
3. [`apps/gateway/api/inbound.py`](/Users/scottcornell/src/projects/python-claw/apps/gateway/api/inbound.py) to see the main write path.
4. [`src/sessions/service.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/service.py) to understand the business flow.
5. [`src/routing/service.py`](/Users/scottcornell/src/projects/python-claw/src/routing/service.py) for deterministic routing and session-key composition.
6. [`src/gateway/idempotency.py`](/Users/scottcornell/src/projects/python-claw/src/gateway/idempotency.py) for `claimed` vs `completed` dedupe behavior.
7. [`src/context/service.py`](/Users/scottcornell/src/projects/python-claw/src/context/service.py) for transcript-first assembly and overflow behavior.
8. [`src/sessions/repository.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/repository.py) and [`src/db/models.py`](/Users/scottcornell/src/projects/python-claw/src/db/models.py) for storage details.
9. [`tests/`](/Users/scottcornell/src/projects/python-claw/tests) to see the expected behavior end to end.

### Request Lifecycle

For a direct message:

- routing input is trim-normalized
- `channel_kind` must already be lowercase
- exactly one of `peer_id` or `group_id` must be present
- direct conversations always map to scope `direct` and scope name `main`
- the canonical direct session key is `{channel_kind}:{channel_account_id}:direct:{peer_id}:main`

For a group message:

- scope is `group`
- scope name is the `group_id`
- the canonical group session key is `{channel_kind}:{channel_account_id}:group:{group_id}`

### Persistence Model

The current database tables are:

- `sessions`: canonical session identity and routing metadata
- `messages`: append-only transcript rows
- `inbound_dedupe`: persisted idempotency claims and replay metadata
- `session_artifacts`: append-only runtime artifact rows
- `tool_audit_events`: append-only execution audit rows
- `governance_transcript_events`: append-only transcript-linked governance history
- `resource_proposals`: proposal lifecycle state
- `resource_versions`: immutable proposed content versions
- `resource_approvals`: exact-match approval and revocation state
- `active_resources`: activation and revocation state
- `execution_runs`: durable queued and terminal worker-owned turn execution
- `session_run_leases`: same-session FIFO lease ownership
- `global_run_leases`: bounded global concurrency slots
- `scheduled_jobs`: durable scheduler definitions
- `scheduled_job_fires`: replay-safe scheduler fire records
- `summary_snapshots`: additive versioned summaries for continuity compaction
- `outbox_jobs`: post-commit summary, retrieval, and repair jobs
- `context_manifests`: persisted per-turn assembly manifests
- `agent_sandbox_profiles`: per-agent sandbox defaults and timeout ceilings
- `node_execution_audits`: signed remote-execution attempt and terminal audit state

Important current behaviors:

- duplicate deliveries return the original `session_id` and `message_id`
- a fresh duplicate that hits an in-progress non-stale claim returns `409`
- stale `claimed` dedupe rows are recoverable after `dedupe_stale_after_seconds`
- transcript pagination is cursor-based with `before_message_id`
- summary selection prefers the latest valid snapshot whose covered range is strictly before the current message
- context manifests are retained with a bounded per-session history
- approval visibility can be replayed from governance transcript events if normalized approval rows are missing
- duplicate inbound deliveries reuse the same execution trigger identity instead of creating a second run
- duplicate node-runner deliveries reuse the same `request_id` audit row instead of starting a second process

## Environment Setup

### 1. Python And `uv`

This project requires Python `3.11+` and now uses `uv` for environment and dependency management.

```bash
uv python install 3.11
uv sync --group dev
```

If you already have a compatible Python `>=3.11` installed, `uv sync --group dev` is enough. `uv` will create and manage the local `.venv` automatically.

If you prefer an activated shell after syncing, use:

```bash
source .venv/bin/activate
```

### 2. Project `.env`

This project uses `python-dotenv` to load configuration from a project-root `.env` file for application runtime and Alembic migrations.

A starter [`.env`](/Users/scottcornell/src/projects/python-claw/.env) is included with local development defaults:

```dotenv
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
PYTHON_CLAW_POSTGRES_DB=openassistant
PYTHON_CLAW_POSTGRES_USER=openassistant
PYTHON_CLAW_POSTGRES_PASSWORD=openassistant
PYTHON_CLAW_POSTGRES_PORT=5432
PYTHON_CLAW_REDIS_PORT=6379
```

Update that file before running the stack if you want different local ports, credentials, or database names.

For a brand new checkout, the quickest happy path is:

```bash
uv sync --group dev
docker compose --env-file .env up -d
uv run alembic upgrade head
uv run uvicorn apps.gateway.main:app --reload
```

### 3. PostgreSQL And Redis

A local `docker-compose.yml` is included for developer infrastructure:

- PostgreSQL `17`
- Redis `7`

Start both services with the project `.env` file:

```bash
docker compose --env-file .env up -d
```

Useful checks:

```bash
docker compose ps
docker compose logs postgres
docker compose logs redis
```

The default container credentials are:

- PostgreSQL database: `openassistant`
- PostgreSQL user: `openassistant`
- PostgreSQL password: `openassistant`
- PostgreSQL port: `5432`
- Redis port: `6379`

The matching SQLAlchemy PostgreSQL URL is:

```bash
postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
```

Note on current status: Redis is provisioned for the wider architecture, but this spec implementation does not yet use Redis in the request path. Right now the gateway uses the configured SQL database plus in-process FastAPI services.

### 4. Application Configuration

Settings are defined in [`src/config/settings.py`](/Users/scottcornell/src/projects/python-claw/src/config/settings.py) and load from the project `.env` file through `python-dotenv`, using environment variable names prefixed with `PYTHON_CLAW_`.

The main variables you will care about are:

- `PYTHON_CLAW_DATABASE_URL`
- `PYTHON_CLAW_DEDUPE_RETENTION_DAYS`
- `PYTHON_CLAW_DEDUPE_STALE_AFTER_SECONDS`
- `PYTHON_CLAW_MESSAGES_PAGE_DEFAULT_LIMIT`
- `PYTHON_CLAW_MESSAGES_PAGE_MAX_LIMIT`
- `PYTHON_CLAW_RUNTIME_TRANSCRIPT_CONTEXT_LIMIT`
- `PYTHON_CLAW_EXECUTION_RUN_LEASE_SECONDS`
- `PYTHON_CLAW_EXECUTION_RUN_GLOBAL_CONCURRENCY`
- `PYTHON_CLAW_REMOTE_EXECUTION_ENABLED`
- `PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID`
- `PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET`
- `PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES`

Compose-specific values in the same `.env` file are:

- `PYTHON_CLAW_POSTGRES_DB`
- `PYTHON_CLAW_POSTGRES_USER`
- `PYTHON_CLAW_POSTGRES_PASSWORD`
- `PYTHON_CLAW_POSTGRES_PORT`
- `PYTHON_CLAW_REDIS_PORT`

If you do not set `PYTHON_CLAW_DATABASE_URL`, the app now defaults to:

```bash
postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
```

That matches the bundled Docker Compose PostgreSQL service, so the application and Alembic target the same local database by default.

## Database Setup

Alembic is configured in [`alembic.ini`](/Users/scottcornell/src/projects/python-claw/alembic.ini) and [`migrations/env.py`](/Users/scottcornell/src/projects/python-claw/migrations/env.py).

Alembic now reads the database URL from the same project `.env` file as the application and falls back to the same PostgreSQL local-development URL when the variable is unset. For local Docker Compose, the default [`.env`](/Users/scottcornell/src/projects/python-claw/.env) already points at:

```bash
postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
```

With PostgreSQL running, apply the schema:

```bash
uv run alembic upgrade head
```

After the migration runs, the database should contain:

- `sessions`
- `messages`
- `inbound_dedupe`
- `session_artifacts`
- `tool_audit_events`
- `governance_transcript_events`
- `resource_proposals`
- `resource_versions`
- `resource_approvals`
- `active_resources`
- `execution_runs`
- `session_run_leases`
- `global_run_leases`
- `scheduled_jobs`
- `scheduled_job_fires`
- `agent_sandbox_profiles`
- `node_execution_audits`

Current note for continuity tables: the ORM models and tests include `summary_snapshots`, `outbox_jobs`, and `context_manifests`, but there is not yet a `004` Alembic migration under [`migrations/versions`](/Users/scottcornell/src/projects/python-claw/migrations/versions). If you rely on Alembic alone against PostgreSQL today, those three continuity tables will not be created until that migration is added.

## How To Run The Application

With dependencies synced, `.env` configured, and Docker services running:

```bash
uv run uvicorn apps.gateway.main:app --reload
```

By default the app will be available at:

```text
http://127.0.0.1:8000
```

Quick smoke checks:

```bash
curl http://127.0.0.1:8000/health
```

Example inbound request for a direct conversation:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H "Content-Type: application/json" \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-1",
    "external_message_id": "msg-1",
    "sender_id": "sender-1",
    "content": "hello",
    "peer_id": "peer-1"
  }'
```

Example response:

```json
{
  "session_id": "2f9f0d1f-1ab2-4d55-a4d8-0fcbf0fd1df7",
  "message_id": 1,
  "run_id": "d7bb6bc6-0b0f-4c0f-89fc-45126377b2d0",
  "status": "queued",
  "dedupe_status": "accepted"
}
```

Runtime smoke test using the built-in local echo tool:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H "Content-Type: application/json" \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-1",
    "external_message_id": "msg-echo-1",
    "sender_id": "sender-1",
    "content": "echo hello runtime",
    "peer_id": "peer-1"
  }'
```

Runtime smoke test using the outbound-intent tool:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H "Content-Type: application/json" \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-1",
    "external_message_id": "msg-send-1",
    "sender_id": "sender-1",
    "content": "send hello channel",
    "peer_id": "peer-1"
  }'
```

Read back the session metadata:

```bash
curl http://127.0.0.1:8000/sessions/<session_id>
```

Read back transcript history:

```bash
curl "http://127.0.0.1:8000/sessions/<session_id>/messages?limit=50"
```

Read back run diagnostics:

```bash
curl http://127.0.0.1:8000/runs/<run_id>
curl http://127.0.0.1:8000/sessions/<session_id>/runs
```

Run one worker pass locally:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once

print(run_once())
PY
```

Start the internal node runner locally when working on Spec 006:

```bash
uv run uvicorn apps.node_runner.main:app --reload --port 8010
```

## How To Test The Code

Sync dev dependencies first:

```bash
uv sync --group dev
```

Run the full test suite:

```bash
uv run pytest
```

The tests currently use temporary SQLite databases created by pytest fixtures, so they do not require local PostgreSQL or Redis to pass.

### What The Tests Cover

- [`tests/test_routing.py`](/Users/scottcornell/src/projects/python-claw/tests/test_routing.py): routing normalization, lowercase `channel_kind`, and session-key composition
- [`tests/test_idempotency.py`](/Users/scottcornell/src/projects/python-claw/tests/test_idempotency.py): first-claim, finalize, duplicate replay, conflict, and stale-claim recovery
- [`tests/test_repository.py`](/Users/scottcornell/src/projects/python-claw/tests/test_repository.py): session reuse, append-order message paging, and append-only runtime artifacts
- [`tests/test_repository.py`](/Users/scottcornell/src/projects/python-claw/tests/test_repository.py): also covers summary snapshot selection, context manifest retention, outbox dedupe, outbox worker summary generation, and governance replay from transcript history
- [`tests/test_runtime.py`](/Users/scottcornell/src/projects/python-claw/tests/test_runtime.py): graph branching, policy-aware tool binding, and no fabricated success on tool failure
- [`tests/test_api.py`](/Users/scottcornell/src/projects/python-claw/tests/test_api.py): inbound acceptance, duplicate replay, invalid routing, session history with assistant replies, and dedupe isolation across channels
- [`tests/test_integration.py`](/Users/scottcornell/src/projects/python-claw/tests/test_integration.py): restart-safe session reuse, replay after restart, stale recovery, governed-tool flows, overflow degradation with continuity-repair enqueueing, and governance replay after normalized-state loss
- [`tests/test_async_queueing_coverage.py`](/Users/scottcornell/src/projects/python-claw/tests/test_async_queueing_coverage.py): queued-run creation, worker execution, run diagnostics, FIFO lane behavior, and scheduler submission coverage
- [`tests/test_node_sandbox.py`](/Users/scottcornell/src/projects/python-claw/tests/test_node_sandbox.py): stable request identity, signed request verification, deny-by-default remote tool binding, duplicate delivery reuse, and node-runner execution audit coverage

Useful commands during development:

```bash
uv run pytest tests/test_runtime.py
uv run pytest tests/test_api.py
uv run pytest tests/test_integration.py
uv run pytest tests/test_routing.py -q
uv run pytest tests/test_async_queueing_coverage.py
uv run pytest tests/test_node_sandbox.py
```

## Current Limitations

This repository is intentionally still at the foundation stage of the broader architecture. In its current form:

- the assistant runtime is single-turn only
- the default model is a local rule-based adapter, not a provider-backed model
- remote execution exists only as a tightly scoped, approval-gated internal capability rather than a broad user-facing shell surface
- outbound messaging stops at persisted intent creation; no transport dispatch layer exists yet
- Redis is provisioned, but not yet used by the application code
- tests validate behavior mostly against SQLite fixtures rather than a live PostgreSQL instance
- retrieval indexing is only represented as queued `outbox_jobs`; no retrieval store or retrieval-based assembly exists yet
- summary generation is a simple local heuristic worker, not a provider-backed summarization pipeline
- the deterministic compaction path currently retries with at most one summary message plus a short tail, rather than a richer retrieval or chunking strategy
- the continuity tables from Spec 004 are present in ORM models and tests, but Alembic migration support for them is still pending
- the node-runner contract and audit flow are implemented, but the container backend is still scaffold-only rather than full production isolation

That means the code is already useful for validating routing, session identity, transcript persistence, idempotent webhook handling, and the first runtime/tooling slice, but it is not yet a full multi-provider, multi-turn assistant platform.
