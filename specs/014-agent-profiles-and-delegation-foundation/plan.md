# Plan 014: Agent Profiles and Delegation Foundation

## Target Modules
- `apps/gateway/main.py`
- `apps/gateway/deps.py`
- `apps/gateway/api/admin.py`
- `src/config/settings.py`
- `src/db/models.py`
- `src/domain/schemas.py`
- `src/sessions/repository.py`
- `src/sessions/service.py`
- `src/jobs/repository.py`
- `src/jobs/service.py`
- `src/graphs/state.py`
- `src/graphs/nodes.py`
- `src/graphs/assistant_graph.py`
- `src/providers/models.py`
- `src/policies/service.py`
- `src/tools/registry.py`
- `src/observability/diagnostics.py`
- `src/sandbox/service.py` only if additive ownership validation hooks are needed
- `migrations/versions/`
- `tests/`

## Success Conditions
- Durable `agent_profiles` and `model_profiles` preserve the current single-agent system after migration and seeding.
- Every `sessions` row has durable ownership metadata:
  - `owner_agent_id`
  - `session_kind`
  - `parent_session_id`
- Session ownership becomes the only runtime source of truth for existing conversations; `default_agent_id` remains bootstrap-only for new `primary` sessions.
- Every new `execution_runs` row persists the resolved execution profile:
  - `agent_id`
  - `model_profile_key`
  - `policy_profile_key`
  - `tool_profile_key`
- Worker execution resolves one typed per-run binding before graph invocation and uses it for model selection, tool binding, policy checks, and diagnostics.
- Worker execution uses the persisted run profile keys as the run’s execution identity and re-validates those persisted keys at execution time rather than silently switching to whatever profile links the agent has later.
- Disabled or invalid agents fail closed before transcript mutation or run creation for inbound and scheduler work.
- Routing-tuple scheduler flows continue to reuse or create canonical `primary` sessions only.
- Admin and diagnostics surfaces expose agent ownership and execution-profile visibility without weakening existing operator protections.

## Current Codebase Constraints From Specs 001-013
- Spec 001 made the canonical session key the routing source of truth; Spec 014 must preserve that key and add ownership as durable session metadata rather than as part of routing identity.
- Specs 002, 009, and 010 built a shared runtime, tool, and provider seam, but current wiring in `apps/gateway/deps.py` still constructs one process-wide model adapter and one process-wide `PolicyService`.
- Spec 005 moved execution to queued runs and worker-owned processing, so profile resolution must happen both:
  - before run creation
  - again when the worker reloads the run for execution
- Spec 006 already keys sandbox resolution by `agent_id`, which makes durable owner resolution the missing upstream guarantee rather than a sandbox redesign.
- Specs 011 through 013 added more runtime state, outbound delivery, and diagnostics, so the new binding must flow through existing graph state and observability rather than creating a side channel.

## Migration Order
1. Add durable profile tables first:
   - `model_profiles`
   - `agent_profiles`
2. Extend `sessions` additively with:
   - nullable `owner_agent_id`
   - nullable `session_kind`
   - nullable `parent_session_id`
3. Extend `execution_runs` additively with nullable backfill fields:
   - `model_profile_key`
   - `policy_profile_key`
   - `tool_profile_key`
4. Seed or migrate the minimum profile records needed to preserve existing behavior:
   - one default enabled `model_profile`
   - one enabled `agent_profile` for `default_agent_id`
   - one enabled `agent_profile` for each additional historical `agent_id`
   - optional operator override mapping may change linked profile keys for migrated historical agents, but omission defaults them to the seeded default profiles
5. Backfill session ownership deterministically:
   - one historical run owner means adopt that owner
   - no historical runs means use current `default_agent_id`
   - conflicting historical run owners for one session fail the migration loudly
6. Backfill `session_kind=primary` and `parent_session_id=null` for all existing sessions.
7. Backfill run profile keys from the migrated or seeded owning agent profile for each historical `agent_id`.
8. Add non-null constraints, foreign keys, enums or validated string domains, and indexes only after backfill succeeds.

## Implementation Shape
- Introduce one explicit agent-resolution seam instead of spreading lookups across gateway, worker, and graph code:
  - add `AgentProfileService` and repository helpers as the sole source for agent existence, enablement, linked model profile, and settings-backed policy or tool profile resolution
  - return a typed `AgentExecutionBinding` used by queue submission and worker execution
