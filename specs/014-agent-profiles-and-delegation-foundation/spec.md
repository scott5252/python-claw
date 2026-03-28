# Spec 014: Agent Profiles and Delegation Foundation

## Purpose
Add durable agent identity, agent-owned session metadata, and per-agent execution profile resolution so the runtime can support specialist assistants safely later without yet implementing delegation orchestration.

## Non-Goals
- Creating delegation records, delegation tools, or child-run orchestration
- Changing the canonical routing tuple or session-key rules from Spec 001
- Introducing provider-auth rotation or multi-credential failover
- Adding human handoff, reassignment workflows, or operator takeover state
- Implementing prompt-only hidden helpers or any model-controlled spawning behavior
- Replacing the existing approval, sandbox, or streaming contracts rather than binding them to explicit agent ownership

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
- Spec 013

## Scope
- Durable `agent_profiles` records as the canonical registry of known agents
- Durable `model_profiles` records for per-agent model selection
- Settings-backed `policy_profiles` and `tool_profiles` registries keyed by stable profile keys referenced from `agent_profiles`
- Session ownership metadata so every session has a durable owning agent and a declared session kind
- Runtime resolution of effective agent, model, policy, and tool profiles before run creation and graph invocation
- Disabled-agent handling for new work and existing owned sessions
- Admin and diagnostics read surfaces for agents, model profiles, and agent-to-session relationships
- Migrations, backfill, and tests covering bootstrap behavior from the current single-agent system

## Current-State Baseline
- `src/config/settings.py` still exposes one global `default_agent_id` plus one global LLM configuration block.
- `src/sessions/service.py` creates new execution runs with `agent_id=self.default_agent_id` rather than resolving durable session ownership.
- `src/db/models.py` stores `agent_id` on `execution_runs` and several audit tables, but `sessions` do not yet record an owning agent, a parent session, or a session kind.
- `apps/gateway/deps.py` constructs one global model adapter and one policy service from application settings rather than from the current session owner.
- `src/providers/models.py` resolves provider settings from one `Settings` object, which is sufficient for one assistant but not for agent-specific model selection.
- `src/policies/service.py` and `src/tools/registry.py` support policy-aware tool binding, but there is no first-class profile layer that binds different tool or policy envelopes to different agents.

## Data Model Changes
- `agent_profiles`
  - `agent_id` primary key
  - `display_name`
  - `role_kind`
  - `description` nullable
  - `default_model_profile_id` foreign key to `model_profiles.id`
  - `policy_profile_key`
  - `tool_profile_key`
  - `enabled`
  - `created_at`
  - `updated_at`
  - optional `disabled_at`
  - required indexes
    - unique index on `agent_profiles(agent_id)`
    - lookup index on `agent_profiles(enabled, role_kind)`
    - lookup index on `agent_profiles(default_model_profile_id)`
- `model_profiles`
  - `id`
  - `profile_key` unique
  - `runtime_mode` with values `rule_based` or `provider`
  - `provider` nullable and required when `runtime_mode=provider`
  - `model_name` nullable and required when `runtime_mode=provider`
  - `temperature` nullable
  - `max_output_tokens` nullable
  - `timeout_seconds`
  - `tool_call_mode`
  - `streaming_enabled`
  - `enabled`
  - `created_at`
  - `updated_at`
  - optional `base_url` nullable for bounded provider override support
  - required indexes
    - unique index on `model_profiles(profile_key)`
    - lookup index on `model_profiles(enabled, runtime_mode)`
- `sessions`
  - add `owner_agent_id` non-null foreign key to `agent_profiles.agent_id`
  - add `session_kind` with values `primary`, `child`, `system`
  - add `parent_session_id` nullable foreign key to `sessions.id`
  - required indexes
    - lookup index on `sessions(owner_agent_id, created_at)`
    - lookup index on `sessions(parent_session_id, created_at)`
    - lookup index on `sessions(session_kind, created_at)`
