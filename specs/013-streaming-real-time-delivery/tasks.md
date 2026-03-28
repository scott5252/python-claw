# Tasks 014: Agent Profiles And Delegation Foundation

> Stored in `specs/013-streaming-real-time-delivery` per request. These tasks implement roadmap Spec 014 from `docs/features_plan.md`.

## Alignment Decisions

### Gap 1: The runtime still treats `default_agent_id` as the direct execution identity
Options considered:
- Option A: keep `default_agent_id` as the primary runtime source and only add better docs
- Option B: add session ownership only and defer the registry
- Option C: keep `default_agent_id` only as bootstrap input and resolve runtime identity through a durable default agent profile
- Option D: wait until Spec 015 to introduce any durable agent identity

Selected option:
- Option C

### Gap 2: Session ownership is missing even though runs already persist `agent_id`
Options considered:
- Option A: continue resolving agent identity only at run creation time
- Option B: store `agent_id` only on `execution_runs`
- Option C: add `owner_agent_id` and `session_kind` to `sessions` now so session ownership becomes the source of truth
- Option D: allow session ownership to be mutable per message

Selected option:
- Option C

### Gap 3: Model selection must become agent-specific without moving secrets into the database
Options considered:
- Option A: keep model selection entirely global in `Settings`
- Option B: store full provider credentials per agent profile
- Option C: add durable non-secret model profiles linked from agents while keeping credentials deployment-managed
- Option D: let each run choose any model profile ad hoc

Selected option:
- Option C

### Gap 4: Policy scoping needs an explicit profile before delegation lands
Options considered:
- Option A: keep one global policy configuration with no durable profile concept
- Option B: inline every policy field on `agent_profiles`
- Option C: add reusable linked `policy_profiles` and resolve policy behavior from them
- Option D: defer policy-profile linkage until Spec 015

Selected option:
- Option C

### Gap 5: Existing sandbox profile rows from Spec 006 must remain canonical
Options considered:
- Option A: continue resolving sandbox settings from a raw `agent_id` string only
- Option B: move all sandbox fields onto `agent_profiles` and delete the current table
- Option C: preserve the existing sandbox-profile table but anchor it to the durable agent registry
- Option D: ignore sandbox alignment in this slice

Selected option:
- Option C

### Gap 6: Future child-session support needs a durable session relationship shape now
Options considered:
- Option A: add no child-session-related fields until delegation exists
- Option B: add only a later `delegations` table
- Option C: add `session_kind` plus nullable `parent_session_id` now without implementing delegation flows
- Option D: encode child relationships only in transcript artifacts

Selected option:
- Option C

## Tasks

