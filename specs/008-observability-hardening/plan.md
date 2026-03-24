# Plan 008: Observability, Diagnostics, and Operational Hardening

## Target Modules
- `apps/gateway/main.py`
- `apps/gateway/api/health.py`
- `apps/gateway/api/admin.py`
- `apps/gateway/api/inbound.py`
- `apps/gateway/deps.py`
- `apps/worker/jobs.py`
- `apps/node_runner/main.py`
- `apps/node_runner/api/internal.py`
- `apps/node_runner/policy.py`
- `apps/node_runner/executor.py`
- `src/config/settings.py`
- `src/db/models.py`
- `src/domain/schemas.py`
- `src/sessions/service.py`
- `src/sessions/repository.py`
- `src/jobs/service.py`
- `src/jobs/repository.py`
- `src/context/service.py`
- `src/context/outbox.py`
- `src/channels/dispatch.py`
- `src/media/processor.py`
- `src/execution/runtime.py`
- `src/execution/audit.py`
- `src/graphs/nodes.py`
- `src/policies/service.py`
- `src/observability/`
- `migrations/versions/`
- `tests/`

## Migration Order
1. Extend durable operational records so telemetry and diagnostics can correlate work already introduced in Specs 001 through 007:
   - `execution_runs`
     - make `trace_id` required for new accepted runs
     - add nullable `correlation_id`
     - add nullable `degraded_reason`
     - add nullable `failure_category`
   - `outbox_jobs`
     - add nullable `trace_id`
     - add nullable `failure_category`
   - `outbound_deliveries`
     - add nullable `trace_id`
     - add nullable `failure_category`
   - `outbound_delivery_attempts`
     - add nullable `trace_id`
   - confirm `node_execution_audits.trace_id` is populated whenever the parent run has one
   - backfill legacy correlation fields where practical and define lazy repair on reused pre-008 runs with null `trace_id`
2. Add any indexes needed for bounded diagnostics and stale-work inspection:
   - `execution_runs(status, updated_at)` or equivalent stale lookup support
   - `outbox_jobs(status, updated_at)` or equivalent stale lookup support
   - `outbound_deliveries(status, created_at)`
   - `outbound_delivery_attempts(status, created_at)`
   - `node_execution_audits(status, updated_at)` if current indexes are insufficient for stale detection
   - `message_attachments(normalization_status, created_at)` if attachment diagnostics need direct filtering
3. Introduce observability contracts and configuration before endpoint or service rewiring:
   - structured event schema
   - failure-category enum mapping
   - redaction helpers
   - correlation or trace context propagation helpers
   - metrics and tracing facade with local no-op support
   - diagnostics authorization settings
4. Wire correlation and structured logging through gateway, worker, context, dispatcher, media, execution runtime, and node runner before adding new diagnostics read surfaces.
5. Add liveness and readiness endpoints with dependency-aware checks before operator diagnostics so deployment automation gets the correct fail-closed surface early.
6. Add bounded read-only diagnostics queries and API endpoints over canonical tables or rebuildable views only.
7. Add metrics, stale-work signals, alert thresholds, and tracing export integration on top of the same identifiers and state transitions established earlier in the slice.
8. Finish with unit, API, repository, and integration coverage using `uv run pytest`.

## Implementation Shape
- Replace the stale pre-update plan completely: this slice does not include presence feeds, WebSocket presence control, or auth-profile failover. The updated spec is purely about telemetry, diagnostics, health or readiness, and operational safeguards for the capabilities already delivered in Specs 001 through 007.
- Preserve the current gateway-first architecture from the README and earlier plans:
  - gateway owns acceptance, dedupe, session resolution, and run creation
  - worker owns queued execution and outbound dispatch
  - node runner remains an internal execution boundary
  - observability must describe these flows, not redefine them
- Treat `execution_runs.trace_id` as the canonical end-to-end identifier for one accepted run in this slice:
  - generated on the gateway acceptance path when a run is created or reused
  - reused by worker execution, context assembly, governance checks, node execution, attachment normalization, and outbound delivery work
  - never replaced by per-component ad hoc identifiers
  - if a reused legacy run lacks `trace_id`, repair it on the gateway path before emitting downstream telemetry
- Keep logs, metrics, traces, and diagnostics aligned with persisted truth:
  - emit telemetry at the same durable transition points already owned by repositories and services
  - do not invent operator-visible state that cannot be tied back to canonical tables
- Keep observability dependency-injected and testable:
  - introduce explicit telemetry helpers, redaction helpers, and health-check services rather than hidden globals
  - local development must still work with JSON logs and no-op exporters when external backends are absent
- Split delivery into the same phases defined by the spec so identifiers and ownership stabilize before later instrumentation grows around them.