- `execution_runs`
  - keep existing `agent_id` as the denormalized execution owner
  - add `model_profile_key` nullable during backfill and non-null for new rows
  - add `policy_profile_key` nullable during backfill and non-null for new rows
  - add `tool_profile_key` nullable during backfill and non-null for new rows
  - required indexes
    - lookup index on `execution_runs(agent_id, created_at)`
    - lookup index on `execution_runs(model_profile_key, created_at)`
- Existing Spec 006 tables
  - `agent_sandbox_profiles.agent_id` becomes the canonical sandbox-profile owner key for `agent_profiles.agent_id`
  - this spec may add a foreign key if the migration path is safe for current seeded data; otherwise the implementation must enforce referential integrity in repositories and service validation

## Settings and Registry Changes
- Keep `default_agent_id`, but narrow its meaning:
  - it is only the bootstrap resolver for creating a new `primary` session when no durable session exists yet and no future routing override is configured
  - it is no longer the runtime source of truth for existing session ownership
- Add settings-backed `policy_profiles` registry keyed by `policy_profile_key`
  - each profile must be explicit and fail closed when missing
  - each profile must define bounded runtime policy flags needed in this slice, including at minimum:
    - `remote_execution_enabled`
    - optional denied capability names
    - optional future-facing `delegation_enabled`, defaulting to `false`
- Add settings-backed `tool_profiles` registry keyed by `tool_profile_key`
  - each profile contains an explicit allowlist of capability names
  - tool visibility is the intersection of:
    - tool registry membership
    - tool profile allowlist
    - policy profile rules
    - channel and runtime context checks already enforced by earlier specs
- Provider credentials remain settings-only inputs and must not be duplicated into database rows for `agent_profiles` or `model_profiles`

## Contracts
### Agent Registry Contract
- `AgentProfileService` or equivalent is the sole resolver for agent identity, model profile lookup, policy profile lookup, and tool profile lookup.
- `agent_profiles` are the durable source of truth for whether an agent exists and whether it is enabled.
- Agent profiles referenced by sessions, runs, approvals, or sandbox rows must be soft-disabled rather than hard-deleted in this spec.
- Every enabled agent must reference:
  - one enabled `model_profile`
  - one valid settings-backed `policy_profile_key`
  - one valid settings-backed `tool_profile_key`
- Missing or disabled linked profiles must fail closed during validation and before runtime execution begins.

### Session Ownership Contract
- Every session must carry one durable `owner_agent_id`.
- Every session must carry one `session_kind`:
  - `primary` for normal user-facing conversations
  - `child` reserved for future delegated specialist sessions
  - `system` for scheduler or other internal sessions that are not user-facing primary conversations
- `parent_session_id` rules:
  - `primary` sessions must have `parent_session_id=null`
  - `child` sessions must have non-null `parent_session_id`
  - `system` sessions may have `parent_session_id=null` in this spec
- Spec 014 does not yet create delegation records, but it must make `child` session shape durable now so Spec 015 can build on stable ownership semantics.
- Session ownership is immutable in this spec after session creation.
- The canonical session key from Spec 001 remains unchanged and does not include `owner_agent_id`.
- Because the canonical session key remains unchanged in this slice, routing-tuple session resolution cannot create a parallel `system` session alongside an existing `primary` session for the same tuple.
- For existing routing tuples, the persisted session owner wins over current settings. Changing `default_agent_id` must not silently reassign existing sessions.

### Session Creation and Bootstrap Contract
- On inbound processing:
  - if the canonical session already exists, the gateway must use its persisted `owner_agent_id`
  - if the canonical session does not exist, the gateway must resolve the owner through the bootstrap resolver and create the session with that owner
- The bootstrap resolver for this slice may be settings-backed and return the configured `default_agent_id`
- Before any transcript mutation or run creation:
  - the resolved owner agent must exist
  - the owner agent must be enabled
  - the linked model profile must be enabled
  - the linked policy and tool profile keys must resolve successfully
