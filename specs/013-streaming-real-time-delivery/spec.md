# Spec 014: Agent Profiles And Delegation Foundation

> Stored in `specs/013-streaming-real-time-delivery` per request. This document defines roadmap Spec 014 from `docs/features_plan.md`.

## Purpose
Make agent identity a durable first-class backend concept so sessions, runs, context assembly, policy binding, model selection, and sandbox resolution no longer depend on one global `default_agent_id`. This slice establishes the database and runtime foundation required for future specialist agents and child-session delegation, while intentionally stopping short of implementing delegation orchestration itself.

## Non-Goals
- Implementing parent-to-child delegation tools or any `delegate_task` workflow
- Creating child sessions automatically from model output
- Adding delegation lineage tables or sub-agent execution state machines from planned Spec 015
- Adding human handoff, assignment UX, or operator collaboration workflows
- Changing the existing gateway-first, worker-owned, append-only execution architecture
- Replacing current tool, approval, memory, retrieval, or delivery models beyond the agent-resolution inputs they consume

## Upstream Dependencies
- Spec 001
- Spec 002
- Spec 003
- Spec 004
- Spec 005
- Spec 006
- Spec 007
- Spec 008
- Spec 009
- Spec 010
- Spec 011
- Spec 012

## Scope
- Add a durable agent-profile registry so runtime behavior no longer depends only on `Settings.default_agent_id`
- Introduce explicit model-profile and policy-profile records or equivalent durable registry rows linked from each enabled agent profile
- Fold existing per-agent sandbox configuration into the same durable agent-identity model instead of leaving it as an isolated side table with no primary agent registry
- Extend `sessions` so every session has an owning agent and a declared session relationship kind suitable for future child or system sessions
- Update inbound session creation, scheduler session creation, execution-run creation, graph invocation, context assembly, and dispatcher-owned post-turn work so they consistently resolve behavior from the owning agent profile
- Add read-only admin and diagnostics surfaces for agent profiles, model or policy linkage, enabled state, and agent-to-session relationships
- Add migrations, seed or bootstrap behavior, and tests for agent lookup, disabled agents, profile linkage, and fail-closed runtime behavior

## Current-State Baseline
- Inbound runs are currently created with one configured default agent in [src/sessions/service.py](/Users/scottcornell/src/my-projects/python-claw/src/sessions/service.py).
- `sessions` currently have no durable `agent_id`, `owner_agent_id`, `parent_session_id`, or `session_kind` fields in [src/db/models.py](/Users/scottcornell/src/my-projects/python-claw/src/db/models.py).
- `execution_runs`, governance records, node-execution audits, and sandbox profiles already persist `agent_id`, but they treat it as a free-form string rather than a foreign-key-backed identity.
- Graph invocation, context assembly, policy lookup, and sandbox resolution already accept `agent_id` inputs, which means the runtime seam is present but the agent source of truth is not.
- Admin and diagnostics routes can already filter runs by `agent_id`, but there is no read surface for agent profile definitions or for which agent owns a session.
- `agent_sandbox_profiles` already exist from Spec 006, but they are not anchored to an explicit `agent_profiles` registry.

## Data Model Changes
### `agent_profiles`
- `agent_id` primary key
- `display_name`
- `description`
- `agent_kind` with values `primary`, `specialist`, or `system`
- `status` with values `enabled` or `disabled`
- `default_model_profile_id`
- `policy_profile_id`
- `tool_profile_id` nullable in this slice if tool policy remains settings-backed or policy-derived
- `sandbox_profile_id` nullable when no explicit sandbox profile applies
- `is_default` boolean with at most one active default profile
- `created_at`
- `updated_at`
- Required indexes:
  - unique index on `is_default` where `is_default=true`
  - lookup index on `(status, agent_kind)`

### `model_profiles`
- `id` primary key
- `provider`
- `model_name`
- `temperature`
- `max_output_tokens`
- `timeout_seconds`
- `max_retries`
- `tool_call_mode`
- `enabled`
- `created_at`
- `updated_at`
- Notes:
  - this slice makes model choice durable and agent-bound
  - provider credentials still remain deployment settings, not database rows