## Delivery Phases
### Phase A: Correlation, Structured Logging, and Failure Categories
- Add a shared observability package, for example:
  - `src/observability/logging.py`
  - `src/observability/context.py`
  - `src/observability/redaction.py`
  - `src/observability/failures.py`
  - `src/observability/metrics.py`
  - `src/observability/tracing.py`
- Standardize required event fields across gateway, worker, dispatcher, context, media, execution, and node runner:
  - `event_name`
  - `trace_id`
  - `session_id`
  - `execution_run_id`
  - `message_id`
  - `agent_id`
  - `channel_kind`
  - `channel_account_id`
  - `component`
  - `status`
  - `duration_ms` where timing is meaningful
- Add domain-specific event fields where the current code already has the underlying identifiers:
  - queueing and leases from `execution_runs` and lease tables
  - continuity and manifests from `context_manifests` and `summary_snapshots`
  - governance proposal and approval identifiers
  - node execution request and sandbox metadata
  - media and delivery identifiers from attachment and outbound tables
- Replace free-form logging in places such as `apps/gateway/api/inbound.py` and `src/context/service.py` with structured event helpers.
- Define one explicit failure-category mapping reused by logs, durable state, and diagnostics:
  - `validation`
  - `dependency_unavailable`
  - `policy_denied`
  - `approval_missing`
  - `timeout`
  - `retry_exhausted`
  - `delivery_failed`
  - `continuity_degraded`
  - `unexpected_internal`
- Apply redaction centrally:
  - hide `.env` and settings secrets
  - suppress auth headers, cookies, signed request bodies, and signing secrets
  - keep stdout and stderr previews bounded
  - keep transcript-content logging disabled by default except bounded preview mode when explicitly configured

### Phase B: Health, Readiness, and Dependency State
- Replace the current single `GET /health` shape in `apps/gateway/api/health.py` with:
  - `GET /health/live`
  - `GET /health/ready`
- Keep liveness process-only and cheap.
- Add readiness evaluation service, for example `src/observability/health.py`, that is configuration-aware:
  - PostgreSQL is required now
  - Redis, object storage, tracing backend, or node-runner connectivity are checked only when the deployment actually enables the relevant capability
  - disabled dependencies report `not_enabled` or `not_configured`, not synthetic healthy state
- Expose explicit degraded visibility in readiness responses instead of collapsing everything into a single boolean.
- Default exposure policy is:
  - `GET /health/live` may remain available for local development or container liveness checks
  - `GET /health/ready` is internal-only by default
  - `/diagnostics/*` remains explicitly authenticated and deny-by-default
- Mirror the same readiness pattern in the node runner if a separate service-level readiness surface is needed for deployment automation.

### Phase C: Read-Only Diagnostics APIs
- Extend gateway admin routing with bounded operator diagnostics:
  - `GET /diagnostics/runs`
  - `GET /diagnostics/runs/{run_id}`
  - `GET /diagnostics/sessions/{session_id}/continuity`
  - `GET /diagnostics/outbox-jobs`
  - `GET /diagnostics/node-executions`
  - `GET /diagnostics/deliveries`
  - `GET /diagnostics/attachments`
- Reuse or extend `apps/gateway/api/admin.py` rather than creating an unauthenticated side channel.
- Introduce dedicated read services, for example:
  - `src/observability/diagnostics.py`
  - additive repository methods in `src/sessions/repository.py` and `src/jobs/repository.py`
- Keep diagnostics bounded and deterministic:
  - explicit limit and pagination defaults
  - deterministic ordering
  - one shared cursor-based response envelope with `items`, `limit`, `next_cursor`, and `has_more`
  - filtered lookup by status, trigger kind, session, agent, recency, and stale-only flags where required
  - sanitized error summaries and bounded previews only
- Keep diagnostics routes stable even when optional capabilities are disabled:
  - return typed payloads with `capability_status`
  - use `enabled`, `not_enabled`, or `not_configured` instead of disappearing routes or ambiguous empty payloads
- Define concrete authorization before the endpoints are considered complete:
  - internal service token for machine callers
  - admin bearer token for human operators
  - deny by default when credentials are missing or invalid
  - keep `/health/*` authorization policy independent from `/diagnostics/*`

### Phase D: Metrics, Stale-Work Detection, and Tracing
- Add an OpenTelemetry-compatible facade with local no-op or console behavior when exporters are not configured.
- Support a Prometheus-compatible metrics endpoint only when configuration enables it.
- Emit bounded-cardinality metrics for the capabilities that exist now:
  - inbound acceptance, rejection, duplicate replay, and request latency
  - `execution_runs` status counts, queue depth, queue age, claim latency, run duration, retry counts, and dead-letter counts
  - lane contention and lease-steal recovery
  - `outbox_jobs` counts, age, failures, and backlog
  - governance approval backlog and age when approval-gated flows are active
  - node-runner execution counts, status, timeout, and duration
  - attachment normalization counts and failures
  - outbound delivery counts, attempts, retries, failures, and chunk totals