- For a first-time canonical session, owner resolution and validation must complete before inserting the `sessions` row so invalid bootstrap ownership cannot create an empty or partially initialized session.
- If the resolved owner agent is disabled or invalid, the request must fail closed and must not append a new transcript row or create an execution run.

### Run Creation Contract
- `execution_runs.agent_id` must always equal the owning session’s `owner_agent_id`.
- New `execution_runs` rows must also persist the resolved `model_profile_key`, `policy_profile_key`, and `tool_profile_key` used for that run.
- For runs attached to an existing session, the run profile keys must come from the owning session’s current agent profile at queue time.
- Queued execution must use the persisted run profile keys as the execution-profile identity for that run rather than silently switching to whatever profile links the agent points to later.
- Worker-time validation must still fail closed if:
  - the owning agent is now disabled
  - any persisted run profile key no longer resolves
  - any persisted linked profile is now disabled
- For new session creation plus run creation in the same request path, session owner resolution and run profile resolution must occur in one transaction boundary before the run is returned.
- Scheduler-created work must also resolve through explicit agent ownership:
  - if targeting an existing session, the session owner is authoritative
  - if targeting a routing tuple in this slice, the scheduler must reuse or create the canonical session for that tuple as a `primary` session
  - creation of new `system` sessions is not permitted through routing-tuple resolution in this slice
  - `system` sessions may exist only when explicitly created through an internal control-plane path or when a scheduler job targets an already-known `session_id`
  - when `scheduled_jobs.agent_id` is present, it must match the resolved owner or the submission must fail closed before transcript mutation or run creation

### Runtime Binding Contract
- Graph assembly and invocation must consume an `AgentExecutionBinding` or equivalent typed structure containing at minimum:
  - `agent_id`
  - `session_kind`
  - `model_profile_key`
  - `policy_profile_key`
  - `tool_profile_key`
  - bounded resolved model settings needed by the model adapter
- `apps/gateway/deps.py` must no longer construct one global runtime model or policy configuration that ignores session ownership.
- The runtime must resolve the execution binding per run before graph invocation.
- `AssistantState` or equivalent runtime state must carry the resolved profile keys for observability and deterministic tool binding.

### Model Profile Contract
- `model_profiles` define the bounded runtime model configuration for a run.
- Supported `runtime_mode` values in this slice are:
  - `rule_based`
  - `provider`
- When `runtime_mode=provider`, the profile must specify:
  - `provider`
  - `model_name`
  - `timeout_seconds`
  - `tool_call_mode`
- Provider auth secrets remain outside the profile and must still resolve from deployment settings.
- A provider-backed model adapter must use the resolved model profile rather than the application-global default model fields.
- This spec does not require multi-provider credential routing; it requires only that the per-agent model selection seam become explicit and additive.

### Policy and Tool Profile Contract
- Tool visibility must be profile-driven.
- `tool_profile_key` resolves the explicit capability allowlist for the current agent.
- `policy_profile_key` resolves runtime policy flags and denials for the current agent.
- Capability exposure must fail closed if:
  - the tool profile key is unknown
  - the policy profile key is unknown
  - the requested capability is not allowlisted by the tool profile
  - policy rules deny the capability
- Exact approval matching from Spec 003 remains scoped to the execution `agent_id`. This spec does not introduce approval inheritance or profile-based approval broadening.

### Sandbox Linkage Contract
- Sandbox resolution remains owned by Spec 006 services.
- The current run’s `agent_id` remains the identity used to resolve `agent_sandbox_profiles`.
- Spec 014 must ensure sandbox resolution now uses the durable owning agent rather than a global default agent.
- If an enabled agent has no sandbox profile row, the existing Spec 006 fallback rules still apply unless later policy denies that mode.

### Admin and Diagnostics Contract
- Extend session read surfaces to expose:
  - `owner_agent_id`
  - `session_kind`
  - `parent_session_id`
