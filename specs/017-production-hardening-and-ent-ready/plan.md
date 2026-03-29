# Plan 017: Production Hardening and Enterprise Readiness

## Target Modules
- `src/config/settings.py`
- `src/db/models.py`
- `src/domain/schemas.py`
- `src/security/signing.py`
- `src/observability/metrics.py`
- `src/observability/tracing.py`
- `src/observability/redaction.py`
- `src/observability/logging.py`
- `src/observability/health.py`
- `src/observability/diagnostics.py`
- `src/observability/failures.py`
- `src/providers/models.py`
- `src/sessions/service.py`
- `src/sessions/repository.py`
- `src/jobs/repository.py`
- `src/jobs/service.py`
- `src/context/outbox.py`
- `src/channels/dispatch.py`
- `src/channels/adapters/slack.py`
- `src/channels/adapters/telegram.py`
- `src/channels/adapters/webchat.py`
- `src/execution/runtime.py`
- `src/execution/audit.py`
- `src/sandbox/service.py`
- `src/media/processor.py`
- `apps/gateway/deps.py`
- `apps/gateway/main.py`
- `apps/gateway/api/admin.py`
- `apps/gateway/api/health.py`
- `apps/gateway/api/inbound.py`
- `apps/gateway/api/slack.py`
- `apps/gateway/api/telegram.py`
- `apps/gateway/api/webchat.py`
- `apps/node_runner/main.py`
- `apps/node_runner/api/health.py`
- `apps/node_runner/api/internal.py`
- `apps/node_runner/policy.py`
- `apps/worker/jobs.py`
- `migrations/versions/`
- `docs/`
- `tests/`

## Success Conditions
- All admin, diagnostics, governance-read, transcript-read, and readiness surfaces fail closed behind one shared dual-caller auth contract with distinct operator and internal-service principals.
- Operator-authored mutations continue to require a durable human operator principal and cannot be satisfied by internal-service credentials.
- Real provider, channel, and node-runner credentials are validated at startup, redacted in logs and diagnostics, and never returned raw by health, admin, or diagnostics APIs.
- Rate limiting and quota enforcement are handled by one backend-owned quota service with durable PostgreSQL-backed counters and bounded scopes.
- Inbound and callback rate-limit rejection returns `429`, sets `Retry-After` when meaningful, and does not mutate transcript, dedupe, or queue state.
- Provider-backed model calls use bounded exponential backoff with jitter and preserve one logical `execution_run` identity per turn.
- Outbound delivery retries and redrive operate from existing outbound intent and delivery state without re-running model inference or duplicating assistant transcript rows.
- One explicit recovery service owns stale detection and repair for `execution_runs`, `outbox_jobs`, `outbound_deliveries`, and `node_execution_audits` using one typed stale-state matrix.
- Metrics and tracing facades gain real exporter-backed implementations behind settings gates, while local development still works with no-op behavior.
- Diagnostics remain bounded, retention-aware, and authenticated; they never require unbounded scans to explain current operational state.
- Node-runner execution stays signed in both modes and additionally requires transport auth in `http` mode.
- Sandbox and remote-exec posture fail closed in production, with bounded stdout or stderr capture and explicit `off`-mode restrictions.
- Media retention includes purge scheduling and safe failure visibility for expired files and derivatives.
- The repo ships a deterministic full-path smoke suite using local process boundaries, fake providers or channels, signed node-runner requests, and real durable state.
- The repo ships operator-readable disaster-recovery and rotation procedures in `docs/`.

