# Spec 017: Production Hardening and Enterprise Readiness

## Purpose
Finish the platform with the operational safeguards required for reliable production use, while preserving the existing gateway-first, worker-owned, append-only architecture established in Specs 001 through 016.

## Non-Goals
- Replacing the gateway, worker, graph, policy, or database architecture with a new control plane
- Introducing a new external secrets manager, service mesh, or identity platform as a prerequisite for this slice
- Rewriting earlier feature slices such as retrieval, streaming, delegation, or collaboration
- Building tenant billing, usage invoicing, or a generalized enterprise RBAC product
- Replacing PostgreSQL-backed durability with Redis-, Kafka-, or vendor-managed queue-first infrastructure
- Requiring real Slack, Telegram, or provider accounts for the core automated test suite

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
- Spec 014
- Spec 015
- Spec 016

## Scope
- Strengthen authentication and authorization for operator-facing routes, diagnostics reads, node-runner internal APIs, and channel/provider callback surfaces
- Harden credential handling in `src/config/settings.py`, adapters, diagnostics, and logs so secrets are validated, redacted, and never returned raw
- Add production-grade rate limiting and quota enforcement for inbound traffic, operator/admin surfaces, approval-action callbacks, and provider-backed runtime usage
- Add bounded exponential backoff with jitter and retry classification for provider calls, outbound delivery retries, and recovery-safe redrive flows
- Refine stale-run, stale-outbox, stale-delivery, and stale-node-execution recovery so background work can be repaired without replaying user input unsafely
- Upgrade observability from stubs into exporter-backed metrics and tracing behind the existing facades in `src/observability/metrics.py` and `src/observability/tracing.py`
- Add alertable operational signals, bounded diagnostics queries, and retention-aware audit/query behavior suitable for production operators
- Harden media retention, sandbox isolation, node-runner request validation, and remote execution controls for safer real-world deployment
- Add documented disaster-recovery, restore, and migration procedures for PostgreSQL state, media storage, background work continuity, and key rotation
- Build integration and smoke suites that validate the full system path with deterministic test doubles and deployment-realistic process boundaries

## Implementation Gap Resolutions
### Gap 1: Production Auth Boundary for Admin and Diagnostics Surfaces
The roadmap calls for stronger auth, but the current repository still leaves some session and governance reads open while other routes use one shared operator token check.

Options considered:
- Option A: keep mixed public and protected reads and rely on deployment-layer network isolation
- Option B: add a full external identity provider integration in this slice
- Option C: make all operator, admin, diagnostics, governance-read, and transcript-read surfaces fail closed behind one backend-owned operator auth contract, with an internal-service escape hatch for trusted automation
- Option D: protect only mutation routes and leave read routes unchanged

Selected option:
- Option C

Decision:
- All routes in `apps/gateway/api/admin.py` and production diagnostics/health-readiness surfaces that expose internal state must require operator or internal-service authentication.
- The repository standard in this slice is backend-owned header/token validation plus durable operator principal propagation, not anonymous reads and not mandatory external SSO.
- This slice may remain compatible with upstream API gateways or identity proxies, but the application must fail closed even when deployed without them.

### Gap 2: Quota and Rate-Limit Storage Strategy
Production rate limiting is required, but the current codebase has no Redis dependency and already treats PostgreSQL as the durable system of record.

Options considered:
- Option A: require Redis before this spec can land
- Option B: implement only in-memory per-process rate limiting
- Option C: introduce a bounded PostgreSQL-backed quota counter service with fixed-window or token-bucket behavior, while keeping the contract abstract enough to allow Redis later
- Option D: rely only on provider-side rate limits and worker retries

Selected option:
- Option C

Decision:
- This slice introduces one backend-owned quota service contract backed by PostgreSQL durable counters.
- The implementation may later swap storage, but gateway and worker logic must depend on the quota-service abstraction rather than on a Redis-specific API.
- The first implementation must support process restarts, multi-worker correctness, and bounded cardinality without per-user unbounded metric labels.

### Gap 3: Recovery Ownership for Stale Background Work
The platform already has retries, leases, and diagnostics, but there is no single authoritative repair path for stale claimed or running work across runs, outbox jobs, deliveries, and node executions.

Options considered:
- Option A: let every read path opportunistically repair stale records
- Option B: rely only on manual operator intervention through diagnostics
- Option C: add one explicit recovery service and reaper workflow that owns stale-work detection, repair decisions, and audit visibility
- Option D: mark stale work failed immediately without redrive paths

Selected option:
- Option C

Decision:
- This slice introduces an explicit recovery service that scans bounded stale candidates and applies typed repair rules per workflow family.
- Recovery decisions must be idempotent, auditable, bounded, and must never duplicate canonical user transcript rows.
- Redrive must prefer already-persisted run, outbox, delivery, and node-execution records instead of replaying user input from scratch.

### Gap 4: Credential Hardening Without a Secrets-Manager Rewrite
The roadmap calls for safer credential handling, but the current repository stores runtime credentials in settings and channel account config.

