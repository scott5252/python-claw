# Tasks 014: Agent Profiles and Delegation Foundation

## Implementation Readiness Review

- The spec and plan are implementable against the current codebase, but the work must explicitly replace three still-global assumptions with durable per-session ownership:
  - `src/sessions/service.py` still creates inbound runs with `default_agent_id`
  - `src/jobs/service.py` still invokes the graph with only `run.agent_id` and no resolved execution binding
  - `apps/gateway/deps.py` still constructs one process-wide model adapter and one `PolicyService`
- The highest-risk implementation failures to guard against are:
  - migrating legacy sessions to an incorrect owner when historical runs disagree
  - adding durable tables but leaving runtime model, tool, or policy selection global
  - allowing existing sessions to silently change owners after `default_agent_id` changes
  - permitting disabled or invalid agents to append transcript rows before the request fails
  - persisting new sessions or runs without the profile keys required for diagnostics and deterministic replay
  - widening approval or sandbox behavior beyond the exact `agent_id` rules established by Specs 003 and 006
- The tasks below are structured to lock down migration and ownership invariants first, then add the new `src/agents/` seam, then wire inbound, scheduler, worker, and diagnostics flows through one typed execution binding.

## Tasks

1. Confirm the current ownership and runtime seams in `src/config/settings.py`, `src/db/models.py`, `src/sessions/repository.py`, `src/sessions/service.py`, `src/jobs/repository.py`, `src/jobs/service.py`, `apps/gateway/deps.py`, `src/providers/models.py`, `src/policies/service.py`, `src/tools/registry.py`, `src/graphs/state.py`, `src/graphs/nodes.py`, `src/observability/diagnostics.py`, and `apps/gateway/api/admin.py` so Spec 014 extends the existing session, queue, worker, and diagnostics architecture rather than introducing a parallel runtime path.
2. Add high-risk migration tests first proving session ownership backfill adopts the sole historical `execution_runs.agent_id`, uses `default_agent_id` only when a session has no runs, backfills `session_kind=primary` and `parent_session_id=null`, and fails loudly when one session has conflicting historical run owners.
3. Add high-risk migration tests first proving historical run profile-key backfill derives from the migrated or seeded durable agent profile, creates enabled default records that preserve the current single-agent behavior, and does not persist provider credentials into durable tables.
4. Add high-risk session-service tests first proving a new canonical session is created with a bootstrap-resolved owner, an existing session keeps its persisted owner after `default_agent_id` changes, and disabled or invalid owners fail closed before transcript mutation, attachment staging, or run creation.
5. Add high-risk worker tests first proving queued runs reload and validate a durable execution binding before graph invocation, execute against their persisted profile-key identity rather than silently drifting to newly linked agent profiles, disabled linked profiles fail closed for queued work, and two enabled agents can execute with different model profiles or capability envelopes without changing graph topology.
6. Extend `src/config/settings.py` with typed settings-backed registries for `policy_profiles` and `tool_profiles`, including validation for duplicate keys, blank keys, invalid capability allowlists, and additive policy flags such as `remote_execution_enabled`, denied capabilities, and future-facing `delegation_enabled` defaulting to `false`.
7. Add a settings-backed historical-agent override registry keyed by legacy `agent_id` so migrations can override default model, policy, and tool linkage deterministically when needed.
8. Preserve current single-agent behavior in settings by defining a default policy profile and default tool profile that mirror today’s capability exposure, while keeping provider credentials and auth material settings-only and out of durable profile rows or diagnostics payloads.
9. Extend `src/db/models.py` and add a migration under `migrations/versions/` for the additive durable profile contract:
   - add `model_profiles` with enabled state, bounded runtime model settings, and the required unique and lookup indexes
   - add `agent_profiles` with soft-disable fields, linkage to `model_profiles`, settings-backed `policy_profile_key` and `tool_profile_key`, and the required indexes
   - extend `sessions` with nullable backfill columns for `owner_agent_id`, `session_kind`, and `parent_session_id`
   - extend `execution_runs` with nullable backfill columns for `model_profile_key`, `policy_profile_key`, and `tool_profile_key`
   - add enums or validated string domains, non-null constraints, foreign keys, and final indexes only after backfill succeeds