## Current Codebase Constraints From Specs 001-016
- Spec 001 established the gateway-first ingress path, canonical session identity, PostgreSQL durability, and append-only transcript rules. Production hardening must preserve those invariants and may not repair stale work by replaying inbound user input.
- Specs 002, 009, and 010 already separate graph orchestration, typed tool execution, and provider-backed runtime behavior from transport logic. Hardening should add retries, quotas, and auth at those seams rather than rewire orchestration.
- Spec 003 made exact approval enforcement backend-authoritative, which means approval callbacks and admin decisions must reuse the same services and must not become a second source of truth.
- Specs 004 and 011 already rely on durable context artifacts and recovery-friendly rebuild paths, so diagnostics and retention work must stay additive and bounded.
- Spec 005 made `execution_runs` the durable queue owner with retries on the same row. Spec 017 should extend that row with recovery fields rather than inventing a parallel repair queue.
- Spec 006 established signed node execution, sandbox resolution, and capability-owned command templates. Production hardening should strengthen transport auth, output bounds, and mode handling around that existing contract.
- Specs 007, 012, and 013 already separate outbound intents, deliveries, delivery attempts, and streaming events. The spec’s retry-ownership decision fits the current `src/channels/dispatch.py` design: pre-delivery orchestration remains outbox-owned, but once a logical delivery exists, redrive should hang off that delivery identity.
- Spec 008 introduced structured logging, health, diagnostics, trace ids, and stale thresholds, but the metrics and tracing facades are still mostly stubs and diagnostics auth remains inconsistent.
- Specs 014 through 016 already added durable agent bindings, delegation, blocked automation, approval prompts, and collaboration controls. Recovery and auth changes must respect those durable identities and must not create second child sessions, prompts, or operator actors during redrive.
- The current repository already has the right implementation seams:
  - `apps/gateway/deps.py` centralizes dependency wiring and current auth helpers
  - `apps/gateway/api/admin.py` and `apps/gateway/api/health.py` already expose the sensitive surfaces that need consistent auth
  - `apps/node_runner/api/internal.py` already verifies signed payloads but lacks a second transport guard
  - `src/providers/models.py` already retries provider calls, but only through adapter-local settings and without the broader quota or observability contract
  - `src/jobs/service.py` already owns worker execution, suppression checks, and retry transitions
  - `src/jobs/repository.py` already owns queue claim, leases, and blocked-run release
  - `src/channels/dispatch.py` already owns durable delivery creation and append-only attempts
  - `src/observability/health.py`, `src/observability/logging.py`, `src/observability/redaction.py`, `src/observability/metrics.py`, and `src/observability/tracing.py` already provide the façade layer that this slice should harden
  - `src/sandbox/service.py`, `src/execution/runtime.py`, and `apps/node_runner/policy.py` already form the remote-execution trust boundary
- Main production gaps still open in code:
  - unauthenticated admin or transcript reads still exist
  - operator and internal-service caller identity are not cleanly separated
  - diagnostics tokens are still diagnostics-specific rather than one shared auth contract
  - no durable quota table or quota service exists
  - stale thresholds are configured, but no single recovery owner implements typed repair rules across workflow families
  - delivery retry ownership is not yet codified around the durable delivery row
  - metrics and tracing remain mostly placeholder facades
  - secret validation and secret exposure rules are incomplete
  - node-runner HTTP transport auth and rotation overlap are not yet modeled explicitly
  - no documented disaster-recovery runbook or deterministic smoke suite covers the whole production path

## Migration Order
1. Extend durable operational schema first:
   - `rate_limit_counters`
   - recovery fields on `execution_runs`
   - recovery and retry fields on `outbox_jobs`
   - retry and recovery fields on `outbound_deliveries`
   - recovery fields on `node_execution_audits`
2. Add lookup indexes needed for bounded recovery scans, bounded diagnostics, and quota retention cleanup before enabling new workflows.
3. Expand settings and shared auth or quota contracts before route rewiring:
   - shared operator and internal auth settings
   - node-runner mode settings
   - quota and retry settings
   - retention, diagnostics-lookback, and exporter settings
   - sandbox and media hardening settings
4. Implement shared auth dependencies and caller-principal models before changing admin, diagnostics, readiness, and node-runner endpoints.
5. Implement quota service and enforcement points before stronger provider retry or recovery automation so overload decisions happen at ingress and before expensive work.
6. Implement retry classification and durable delivery or provider backoff next so existing run and delivery rows can survive transient failures safely.
7. Add recovery service and bounded reaper workflows after durable state and retry fields are in place.
8. Upgrade metrics, tracing, health, and diagnostics on top of the same state transitions so telemetry reflects persisted truth.
9. Harden sandbox, remote execution, and media purge after auth and recovery primitives exist.
10. Finish with docs, smoke coverage, and rollout-safe enforcement defaults.

