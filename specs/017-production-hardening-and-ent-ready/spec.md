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

## Current-State Baseline
- `apps/gateway/deps.py` already centralizes service construction and currently exposes operator auth through `verify_operator_access(...)`, but only some admin and health surfaces require it.
- `apps/gateway/api/admin.py` already exposes sensitive session, governance, run, delegation, and diagnostics reads, but several read routes remain unauthenticated.
- `apps/node_runner/api/internal.py` validates signed execution payloads, but the route itself does not currently require a second transport-level internal auth guard.
- `src/config/settings.py` already holds provider, channel, diagnostics, sandbox, retention, and observability configuration, but production-safe defaults and startup validation are still minimal.
- `src/observability/metrics.py` and `src/observability/tracing.py` are still stub facades and do not yet emit exporter-backed telemetry.
- `src/jobs/service.py`, `src/channels/dispatch.py`, `src/observability/diagnostics.py`, and the existing lease tables already provide the persistence seams needed for retry, recovery, and alertable stale-work detection.
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
  - `operator_principal_header_name`
  - `node_runner_internal_bearer_token` nullable but required when remote execution is enabled outside local test mode
  - `auth_fail_closed_in_production` boolean default `true`
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
- Operator, admin, diagnostics, governance-read, collaboration, run-inspection, and transcript-inspection routes exposed from `apps/gateway/api/admin.py` must require authenticated operator or internal-service access in production mode.
- If `admin_reads_require_auth=true`, even read-only session and transcript routes must fail closed without valid operator credentials.
- `get_operator_principal(...)` or its replacement remains the sole gateway-owned source of durable operator identity for operator-authored mutations and audit joins.
- Internal-service access remains distinct from operator access:
  - internal-service calls may satisfy authorization for trusted automation
  - internal-service callers must not implicitly become arbitrary operators
  - operator-authored writes still require a durable principal identifier
- `apps/node_runner/api/internal.py` must require both:
  - valid transport-level internal authentication such as `Authorization: Bearer ...` or equivalent header contract
  - valid signed request verification through the existing signing policy
- A request that fails either node-runner check must fail closed before execution.
- Channel-provider callback surfaces must continue verifying provider signatures or secrets through their adapters before acceptance, and failures must return bounded auth errors without leaking configured credentials.
- Health and readiness surfaces may stay public only for `live` probes. Any surface that reveals dependency readiness, configuration posture, or diagnostics detail must require auth when the corresponding hardening setting is enabled.

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

### Recovery and Reaper Contract
- One `RecoveryService` or equivalent is the sole owner of stale background-work detection and repair for:
  - `execution_runs`
  - `outbox_jobs`
  - `outbound_deliveries`
  - `node_execution_audits`
- Recovery scans must be bounded by configurable batch size and lookback windows.
- Recovery decisions must be idempotent and auditable.
- Minimum recovery actions in this slice are:
  - reclaim stale claimed or running `execution_runs` whose leases are expired and whose terminal state was not persisted
  - redrive stale `outbox_jobs` that are safe to retry from existing durable inputs
  - reschedule retryable `outbound_deliveries` whose `available_at` is due
  - reconcile `node_execution_audits` stuck in in-flight states by rechecking or terminally classifying them according to signed request id and timeout rules
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
- `apps/node_runner/api/internal.py` rejects requests that lack valid internal auth even if the signed payload is otherwise well formed.
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
- Unit tests for node-runner dual-auth enforcement and signing-key rotation overlap
- Unit tests for quota counter decisions, bounded scope keys, counter retention, and concurrent increment correctness
- Unit tests for provider backoff classification and delivery retry scheduling
- Unit tests for recovery-service decision logic and idempotent redrive behavior
- Unit tests for metrics/tracing adapters proving enabled vs disabled behavior through the existing facades
- Unit tests for secret redaction and masked diagnostics payloads
- Integration tests for inbound rate limiting with no duplicate transcript writes
- Integration tests for retryable provider failure followed by successful completion on the same logical run
- Integration tests for retryable delivery failure followed by redrive from persisted outbound artifacts only
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