10. Implement the migration backfill and seed logic so startup data preserves current behavior:
   - seed one default enabled `model_profile` from the current LLM settings
   - seed one enabled default `agent_profile` for `settings.default_agent_id`
   - seed additional enabled historical `agent_profiles` for distinct legacy run `agent_id` values when needed
   - apply settings-backed historical-agent overrides when present
   - backfill sessions and historical runs deterministically
   - fail the migration loudly on conflicting session ownership history instead of silently choosing an owner
11. Add repository coverage for the new durable profile tables and ownership columns, including enabled-only lookups, soft-disabled reads, model-profile reads by profile key, owned-session listing by agent, and immutable session ownership persistence.
12. Add a new `src/agents/` package and implement repository helpers in `src/agents/repository.py` for agent profile reads, model profile reads, bootstrap upserts or seeds, linked-session listing, and validation-oriented fetches without exposing hard-delete flows for referenced agents.
13. Implement `src/agents/service.py` as the sole `AgentProfileService` seam that resolves durable agent identity, linked model profile, settings-backed policy profile, settings-backed tool profile, and one typed `AgentExecutionBinding` used by queue submission and worker execution.
14. Define the typed execution-binding structures in `src/agents/service.py`, `src/domain/schemas.py`, or another focused runtime contract module so a binding includes at minimum `agent_id`, `session_kind`, `model_profile_key`, `policy_profile_key`, `tool_profile_key`, and the bounded resolved model settings needed by provider or rule-based execution.
15. Add `src/agents/bootstrap.py` and startup wiring so the application seeds default profiles idempotently after migrations and validates startup invariants loudly when the configured default agent is missing, disabled, or linked to missing or disabled profiles.
16. Update `apps/gateway/main.py` and `apps/gateway/deps.py` so startup builds the agent-profile registry, runs bootstrap validation before accepting traffic, and exposes the new agent services through dependency wiring without hidden globals.
17. Extend `src/sessions/repository.py` and `src/domain/schemas.py` so session persistence and read models include `owner_agent_id`, `session_kind`, and `parent_session_id`, while enforcing the Spec 014 shape rules for `primary`, `child`, and `system` sessions and keeping ownership immutable after creation.
18. Refactor `src/sessions/service.py` so inbound processing resolves the owner binding before transcript mutation, uses a bootstrap resolver only when the canonical session does not yet exist, validates bootstrap ownership before inserting a new `sessions` row, trusts persisted `sessions.owner_agent_id` for existing sessions, and persists new runs with the full resolved execution profile identity rather than `default_agent_id` alone.
19. Extend `src/jobs/repository.py` so `create_or_get_execution_run(...)`, scheduler-backed run creation, and run read models persist and return `model_profile_key`, `policy_profile_key`, and `tool_profile_key` alongside `agent_id`, while keeping trigger idempotency and lane semantics unchanged from Spec 005.
20. Refactor scheduler submission in `src/sessions/service.py`, `src/jobs/service.py`, and related repository helpers so existing `session_id` targets always use the persisted owner, routing-tuple targets reuse or create only canonical `primary` sessions, no new `system` sessions are created through routing-tuple resolution in this slice, and `scheduled_jobs.agent_id` mismatches against the resolved owner fail closed.
21. Extend `src/graphs/state.py` and any supporting runtime contracts so `AssistantState` or the worker-owned runtime state carries the resolved binding and persisted profile keys for observability, deterministic tool binding, and replay-safe execution.
22. Refactor `src/jobs/service.py` so `RunExecutionService` reloads the current run, session, and durable binding before graph invocation, validates that the owning agent and persisted linked profiles are still enabled, executes against the persisted run profile keys, and fails closed before execution when queued work references disabled or broken profile links.
23. Replace process-wide model selection in `apps/gateway/deps.py` and `src/providers/models.py` with per-binding model resolution so provider-backed and rule-based execution both consume the resolved model profile rather than the application-global LLM fields.
24. Refactor `src/policies/service.py` so policy decisions are driven by the resolved `policy_profile_key` and per-agent runtime flags instead of constructor-time globals, while preserving exact approval matching on `session_id` plus `agent_id` from Spec 003.
25. Refactor `src/tools/registry.py` so capability exposure becomes the intersection of registry membership, the resolved tool-profile allowlist, resolved policy-profile denials or flags, and the existing runtime and channel constraints from earlier specs.
26. Verify `src/sandbox/service.py` and the Spec 006 execution path continue to resolve sandbox behavior from the durable owning `agent_id`, adding only the minimal validation hooks needed so sandbox lookup now follows session ownership instead of a global default agent assumption.
27. Extend `src/domain/schemas.py`, `src/sessions/service.py`, and `apps/gateway/api/admin.py` so session read surfaces expose `owner_agent_id`, `session_kind`, and `parent_session_id`, and add operator-protected admin endpoints for `GET /agents`, `GET /agents/{agent_id}`, `GET /agents/{agent_id}/sessions`, `GET /model-profiles`, and `GET /model-profiles/{profile_key}`.
28. Extend `src/observability/diagnostics.py` and related diagnostics schemas so run diagnostics expose persisted execution profile keys, agent diagnostics can report enabled status and linked profiles, and agent detail surfaces can answer whether a sandbox profile exists and which sessions are currently owned by that agent.
29. Add API and diagnostics tests proving the new agent and model-profile endpoints are operator-protected, session metadata surfaces show the new ownership fields, and run diagnostics expose `agent_id`, `model_profile_key`, `policy_profile_key`, and `tool_profile_key` without leaking settings-only secrets.
30. Add startup and bootstrap tests proving migrate-then-seed ordering is correct, default profiles are created idempotently, startup fails loudly when the configured default agent is missing or disabled after validation, settings-backed policy or tool profile mismatches fail closed before the app serves traffic, and invalid bootstrap ownership cannot create an empty session row.
31. Add worker, provider-runtime, session-service, scheduler, and integration tests proving:
   - new sessions bootstrap from the configured default agent only when no durable session exists
   - existing sessions retain ownership across config changes
   - queued work persists and reloads the same execution profile identity
   - queued work does not silently drift to newly linked agent profiles after queue time
   - two enabled agents can resolve different model profiles and tool exposure safely
   - scheduled-job `agent_id` mismatches fail closed against the resolved owner
   - disabled owners or broken linked profiles block new work and queued execution without partial transcript mutation