## Implementation Shape
- Keep the current architecture intact:
  - gateway accepts and authenticates ingress
  - session service persists canonical transcript state and enqueues work
  - worker owns queued execution
  - dispatcher owns outbound transport
  - node runner remains a separate execution boundary
  - diagnostics and telemetry remain additive views over durable state
- Introduce four explicit shared services instead of scattering logic:
  - `AuthService` or equivalent shared dependency in `apps/gateway/deps.py` for operator vs internal-service caller validation and principal derivation
  - `QuotaService` for durable rate-limit and quota decisions backed by PostgreSQL counters
  - `RecoveryService` for stale-work detection and typed repair actions across workflow families
  - `SecretPostureService` or lightweight helpers for startup validation, masking, key-fingerprint reporting, and rotation-aware exposure rules
- Keep enforcement at the actual ownership seams:
  - gateway routes enforce auth and ingress quotas
  - provider runtime enforces provider quotas and retries
  - dispatcher and outbox paths enforce delivery retries and redrive
  - recovery service repairs durable rows rather than replaying source inputs
  - observability hooks emit from the same state transitions already persisted by repositories and services
- Treat node-runner mode explicitly:
  - `in_process` remains valid for tests, local dev, and single-process deployments
  - `http` requires transport auth plus signed payload verification on every request
- Treat retention and diagnostics as bounded operational views:
  - do not expose raw secrets
  - do not require unbounded scans
  - do not invent operator-visible state that cannot be reconstructed from durable records

## Workstreams
### 1. Shared Auth and Caller Identity
- Extend `src/config/settings.py` with the explicit Spec 017 auth settings:
  - `admin_reads_require_auth`
  - `diagnostics_require_auth`
  - `operator_auth_bearer_token`
  - `internal_service_auth_token`
  - `operator_principal_header_name`
  - `internal_service_principal_header_name`
  - `node_runner_internal_bearer_token`
  - `auth_fail_closed_in_production`
- Preserve rollout compatibility by accepting current diagnostics token settings as aliases during migration, but normalize all route dependencies onto one shared auth contract.
- Refactor `apps/gateway/deps.py` so it exposes:
  - one validator for operator callers
  - one validator for internal-service callers
  - one helper that can authorize either caller kind for approved read surfaces
  - one helper that derives a durable operator principal only for real operator callers
  - one helper that derives a durable internal-service principal for machine-safe reads
- Update `apps/gateway/api/admin.py` so all sensitive reads and writes follow the selected fail-closed auth policy, including session and transcript reads when `admin_reads_require_auth=true`.
- Update `apps/gateway/api/health.py` readiness behavior to use the same shared auth contract rather than a special-case check.
- Update `apps/node_runner/api/internal.py` so `http` transport mode requires valid transport auth before signed payload verification.
- Add clear authorization ceilings:
  - internal service can read approved operational surfaces
  - internal service cannot perform operator-authored collaboration or approval mutations
  - operator writes still require durable human operator identity

### 2. Secret Validation, Redaction, and Rotation Posture
- Expand settings validation in `src/config/settings.py` to fail boot when enabled real accounts or remote execution modes are missing required credentials.
- Add rotation-aware settings support for:
  - overlapping node-runner signing keys
  - bearer-token replacement windows where the old and new credentials can coexist during rollout
- Harden `src/observability/redaction.py` and any settings serialization helpers so all secret-bearing keys and headers are masked consistently, including new auth and node-runner settings.
- Ensure `src/observability/logging.py`, diagnostics serializers, and health responses expose only posture data:
  - configured vs missing
  - key id
  - masked suffix or stable fingerprint
  - no raw secret material