Options considered:
- Option A: require HashiCorp Vault or cloud secrets-manager integration immediately
- Option B: leave credentials in settings unchanged and rely only on redaction
- Option C: keep settings-backed secret injection for this slice, but tighten validation, startup checks, rotation support, redaction, diagnostics masking, and per-surface exposure rules
- Option D: move secrets into database tables managed by the app

Selected option:
- Option C

Decision:
- Credentials remain settings-injected in this slice.
- Production hardening focuses on fail-closed validation, masked diagnostics, redaction, key-id rotation support, and explicit separation between secret material and non-secret configuration fingerprints.
- This spec must not introduce database-stored raw channel or provider secrets.

### Gap 5: Full-Path Smoke Testing Strategy
The roadmap requires full-path validation, but a production-ready spec cannot depend on live third-party systems for every CI run.

Options considered:
- Option A: require live provider and live channel credentials in every test environment
- Option B: keep only unit tests and trust manual staging validation
- Option C: require deterministic smoke and integration suites that run against local process boundaries, fake provider/channel adapters, signed node-runner requests, and real database state, with optional environment-gated live-provider checks later
- Option D: defer full-path smoke coverage to deployment tooling outside the repo

Selected option:
- Option C

Decision:
- The required implementation suite for this slice uses local or fake adapters for CI reliability and repeatability.
- Optional environment-gated live-provider or live-channel checks may be added, but they are additive and must not replace the deterministic smoke suite.

### Gap 6: Distinct Operator vs Internal-Service Caller Identity
The spec requires stronger auth on admin and diagnostics surfaces, but the current code still treats one bearer token check plus optional headers as enough for both human operators and trusted automation.

Options considered:
- Option A: keep one shared token path and let callers optionally provide an operator header
- Option B: rely on deployment-layer routing to separate machine and human callers without changing the backend contract
- Option C: define one explicit dual-caller auth contract where operator callers and internal-service callers authenticate differently, carry different principals, and have different authorization ceilings
- Option D: require full JWT- or SSO-based role mapping in this slice

Selected option:
- Option C

Decision:
- This slice defines two authenticated caller kinds:
  - operator callers
  - internal-service callers
- Operator-authored mutation routes must require both:
  - valid operator authentication
  - a durable non-empty operator principal identifier
- Internal-service callers may satisfy authorization only for machine-safe surfaces such as readiness, diagnostics reads, and other explicitly internal automation paths.
- Internal-service authentication must not satisfy operator-authored mutation requirements, and implementations must not persist a placeholder principal such as `internal-service` into operator audit fields.
- Existing diagnostics-specific tokens may remain as rollout aliases, but the production implementation must converge on one shared auth dependency that applies the same caller-kind rules across admin, diagnostics, and readiness surfaces.

### Gap 7: Node-Runner Transport Mode vs Existing In-Process Execution Path
The spec requires transport-level auth for the node-runner API, but the current gateway/runtime wiring still supports direct in-process execution via an injected runner client.

Options considered:
- Option A: require all node execution to move to authenticated HTTP immediately
- Option B: leave local in-process and remote HTTP behavior implicit and let implementations decide case by case
- Option C: explicitly support `in_process` and `http` node-runner modes, with signed requests always required and transport auth required only when an HTTP boundary exists
- Option D: remove in-process execution support from the repository entirely

Selected option:
- Option C

Decision:
- This slice supports exactly two node-runner modes:
  - `in_process`
  - `http`
- Signed request verification remains mandatory in both modes.
- In `in_process` mode, there is no network transport boundary, so the runtime may call the policy/executor seam directly inside the trusted process.
- In `http` mode, gateway-to-runner requests must include both:
  - transport-level internal authentication
  - the existing signed request payload
- `http` mode must be the required production path for remote or separately deployed node runners, while `in_process` remains valid for local development, deterministic tests, and single-process deployments.

### Gap 8: Exact Stale-State Thresholds and Repair Actions
The spec assigns recovery ownership, but implementation would still be inconsistent unless stale detection thresholds and allowed repair actions are concretely defined per durable workflow family.

Options considered:
- Option A: let each repository or service choose its own stale heuristics
- Option B: use one global stale timeout for every workflow family
- Option C: define one typed stale-state matrix with per-family thresholds and per-family allowed repair actions
- Option D: keep stale detection diagnostic-only and require manual repair

Selected option:
- Option C

Decision:
- This slice defines one authoritative stale-state matrix covering:
  - `execution_runs`
  - `outbox_jobs`
  - `outbound_deliveries`
  - `node_execution_audits`
- Each workflow family must have:
  - one explicit stale threshold source from settings
  - one bounded eligible-state set
  - one bounded repair action set
- Recovery implementations must use that matrix rather than ad hoc service-local heuristics.
- Diagnostics, alerts, and recovery scans must all derive stale classification from the same threshold and state rules.

### Gap 9: Retry Ownership Between Outbox Jobs and Durable Deliveries
The repository already has both `outbox_jobs` and `outbound_deliveries`, but the draft does not yet say which durable artifact owns redrive once a delivery row has been created.