### `policy_profiles`
- `id` primary key
- `profile_key` unique stable identifier
- `display_name`
- `description`
- `remote_execution_enabled`
- `approval_mode`
- `allowed_channel_kinds_json`
- `tool_allowlist_json`
- `delegation_enabled` boolean default `false`
- `max_delegation_depth` integer default `0`
- `enabled`
- `created_at`
- `updated_at`
- Notes:
  - `delegation_enabled=false` and `max_delegation_depth=0` are mandatory in this slice because actual delegation is out of scope but future policy shape must be reserved now

### `agent_sandbox_profiles`
- Preserve the existing table from Spec 006 but anchor it to the durable registry
- Replace free-form uniqueness assumptions with a foreign-key-backed relationship from `agent_profiles.sandbox_profile_id` or keep one-to-one by `agent_id` with an explicit foreign key to `agent_profiles.agent_id`
- The selected implementation must leave one canonical path for sandbox resolution by current agent profile

### `sessions`
- Add `owner_agent_id` non-null foreign key to `agent_profiles.agent_id`
- Add `session_kind` non-null with values:
  - `primary`
  - `child`
  - `system`
- Add `parent_session_id` nullable foreign key to `sessions.id`
- Add `origin_kind` nullable, bounded operational field with values such as `inbound`, `scheduler`, or `system`
- Required indexes:
  - lookup index on `(owner_agent_id, created_at)`
  - lookup index on `(parent_session_id, created_at)`
  - lookup index on `(session_kind, created_at)`
- Invariant:
  - `parent_session_id` must be null for `primary` and `system`
  - `parent_session_id` remains nullable for all sessions in this slice because child-session creation is deferred

### Existing `execution_runs`, governance, and diagnostics-linked tables
- Prefer additive foreign-key constraints or validation discipline rather than broad schema rewrites
- `execution_runs.agent_id`, governance proposal `agent_id`, and node execution audit `agent_id` must resolve to an enabled or historically valid agent profile rather than arbitrary strings
- Historical runs and approvals must remain queryable even if an agent is later disabled

## Contracts
### Agent Resolution Contract
- `AgentProfileService` or equivalent runtime component becomes the sole source for resolving agent identity and effective runtime configuration.
- It must support:
  - get enabled profile by `agent_id`
  - get the default enabled profile
  - resolve the effective model profile, policy profile, and sandbox profile for a given agent
  - fail closed when required linked profiles are missing or disabled
- No runtime path may fabricate an `agent_id` ad hoc once this spec lands.

### Session Ownership Contract
- Every session must have exactly one `owner_agent_id`.
- Inbound user sessions created through `SessionService.process_inbound(...)` resolve `owner_agent_id` from the default enabled agent profile in this slice.
- Scheduler-created sessions or scheduler fires may target a specific `agent_id`, but the session and all created runs must agree on the resolved owning agent.
- Existing sessions created before this migration must be backfilled to the default agent profile.
- The session owner becomes the canonical agent source for:
  - new execution runs created for that session
  - context assembly
  - graph invocation
  - policy binding
  - model-profile selection
  - sandbox resolution
  - operator diagnostics concerning the session

### Execution Run Contract
- `execution_runs.agent_id` remains denormalized operational state but must be sourced from the owning session agent or an explicitly targeted scheduler agent validated against the registry.
- A run may not be created for a disabled agent profile.
- For normal session work, `execution_runs.agent_id` must equal `sessions.owner_agent_id`.
- Future delegation may create parent and child sessions with different owners, but this spec does not allow one session to switch owners midstream.

### Model Profile Contract
- Runtime model selection must move from global settings-only selection to agent-resolved profile selection.
- The provider adapter boundary in [src/providers/models.py](/Users/scottcornell/src/my-projects/python-claw/src/providers/models.py) remains intact, but the selected provider and model settings must come from the resolved model profile plus deployment credentials.
- Credentials, secrets, and base URLs remain deployment-configured, not stored in model-profile rows.
- A disabled or missing model profile must fail the run safely before provider invocation.

### Policy Profile Contract
- Tool exposure, governed-action eligibility, and future delegation permissions must resolve from the session owner’s linked policy profile.
- Deterministic approval and revocation handling remain in [src/policies/service.py](/Users/scottcornell/src/my-projects/python-claw/src/policies/service.py).
- This slice may keep current tool-governance logic internally, but the selected policy profile must become the explicit runtime input that decides what the policy service exposes or denies.
- A disabled or missing policy profile must fail closed before model or tool execution begins.