- Add admin read surfaces for:
  - `GET /agents`
  - `GET /agents/{agent_id}`
  - `GET /agents/{agent_id}/sessions`
  - `GET /model-profiles`
  - `GET /model-profiles/{profile_key}`
- Diagnostics must expose the resolved execution profile for each run:
  - `agent_id`
  - `model_profile_key`
  - `policy_profile_key`
  - `tool_profile_key`
- Diagnostics for an agent must be able to answer:
  - whether the agent is enabled
  - which model profile it uses
  - which policy and tool profile keys it references
  - whether a sandbox profile exists for that agent
  - which sessions are currently owned by that agent

## Runtime Invariants
- Every session has exactly one durable owner agent.
- Every execution run uses the owning session’s agent identity.
- Existing sessions keep their owner even if `default_agent_id` changes later.
- New primary sessions cannot be created for disabled or invalid agents.
- Tool binding and policy binding are resolved from the current run’s owning agent, not from process-wide defaults.
- Queued runs execute against their persisted profile-key identity and do not silently drift to newly linked agent profiles after queue time.
- Sandbox identity remains exact to the resolved `agent_id`.
- Session kinds are explicit now even though `child` sessions are not yet orchestrated in this spec.

## Security Constraints
- Unknown, disabled, or invalidly linked agents fail closed before transcript mutation or run creation.
- Missing policy or tool profiles fail closed.
- Provider credentials remain settings-only and are never persisted in agent or model profile tables.
- Approvals remain exact to `session_id` and `agent_id`; this spec must not weaken that invariant.
- Admin agent and model-profile surfaces require the same operator protections used by existing diagnostics endpoints.

## Operational Considerations
- The migration must backfill existing sessions using the safest deterministic ownership source available:
  - if a session has execution runs with exactly one distinct historical `agent_id`, backfill `owner_agent_id` to that agent id
  - if a session has no historical runs, backfill `owner_agent_id=<current default_agent_id>`
  - if a session has conflicting historical run agent ids, the migration must fail loudly rather than silently choosing an owner
- The migration must backfill `session_kind` deterministically:
  - all existing sessions must backfill to `session_kind=primary`
  - all existing sessions must backfill `parent_session_id=null`
  - new sessions created through inbound traffic or scheduler routing-tuple resolution in this slice must default to `session_kind=primary`
- The migration must backfill existing execution runs with `model_profile_key`, `policy_profile_key`, and `tool_profile_key` derived from a seeded or migrated `agent_profile` matching each run’s existing `agent_id`.
- When historical execution runs reference distinct `agent_id` values from before Spec 014:
  - the migration must create or seed one enabled `agent_profile` for each distinct historical `agent_id`
  - each migrated historical agent must default to the seeded default `model_profile_key`, `policy_profile_key`, and `tool_profile_key` unless an explicit operator-provided override map is supplied
  - the migration must not leave historical runs with null or unknown profile keys after backfill completes
- The application must seed at least one enabled default `agent_profile` and one enabled default `model_profile` that preserve current single-agent behavior, and it must also seed or migrate any additional distinct historical agent ids needed to satisfy referential integrity for backfilled sessions or runs.
- Seeded defaults must map cleanly to current behavior:
  - default agent id equals the existing `default_agent_id`
  - default model profile reflects the current global runtime settings
  - default policy and tool profile keys preserve the current capability exposure
- Startup/bootstrap order in this slice must be:
  - apply migrations
  - perform idempotent seeding for required default profiles and any historical-agent backfill records
  - run startup validation
- If startup validation finds that the configured default agent id does not exist or is disabled, startup must fail loudly rather than letting inbound traffic create invalid sessions.
- Historical runs may point to profile keys whose current settings-backed definitions have changed; diagnostics should expose both the persisted keys and the current resolved definitions when available.

## Implementation Gap Resolutions
### Gap 1: Global `default_agent_id` vs Durable Session Ownership
The current runtime uses one global default agent when creating runs. That is insufficient for specialist agents and would silently reassign behavior if configuration changes later.