32. Add migration and repository regression coverage proving historical approvals, sandbox rows, and run diagnostics remain tied to exact `agent_id` semantics, soft-disabled agents stay queryable for existing references, settings-backed historical-agent overrides apply deterministically when present, and no hard-delete or reassignment path is introduced accidentally.
33. Update `README.md` and any relevant operator-facing docs only after behavior lands so the documented runtime model, session ownership rules, bootstrap semantics, admin read surfaces, and current non-goals around delegation orchestration match the implemented Spec 014 behavior.
34. Finish with a final implementation review against `specs/014-agent-profiles-and-delegation-foundation/spec.md` and `specs/014-agent-profiles-and-delegation-foundation/plan.md`, confirming the task list and resulting implementation preserve the Spec 001 canonical session key, add durable session ownership, resolve one typed execution binding per run, keep provider credentials settings-only, execute queued work against persisted profile identity, fail closed for invalid or disabled agents before session creation, transcript mutation, or run execution, preserve exact approval and sandbox identity semantics, and stop short of introducing delegation orchestration or child-run spawning behavior.

## Final Task Review

- Coverage against the spec is complete:
  - durable `agent_profiles` and `model_profiles`
  - settings-backed `policy_profiles` and `tool_profiles`
  - durable session ownership and session-kind metadata
  - per-run execution binding persistence and worker-time validation
  - per-agent model, tool, policy, sandbox, admin, and diagnostics behavior
- Coverage against the current codebase is concrete:
  - tasks explicitly replace the current `default_agent_id` run-creation shortcut in `src/sessions/service.py`
  - tasks explicitly replace the current global model and policy construction in `apps/gateway/deps.py`
  - tasks explicitly extend the existing session, queue, graph, worker, and diagnostics seams instead of inventing a second runtime
- The task list should support successful implementation of Spec 014 because it specifies:
  - the migration and backfill invariants that must be proven first
  - the new `src/agents/` ownership seam that becomes the single source of truth
  - the transaction and validation boundaries where ownership and profile resolution must happen
  - the admin and diagnostics surfaces needed to inspect the new durable profile model
  - the explicit non-goal boundary that keeps delegation orchestration out of this slice
