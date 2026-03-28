# Plan 014: Agent Profiles And Delegation Foundation

> Stored in `specs/013-streaming-real-time-delivery` per request. This plan implements roadmap Spec 014 from `docs/features_plan.md`.

## Target Modules
- `README.md` only if the documented current architecture needs to mention durable agent ownership once implemented
- `apps/gateway/api/admin.py`
- `apps/gateway/deps.py`
- `src/config/settings.py`
- `src/db/models.py`
- `migrations/versions/`
- `src/domain/schemas.py`
- `src/sessions/service.py`
- `src/sessions/repository.py`
- `src/jobs/repository.py`
- `src/jobs/service.py`
- `src/context/service.py`
- `src/graphs/assistant_graph.py`
- `src/graphs/nodes.py`
- `src/graphs/state.py`
- `src/providers/models.py`
- `src/policies/service.py`
- `src/sandbox/service.py`
- `src/capabilities/repository.py`
- `src/observability/diagnostics.py`
- `src/observability/logging.py`
- `src/observability/failures.py`
- `tests/`

## Success Conditions
- The runtime gains a durable `agent_profiles` registry and no longer depends on `Settings.default_agent_id` as the direct source of execution identity.
- Sessions gain explicit `owner_agent_id`, `session_kind`, and nullable `parent_session_id`, with all existing rows backfilled safely.
- Model selection, policy binding, and sandbox resolution all flow from the resolved owning agent profile rather than from unrelated global or free-form `agent_id` inputs.
- Existing single-agent behavior remains intact when one enabled default profile exists.
- Disabled or misconfigured agent profiles fail closed for new work while historical rows remain readable.
- Operator-facing read surfaces can inspect agent profiles and agent-to-session relationships without exposing secrets.
- The slice prepares for future child sessions and delegation without implementing actual delegation tooling or orchestration.

## Migration Order
1. Define the durable profile model first:
   - `agent_profiles`
   - `model_profiles`
   - `policy_profiles`
   - any required linkage to existing `agent_sandbox_profiles`
2. Add additive session-ownership fields before runtime cutover:
   - `owner_agent_id`
   - `session_kind`
   - `parent_session_id`
   - optional bounded `origin_kind`
3. Backfill and bootstrap safely:
   - seed or validate one default enabled agent profile from compatibility settings
   - backfill existing sessions to that owner
   - verify existing run and sandbox rows remain resolvable
4. Introduce one agent-resolution service or repository seam:
   - resolve default enabled agent
   - resolve effective model, policy, and sandbox linkage
   - centralize enabled or disabled validation
5. Switch session creation and run creation to the resolved session owner rather than direct settings usage.
6. Thread agent-profile resolution through graph, context, provider, policy, and sandbox seams.
7. Add admin and diagnostics read surfaces after the underlying runtime state is stable.
8. Finish with failure-path and regression coverage proving single-agent compatibility and fail-closed behavior.

## Implementation Shape
- Preserve the current architecture:
  - gateway remains the only ingress
  - session service remains the owner of inbound session and run creation
  - worker remains the executor
  - graph remains provider- and tool-orchestration owner
  - policy and approvals remain backend-enforced
- Keep the first runtime cut small:
  - add durable registry and session ownership
  - keep default-agent semantics behaviorally identical for current deployments
  - resolve everything through the registry internally
- Reuse existing `agent_id`-accepting seams rather than redesigning runtime contracts:
  - graph invocation already accepts `agent_id`
  - context assembly already accepts `agent_id`
  - sandbox resolution already accepts `agent_id`
  - provider and policy seams can be extended additively with resolved profile data
- Avoid turning this slice into delegation work:
  - no delegation table
  - no child-session creation workflow
  - no `delegate_task` tool
  - only durable identity and ownership groundwork

## Service and Module Boundaries
### Settings and Bootstrap
- `src/config/settings.py`
  - keep `default_agent_id` as compatibility and bootstrap input only
  - add only minimal bootstrap settings if needed, such as default profile display name or default policy key
  - keep provider credentials and secrets deployment-owned
- Bootstrap rules:
  - if the default profile does not exist, migration or startup bootstrap creates it with linked default model and policy profiles
  - if it exists but is disabled or linked incorrectly, the runtime fails clearly

### Durable Registry and Session Ownership
- `src/db/models.py`
  - add durable agent, model, and policy profile records
  - add session ownership and relationship fields
  - add foreign keys and indexes conservatively so migrations stay additive
- `src/sessions/repository.py`
  - add repository helpers to:
    - read and list agent profiles
    - resolve the default enabled profile
    - read linked model or policy profile data
    - persist and fetch session owner metadata
    - list sessions by owner agent
- `src/sessions/service.py`
  - stop writing runs from `settings.default_agent_id` directly
  - resolve the session owner through the durable registry
  - ensure scheduler-targeted work validates agent ownership explicitly

### Runtime Resolution
- Introduce one explicit agent-resolution boundary, likely in `src/sessions/repository.py` or a new service helper, that can:
  - resolve default enabled agent
  - resolve effective model profile
  - resolve effective policy profile
  - resolve sandbox profile linkage
  - enforce enabled-state checks