Options considered:
- Option A: let recovery recreate missing or failed deliveries by replaying outbox work every time
- Option B: allow both outbox scans and delivery scans to retry the same logical send independently
- Option C: keep `outbox_jobs` as the owner of pre-dispatch orchestration, but once an `outbound_delivery` exists, all transport retry and redrive must hang off that durable delivery identity and its attempts
- Option D: collapse delivery retry back into outbox-only orchestration

Selected option:
- Option C

Decision:
- `outbox_jobs` remain the owner of after-turn orchestration before transport delivery is materialized.
- Once a logical `outbound_delivery` row exists for an outbound intent or chunk, later transport retries and recovery-safe redrive must use that `outbound_delivery` identity and append-only attempts rather than minting fresh outbox work.
- Recovery may materialize a missing delivery row from an existing outbound intent only when no logical delivery row exists yet for that identity.
- Recovery and retry code must never create a second logical delivery row for the same existing `(outbound_intent_id, chunk_index)` identity.

## Current-State Baseline
- `apps/gateway/deps.py` already centralizes service construction and currently exposes operator auth through `verify_operator_access(...)`, but only some admin and health surfaces require it.
- `apps/gateway/api/admin.py` already exposes sensitive session, governance, run, delegation, and diagnostics reads, but several read routes remain unauthenticated.
- `apps/node_runner/api/internal.py` validates signed execution payloads, but the route itself does not currently require a second transport-level internal auth guard.
- `apps/gateway/deps.py` currently allows the internal-service token path to satisfy operator access and to collapse principal derivation to a placeholder `internal-service`, which is not sufficient for durable operator-authored audit semantics.
- `src/execution/runtime.py` and `apps/gateway/deps.py` currently support an injected in-process node-runner client path, so the spec must distinguish local trusted execution from remote HTTP transport hardening explicitly.
- `src/config/settings.py` already holds provider, channel, diagnostics, sandbox, retention, and observability configuration, but production-safe defaults and startup validation are still minimal.
- `src/config/settings.py` already includes stale-threshold settings for runs, outbox jobs, deliveries, and node execution, but today those thresholds primarily support diagnostics rather than one authoritative repair matrix.
- `src/observability/metrics.py` and `src/observability/tracing.py` are still stub facades and do not yet emit exporter-backed telemetry.
- `src/jobs/service.py`, `src/channels/dispatch.py`, `src/observability/diagnostics.py`, and the existing lease tables already provide the persistence seams needed for retry, recovery, and alertable stale-work detection.
- `src/channels/dispatch.py` already creates durable delivery rows and append-only attempts, but retry ownership between those rows and the higher-level outbox workflow is not yet codified as one production-safe contract.
- `src/sandbox/service.py`, `src/execution/runtime.py`, `apps/node_runner/policy.py`, and `src/db/models.py` already contain the remote execution and sandbox boundaries that this spec must harden rather than replace.

## Data Model Changes
- `rate_limit_counters`
  - bounded durable quota table for gateway and worker limits
  - `id` primary key
  - `scope_kind` non-null stable enum-like classifier such as:
    - `gateway_route`
    - `channel_account`
    - `operator_principal`
    - `agent_id`
    - `provider_model`
    - `approval_surface`
  - `scope_key` non-null bounded identifier
  - `window_kind` non-null stable classifier such as `minute`, `hour`, or `day`
  - `window_started_at` non-null
  - `request_count` non-null integer
  - `token_estimate` non-null integer default `0`
  - `last_seen_at` non-null
  - required indexes
    - unique index on `rate_limit_counters(scope_kind, scope_key, window_kind, window_started_at)`
    - lookup index on `rate_limit_counters(last_seen_at)`
- `execution_runs`
  - add nullable `recovery_state`
  - add nullable `recovery_reason`
  - add nullable `recovered_at`
  - add non-null integer `recovery_attempt_count` default `0`
  - required indexes
    - lookup index on `execution_runs(recovery_state, updated_at)`
    - lookup index on `execution_runs(status, recovery_state, updated_at)`
- `outbox_jobs`
  - add nullable `recovery_state`
  - add nullable `recovery_reason`
  - add nullable `recovered_at`
  - add non-null integer `max_attempts` default aligned with settings if not already derivable elsewhere
  - required indexes
    - lookup index on `outbox_jobs(recovery_state, updated_at)`
- `outbound_deliveries`
  - add nullable `available_at` for retry scheduling
  - add non-null integer `attempt_count` default `0`
  - add nullable `last_attempt_at`
  - add nullable `recovery_state`
  - add nullable `recovery_reason`
  - add nullable `recovered_at`
  - required indexes
    - lookup index on `outbound_deliveries(status, available_at, created_at)`
    - lookup index on `outbound_deliveries(recovery_state, created_at)`
- `node_execution_audits`
  - add nullable `available_at` for bounded redrive or status recheck
  - add nullable `recovery_state`
  - add nullable `recovery_reason`
  - add nullable `recovered_at`
  - add non-null integer `recovery_attempt_count` default `0`
  - required indexes
    - lookup index on `node_execution_audits(status, recovery_state, updated_at)`
- No new table is required for secret material storage in this slice.
- No migration may rewrite canonical transcript content, proposal content, approvals, or session identity.