- Keep labels bounded to enum-like dimensions only:
  - `component`
  - `status`
  - `channel_kind`
  - `sandbox_mode`
  - `trigger_kind`
  - `failure_category`
- Add stale-work detection derived from durable state, not log scraping:
  - stale `execution_runs` in `claimed` or `running`
  - stale `outbox_jobs`
  - stale `scheduled_job_fires`
  - stale `outbound_deliveries` and `outbound_delivery_attempts`
  - stale `node_execution_audits`
  - stale or repeatedly failing attachment normalization
- Add causal tracing from gateway acceptance through worker completion when enabled:
  - inbound validation and dedupe
  - session resolution and transcript persistence
  - run creation or reuse
  - worker claim and lease acquisition
  - attachment normalization
  - context assembly
  - model or runtime execution
  - tool execution with a distinct remote-node segment when used
  - outbound dispatch and adapter sends
  - continuity follow-up or repair enqueue decisions

## Service and Module Boundaries
### Shared Observability Infrastructure
- `src/observability/context.py`
  - create, attach, and propagate `trace_id` and optional correlation metadata across service boundaries
- `src/observability/logging.py`
  - emit structured JSON events with required common fields
- `src/observability/redaction.py`
  - sanitize log and diagnostics payloads centrally
- `src/observability/failures.py`
  - map exceptions and terminal states to stable `failure_category` values
- `src/observability/health.py`
  - implement liveness and readiness checks
- `src/observability/diagnostics.py`
  - aggregate read-only diagnostics views from canonical tables
- `src/observability/metrics.py` and `src/observability/tracing.py`
  - provide exporter-agnostic instrumentation hooks with no-op local mode

### Gateway Responsibilities
- `apps/gateway/api/inbound.py`
  - create or reuse run correlation identifiers on accept
  - emit structured acceptance, duplicate, and rejection events
  - avoid free-form payload logging
  - repair missing `trace_id` on reused legacy runs before follow-on work continues
- `apps/gateway/api/health.py`
  - expose `GET /health/live` and `GET /health/ready`
- `apps/gateway/api/admin.py`
  - host read-only diagnostics endpoints and enforce explicit diagnostics authorization
- `apps/gateway/deps.py`
  - inject observability services, diagnostics authorization, and health services without global hidden state
- `apps/gateway/main.py`
  - register the updated health and diagnostics routes and any metrics endpoint if enabled

### Worker, Runtime, and Continuity Responsibilities
- `apps/worker/jobs.py`
  - preserve `trace_id` during claim, execution, retry, and terminal transitions
  - emit lease, retry, and stale-work visibility
- `src/jobs/service.py` and `src/jobs/repository.py`
  - emit queue and lease telemetry at durable transition boundaries
  - expose bounded diagnostics queries for run and outbox inspection
- `src/context/service.py` and `src/context/outbox.py`
  - emit manifest generation, degraded continuity fallback, compaction retry, and repair signals with bounded details
- `src/graphs/nodes.py`
  - propagate trace context through model and tool execution segments
- `src/policies/service.py`
  - emit governance visibility and approval gating signals only when those flows are active

### Media, Delivery, and Node Execution Responsibilities
- `src/media/processor.py`
  - emit normalization attempt, terminal outcome, and failure-category telemetry without exposing raw bytes
- `src/channels/dispatch.py`
  - emit structured delivery and chunk-attempt events
  - update delivery failure categories alongside durable state transitions
- `src/execution/runtime.py`
  - preserve parent `trace_id` in `NodeExecRequest`
  - classify timeout, denial, and transport failures consistently
- `src/execution/audit.py`
  - align node execution telemetry with persisted audit rows
- `apps/node_runner/api/internal.py`, `apps/node_runner/policy.py`, and `apps/node_runner/executor.py`
  - preserve incoming trace context
  - emit structured verification, execution start, timeout, rejection, and terminal outcome events with redacted bounded previews only

## Diagnostics Authorization Plan
- Add explicit settings in `src/config/settings.py`, for example:
  - `diagnostics_enabled`
  - `diagnostics_admin_bearer_token`
  - `diagnostics_internal_service_token`
  - `metrics_enabled`
  - `metrics_path`
  - `observability_log_json`
  - `observability_log_content_preview_enabled`
  - timeout and stale-threshold settings per domain
- Implement one shared dependency in `apps/gateway/deps.py` that distinguishes:
  - infrastructure access to `/health/*`
  - admin or internal authorized access to `/diagnostics/*`
- Treat `GET /health/ready` as internal-only by default even when `GET /health/live` is left open for liveness probes.
- Deny by default:
  - no placeholder open diagnostics mode
  - inability to validate caller trust is an authorization failure, not a warning