- `apps/gateway/deps.py`
  - inject the new resolver or profile-aware dependencies once
  - stop building runtime pieces that implicitly assume one global direct agent string

### Graph, Policy, Provider, and Context
- `src/jobs/service.py`
  - continue using `run.agent_id` operationally
  - optionally enrich failure classification or logging when agent-profile resolution fails during run processing
- `src/context/service.py`
  - keep current assembly behavior but accept profile-linked policy or model metadata additively if needed
  - do not make context assembly query raw settings for agent behavior directly
- `src/providers/models.py`
  - accept effective model-profile settings as runtime input while keeping credential sourcing in `Settings`
  - preserve current provider adapter seam
- `src/policies/service.py`
  - make policy behavior explicitly profile-scoped rather than implicitly global
  - keep deterministic approval and revocation logic unchanged
- `src/sandbox/service.py` and `src/capabilities/repository.py`
  - resolve sandbox profile from the current durable agent profile path
  - preserve Spec 006 execution semantics

### Admin and Diagnostics
- `apps/gateway/api/admin.py`
  - add read-only agent-profile listing and detail endpoints
  - add agent-to-session relationship listing endpoints if kept on the same operator surface
- `src/domain/schemas.py`
  - add typed response models for agent profiles and session-owner views
- `src/observability/diagnostics.py`
  - add bounded inspection helpers for agent profiles and sessions by agent
  - enrich run diagnostics with resolved model, policy, and sandbox profile identifiers
- `src/observability/logging.py` and `src/observability/failures.py`
  - classify configuration failures such as disabled agent, missing linked profile, or invalid session owner distinctly from provider or tool failures

## Contracts to Implement
### Agent Registry Contract
- One durable registry owns agent identity.
- Every enabled agent must link to:
  - one enabled model profile
  - one enabled policy profile
  - zero or one sandbox profile path in this slice
- One and only one agent profile may be the default enabled profile used for ordinary inbound session creation.

### Session Ownership Contract
- `sessions.owner_agent_id` is required and becomes the canonical owner for normal session work.
- `execution_runs.agent_id` for standard session-triggered work must match `sessions.owner_agent_id`.
- `session_kind` is required even before child sessions exist so later specs can extend behavior additively.

### Runtime Resolution Contract
- The runtime must resolve behavior from the session owner or explicit validated scheduler target.
- Missing, disabled, or inconsistent profiles fail closed before model or tool execution.
- Runtime code must not silently fall back to unrelated settings defaults once a session exists.

### Historical Compatibility Contract
- Existing rows remain readable after migration.
- Historical runs and approvals remain inspectable even if an agent is later disabled.
- A deployment with one default profile behaves equivalently to today’s single-agent system.

## Risk Areas
- Backfilling sessions incorrectly and creating mismatches between `sessions.owner_agent_id` and historical `execution_runs.agent_id`
- Allowing two effective defaults through bootstrap or migration bugs
- Silently falling back to settings-based model selection when linked profiles are missing
- Treating disabled agents as hard deletes and breaking diagnostics or historical audit queries
- Stranding Spec 006 sandbox profiles by introducing a second inconsistent source of sandbox truth
- Adding admin surfaces that expose secrets or too much mutable configuration before write controls exist
- Letting future-facing delegation fields accidentally imply delegation is already supported

## Rollback Strategy
- Keep migrations additive where possible:
  - add profile and ownership tables or columns first
  - backfill safely
  - only then cut runtime reads over
- Preserve `default_agent_id` as compatibility bootstrap input during rollout so a temporary rollback can still run single-agent mode.
- Do not delete or rewrite historical `agent_id` values in runs, approvals, or node execution audits.
- If profile-linked model selection regresses, fall back temporarily to the seeded default model profile while keeping registry-backed agent ownership intact.

## Test Strategy
- Unit:
  - agent-profile lookup and enabled-state validation
  - default-profile resolution
  - model or policy profile linkage resolution
  - session ownership invariants
  - configuration-failure classification
- Repository:
  - session backfill correctness
  - listing sessions by owner agent
  - reading linked sandbox profile through the registry-backed path
  - preserving historical disabled-agent queryability
- Runtime:
  - inbound session creation through the durable default profile
  - run creation from session owner
  - scheduler validation for explicit agent targeting
  - provider model selection from linked model profile
  - policy scoping from linked policy profile
  - sandbox lookup from linked agent profile
- API and diagnostics:
  - list agent profiles
  - get one agent profile
  - list sessions for an agent
  - enriched run diagnostics with resolved profile identifiers
- Regression:
  - current single-agent inbound, tool, approval, retrieval, and delivery flows still succeed with one enabled default profile

## Constitution Check
- Gateway-first inbound handling remains unchanged.
- Worker-owned execution remains unchanged.
- Policy and approval enforcement remain backend-owned.
- Remote execution isolation remains tied to the same sandbox semantics from Spec 006.
- The slice adds durable identity and ownership without introducing hidden orchestration or model-owned delegation behavior.