### Sandbox Profile Contract
- Sandbox resolution continues to work through [src/sandbox/service.py](/Users/scottcornell/src/my-projects/python-claw/src/sandbox/service.py), but profile lookup must be anchored in the resolved agent profile rather than a free-floating `agent_id` string assumption.
- Existing Spec 006 behavior for `off`, `shared`, and `agent` sandbox modes remains unchanged.
- This slice does not add per-run sandbox overrides or child-session sandbox inheritance rules beyond reserving clean ownership boundaries for Spec 015.

### Diagnostics and Admin Contract
- Add read-only admin surfaces for:
  - listing agent profiles
  - reading one agent profile
  - listing sessions for an agent
  - listing agent-to-session relationships, including `session_kind` and `parent_session_id`
- Extend diagnostics so operator views can explain:
  - which model profile, policy profile, and sandbox profile were resolved for a run
  - whether the agent profile was enabled, disabled, or degraded at run time
  - whether a failure came from missing linked profiles or invalid agent resolution
- Secrets and provider credentials remain excluded from diagnostics.

## Implementation Gap Resolutions
### Gap 1: Agent identity exists operationally but not durably
Options considered:
- Option A: keep `agent_id` as a settings-only string and document conventions better
- Option B: add only session-level `owner_agent_id` and no registry
- Option C: add a durable `agent_profiles` registry with linked model, policy, and sandbox profile resolution
- Option D: defer all agent identity work until full delegation lands

Selected option:
- Option C

Decision:
- This spec introduces a durable agent registry and makes it the canonical source of runtime identity.
- Session ownership, run creation, diagnostics, and future delegation work all build on that registry.

### Gap 2: Session ownership is currently ambiguous
Options considered:
- Option A: keep sessions agent-agnostic and resolve agent only at run creation time
- Option B: store only `agent_id` on `execution_runs`
- Option C: persist one `owner_agent_id` on `sessions` and treat it as the source of truth for normal session work
- Option D: allow sessions to switch owning agents over time

Selected option:
- Option C

Decision:
- Sessions gain explicit ownership and a lightweight session-kind model.
- This gives Spec 015 a clean place to attach child sessions later without making current sessions mutable or ambiguous.

### Gap 3: Model selection needs durable linkage without storing secrets in the database
Options considered:
- Option A: keep all model settings global in `Settings` and let agents differ only by prompt wording
- Option B: persist API credentials per agent in the database
- Option C: persist non-secret model profile settings durably and combine them with deployment-managed credentials at runtime
- Option D: let every run pick an arbitrary model profile ad hoc

Selected option:
- Option C

Decision:
- Model profiles become durable configuration records for agent behavior.
- Secrets remain deployment-owned settings and are never copied into profile rows or diagnostics.

### Gap 4: Policy scoping needs to become explicit before delegation exists
Options considered:
- Option A: keep one global policy service with no agent-linked profile concept
- Option B: put policy details directly on `agent_profiles`
- Option C: add linked `policy_profiles` so policy selection is explicit and reusable
- Option D: defer policy-profile work until delegation tools exist

Selected option:
- Option C

Decision:
- A dedicated policy-profile layer is introduced now so tool sets, remote execution eligibility, and future delegation permissions can vary by agent without rewriting runtime seams later.

### Gap 5: Existing sandbox profile rows already use `agent_id` and must not be stranded
Options considered:
- Option A: leave sandbox profiles separate and continue resolving them by raw string
- Option B: migrate sandbox settings fully onto `agent_profiles` and delete the Spec 006 table
- Option C: preserve the Spec 006 table but anchor it to the new durable agent registry through a canonical relationship
- Option D: defer sandbox alignment to a later spec

Selected option:
- Option C

Decision:
- The Spec 006 sandbox profile contract remains intact, but its identity becomes registry-backed.
- This avoids breaking remote execution while still making agent ownership first-class.

### Gap 6: Default-agent behavior must remain bootstrap-friendly
Options considered:
- Option A: require operators to create an agent profile manually before the app can start
- Option B: keep `default_agent_id` forever as the real runtime source of truth
- Option C: keep `default_agent_id` only as bootstrap seed input used to create or validate one default enabled agent profile
- Option D: hard-code a default agent profile in application code

Selected option:
- Option C

Decision:
- `Settings.default_agent_id` becomes bootstrap and compatibility input only.
- Runtime work resolves through the durable default enabled agent profile, not directly through settings.