## Settings and Registry Changes
- Add explicit production auth settings in `src/config/settings.py`:
  - `admin_reads_require_auth` boolean default `true`
  - `diagnostics_require_auth` boolean default `true`
  - `operator_auth_bearer_token`
  - `internal_service_auth_token`
  - `operator_principal_header_name`
  - `internal_service_principal_header_name`
  - `node_runner_internal_bearer_token` nullable but required when remote execution is enabled outside local test mode
  - `auth_fail_closed_in_production` boolean default `true`
- Support rollout-safe aliases from existing diagnostics auth settings where needed, but the application contract after this slice is one shared operator/internal auth configuration rather than diagnostics-only tokens.
- Add node-runner transport settings:
  - `node_runner_mode` with allowed values `in_process` or `http`
  - `node_runner_base_url` required when `node_runner_mode=http`
- Add quota and rate-limit settings:
  - `rate_limits_enabled`
  - `inbound_requests_per_minute_per_channel_account`
  - `admin_requests_per_minute_per_operator`
  - `approval_action_requests_per_minute_per_session`
  - `provider_tokens_per_hour_per_agent`
  - `provider_requests_per_minute_per_model`
  - `quota_counter_retention_days`
- Add retry and recovery settings:
  - `provider_retry_base_seconds`
  - `provider_retry_max_seconds`
  - `provider_retry_jitter_seconds`
  - `outbox_max_attempts`
  - `delivery_retry_base_seconds`
  - `delivery_retry_max_seconds`
  - `delivery_max_attempts`
  - `recovery_scan_interval_seconds`
  - `recovery_batch_size`
  - `recovery_max_attempts_per_record`
  - `execution_run_recovery_grace_seconds`
  - `outbox_job_recovery_grace_seconds`
  - `outbound_delivery_recovery_grace_seconds`
  - `node_execution_recovery_grace_seconds`
- Add observability and diagnostics settings:
  - `audit_retention_days`
  - `diagnostics_default_lookback_hours`
  - `diagnostics_max_lookback_days`
  - `metrics_exporter_kind`
  - `tracing_exporter_kind`
- Add sandbox and media-hardening settings:
  - `media_purge_interval_seconds`
  - `media_delete_grace_seconds`
  - `sandbox_off_mode_allowed_environments`
  - `sandbox_exec_max_stdout_bytes`
  - `sandbox_exec_max_stderr_bytes`
  - `node_runner_key_rotation_overlap_seconds`
- Existing tool, policy, model, and channel registries remain authoritative; this slice hardens them and does not replace them.

## Contracts
### Auth and Authorization Contract
- This slice defines one authoritative route-auth matrix so operator and internal-service callers are handled consistently across gateway surfaces:
  - `public_live_only`
    - `GET /health`
    - `GET /health/live`
    - allowed callers: anonymous, operator, internal-service
  - `internal_or_operator_read`
    - `GET /health/ready` when readiness auth is enabled
    - diagnostics list and detail reads
    - exporter posture reads
    - bounded run-inspection reads intended for trusted automation
    - allowed callers: operator or internal-service
  - `operator_only_read`
    - admin session metadata reads
    - transcript reads
    - governance reads
    - collaboration-state reads
    - approval-prompt reads
    - agent/profile inventory reads
    - allowed callers: operator only when `admin_reads_require_auth=true`
  - `operator_only_mutation`
    - collaboration takeover, pause, resume, assignment, and note mutation routes
    - operator approval-decision routes exposed through admin APIs
    - any future operator-authored admin mutation that writes durable operator-visible state
    - allowed callers: operator only
- `admin_reads_require_auth=true` means all admin routes in `apps/gateway/api/admin.py` fail closed.
- When `admin_reads_require_auth=true`, session, transcript, governance, collaboration, approval-prompt, delegation, and profile reads are classified as `operator_only_read`, not `internal_or_operator_read`.
- Internal-service callers remain limited to explicitly machine-safe operational surfaces and must not read operator-facing session or transcript history through admin routes merely because the route is read-only.
- `get_operator_principal(...)` or its replacement remains the sole gateway-owned source of durable operator identity for operator-authored mutations and audit joins.
- Internal-service access remains distinct from operator access:
  - internal-service calls may satisfy authorization for trusted automation
  - internal-service callers must not implicitly become arbitrary operators
  - operator-authored writes still require a durable principal identifier
- Internal-service callers must carry a durable service principal separate from human operator identity, using a bounded header or equivalent internal caller contract.
- Routes that mutate collaboration state, assignments, operator notes, or operator approval decisions must reject internal-service-only caller identity even when the internal-service token is otherwise valid.
- Health readiness and diagnostics read routes may accept internal-service authentication, but operator-facing admin mutations may not.
- Shared auth helpers must derive one typed caller identity carrying at minimum:
  - `caller_kind` with values `operator` or `internal_service`
  - bounded authenticated principal id
  - authorization ceiling derived from the route-auth matrix
- Route handlers must authorize against the route-auth matrix rather than ad hoc token checks.
- `apps/node_runner/api/internal.py` must require both:
  - valid transport-level internal authentication such as `Authorization: Bearer ...` or equivalent header contract
  - valid signed request verification through the existing signing policy