- Keep profile storage split as defined by the spec:
  - database-backed `agent_profiles`
  - database-backed `model_profiles`
  - settings-backed `policy_profiles`
  - settings-backed `tool_profiles`
- Treat runtime binding as an additive replacement for process-wide defaults:
  - `Settings` still owns provider credentials and bootstrap defaults
  - run-time model, tool, and policy behavior come from the resolved binding
- Preserve shared graph topology from Specs 002 through 013; vary execution behavior through injected binding data rather than per-agent graphs.

## Workstreams
### 1. Settings and Registry Contracts
- Extend `src/config/settings.py` with typed settings-backed registries for:
  - `policy_profiles`
  - `tool_profiles`
- Add a settings-backed historical-agent override registry keyed by legacy `agent_id` so migrations can override seeded default model, policy, and tool linkage when needed.
- Fail closed during validation when profile keys are blank, duplicated, or structurally invalid.
- Preserve current single-agent behavior by defining a default policy profile and default tool profile that mirror today’s capability exposure.
- Keep provider credentials and auth material settings-only; do not duplicate them into durable profile rows.

### 2. Durable Data Model and Repositories
- Add ORM models and repository helpers for:
  - agent profile CRUD-style reads
  - model profile reads
  - agent-to-session listing
  - session creation with immutable ownership metadata
- Treat agent removal as soft-disable only in this slice; repository and service contracts should not expose hard-delete flows for rows that may already be referenced by sessions, runs, approvals, or sandbox state.
- Extend `SessionRecord` and `ExecutionRunRecord` mappings with the new ownership and profile-key columns.
- Extend `JobsRepository.create_or_get_execution_run(...)` so run creation persists the full resolved profile identity, not just `agent_id`.
- Keep ownership immutable after session creation in repository or service contracts to avoid accidental reassignment.

### 3. Bootstrap, Seeding, and Startup Validation
- Add an idempotent bootstrap path that runs in app startup after migrations and before traffic is accepted.
- Seed the default `model_profile` from current settings:
  - `runtime_mode`
  - provider
  - model name
  - timeout
  - temperature
  - max output tokens
  - tool-call mode
  - streaming flag
- Seed the default `agent_profile` using:
  - `agent_id=settings.default_agent_id`
  - default model profile linkage
  - default policy profile key
  - default tool profile key
- Validate startup invariants loudly:
  - configured default agent exists
  - default agent is enabled
  - linked model profile is enabled
  - referenced settings-backed policy and tool profiles exist

### 4. Session Ownership Resolution
- Refactor `SessionRepository.get_or_create_session(...)` and `SessionService.process_inbound(...)` so new sessions are created with a resolved owner binding rather than with no durable owner.
- Add a bootstrap owner resolver used only when the canonical session does not yet exist.
- When the session already exists, always trust `sessions.owner_agent_id` over current settings.
- Resolve and validate bootstrap ownership before inserting a first-time `sessions` row so invalid owners cannot leave behind empty sessions.
- Apply the same ownership rules in scheduler submission:
  - existing `session_id` targets use the persisted owner
  - routing-tuple targets reuse or create a `primary` session through the bootstrap resolver
  - no new `system` session creation through routing-tuple resolution in this slice
  - when `scheduled_jobs.agent_id` is present, it must match the resolved owner or the submission fails closed

### 5. Run Binding and Worker Execution
- Add a typed `AgentExecutionBinding` to carry:
  - `agent_id`
  - `session_kind`
  - `model_profile_key`
  - `policy_profile_key`
  - `tool_profile_key`
  - resolved bounded model settings
- Resolve and persist that binding before run creation returns.
- Reload and validate the binding again in `RunExecutionService` before graph invocation so disabled agents or broken persisted profile links fail closed even for queued work.
- Execute queued work using the persisted run profile keys rather than re-deriving profile identity from an agent’s current linked profiles.
- Extend `AssistantState` and graph dependencies to carry the resolved profile keys for observability and deterministic tool binding.