- Review channel adapter and provider error paths to ensure exceptions cannot accidentally include raw credentials in structured logs or diagnostics payloads.

### 3. Durable Quota and Rate-Limit Service
- Add `rate_limit_counters` to `src/db/models.py` and a migration with the required uniqueness and retention indexes.
- Add repository helpers for counter increment, window resolution, and retention cleanup.
- Implement a `QuotaService` that supports bounded windows and scope kinds from the spec:
  - `gateway_route`
  - `channel_account`
  - `operator_principal`
  - `agent_id`
  - `provider_model`
  - `approval_surface`
- Enforce quotas at the required first points:
  - `POST /inbound/message`
  - provider callback routes
  - approval action routes
  - authenticated admin and diagnostics routes
  - provider-backed model execution before network calls
- Return `429` plus `Retry-After` when appropriate and ensure rejection happens before dedupe finalization, transcript append, run creation, or provider request dispatch.
- Emit bounded telemetry and diagnostics context for rate-limit denials without adding unbounded labels or scope keys.
- Add the explicit quota settings contract to `src/config/settings.py`, including:
  - `rate_limits_enabled`
  - `inbound_requests_per_minute_per_channel_account`
  - `admin_requests_per_minute_per_operator`
  - `approval_action_requests_per_minute_per_session`
  - `provider_tokens_per_hour_per_agent`
  - `provider_requests_per_minute_per_model`
  - `quota_counter_retention_days`

### 4. Provider Retry, Backoff, and Quota Integration
- Refactor `src/providers/models.py` so retry timing comes from explicit Spec 017 settings rather than the current hard-coded adapter-local values.
- Keep retries bounded within one logical run attempt and never create a new `execution_run`.
- Preserve Spec 009 semantic-fallback behavior by retrying only classified transport or availability failures, not malformed semantic outputs that should resolve safely.
- Add provider request counting and token-estimate reporting into the metrics façade using bounded model or profile dimensions.
- Integrate provider quotas so exhausted quotas either:
  - reschedule the existing run with bounded backoff, or
  - fail it terminally with explicit quota classification when retry cannot help
- Add the explicit provider-retry settings contract:
  - `provider_retry_base_seconds`
  - `provider_retry_max_seconds`
  - `provider_retry_jitter_seconds`

### 5. Delivery Retry Ownership and Durable Redrive
- Extend `outbound_deliveries` and related repository methods with:
  - `available_at`
  - `attempt_count`
  - `last_attempt_at`
  - `recovery_state`
  - `recovery_reason`
  - `recovered_at`
- Keep `outbox_jobs` as the pre-delivery orchestrator, but once a logical delivery row exists for `(outbound_intent_id, chunk_index)`, route all automatic retry and recovery-safe redrive through that delivery identity.
- Update `src/channels/dispatch.py` so retryable send failures:
  - increment attempt counters
  - persist the next `available_at`
  - record bounded retry classification
  - do not create duplicate logical delivery rows
- Ensure non-retryable failures end in a terminal delivery state and do not loop through outbox redrive.
- Add a dispatcher or repository entrypoint for redriving due deliveries from existing persisted payloads without re-running graph execution or re-creating transcript rows.
- Add the explicit delivery and outbox retry settings contract:
  - `outbox_max_attempts`
  - `delivery_retry_base_seconds`
  - `delivery_retry_max_seconds`
  - `delivery_max_attempts`

### 6. Recovery Service and Reaper Workflow
- Add recovery fields to `execution_runs`, `outbox_jobs`, `outbound_deliveries`, and `node_execution_audits` as specified.
- Implement one `RecoveryService` that owns the stale-state matrix and uses settings-backed grace thresholds and batch sizes.
- Provide typed scanners and repair methods for:
  - stale claimed or running `execution_runs`
  - stale `outbox_jobs`
  - due or stale retryable `outbound_deliveries`
  - stale `node_execution_audits`
- Ensure repair actions are idempotent and bounded:
  - requeue the same run row
  - move the same outbox row back to pending with a future `available_at`
  - create a new attempt under the same logical delivery row
  - reconcile or terminally classify the same node execution request id