- A request that fails either node-runner check must fail closed before execution.
- Supported node-runner transport modes are:
  - `in_process`, where no HTTP transport auth applies because the execution path stays inside the trusted process boundary
  - `http`, where both internal bearer auth and signed request verification are mandatory on every POST and status GET
- Channel-provider callback surfaces must continue verifying provider signatures or secrets through their adapters before acceptance, and failures must return bounded auth errors without leaking configured credentials.
- Health and readiness surfaces may stay public only for `live` probes. Any surface that reveals dependency readiness, configuration posture, or diagnostics detail must require auth when the corresponding hardening setting is enabled.

### Node-Runner HTTP Wire Contract
- `node_runner_mode=http` uses one explicit backend-owned HTTP auth contract rather than implicit shared-secret checks.
- Required request headers for `POST /internal/node/exec` and `GET /internal/node/exec/{request_id}` are:
  - `Authorization: Bearer {token}` carrying one valid internal bearer token from the active overlap set
  - signed-request metadata required by the existing signing policy, including key id and signed canonical payload material for execute requests
- `POST /internal/node/exec` must verify, in order:
  - transport bearer token
  - request-shape validity
  - signed payload validity and key-id match
  - policy authorization
- `GET /internal/node/exec/{request_id}` must verify the same transport bearer contract as the POST surface before returning bounded status data.
- Bearer-token rotation must support exactly two concurrent accepted tokens during the configured overlap window:
  - current token
  - previous token
- Signing-key rotation must support exactly two concurrent accepted signing key ids during the configured overlap window:
  - current signing key id
  - previous signing key id
- Outside the configured overlap window, previous bearer tokens and previous signing key ids must fail closed.
- Execute and status responses must never disclose which secret value failed verification; they may disclose only bounded auth failure categories.
- `node_runner_mode=in_process` bypasses only the HTTP transport layer; it does not weaken signed-request construction, request-id determinism, sandbox enforcement, or audit persistence.

### Credential and Secret-Handling Contract
- Provider API keys, channel tokens, signing secrets, webhook secrets, and node-runner bearer tokens remain settings-backed secrets in this slice.
- The app must validate required credentials at startup for every enabled real provider or real channel account and must fail boot if required credentials are missing.
- Diagnostics and admin APIs may expose only bounded credential posture such as:
  - configured vs not configured
  - key id
  - masked suffix or stable fingerprint
  - last rotation timestamp if persisted outside the secret value
- Raw secret material must never be returned from settings serialization, diagnostics, health, logs, traces, metrics labels, approval payloads, or audit preview fields.
- Key rotation must be supported through overlapping key ids for node-runner signing and bearer-token replacement so one deploy does not require a hard cutover outage.

### Quota and Rate-Limit Contract
- One backend-owned `QuotaService` or equivalent is authoritative for rate-limit decisions across gateway and worker entry points.
- The first required enforcement points are:
  - `POST /inbound/message`
  - provider callback routes in `apps/gateway/api/slack.py`, `apps/gateway/api/telegram.py`, and `apps/gateway/api/webchat.py`
  - approval-action decision callbacks
  - authenticated admin and diagnostics routes
  - provider-backed model execution before expensive provider requests
- A rate-limit decision must be based on a bounded scope and bounded window, not on unbounded free-form user identifiers.
- The quota policy matrix for this slice is:
  - inbound gateway acceptance
    - enforcement point: `POST /inbound/message`
    - scope kind: `channel_account`
    - scope key: `{channel_kind}:{channel_account_id}`
    - window: minute
    - on exceed: reject with `429` before dedupe claim finalization, transcript append, or run creation
  - provider callback ingress
    - enforcement point: verified Slack, Telegram, and webchat callback routes
    - scope kind: `channel_account`
    - scope key: `{channel_kind}:{channel_account_id}`
    - window: minute
    - on exceed: reject with `429` before transcript append, dedupe finalization, approval mutation, or delivery mutation
  - admin and operator reads or mutations
    - enforcement point: authenticated routes in `apps/gateway/api/admin.py`
    - scope kind: `operator_principal`
    - scope key: authenticated operator principal id
    - window: minute
    - on exceed: reject with `429` before any durable mutation; read routes perform no repository mutation after denial
  - diagnostics and readiness machine-safe reads
    - enforcement point: authenticated diagnostics and readiness routes
    - scope kind: `gateway_route`
    - scope key: `{route_class}:{caller_kind}`
    - window: minute
    - on exceed: reject with `429` before diagnostics query execution
  - approval action callbacks
    - enforcement point: callback or write endpoint that consumes one approval action token
    - scope kind: `approval_surface`
    - scope key: `{session_id}:{channel_kind}:{decision_surface}`
    - window: minute
    - on exceed: reject with `429` before proposal mutation or prompt-state mutation
  - provider model requests
    - enforcement point: provider-backed runtime before outbound provider network calls
    - scope kind: `provider_model`
    - scope key: `{agent_id}:{model_profile_key}`
    - windows:
      - minute for request counts
      - hour for token estimates
    - on exceed: reschedule or terminally fail the existing run according to retryability; never create a new run