### Gap 7: Disabled agents must not break historical state or operator visibility
Options considered:
- Option A: hard-delete agents and cascade their sessions and runs
- Option B: allow disabled agents to continue running existing sessions
- Option C: use soft disable semantics where existing historical records remain visible but new runs and new session creation fail closed for disabled agents
- Option D: rewrite historical runs to a fallback agent when a profile is disabled

Selected option:
- Option C

Decision:
- Agent profiles are never required to stay enabled forever.
- Disabled agents preserve historical queryability, but new work may not resolve to them.

### Gap 8: Future child-session support needs a session relationship shape now
Options considered:
- Option A: add no session relationship fields until full delegation is implemented
- Option B: add `parent_session_id` only when Spec 015 begins
- Option C: add `session_kind` and nullable `parent_session_id` now so current sessions gain durable ownership semantics and future child sessions can land additively
- Option D: represent child relationships only in a later delegation table

Selected option:
- Option C

Decision:
- This slice adds the minimum durable session relationship model needed to support future child sessions cleanly, without creating any delegation flow yet.

## Runtime Invariants
- Every session has exactly one owning agent profile.
- New inbound sessions resolve ownership through the default enabled durable agent profile.
- New runs for an existing session reuse the session owner.
- Disabled or missing linked profiles fail closed before model or tool execution.
- Session ownership is durable and does not change as part of ordinary message handling in this slice.
- Admin and diagnostics views can explain which agent profile a session or run used.
- The gateway remains the sole ingress path, the worker remains the executor, and the database remains the durable source of truth.

## Security Constraints
- Agent resolution failures must fail closed.
- Disabled agents may not receive new inbound or scheduler-created work.
- Missing linked model or policy profiles may not silently fall back to arbitrary defaults.
- Deployment credentials remain outside the database and outside diagnostics payloads.
- Policy-profile linkage must not weaken current approval enforcement or governed execution boundaries.
- Sandbox-profile linkage must not silently downgrade remote execution isolation.

## Operational Considerations
- Provide one additive migration path that backfills existing sessions and validates or seeds one default enabled agent profile before the runtime depends on it.
- Historical rows in `execution_runs`, governance tables, node execution audits, and summaries must remain readable after the registry becomes authoritative.
- Diagnostics should distinguish configuration errors such as missing default agent profile, disabled linked profile, or invalid session owner from provider or tool failures.
- Seed or bootstrap behavior must work in local development and CI without manual database setup beyond normal migrations.
- The implementation should prefer additive schema changes and staged runtime cutover so the application remains runnable throughout rollout.

## Acceptance Criteria
- The database contains a durable enabled default agent profile linked to valid model and policy profiles after migration or bootstrap.
- Every session row has `owner_agent_id` and `session_kind`, and pre-existing rows are backfilled safely.
- Inbound processing resolves the session owner from the durable default agent profile instead of using `Settings.default_agent_id` directly during run creation.
- Execution runs created for a session use that session’s `owner_agent_id`.
- Graph invocation, context assembly, policy binding, provider model selection, and sandbox resolution all consume the resolved owning agent profile.
- Disabled agents cannot receive new session or run creation, but historical runs and sessions remain readable.
- Missing linked model or policy profiles fail closed with bounded diagnostics rather than silently falling back.
- Operator read surfaces can list agent profiles and inspect agent-to-session ownership relationships.
- Existing single-agent behavior remains functionally intact when only one enabled default agent profile exists.

## Test Expectations
- Migration tests for registry creation, session backfill, default-agent seeding or validation, and sandbox-profile linkage preservation
- Repository tests for agent-profile lookup, enabled or disabled filtering, session ownership persistence, and model or policy linkage reads
- Session-service tests proving inbound session creation and run creation resolve through the durable default agent profile
- Scheduler tests proving explicit scheduler agent targeting validates against the registry and preserves session or run ownership rules
- Runtime tests proving graph invocation, context assembly, policy inputs, provider model selection, and sandbox lookup all use the resolved agent profile
- Failure-path tests for disabled agents, missing default agent profile, missing linked model profile, missing linked policy profile, and inconsistent session-owner or run-agent combinations
- API tests for new agent admin or diagnostics read surfaces and for existing session or run surfaces returning the new ownership metadata where appropriate
- Regression tests proving current single-agent flows still pass when one default enabled profile is configured