- Record recovery state and reason on the repaired row and emit auditable telemetry so diagnostics can explain what happened.
- Keep the repair rules aligned with existing durable identities introduced in earlier specs:
  - never create a second inbound transcript row
  - never create a second child session or delegation row
  - never create a second approval prompt for the same durable prompt identity
- Add the explicit recovery settings contract:
  - `recovery_scan_interval_seconds`
  - `recovery_batch_size`
  - `recovery_max_attempts_per_record`
  - `execution_run_recovery_grace_seconds`
  - `outbox_job_recovery_grace_seconds`
  - `outbound_delivery_recovery_grace_seconds`
  - `node_execution_recovery_grace_seconds`

### 7. Metrics, Tracing, Health, and Diagnostics
- Replace the stub behavior in `src/observability/metrics.py` and `src/observability/tracing.py` with exporter-backed implementations behind explicit enablement settings.
- Keep local default behavior as no-op or in-memory so tests and local development remain deterministic.
- Emit bounded-cardinality metrics for the required spec dimensions:
  - inbound accepted, rejected, duplicate, rate-limited
  - execution-run queue depth, active, retry, dead-letter, stale, duration
  - provider requests, errors, token estimates
  - outbox backlog, stale, retry, failure
  - delivery success, retry, terminal failure, backlog
  - node-execution request, reject, timeout, reconcile
  - media purge counts
  - auth failure counts
- Extend `src/observability/health.py` so readiness reflects configuration-aware dependency posture, not only PostgreSQL plus static flags.
- Extend `src/observability/diagnostics.py` and admin routes with bounded, retention-aware filters:
  - status
  - failure category
  - stale-only
  - bounded lookback
- Ensure diagnostics degrade gracefully when retention horizons have expired rather than scanning indefinitely.
- Add the explicit observability and diagnostics settings contract:
  - `audit_retention_days`
  - `diagnostics_default_lookback_hours`
  - `diagnostics_max_lookback_days`
  - `metrics_exporter_kind`
  - `tracing_exporter_kind`

### 8. Sandbox, Node-Runner, and Media Hardening
- Expand settings for:
  - `node_runner_mode`
  - `node_runner_base_url`
  - `sandbox_off_mode_allowed_environments`
  - `sandbox_exec_max_stdout_bytes`
  - `sandbox_exec_max_stderr_bytes`
  - `node_runner_key_rotation_overlap_seconds`
  - `media_purge_interval_seconds`
  - `media_delete_grace_seconds`
- Update `src/security/signing.py` and node-runner wiring to support overlapping signing keys and explicit key-id validation during rotation windows.
- Update `src/execution/runtime.py` and dependency wiring so remote execution can cleanly switch between `in_process` and `http` modes without weakening signing requirements.
- Harden `src/sandbox/service.py` and `apps/node_runner/policy.py` so `off` mode is treated as exceptional and environment-gated.
- Ensure node-runner audit storage and executor behavior cap stdout or stderr previews and truncation metadata deterministically.
- Add a media purge workflow in `src/media/processor.py` or a small retention helper that deletes expired files safely and records purge-pending or purge-failed state when cleanup fails.

### 9. Docs, Smoke Tests, and Rollout Safety
- Add a disaster-recovery runbook under `docs/` covering:
  - PostgreSQL backup and restore order
  - media backup and restore order
  - signing-key rotation and rollback
  - worker and recovery restart sequence
  - reconciliation steps after restore
- Add deterministic smoke coverage that exercises:
  - gateway ingress
  - session and dedupe persistence
  - worker execution
  - provider-backed runtime through a fake provider
  - approval gating
  - outbound delivery persistence and retry
  - authenticated diagnostics inspection
  - signed node-runner execution in a test-safe mode
  - one stale-work or retry recovery path
- Keep live-provider or live-channel checks optional and environment-gated only.
- Sequence enforcement toggles last so schema, reads, and diagnostics can work before strict defaults are enabled.