- Scope keys must be derived only from bounded enum-like identifiers, durable principal ids, session ids, agent ids, model profile keys, and channel account ids already persisted or validated by the backend.
- Raw user ids, free-form transport addresses, request bodies, prompt text, and provider-native opaque payloads must not be used as quota scope keys.
- Gateway rate-limit rejection must:
  - return HTTP `429`
  - set `Retry-After` when a meaningful retry boundary exists
  - record structured telemetry and bounded diagnostics context
  - avoid mutating transcript or queue state after the limit is exceeded
- Worker/provider quota exhaustion must not fabricate completed assistant turns.
- For worker-side quota exhaustion, the runtime must either:
  - reschedule the existing run or delivery using bounded backoff, or
  - fail it terminally with explicit quota classification when retry would not help

### Provider Backoff and Retry Contract
- The provider-backed runtime in `src/providers/models.py` must use bounded exponential backoff with jitter for retryable provider failures classified in Spec 009, such as timeout, unavailable, and rate-limited cases.
- Provider retry remains bounded within one logical run attempt; it must not create duplicate execution runs.
- Provider retry exhaustion must preserve the canonical `execution_run` row and persist a bounded terminal failure classification.
- Semantic provider failures that Spec 009 treats as safe completion paths must not be retried as transport failures merely because a payload was malformed.

### Delivery Retry and Redrive Contract
- `src/channels/dispatch.py` must persist enough state for retryable delivery failures to be redriven without re-running model inference.
- Retryable delivery failures must update the durable delivery record with:
  - incremented `attempt_count`
  - `available_at`
  - bounded retry classification
  - latest retryable failure code
- Non-retryable delivery failures must transition to a terminal failed state and must not be retried automatically.
- Delivery redrive must operate from already-persisted outbound intent artifacts and delivery rows only.
- Delivery redrive must not append a second assistant transcript message and must not re-execute tools.
- `outbox_jobs` may own the pre-delivery orchestration step, but once a logical `outbound_delivery` row exists for an intent identity, transport retry ownership transfers to the delivery row plus its append-only attempts.
- Recovery may create a missing delivery row from an existing outbound intent only when no prior logical delivery row exists for that durable identity.
- Recovery and retry must never create a second logical delivery row for an already-materialized `(outbound_intent_id, chunk_index)` pair.

### Recovery and Reaper Contract
- One `RecoveryService` or equivalent is the sole owner of stale background-work detection and repair for:
  - `execution_runs`
  - `outbox_jobs`
  - `outbound_deliveries`
  - `node_execution_audits`
- Recovery scans must be bounded by configurable batch size and lookback windows.
- Recovery decisions must be idempotent and auditable.
- Before applying any repair action, `RecoveryService` must evaluate family-specific prechecks against the current durable row set:
  - whether the target row is already terminal
  - whether a newer successful attempt or terminal state already exists for the same durable identity
  - whether collaboration state currently requires the work to remain blocked rather than runnable
  - whether a proposal, prompt, delegation, or delivery identity for the same durable artifact already exists
  - whether the owning run, session, or delivery has been superseded by a later canonical durable outcome
- The stale-state matrix for this slice is:
  - `execution_runs`
    - stale when status is `claimed` or `running` and either the active lease is expired or the row age exceeds the configured run recovery grace threshold
    - prechecks must confirm the run is not already terminal, not intentionally `blocked`, and not already superseded by a later successful continuation for the same trigger identity
    - repair actions may only requeue, classify failed, or dead-letter the existing row
  - `outbox_jobs`
    - stale when status is `running` and `updated_at` is older than the configured outbox recovery grace threshold
    - prechecks must confirm no terminal delivery-owned outcome already exists for the same logical outbound work and that current collaboration state does not require suppression
    - repair actions may only return the existing job to `pending` with a bounded future `available_at`, or mark it terminally failed
  - `outbound_deliveries`
    - stale when the latest attempt is non-terminal beyond the configured delivery recovery grace threshold, or when a retryable failed delivery is due for redrive at `available_at`
    - prechecks must confirm the logical delivery row is still the canonical owner for `(outbound_intent_id, chunk_index)` and that no later sent or terminal non-retryable outcome already exists
    - repair actions may only create a new attempt under the existing logical delivery row, or mark the existing delivery terminally failed
  - `node_execution_audits`
    - stale when status is `received` or `running` beyond the configured node-execution recovery grace threshold
    - prechecks must confirm no later terminal audit exists for the same `request_id` and that the owning run is still eligible for retry or terminal reconciliation
    - repair actions may only reconcile the existing `request_id` to a bounded terminal state, or release the owning run to retry through a later execution attempt
- Minimum recovery actions in this slice are:
  - reclaim stale claimed or running `execution_runs` whose leases are expired and whose terminal state was not persisted
  - redrive stale `outbox_jobs` that are safe to retry from existing durable inputs
  - reschedule retryable `outbound_deliveries` whose `available_at` is due
  - reconcile `node_execution_audits` stuck in in-flight states by rechecking or terminally classifying them according to signed request id and timeout rules