### 6. Model, Tool, and Policy Binding
- Replace process-wide model selection in `apps/gateway/deps.py` and `src/providers/models.py` with per-binding model adapter construction or invocation-time model selection.
- Refactor `PolicyService` so denied capabilities and runtime flags come from the resolved policy profile instead of constructor-time globals.
- Refactor `ToolRegistry.bind_tools(...)` so capability exposure is the intersection of:
  - registry membership
  - tool profile allowlist
  - policy profile decisions
  - existing runtime and channel constraints
- Keep approval matching exact to `session_id` plus `agent_id`; do not widen approval scope through profiles.

### 7. Admin and Diagnostics Surfaces
- Extend `SessionResponse` and related read paths with:
  - `owner_agent_id`
  - `session_kind`
  - `parent_session_id`
- Add operator-protected endpoints for:
  - `GET /agents`
  - `GET /agents/{agent_id}`
  - `GET /agents/{agent_id}/sessions`
  - `GET /model-profiles`
  - `GET /model-profiles/{profile_key}`
- Extend run diagnostics so each run shows persisted execution profile keys and, when available, the current resolved profile definitions.
- Add agent diagnostics visibility for:
  - enabled status
  - linked model profile
  - linked policy and tool profile keys
  - sandbox profile presence
  - owned sessions

## Recommended Module Layout
- Add a new `src/agents/` package rather than overloading `sessions` or `policies` with durable profile logic.
- Suggested files:
  - `src/agents/repository.py`
  - `src/agents/service.py`
  - `src/agents/bootstrap.py`
- Keep session ownership persistence in `src/sessions/` and execution profile persistence in `src/jobs/`; the new `src/agents/` package should resolve bindings, not absorb unrelated queue or transcript behavior.

## Testing Strategy
- Migration tests:
  - profile table creation
  - deterministic session ownership backfill
  - deterministic run profile-key backfill
  - migrated historical agent creation for distinct legacy `agent_id` values
  - settings-backed historical-agent override mapping is applied when present
  - migration failure on one session with conflicting historical run owners
- Startup tests:
  - migrate, seed, then validate ordering
  - startup failure when configured default agent is missing or disabled after seeding or validation
- Session-service tests:
  - new session uses bootstrap default agent
  - existing session keeps durable owner after `default_agent_id` changes
  - inbound request fails closed before transcript mutation when owner agent is disabled or invalid
- Scheduler tests:
  - existing session target uses persisted owner
  - routing-tuple target reuses or creates a `primary` session only
  - disabled owner blocks run creation
  - scheduled-job `agent_id` mismatch against resolved owner fails closed
- Worker tests:
  - queued run uses persisted profile keys and resolved binding during execution
  - queued run does not silently drift to newly linked agent profiles after queue time
  - disabled linked profiles fail closed before graph invocation
  - two enabled agents can resolve different model profiles without changing graph topology
- Admin and diagnostics tests:
  - new session metadata appears on read surfaces
  - agent and model-profile endpoints are operator-protected
  - run diagnostics expose persisted profile keys

## Implementation Sequence
1. Add settings registry types and validation for policy and tool profiles.
2. Add database models, migration, and backfill logic for profiles, session ownership, and run profile keys.
3. Add `src/agents/` repository, service, and bootstrap validation or seeding.
4. Refactor session creation and scheduler submission to resolve durable ownership before transcript mutation and run creation.
5. Refactor run creation and worker execution to persist and consume `AgentExecutionBinding`.
6. Refactor provider, policy, and tool binding to use the resolved binding rather than process-wide defaults.
7. Extend admin and diagnostics surfaces.
8. Add migration, unit, and integration coverage, then run targeted test suites for sessions, jobs, provider runtime, diagnostics, and the new spec coverage.

## Review Notes
- The highest-risk area is migration correctness because pre-014 data can contain legacy `agent_id` diversity on `execution_runs` while `sessions` currently have no owner column. The plan therefore makes backfill logic and conflict failure explicit before any runtime refactor.
- The second highest-risk area is partial refactoring in `apps/gateway/deps.py`. If the implementation only adds durable tables but leaves model and policy construction global, Spec 014 will appear complete in the schema while still violating runtime invariants. The plan keeps runtime binding as a first-class workstream to avoid that trap.
- The cleanest additive seam is a new `src/agents/` package plus a typed `AgentExecutionBinding`; that keeps Specs 001 through 013 stable while giving Spec 015 a durable foundation for child sessions and delegation records later.