Options considered:
- Option A: keep `default_agent_id` as the runtime truth and add agent profiles later
- Option B: store `owner_agent_id` only on `execution_runs`
- Option C: store `owner_agent_id` on `sessions` and treat `default_agent_id` only as the bootstrap owner resolver for new primary sessions
- Option D: add agent ownership only when delegation lands

Selected option:
- Option C

Decision:
- `sessions.owner_agent_id` becomes the durable source of truth for agent ownership.
- `default_agent_id` remains only the bootstrap resolver for creating a new primary session when no session yet exists.
- `execution_runs.agent_id` stays as a denormalized copy for run isolation, auditability, and Spec 003/006 exact-scoping behavior.

### Gap 2: Durable vs Settings-Backed Profile Sources
Different agents need different model, policy, and tool envelopes, but not every profile type needs the same storage strategy in this slice.

Options considered:
- Option A: store agent, model, policy, and tool profiles all in the database immediately
- Option B: keep everything in settings only
- Option C: store `agent_profiles` and `model_profiles` durably, and keep `policy_profiles` plus `tool_profiles` as validated settings-backed registries referenced by stable keys
- Option D: postpone all profile work until delegation is implemented

Selected option:
- Option C

Decision:
- Durable agent identity and model selection are required now, so `agent_profiles` and `model_profiles` are database-owned.
- Policy and tool profile definitions remain settings-backed in this slice because the current code already resolves those concerns in-process and they do not yet need independent mutation APIs.
- Agent profiles reference policy and tool registries by stable keys so diagnostics, validation, and future migration to durable storage remain straightforward.

### Gap 3: Session Kind Shape Before Delegation Exists
Spec 014 needs to prepare for future child sessions without prematurely implementing Spec 015 delegation flow.

Options considered:
- Option A: add only `owner_agent_id` now and defer session kind until delegation
- Option B: add `session_kind` and `parent_session_id` now, but keep child-session creation out of scope
- Option C: implement `delegations` now as part of the foundation
- Option D: use transcript artifacts to infer child relationships later

Selected option:
- Option B

Decision:
- This spec adds explicit session ownership shape now:
  - `session_kind`
  - `parent_session_id`
  - `owner_agent_id`
- Delegation lifecycle records remain deferred to Spec 015.
- `child` is a reserved durable session shape in this slice, not a full orchestration feature.

### Gap 4: Per-Agent Model Selection With a Global Model Adapter Today
The current provider seam is configured from one application settings object and therefore cannot safely vary by owning agent.

Options considered:
- Option A: continue using one global adapter and inject only `agent_id`
- Option B: resolve one typed execution binding per run and let the model adapter consume the binding’s resolved model profile
- Option C: build one long-lived adapter instance per agent at process startup
- Option D: require a different graph implementation per agent

Selected option:
- Option B

Decision:
- The runtime resolves an `AgentExecutionBinding` per run before graph invocation.
- The model adapter consumes the resolved model profile from that binding.
- This keeps graph topology shared while making model selection explicit, testable, and auditable.

### Gap 5: Agent-Specific Tool Exposure Without Duplicating Policy Logic
The repo already has a typed tool registry and policy service, but no profile layer determines which agent sees which tools.

Options considered:
- Option A: let agents differ only by model, not by tools or policy
- Option B: encode tool differences directly in prompt text
- Option C: add explicit `tool_profiles` and `policy_profiles` registries and resolve final capability exposure as an intersection
- Option D: create one custom registry object per agent inline in application wiring

Selected option:
- Option C

Decision:
- Each agent references a `tool_profile_key` and `policy_profile_key`.
- Final capability exposure is the intersection of registry membership, tool allowlist, policy rules, and existing channel/runtime checks.
- This foundation supports later delegation policy restrictions without rewriting the tool-binding seam.

### Gap 6: Disabled Agent Behavior for Existing Sessions
Once agent profiles become durable, the system must define what happens if a session already belongs to an agent that is later disabled.