- Recovery forbidden side effects are explicit:
  - must not create a new inbound dedupe identity or a second inbound transcript row
  - must not create a new `execution_run` when repairing an existing stale run
  - must not create a new child session, new delegation row, or new parent-result continuation for an existing delegation identity
  - must not create a new proposal or a second pending approval prompt for an already-persisted proposal or prompt surface
  - must not append a second assistant transcript row for already-persisted assistant output
  - must not create a second logical delivery row for an existing `(outbound_intent_id, chunk_index)` identity
- Recovery must never create a second inbound transcript row for the same upstream event.
- Recovery must never create a second child session, second delegation row, second proposal, or second approval prompt for the same durable identity.

### Observability and Alerting Contract
- The existing `MetricsSink` and `TracingFacade` remain the application abstraction boundaries, but this slice must provide real exporter-backed implementations when enabled.
- Minimum metrics in this slice must cover:
  - inbound acceptance, rejection, duplicate replay, and rate-limit rejection
  - `execution_runs` queue depth, active count, retry count, dead-letter count, stale count, and duration
  - provider request count, error count by bounded category, and token estimate by bounded profile/model dimension
  - `outbox_jobs` pending, stale, retry, and failure counts
  - outbound delivery success, retry, terminal failure, and backlog counts
  - node execution request, rejection, timeout, completion, and stale reconciliation counts
  - media purge counts and retained-bytes estimates where available
  - auth failures on admin, diagnostics, callback, and node-runner surfaces
- Tracing must support one causal trace from inbound acceptance through worker execution, tool use, delivery, and recovery when enabled.
- Alertable signals must be derivable from emitted metrics or durable state for at least:
  - stale run backlog above threshold
  - dead-letter run growth
  - provider auth failure bursts
  - provider or channel rate-limit bursts
  - delivery retry backlog age
  - node-runner timeout growth
  - media purge failures
- Diagnostics queries must be retention-aware and bounded:
  - callers may filter by status, failure category, and bounded lookback
  - unbounded full-table scans must not be the default operator path
  - records older than the configured retention horizon may be omitted, summarized, or marked expired rather than scanned indefinitely

### Sandbox, Media, and Remote Execution Contract
- `src/sandbox/service.py` remains the authoritative sandbox resolution layer.
- Production posture in this slice is fail closed:
  - sandbox `off` mode is disallowed unless explicitly enabled for approved environments
  - agent sandbox profile maxima remain enforced for timeout and shared/ephemeral mode selection
  - allowed executable and command-template validation must happen before node-runner dispatch
- Node-runner execution must enforce bounded stdout/stderr capture and must not persist or emit unbounded command output.
- Workspace isolation rules must remain deterministic and auditable for `shared`, `ephemeral`, and `off` modes, with `off` treated as exceptional rather than normal.
- Media retention must include a purge workflow that deletes expired stored media and extraction derivatives after the grace window while preserving bounded metadata required for audit and transcript references.
- Media purge must fail safely:
  - expired files may remain temporarily if deletion fails
  - metadata must reflect purge-pending or purge-failed status rather than claiming successful deletion

### Disaster-Recovery and Migration Contract
- This slice must ship an operator-readable disaster-recovery runbook in `docs/` covering:
  - PostgreSQL backup cadence and restore order
  - media-storage backup and restore order
  - node-runner signing-key rotation and rollback
  - how to restart workers and recovery scans after an outage
  - how to reconcile in-flight runs, outbox jobs, deliveries, and node executions after restore
- Migration order must be explicit:
  - additive schema changes first
  - code capable of reading both pre-017 and post-017 rows second
  - enforcement toggles and stricter auth defaults last
- Rollback guidance must identify which toggles can be relaxed without reverting durable data.
- This slice must not require destructive data rewrites to restore service after a failed deploy.

### Full-Path Smoke and Integration Test Contract
- The repository must gain deterministic smoke tests that exercise the full application path:
  - inbound acceptance
  - session resolution and idempotency
  - context assembly
  - provider-backed model decision using a fake or stub provider
  - tool execution
  - approval gating when required
  - outbound delivery persistence and send attempt handling
  - diagnostics inspection
- The smoke suite must run against real process boundaries where practical:
  - gateway app instance
  - worker service or worker loop
  - node-runner app instance for signed remote-exec cases
  - PostgreSQL-backed state or a test-equivalent DB with matching transactional semantics
- The smoke suite must include at least one degraded-path scenario covering stale-work recovery or retryable delivery/provider failure.
- Optional live-provider or live-channel verification may be environment-gated, but the required implementation-ready suite must remain deterministic and local.

## Runtime Invariants
- No production hardening control may bypass the gateway-first, worker-owned execution path.
- Auth failures fail closed and must not reveal internal state.
- Rate-limit rejection must not append duplicate transcript or queue records.
- Recovery workflows may redrive durable work, but they may not duplicate canonical user transcript events.
- Delivery retry must never require re-running model inference for already-persisted assistant output.
- Sandbox and node-runner controls remain backend-authoritative even when channel or provider inputs are malicious or malformed.
- Observability and diagnostics remain additive; they must not become a competing source of truth for session, approval, or execution state.