## Data and Contract Changes to Reflect in Code
- `src/db/models.py` and a new migration must make the additive observability fields from the spec real.
- `src/domain/schemas.py` should add typed health and diagnostics response models instead of returning loosely shaped dicts.
- `src/domain/schemas.py` should define one shared diagnostics page envelope and a typed `capability_status` field reused by disabled-capability diagnostics responses.
- Repository and service return types should expose bounded diagnostics summaries directly so API handlers stay thin.
- Existing read endpoints such as `GET /runs/{run_id}` and `GET /sessions/{session_id}/runs` should remain intact, but the new diagnostics surfaces become the operator-facing inspection layer for stale, degraded, or cross-component state.

## Risk Areas
- Logging or diagnostics accidentally leaking secrets, signed request data, provider metadata, or unrestricted transcript content.
- Letting metrics labels drift into high-cardinality identifiers such as `session_id`, `message_id`, `run_id`, or `request_id`.
- Adding diagnostics queries that become production hot paths because they scan large canonical tables without bounded predicates or indexes.
- Inconsistent `trace_id` propagation between gateway, worker, dispatcher, and node runner, which would make later metrics and tracing hard to trust.
- Emitting telemetry before durable transitions succeed, causing operator-visible events to disagree with database truth.
- Treating disabled optional dependencies as healthy instead of explicitly `not_enabled` or `not_configured`.
- Creating a half-complete diagnostics surface without concrete authorization, which would violate the spec's security constraints.

## Rollback Strategy
- Keep schema changes additive and avoid rewriting canonical business-state ownership from Specs 001 through 007.
- Make exporters, metrics endpoints, and content-preview logging independently disableable by configuration.
- Preserve structured logging and correlation fields as the minimum fallback even if tracing exporters or metrics backends are unavailable.
- Roll back diagnostics endpoints separately from core request or worker flows if bounded query performance or authorization wiring needs to be disabled.
- If readiness checks for optional dependencies prove noisy, leave the dependency status in the payload but gate readiness impact by configuration rather than removing the dependency summary contract.

## Test Strategy
- Unit:
  - failure-category mapping for validation, policy denial, approval missing, timeout, retry exhaustion, delivery failure, continuity degradation, and unexpected internal errors
  - redaction helpers for secrets, signed request fields, auth headers, and bounded previews
  - trace or correlation propagation helpers across gateway, worker, and node-runner contracts
  - readiness classification for required, optional, disabled, and misconfigured dependencies
  - diagnostics authorization success and fail-closed behavior
  - stale-work classification for runs, outbox jobs, deliveries, node audits, scheduled job fires, and attachments
- Repository:
  - additive field persistence on `execution_runs`, `outbox_jobs`, `outbound_deliveries`, `outbound_delivery_attempts`, and `node_execution_audits`
  - legacy-row backfill and lazy repair behavior for reused runs missing `trace_id`
  - bounded diagnostics queries with deterministic ordering and filters
  - index-backed stale lookup behavior where repository methods encode the stale logic
- API:
  - `GET /health/live` remains healthy when external dependencies are unavailable
  - `GET /health/ready` reports false for required failed dependencies and `not_enabled` or `not_configured` for disabled optional ones
  - `GET /health/ready` is protected according to the internal-only default unless deployment config overrides it
  - `/diagnostics/*` routes require explicit authorization
  - diagnostics payloads remain bounded, cursor-paginated, capability-aware, and sanitized
- Integration:
  - one accepted inbound run preserves the same `trace_id` through gateway acceptance, worker execution, node execution if used, attachment normalization, and outbound delivery
  - duplicate replay and retry flows keep correlation coherent without inventing new root identifiers
  - degraded continuity fallback is visible in logs and diagnostics
  - node-runner timeout or unavailability surfaces as readiness or failure telemetry without secret leakage
  - delivery and attachment failure spikes are reflected in durable diagnostics state
- Implementation notes:
  - update existing API coverage such as `tests/test_api.py`
  - add observability-focused integration coverage instead of relying only on log snapshot tests
  - run targeted checks with `uv run pytest`

## Constitution Check
- Gateway-first execution remains intact: observability instruments gateway, worker, dispatcher, and node-runner boundaries without moving orchestration out of existing owners.
- Transcript-first and durable-state-first persistence remain intact: diagnostics and telemetry are derived from canonical tables plus additive instrumentation, not alternate mutable sources of truth.
- Approval and privileged execution boundaries remain intact: observability may expose bounded status and identifiers, but it does not create a new write path into governance or node execution.
- Bounded, inspectable operations remain intact: logs, diagnostics, readiness, and metrics are all constrained by redaction, pagination, bounded previews, and bounded metric dimensions.