Options considered:
- Option A: continue processing existing sessions for disabled agents forever
- Option B: silently swap the session to the new default agent
- Option C: fail closed for new work targeting sessions owned by a disabled agent, without rewriting history
- Option D: mutate old sessions during startup to another enabled agent

Selected option:
- Option C

Decision:
- Session history remains intact.
- New inbound work, scheduler fires, or other run-creation attempts for a disabled owner agent must fail closed before transcript mutation or run creation.
- Existing rows are not reassigned automatically.
- Admin surfaces must make disabled ownership visible so operators can remediate deliberately.

### Gap 7: Auditability of Historical Execution Profiles
If an agent changes its linked model, policy, or tool profile later, operators still need to know what profile keys were used for a historical run.

Options considered:
- Option A: rely only on current `agent_profiles`
- Option B: persist resolved profile keys on `execution_runs`
- Option C: persist the full profile definitions on every run row
- Option D: rely only on logs

Selected option:
- Option B

Decision:
- `execution_runs` persist `model_profile_key`, `policy_profile_key`, and `tool_profile_key`.
- Detailed current resolved definitions may still come from admin or diagnostics services, but the historical key identity is durable on the run.
- Worker execution uses those persisted keys as the run’s execution identity and must not silently swap to an agent’s newly linked profiles after queue time.

### Gap 8: Sandbox Profile Linkage
Spec 006 already added `agent_sandbox_profiles`, but current runtime behavior can still end up using the wrong agent if run creation is not ownership-driven.

Options considered:
- Option A: duplicate sandbox linkage into `agent_profiles`
- Option B: keep sandbox ownership keyed by `agent_id` and make durable session ownership the upstream source of that `agent_id`
- Option C: resolve sandbox mode from model profiles
- Option D: defer sandbox alignment until delegation

Selected option:
- Option B

Decision:
- `agent_sandbox_profiles` remain the sandbox source for this slice.
- Spec 014 fixes the missing upstream ownership guarantee by ensuring the resolved run `agent_id` always comes from the owning session’s durable agent profile.

### Gap 9: `system` Sessions vs Unchanged Canonical Routing Keys
This spec introduces `system` sessions while also preserving the Spec 001 canonical session key, so it must define whether routing-tuple resolution may create a distinct `system` session alongside the existing tuple-owned session.

Options considered:
- Option A: allow routing-tuple resolution to create `system` sessions by implicitly extending the key with hidden kind metadata
- Option B: keep routing-tuple resolution bound to the existing canonical session and reserve new `system` session creation for explicit internal creation paths or known `session_id` targets
- Option C: change the canonical session key now to include `session_kind`
- Option D: remove `system` sessions from this slice

Selected option:
- Option B

Decision:
- Routing-tuple resolution in this slice always reuses or creates the canonical tuple-owned `primary` session.
- New `system` sessions are allowed only through explicit internal creation flows or by targeting an already-known `session_id`.
- This keeps Spec 001 and Spec 005 stable while preserving `system` as a durable session shape for later use.

### Gap 10: Historical Agent Migration When Legacy Runtime Was Global
The pre-014 runtime was effectively single-profile even if historical rows contain multiple `agent_id` values, so the migration must define how those legacy agent ids map onto the new profile system.

Options considered:
- Option A: fail migration on any historical `agent_id` that is not the current `default_agent_id`
- Option B: auto-create enabled `agent_profiles` for each distinct historical `agent_id`, all defaulting to the seeded default model, policy, and tool profiles unless an explicit override map is supplied
- Option C: require an operator-authored mapping for every historical `agent_id`
- Option D: backfill agent ownership but leave legacy run profile keys null

Selected option:
- Option B

Decision:
- The migration must enumerate distinct historical `agent_id` values and create one enabled `agent_profile` for each.
- Unless the operator provides an explicit override map, each migrated historical agent defaults to the same seeded default model, policy, and tool profile keys that preserve current single-agent behavior.
- Legacy runs must receive non-null backfilled profile keys derived from the migrated agent profile for that `agent_id`.