## Security Constraints
- Production defaults must prefer protected routes, disabled `off` sandbox mode, and explicit real-account credential validation.
- Secrets must be redacted everywhere outside the settings source.
- Internal service tokens, provider credentials, channel tokens, and signing secrets must never appear in logs, traces, metric labels, or admin payloads.
- Quota and recovery services must be safe under concurrent workers and process restarts.
- Remote execution remains approval- and policy-bound; production hardening must not broaden what commands are executable.

## Operational Considerations
- This slice should land behind settings flags where stricter enforcement could otherwise break local development or pre-production environments.
- Existing fake adapters and fake channel accounts remain valid for local development and deterministic tests.
- Metrics and tracing exporters must degrade safely to no-op behavior when disabled or not configured.
- Recovery scans must be safe to run continuously and manually.
- Retention jobs for rate-limit counters, diagnostics, audit metadata, and media artifacts must be bounded and restart-safe.
- Operator-facing docs must distinguish between local-development posture and production posture for auth, credentials, sandbox mode, and recovery settings.

## Acceptance Criteria
- Every route in `apps/gateway/api/admin.py` is protected by the production operator-auth contract when production auth is enabled.
- Internal-service auth is accepted only on explicitly machine-safe routes and cannot be used to satisfy operator-authored mutation routes.
- `apps/node_runner/api/internal.py` rejects requests that lack valid internal auth even if the signed payload is otherwise well formed.
- Remote node-runner deployments use `node_runner_mode=http` with both bearer auth and signed requests, while local deterministic environments may still use `node_runner_mode=in_process`.
- Gateway inbound and callback surfaces return bounded `429` responses under configured rate limits without creating duplicate transcript or run records.
- Provider-backed runtime retries retryable provider failures with bounded backoff and preserves one canonical `execution_run`.
- Retryable outbound delivery failures can be redriven from persisted delivery state without re-running the graph or duplicating assistant transcript rows.
- Recovery scans can detect and repair at least one stale run, one stale outbox job, one stale delivery, and one stale node execution in tests.
- Metrics and tracing facades emit real exporter-backed signals when enabled and remain safe no-ops when disabled.
- Diagnostics queries enforce bounded lookback and do not require unbounded full-table scans for common operator workflows.
- Media retention purge deletes expired files or records a bounded purge failure without corrupting transcript-linked metadata.
- A documented restore procedure exists and is validated by at least one restore-oriented integration or smoke scenario.
- The deterministic smoke suite covers the end-to-end path from inbound message to diagnostics visibility, including one approval-gated or recovery-oriented scenario.

## Test Expectations
- Unit tests for operator-auth gating, operator principal derivation, and fail-closed route behavior
- Unit tests for distinct operator vs internal-service caller handling, including rejection of internal-service identity on operator-authored write routes
- Unit tests for node-runner dual-auth enforcement and signing-key rotation overlap
- Unit tests for `node_runner_mode=in_process` versus `node_runner_mode=http` contract behavior
- Unit tests for quota counter decisions, bounded scope keys, counter retention, and concurrent increment correctness
- Unit tests for provider backoff classification and delivery retry scheduling
- Unit tests for recovery-service stale-matrix decision logic and idempotent redrive behavior
- Unit tests for metrics/tracing adapters proving enabled vs disabled behavior through the existing facades
- Unit tests for secret redaction and masked diagnostics payloads
- Integration tests for inbound rate limiting with no duplicate transcript writes
- Integration tests for retryable provider failure followed by successful completion on the same logical run
- Integration tests for retryable delivery failure followed by redrive from persisted outbound artifacts only
- Integration tests proving a previously materialized delivery retries under the existing `outbound_delivery` identity rather than through duplicate outbox replay
- Integration tests for stale claimed or running work reconciliation using lease expiry and recovery scans
- Integration tests for node-runner auth rejection and accepted signed execution
- Integration tests for media purge and bounded metadata preservation after deletion
- Smoke tests for the full path through gateway, worker, approvals, outbound delivery, and diagnostics

## Implementation Readiness Review
### Scope Check
- The slice remains bounded to production hardening of already-existing subsystems rather than inventing new product features.
- The spec explicitly avoids secret-manager rewrites, enterprise IAM rewrites, and architectural replacements that would make implementation sprawl.

### Contract Check
- Auth, quota, retry, recovery, observability, sandbox, retention, and disaster-recovery ownership are all assigned to explicit backend seams.
- Recovery and retry behavior are defined in terms of existing durable records so implementation does not depend on replaying user input unsafely.

### Migration and Rollout Check
- All data-model changes are additive.
- Enforcement-sensitive behavior is expected to land behind settings toggles and then tighten to production defaults after rollout validation.

### Remaining Assumptions
- PostgreSQL remains the only required durable coordination store for this slice.
- Exporter implementations for metrics and tracing may use OpenTelemetry-compatible libraries, but the application-facing abstraction remains the existing local facade interfaces.
- Optional live-provider validation is additive and not required to declare the implementation complete.

### Ready for Implementation
- Yes, provided implementation follows the additive migration order and keeps new enforcement paths behind the documented settings toggles during rollout.