1. Confirm the current agent-related runtime seams in [src/sessions/service.py](/Users/scottcornell/src/my-projects/python-claw/src/sessions/service.py), [apps/gateway/deps.py](/Users/scottcornell/src/my-projects/python-claw/apps/gateway/deps.py), [src/jobs/service.py](/Users/scottcornell/src/my-projects/python-claw/src/jobs/service.py), [src/context/service.py](/Users/scottcornell/src/my-projects/python-claw/src/context/service.py), [src/providers/models.py](/Users/scottcornell/src/my-projects/python-claw/src/providers/models.py), [src/policies/service.py](/Users/scottcornell/src/my-projects/python-claw/src/policies/service.py), and [src/sandbox/service.py](/Users/scottcornell/src/my-projects/python-claw/src/sandbox/service.py) so Spec 014 extends the existing architecture instead of introducing a parallel agent-resolution path.
2. Add high-risk migration and repository tests first for durable `agent_profiles`, `model_profiles`, `policy_profiles`, session ownership fields, and any required sandbox-profile linkage, including uniqueness of the default profile, enabled or disabled filtering, and safe backfill of pre-existing sessions.
3. Add high-risk runtime tests first proving inbound session creation and run creation no longer use `Settings.default_agent_id` directly, but instead resolve the default enabled durable agent profile and persist the resulting `owner_agent_id` and `execution_runs.agent_id` consistently.
4. Add high-risk failure-path tests first for missing default agent profile, duplicate defaults, disabled default agent, disabled linked model profile, disabled linked policy profile, invalid session-owner foreign keys, and mismatched session-owner versus run-agent cases, proving all fail closed without silent fallback.
5. Add high-risk sandbox-alignment tests first proving the current Spec 006 sandbox resolution path still works when agent identity is registry-backed, and does not silently downgrade or bypass the canonical sandbox-profile relationship.
6. Add high-risk scheduler tests first proving explicitly targeted scheduler agents validate against the registry, cannot use disabled agents, and preserve ownership rules for session-targeted versus routing-tuple-targeted fires.
7. Add high-risk diagnostics and admin tests first proving operator-facing read surfaces can list agent profiles, read one profile, filter sessions by owner agent, and surface resolved model, policy, and sandbox profile identifiers for a run without exposing secrets.
8. Extend [src/db/models.py](/Users/scottcornell/src/my-projects/python-claw/src/db/models.py) with durable `agent_profiles`, `model_profiles`, and `policy_profiles`, plus additive session ownership fields `owner_agent_id`, `session_kind`, and nullable `parent_session_id`, keeping changes additive and bounded.
9. Add the migration in `migrations/versions/` to create the new profile tables, add the new session columns and indexes, backfill existing sessions to the default agent profile, and preserve compatibility with existing run, governance, and sandbox rows.
10. Extend [src/config/settings.py](/Users/scottcornell/src/my-projects/python-claw/src/config/settings.py) only as needed so `default_agent_id` becomes bootstrap or compatibility input rather than the direct runtime execution source, while keeping secrets and provider credentials deployment-owned.
11. Add repository helpers in [src/sessions/repository.py](/Users/scottcornell/src/my-projects/python-claw/src/sessions/repository.py) for creating, reading, and listing agent profiles; resolving the default enabled agent; reading linked model or policy profiles; persisting session ownership metadata; and listing sessions by owner agent.
12. Extend [src/capabilities/repository.py](/Users/scottcornell/src/my-projects/python-claw/src/capabilities/repository.py) or add a narrow helper so existing sandbox-profile lookups can resolve through the new durable agent-registry relationship without creating a second sandbox source of truth.
13. Introduce one explicit agent-profile resolution seam, either in [src/sessions/repository.py](/Users/scottcornell/src/my-projects/python-claw/src/sessions/repository.py) or a new service module, that can resolve the default enabled profile, validate enabled state, and return the effective model, policy, and sandbox linkage for runtime consumers.
14. Refactor [src/sessions/service.py](/Users/scottcornell/src/my-projects/python-claw/src/sessions/service.py) so inbound session creation persists `owner_agent_id`, `session_kind`, and any required origin metadata, and creates execution runs using the session owner rather than `self.default_agent_id`.
15. Refactor scheduler-related session and run creation in [src/sessions/service.py](/Users/scottcornell/src/my-projects/python-claw/src/sessions/service.py) so explicit scheduler agent targets are validated against the durable registry and routing-tuple-created sessions receive deterministic ownership.
16. Update [apps/gateway/deps.py](/Users/scottcornell/src/my-projects/python-claw/apps/gateway/deps.py) so session service, assistant-graph construction, policy service, provider adapter setup, and sandbox-capable runtime dependencies can all consume the shared agent-resolution seam instead of reconstructing agent behavior ad hoc.
17. Update [src/jobs/repository.py](/Users/scottcornell/src/my-projects/python-claw/src/jobs/repository.py) only as needed so execution-run creation and lookup preserve the invariant that standard session-triggered runs use `sessions.owner_agent_id`.
18. Extend [src/domain/schemas.py](/Users/scottcornell/src/my-projects/python-claw/src/domain/schemas.py) with additive response models for agent-profile detail and list views, and extend session or run responses only where the new owner metadata needs to surface on existing read APIs.
19. Refine [src/providers/models.py](/Users/scottcornell/src/my-projects/python-claw/src/providers/models.py) so effective provider and model settings can be resolved from the linked model profile while credentials and base URL remain deployment-owned settings.
20. Refine [src/policies/service.py](/Users/scottcornell/src/my-projects/python-claw/src/policies/service.py) so policy behavior becomes profile-scoped, existing deterministic approval and revocation handling stays intact, and future delegation-related fields remain reserved but inactive in this slice.
21. Refine [src/context/service.py](/Users/scottcornell/src/my-projects/python-claw/src/context/service.py), [src/graphs/state.py](/Users/scottcornell/src/my-projects/python-claw/src/graphs/state.py), [src/graphs/nodes.py](/Users/scottcornell/src/my-projects/python-claw/src/graphs/nodes.py), and [src/graphs/assistant_graph.py](/Users/scottcornell/src/my-projects/python-claw/src/graphs/assistant_graph.py) only as needed so graph invocation and context assembly continue to use the resolved `agent_id` consistently and can carry resolved profile identifiers in bounded metadata for diagnostics.
22. Refine [src/sandbox/service.py](/Users/scottcornell/src/my-projects/python-claw/src/sandbox/service.py) so sandbox resolution uses the canonical agent-registry-backed profile path while preserving current Spec 006 mode, key, and workspace semantics.
23. Extend [apps/gateway/api/admin.py](/Users/scottcornell/src/my-projects/python-claw/apps/gateway/api/admin.py) with read-only endpoints for listing agent profiles, fetching a specific agent profile, and listing sessions by owning agent, keeping them on the existing operator-authenticated read boundary where appropriate.
24. Extend [src/observability/diagnostics.py](/Users/scottcornell/src/my-projects/python-claw/src/observability/diagnostics.py) so diagnostics can report agent-to-session ownership, resolved model, policy, and sandbox identifiers for runs, and profile-resolution failures in bounded operator-safe form.
25. Extend [src/observability/logging.py](/Users/scottcornell/src/my-projects/python-claw/src/observability/logging.py) and [src/observability/failures.py](/Users/scottcornell/src/my-projects/python-claw/src/observability/failures.py) so missing or disabled agent-profile failures are classified distinctly from provider, tool, transport, or sandbox failures.
26. Add repository and integration tests proving historical runs, governance rows, node execution audits, and existing session reads remain queryable after agent-profile registry rollout, even when an agent profile is later disabled.
27. Add regression tests proving the current single-agent application path still works when one enabled default profile exists: inbound message, queued run, graph invocation, retrieval or memory context, governed tool handling, outbound dispatch, and diagnostics.
28. Add regression tests proving this slice does not yet implement delegation behavior: no child sessions are auto-created, no `parent_session_id` is populated during normal inbound work, and policy-profile delegation fields remain inactive placeholders only.
29. Update `README.md` only if implementation changes make the documented runtime identity model materially inaccurate; otherwise leave it untouched.
30. Finish with verification that agent identity is now durable and registry-backed, session ownership is explicit, runtime profile linkage is fail-closed, historical auditability is preserved, and the codebase is ready for Spec 015 without already crossing into delegation orchestration.