### Gap 11: Deterministic `session_kind` Backfill
This spec adds a non-null `session_kind`, but historical rows predate any durable distinction between `primary`, `child`, and `system`.

Options considered:
- Option A: backfill all existing sessions to `primary` and default all new inbound or routing-tuple-created sessions in this slice to `primary`
- Option B: infer `system` from scheduler-authored messages or run history
- Option C: infer session kind from transcript artifacts and governance state
- Option D: allow null during migration and repair later

Selected option:
- Option A

Decision:
- All existing sessions backfill to `session_kind=primary` with `parent_session_id=null`.
- New sessions created through current inbound or scheduler routing-tuple flows also default to `primary` in this slice.
- `child` and `system` remain explicit durable shapes for future use, not inferred retrospective categories.

### Gap 12: Seed and Startup-Validation Ordering
The spec requires seeded default profiles and also requires startup failure when the configured default agent is missing or disabled, so it must define ordering on fresh or migrated databases.

Options considered:
- Option A: validate first and fail on empty databases
- Option B: require all seeding to happen completely out of band before app startup
- Option C: define startup/bootstrap order as migrate, idempotently seed required records, then validate
- Option D: lazily create the default agent at first request time

Selected option:
- Option C

Decision:
- Startup/bootstrap order is: apply migrations, idempotently seed required defaults and historical-agent rows, then run validation.
- Validation still fails closed if the resulting seeded state is invalid, incomplete, or disabled.
- Request-time lazy creation is not allowed.

### Gap 13: Scheduled Job Agent Identity vs Durable Session Ownership
`scheduled_jobs` already persist an `agent_id`, but this slice makes durable session ownership authoritative for existing sessions and bootstrap ownership authoritative for new routing-tuple sessions. The spec must define what happens if those identities disagree.

Options considered:
- Option A: keep `scheduled_jobs.agent_id` authoritative
- Option B: ignore `scheduled_jobs.agent_id` entirely
- Option C: keep `scheduled_jobs.agent_id` as additive metadata, but require it to match the resolved owner and fail closed on mismatch
- Option D: remove `scheduled_jobs.agent_id` in this slice

Selected option:
- Option C

Decision:
- `scheduled_jobs.agent_id` remains additive metadata in this slice.
- If a scheduled job targets an existing session, the persisted session owner remains authoritative.
- If a scheduled job targets a routing tuple, bootstrap ownership resolution remains authoritative for any newly created canonical `primary` session.
- When `scheduled_jobs.agent_id` is present, it must match the resolved owner for the targeted work; mismatches fail closed and must not append transcript rows or create runs.

### Gap 14: Invalid First-Time Owner Resolution and Empty Session Rows
This slice requires owner validation before transcript mutation and run creation, but the current repository shape can create a session row before that validation happens. The spec must define whether invalid ownership is allowed to leave behind an empty session.

Options considered:
- Option A: allow empty session rows to remain after failed owner validation
- Option B: resolve and validate owner identity before inserting a new session row
- Option C: create the session row first and delete it on failure
- Option D: create a partial session state for later repair

Selected option:
- Option B

Decision:
- For a first-time canonical session, the runtime must resolve and validate owner identity before inserting the `sessions` row.
- Invalid bootstrap ownership must fail closed without creating an empty or partially initialized session.

### Gap 15: Historical-Agent Override Mapping Shape
The migration allows optional operator overrides for historical `agent_id` rows, but this slice needs one concrete contract for where that mapping lives and what it can override.

Options considered:
- Option A: remove override support and always map historical agents to the default profiles
- Option B: define a settings-backed override map keyed by legacy `agent_id` with explicit profile-key overrides
- Option C: require manual database edits before migration
- Option D: add an interactive admin migration flow

Selected option:
- Option B