## Proposed Delivery Phases
### Phase A: Schema, Settings, and Auth Foundation
- Migrations for quota and recovery fields
- shared auth settings and principal contracts
- startup credential validation
- admin, readiness, diagnostics, and node-runner auth unification

### Phase B: Quotas, Retry, and Delivery Ownership
- quota service and ingress or provider enforcement
- provider retry settings and metrics hooks
- delivery retry ownership encoded in repository and dispatcher behavior

### Phase C: Recovery and Operational Visibility
- recovery service and reaper scan loops
- retention-aware diagnostics filters
- exporter-backed metrics and tracing
- readiness posture expansion and alertable signals

### Phase D: Sandbox, Media, and Production Validation
- node-runner mode split and transport auth
- signing-key rotation overlap
- stdout or stderr bounds
- media purge workflow
- disaster-recovery docs and smoke suites

## Test Strategy
- Settings tests for fail-closed auth, credential validation, node-runner mode requirements, retention bounds, and quota-setting validation.
- API tests for:
  - protected admin and transcript reads
  - protected readiness and diagnostics reads
  - operator vs internal-service caller separation
  - node-runner transport auth plus signed request verification
  - `429` behavior and `Retry-After` headers on inbound, admin, approval, and callback limits
- Repository tests for:
  - quota counter correctness under repeated increments
  - recovery-field transitions
  - due-delivery redrive under one logical delivery identity
  - bounded stale-work scans
- Service tests for:
  - provider retry classification and bounded jittered backoff
  - recovery repair decisions per workflow family
  - delivery retry ownership transfer from outbox to delivery rows
  - secret redaction and fingerprint exposure rules
- Integration tests for:
  - full gateway to worker to delivery flow with fake provider and fake channels
  - retryable provider failure that stays on one `execution_run`
  - stale run or delivery recovery without duplicate transcript rows
  - signed node-runner execution in `http` mode against the local node-runner app
  - diagnostics visibility after recovery or quota-denied events
- Smoke tests should run against real process boundaries where practical, reusing the app factories already present in `apps/gateway/main.py`, `apps/node_runner/main.py`, and `apps/worker/jobs.py`.

## Implementation Risks and Sequencing Notes
- Auth should land before exposing stronger diagnostics because the current code still leaves some sensitive reads open.
- Quotas should reject before transcript or dedupe mutation; otherwise the system can become rate-limited and still produce durable user-visible side effects.
- Recovery must be implemented after retry ownership is explicit, especially for outbound deliveries, or the system risks double-send behavior.
- Key rotation support should be wired before strict production auth defaults are flipped on, otherwise deploys can force hard cutovers.
- Metrics labels and quota scopes must stay bounded from the start; retrofitting bounded cardinality after rollout is painful and easy to get wrong.
- The plan assumes PostgreSQL remains the only durable backend for this slice, matching the spec decision and the current repository architecture.

## Plan Review
- The plan covers every explicit Scope item in `specs/017-production-hardening-and-ent-ready/spec.md`.
- The plan incorporates each gap resolution selected in Spec 017:
  - auth boundary uses one shared dual-caller contract
  - quota storage is PostgreSQL-backed behind an abstraction
  - stale-work repair is owned by one recovery service
  - credential hardening stays settings-backed instead of introducing a secrets-manager rewrite
  - smoke coverage is deterministic and local-first
  - operator and internal-service identities are split cleanly
  - node-runner supports `in_process` and `http`
  - stale detection uses one typed matrix
  - delivery retry ownership transfers to durable delivery rows
- The sequencing is implementation-safe:
  - additive schema first
  - shared contracts second
  - enforcement and recovery after durable state exists
  - docs and strict defaults last
- The plan stays compatible with Specs 001 through 016 by preserving:
  - gateway-first ingress
  - worker-owned execution
  - append-only transcript truth
  - exact approval enforcement
  - durable session, run, delivery, delegation, and collaboration identities
- No unresolved blocker remains at plan level; the spec is implementable with the existing repository seams and the workstreams above.