Decision:
- Historical-agent override mapping is settings-backed in this slice.
- The mapping is keyed by legacy `agent_id` and may explicitly override seeded default linkage for:
  - model profile selection
  - `policy_profile_key`
  - `tool_profile_key`
- If no override exists for a historical `agent_id`, migration falls back to the seeded default profile linkage that preserves current single-agent behavior.

## Acceptance Criteria
- The system stores at least one durable `agent_profile` and one durable `model_profile` that preserve current single-agent behavior after migration.
- Every session has an `owner_agent_id`, `session_kind`, and valid parent-session semantics for its kind.
- The migration handles historical non-default `agent_id` rows safely and fails loudly if one session has conflicting historical run owners.
- Historical sessions backfill deterministically to `session_kind=primary` and `parent_session_id=null`.
- Existing sessions remain bound to their backfilled owner even if `default_agent_id` changes later.
- New runs persist `agent_id`, `model_profile_key`, `policy_profile_key`, and `tool_profile_key` resolved from the owning session’s agent profile.
- Queued runs execute using their persisted profile keys and fail closed if those persisted keys become invalid or disabled before execution.
- The runtime chooses model settings, tool exposure, and policy behavior from the owning agent profile rather than from one global default.
- Disabled agents cannot receive new work through inbound or scheduler-driven run creation.
- Invalid bootstrap ownership cannot create an empty first-time session row.
- Scheduler routing-tuple resolution does not create new `system` sessions in this slice.
- Admin endpoints can list agent profiles, retrieve agent details, and list sessions owned by an agent.
- Session read endpoints expose agent ownership metadata.
- Diagnostics surfaces can show the effective execution profile keys for a run and the current linked profile details for an agent.
- Remote execution and approval checks continue to use the exact resolved `agent_id` with no approval broadening.

## Test Expectations
- Migration tests covering:
  - creation of `agent_profiles` and `model_profiles`
  - backfill of existing sessions with `owner_agent_id` and `session_kind`
  - backfill of existing runs with resolved profile keys
  - creation of migrated `agent_profiles` for distinct legacy `agent_id` values using default profile linkage when no override map is supplied
  - failure when one historical session has conflicting run agent ids
- Migration and service tests proving scheduler routing-tuple resolution reuses or creates `primary` sessions rather than creating parallel `system` sessions
- Migration tests proving settings-backed historical-agent overrides are applied when present
- Startup tests proving bootstrap order is migrate, seed, then validate
- Startup or service tests proving invalid bootstrap owner resolution does not create an empty session row
- Unit tests for agent-profile validation:
  - missing linked model profile
  - disabled linked model profile
  - unknown policy profile key
  - unknown tool profile key
- Unit tests for session bootstrap behavior:
  - new primary session uses configured default agent
  - existing session keeps its durable owner after `default_agent_id` changes
- Unit tests for disabled-agent handling:
  - inbound processing fails closed for a disabled owner agent
  - scheduler run creation fails closed for a disabled owner agent
- Unit tests proving scheduled-job `agent_id` mismatches fail closed against the resolved owner
- Unit tests for per-agent tool exposure showing two enabled agents can bind different tool sets from the same registry
- Unit tests for per-agent policy resolution showing remote execution or other denied capabilities differ by policy profile
- Unit tests for model binding showing two agents can resolve different model profiles without changing graph topology
- Worker tests proving queued runs keep their persisted profile-key identity even if the owning agent later points at different profiles
- Integration tests for inbound message processing proving:
  - session owner is written on first creation
  - execution run uses the session owner
  - run profile keys match the owning agent profile
- Integration tests proving sandbox resolution still uses the exact run `agent_id`
- API tests for:
  - `GET /agents`
  - `GET /agents/{agent_id}`
  - `GET /agents/{agent_id}/sessions`
  - extended `GET /sessions/{session_id}`
  - `GET /model-profiles`
  - `GET /model-profiles/{profile_key}`
- Diagnostics tests proving run detail responses include persisted profile keys and agent detail responses show current linked profile information
