# Spec 008: Observability, Diagnostics, and Operational Hardening

## Purpose
Add the operator-facing telemetry, diagnostics, and fail-closed operational protections needed to run the gateway, worker, continuity, governance, node-runner, and channel-delivery flows from Specs 001 through 007 as a credible multi-user service.

## Non-Goals
- Presence feeds, typing indicators, or WebSocket presence snapshots
- Auth-profile rotation or provider credential failover
- New business capabilities, agent behaviors, or channel features
- Replacing durable audits or canonical persistence contracts from earlier specs
- Mutating recovery actions through public APIs in this slice

## Upstream Dependencies
- Specs 001 through 007

## Scope
- End-to-end correlation identifiers and telemetry contracts across gateway, worker, runtime, dispatcher, and node runner
- Structured logging with required event fields and redaction rules
- Metrics for queueing, continuity, governance, remote execution, media normalization, and outbound delivery
- Tracing or equivalent causal-span instrumentation for one accepted run across internal components
- Read-only operational diagnostics APIs for sessions, runs, outbox work, node execution, attachments, and outbound deliveries
- Health, readiness, and dependency-state surfaces suitable for deployment automation
- Operational hardening rules for timeouts, bounded diagnostics payloads, stale-work detection, and degraded-mode visibility
- Alertable failure classifications and backlog/staleness signals derived from durable state

## Delivery Phases
- This spec is implemented as one bounded slice with phased acceptance so observability hardening can land without collapsing existing service boundaries.
- Phase A: end-to-end correlation identifiers, structured logging, redaction rules, and failure-category mapping for gateway, worker, runtime, dispatcher, and node runner
- Phase B: liveness/readiness surfaces with configuration-aware dependency evaluation and explicit degraded-state visibility
- Phase C: read-only diagnostics APIs for runs, continuity, outbox work, node execution, deliveries, and attachments
- Phase D: metrics, alert thresholds, and tracing/export integration built on the same correlation and durable-state contracts established in earlier phases
- Earlier phases establish the minimum platform needed for later phases; later phases may extend coverage but must not redefine identifiers, durable state, or service ownership established earlier in this spec

## Capability Matrix
- The observability requirements in this spec apply according to capability status so the slice remains aligned with the current project maturity.
- Required now because the capability is already implemented in the repository:
  - gateway inbound acceptance, dedupe handling, session resolution, and run creation
  - worker claim, lease management, retry visibility, and terminal run persistence
  - attachment normalization
  - outbound dispatch and channel adapter send attempts
  - node-runner request construction, request handling, and audit correlation
  - governance checks executed on active approval-gated flows
- Required when the capability is enabled in a deployment or completed in a later spec:
  - continuity summary-staleness metrics, compaction retries, degraded transcript-first fallback visibility, and repair outcomes
  - retrieval-aid degradation visibility tied to continuity or retrieval features that are actually enabled
  - approval backlog metrics or diagnostics for governance paths that are configured for the current deployment
  - dependency readiness checks for optional infrastructure such as Redis, object storage, tracing backends, or node-runner connectivity
- For any capability that is disabled, stubbed, or not yet implemented, the system must either omit the signal entirely or emit an explicit `not_enabled` or `not_configured` status; it must not fabricate healthy-looking metrics or diagnostics for absent behavior

## Data Model Changes
- No new canonical business-state tables are required in this spec if telemetry can be emitted from existing durable state plus application instrumentation.
- Extend durable operational records introduced by earlier specs where needed so diagnostics and telemetry can correlate one execution attempt end to end:
  - `execution_runs`
    - require stable `trace_id`
    - add nullable `correlation_id` if distinct from `trace_id`
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
  - `node_execution_audits`
    - the `trace_id` field from Spec 006 becomes required whenever the parent `execution_run` has one
- Optional additive diagnostics views or materialized views may be introduced for efficient read-only inspection, but they must be rebuildable from canonical tables and must not become the sole source of truth for operator-visible state.
- Legacy rows created before this spec may continue to store nullable observability fields until migrated, but the implementation must define a concrete transition path:
  - perform an additive backfill for legacy `execution_runs`, `outbox_jobs`, and delivery records where practical
  - if a pre-008 `execution_run` is reused and its `trace_id` is null, the gateway must mint and persist a stable `trace_id` before any further telemetry or asynchronous work is emitted for that run
  - diagnostics must not silently treat legacy null correlation fields as healthy modern telemetry; they must either surface the repaired value or mark the record as legacy correlation state until repair occurs

## Contracts
### Correlation and Telemetry Contract
- Every accepted user-visible run must have one stable end-to-end correlation identity beginning on the gateway-owned acceptance path.
- `execution_runs.trace_id` is the canonical trace identifier for the run in this slice.
- Run reuse must preserve, not replace, the canonical correlation identity:
  - if a reused run already has a `trace_id`, all later work must continue using it
  - if a reused run predates this spec and has no `trace_id`, the gateway acceptance path must assign one once and persist it before worker-visible follow-on work continues
- The following components must emit structured telemetry that includes `trace_id` whenever a run exists:
  - gateway inbound acceptance and duplicate replay handling
  - worker claim, lease refresh, execution start, retry, and terminal persistence
  - context assembly, compaction retry, degraded continuity fallback, and repair enqueue decisions
  - governance proposal/approval visibility checks performed during execution
  - tool execution, including remote node execution request construction and result mapping
  - attachment normalization and outbound dispatch activity
  - channel adapter send attempts
- When no `execution_run` exists yet, gateway logs must still emit enough correlation to diagnose the accepted or rejected request:
  - `channel_kind`
  - `channel_account_id`
  - `external_message_id` when present
  - `session_id` and `message_id` once resolved
- Telemetry emitted by asynchronous follow-on work must reuse the parent run `trace_id` rather than inventing an unrelated identifier.

### Structured Logging Contract
- All operator-facing logs in this slice must be structured, machine-parseable events rather than free-form strings only.
- Required common fields for gateway, worker, and dispatcher events are:
  - `event_name`
  - `trace_id`
  - `session_id` nullable only before session resolution
  - `execution_run_id` nullable when no run exists yet
  - `message_id` nullable when no canonical message row exists yet
  - `agent_id` nullable only where not yet resolved
  - `channel_kind` nullable for non-channel internal work
  - `channel_account_id` nullable for non-channel internal work
  - `component`
  - `status`
  - `duration_ms` for bounded operations where timing is meaningful
- Required additional fields by domain are:
  - queueing: `lane_key`, `attempt_count`, `worker_id`, `available_at`, `lease_expires_at`
  - continuity: `manifest_id`, `degraded`, `degraded_reason`, `summary_snapshot_id` nullable
  - governance: `proposal_id`, `approval_id`, `typed_action_id`
  - node execution: `request_id`, `sandbox_mode`, `sandbox_key`, `workspace_root`, `exit_code` nullable
  - media and delivery: `attachment_id`, `outbound_intent_id`, `outbound_delivery_id`, `chunk_index`, `attempt_number`
- Logs must classify terminal failures with one explicit `failure_category` field. Minimum categories in this slice are:
  - `validation`
  - `dependency_unavailable`
  - `policy_denied`
  - `approval_missing`
  - `timeout`
  - `retry_exhausted`
  - `delivery_failed`
  - `continuity_degraded`
  - `unexpected_internal`
- The implementation may emit additional fields, but required fields must remain stable for operators and tests.

### Redaction and Secret-Handling Contract
- Secrets and sensitive content must never be emitted to logs, traces, metrics labels, or diagnostics payloads.
- At minimum, the following must be redacted or excluded:
  - `.env` values and credential material
  - authorization headers, cookies, signed request bodies, and signature keys
  - raw attachment bytes
  - full stdout or stderr beyond the bounded previews already allowed by Spec 006
  - approval packet content when it would reveal secret values rather than identifiers and hashes
- User message content and assistant content may be logged only in bounded preview form when explicitly enabled by configuration; the default production posture must avoid full transcript-content logging.
- Diagnostics APIs may expose identifiers, statuses, timestamps, bounded error summaries, and bounded previews already permitted by earlier specs, but they must not expose raw secrets or unrestricted payload blobs.

### Metrics Contract
- This spec requires process metrics plus domain metrics derived from durable workflow state.
- OpenTelemetry-compatible instrumentation is the preferred abstraction for metrics and tracing in this slice, but the implementation may expose Prometheus-compatible scraping or another exporter format at the service edge.
- Minimum counters, gauges, or histograms must cover:
  - inbound acceptance, rejection, duplicate replay, and request latency
  - `execution_runs` by status, queue depth, queue age, claim latency, run duration, retry count, and dead-letter count
  - session-lane contention and lease-steal recovery
  - `outbox_jobs` pending count, running count, age, failure count, and repair backlog
  - continuity compaction retries, degraded transcript-first runs, summary-staleness observations, and repair outcomes
  - governance pending approvals, approval-age distribution, activation failures, and revocation events
  - node-runner request count, rejection count, timeout count, execution duration, and sandbox-mode distribution
  - attachment normalization counts by terminal status and duration
  - outbound delivery logical-send counts, attempt counts, failures, retry counts, and chunk counts
- Metrics label cardinality must be bounded. High-cardinality identifiers such as `session_id`, `message_id`, `run_id`, `request_id`, or external provider IDs must not be used as metric labels.
- Status, component, channel kind, sandbox mode, trigger kind, and failure category are acceptable metric dimensions if bounded by enum-like values.
- Metrics coverage is mandatory for capabilities listed as required now in the capability matrix and conditionally mandatory for capabilities that are enabled later.

### Tracing Contract
- The implementation must support one causal execution trace from gateway acceptance through worker completion for a run when tracing is enabled.
- Minimum spans or equivalent timing segments are:
  - inbound validation and dedupe handling
  - session resolution and transcript persistence
  - run creation or duplicate run lookup
  - worker claim and lease acquisition
  - attachment normalization
  - context assembly
  - model/runtime execution
  - tool execution, with separate span for remote node execution when used
  - outbound dispatch and adapter send attempts
  - post-turn continuity or repair enqueue decisions
- Trace propagation across internal HTTP boundaries, including the node runner, must preserve the parent run `trace_id` or trace context.
- If full distributed tracing is unavailable in a local or scaffold environment, the implementation must still emit timing-compatible structured events with the same correlation fields.
- The tracing abstraction should align with the same OpenTelemetry-compatible instrumentation used for metrics where practical so local and deployed environments do not diverge in correlation semantics.

### Local Observability Mode Contract
- Local development must support a lightweight observability mode that does not require external metrics or tracing backends.
- Minimum local mode behavior is:
  - structured JSON logs with the same required correlation fields
  - working `GET /health/live` and `GET /health/ready` responses
  - a no-op or console exporter for tracing and metrics when no backend is configured
  - optional metrics endpoint exposure when enabled by configuration
- Local mode must use the same application configuration patterns as other runtime features, including `.env`-driven settings compatible with `python-dotenv`.

### Diagnostics API Contract
- This spec adds read-only operational diagnostics APIs. They are operator-facing surfaces and must not mutate state.
- Diagnostics APIs in this slice must use one shared bounded response contract rather than endpoint-specific ad hoc pagination:
  - list endpoints return a typed envelope containing `items`, `limit`, `next_cursor` nullable, and `has_more`
  - the implementation must use deterministic cursor-based pagination rather than offset-only pagination for operator-facing listings
  - every list endpoint must define one stable default ordering and one stable maximum page size in code and tests
  - endpoint-specific item schemas remain typed, but the paging contract is shared
- Required diagnostics surfaces are:
  - `GET /health/live`
    - process liveness only; should not fail because an external dependency is briefly unavailable
  - `GET /health/ready`
    - readiness for serving new gateway traffic and/or worker claims
    - must report dependency summary for PostgreSQL and any configured Redis, object storage, node-runner connectivity, or other critical dependency used by the current deployment
  - `GET /diagnostics/runs`
    - bounded filtered listing over `execution_runs`
    - supports filters for `status`, `trigger_kind`, `session_id`, `agent_id`, `stale_only`, and recent time window
  - `GET /diagnostics/runs/{run_id}`
    - returns run metadata, bounded recent failure or degraded details, lane/lease state, and correlated artifact identifiers
  - `GET /diagnostics/sessions/{session_id}/continuity`
    - returns bounded continuity health summary using existing `summary_snapshots`, `context_manifests`, `outbox_jobs`, and recent run outcomes
  - `GET /diagnostics/outbox-jobs`
    - bounded filtered listing over pending, running, stale, and failed `outbox_jobs`
  - `GET /diagnostics/node-executions`
    - bounded filtered listing over `node_execution_audits`
  - `GET /diagnostics/deliveries`
    - bounded filtered listing over `outbound_deliveries` and recent attempts
  - `GET /diagnostics/attachments`
    - bounded filtered listing over `message_attachments` by normalization state and recency
- Diagnostics endpoints may join or summarize existing canonical tables, but they must not require operators to issue raw SQL to understand system state.
- Diagnostics responses must support bounded pagination, deterministic ordering, and sanitized error summaries.
- Required diagnostics routes remain stable across deployments even when an optional capability is disabled.
  - when the backing capability is enabled, the endpoint returns its normal typed payload
  - when the backing capability is disabled or not configured, the endpoint must still return a typed payload with explicit `capability_status` such as `enabled`, `not_enabled`, or `not_configured`
  - disabled capability endpoints must not disappear from routing, degrade into ambiguous empty success payloads, or return synthetic healthy summaries
- Access to diagnostics and health surfaces must be split by caller type rather than treated as one undifferentiated admin surface:
  - `GET /health/live` may be exposed for cheap process supervision according to deployment policy
  - `GET /health/ready` must be treated as an internal deployment-automation surface by default unless a deployment deliberately overrides that policy
  - `/diagnostics/*` endpoints must require explicit admin authorization for human operators or explicit internal service authorization for machine callers
  - deployments may enforce this split through separate routers, separate listener exposure, or equivalent policy controls, but deny-by-default behavior is mandatory
- The implementation must define one concrete authorization mechanism for diagnostics before these endpoints are considered complete, such as internal service tokens for machine callers and admin bearer credentials for human operators. A placeholder unauthenticated diagnostics surface is not acceptable.
- Default exposure policy in this slice is:
  - `GET /health/live` may remain unauthenticated when a deployment needs public liveness for local development or container supervision
  - `GET /health/ready` is internal-only by default
  - `/diagnostics/*` is always explicitly authenticated and denied by default

### Stale-Work and Degraded-State Contract
- The system must expose stale-work detection using explicit, durable rules rather than operator guesswork.
- Minimum stale-state rules in this slice are:
  - `execution_runs` in `claimed` or `running` beyond lease-expiry or configured stale threshold
  - `outbox_jobs` in `running` beyond configured worker heartbeat or age threshold
  - `scheduled_job_fires` stuck before terminal linkage or completion beyond configured age threshold
  - `outbound_deliveries` or `outbound_delivery_attempts` in non-terminal states beyond configured delivery timeout threshold
  - `node_execution_audits` in `received` or `running` beyond configured execution timeout plus grace period
  - attachments stuck without a terminal normalization state beyond configured worker retry expectations
- Degraded but still-serving states must be visible in diagnostics and telemetry:
  - transcript-first continuity fallback because summaries or retrieval aids are unavailable
  - node-runner unavailable causing retryable run failure
  - outbound adapter unavailable causing bounded delivery failure
  - dependency readiness partial failure where liveness remains healthy but readiness is false

### Repository and Service Contracts
- Telemetry helpers or middleware must be dependency-injected and testable rather than hidden global side effects.
- Repositories and services responsible for durable state transitions must emit telemetry at the same point the durable transition succeeds or fails, so operators can correlate logs with persisted truth.
- Diagnostics query services must read from canonical durable state or explicitly rebuildable additive views only.
- Readiness checks must be configuration-aware:
  - an optional dependency disabled for a deployment must not fail readiness
  - a dependency required by enabled capabilities must fail readiness when unavailable

## Runtime Invariants
- Operators can correlate one accepted run across gateway, worker, continuity, governance, node execution, and outbound delivery without direct database forensics.
- Observability must not redefine or bypass the canonical persistence contracts from Specs 001 through 007.
- Diagnostics surfaces are read-only in this slice.
- Liveness and readiness remain distinct; transient dependency failure may leave liveness healthy while readiness fails closed.
- High-cardinality identifiers remain available in logs and diagnostics, not in unbounded metric labels.
- Degraded continuity and retryable infrastructure failures remain visible; they are never silently swallowed.
- Telemetry emitted for asynchronous work preserves causal linkage to the original accepted run whenever such a run exists.

## Security Constraints
- Diagnostics endpoints require explicit internal or admin authorization and are denied by default on public surfaces.
- Health and diagnostics authorization must fail closed independently of business APIs; inability to determine caller trust must deny access rather than falling back to public readability.
- Logs, traces, metrics, and diagnostics must follow redaction rules and bounded-preview limits.
- Observability data may not be used as an alternate write path into queue, governance, node-runner, or delivery state.
- Readiness and diagnostics payloads must not leak environment secrets, approval payload secrets, provider credentials, or unrestricted transcript content.
- Failure details should be specific enough for operators while still failing closed on sensitive internals such as signature material or host-security policy contents.

## Operational Considerations
- Alert thresholds must be configurable and derived from the durable workflows already introduced by earlier specs rather than from process logs alone.
- Minimum alertable conditions in this slice are:
  - queue depth or queue age above threshold
  - stale `execution_runs` lease ownership
  - repeated run retries or dead-letter creation
  - continuity degraded-rate spike, compaction failure spike, or repair backlog growth
  - pending approval age above threshold
  - node-runner rejection or timeout spike
  - attachment normalization failure spike
  - outbound delivery failure spike or unsent backlog growth
  - readiness failing for a critical dependency
- Diagnostics queries must remain bounded and index-aware so observability does not become a new production hot path.
- Production defaults should prefer low-noise structured telemetry with explicit sampling or rate-limiting for repetitive success events where appropriate, while always preserving unsampled error visibility.
- The implementation should support local development with observability enabled in lightweight form even when full tracing backends or metrics exporters are absent.

## Acceptance Criteria
- Phase A through Phase D deliverables are implemented in dependency order, and each later phase reuses the identifiers and service boundaries established by earlier phases.
- A single accepted inbound turn can be followed through logs and diagnostics from gateway acceptance to run completion using one stable `trace_id`.
- Legacy runs reused after Spec 008 adoption are backfilled or lazily repaired so correlation never forks or disappears during modern execution.
- Operators can inspect queued, running, retrying, failed, dead-letter, or stale runs through read-only diagnostics endpoints without issuing raw database queries.
- Operators can inspect continuity health for a session, including latest summary coverage, recent degraded manifests, and outstanding repair-oriented `outbox_jobs`.
- Operators can inspect node execution attempts, attachment normalization outcomes, and outbound delivery attempts through bounded diagnostics surfaces.
- Readiness fails closed when a dependency required by enabled capabilities is unavailable, while liveness remains suitable for container/process supervision.
- Diagnostics list endpoints share one typed cursor-based paging contract with deterministic ordering and bounded defaults.
- Health and diagnostics exposure defaults are fail-closed: public liveness may be allowed, readiness is internal by default, and diagnostics always require explicit authorization.
- Logs, traces, metrics, and diagnostics do not expose secrets or unrestricted payload content.
- Metrics and alerts cover the queue, continuity, governance, remote execution, media normalization, and outbound delivery behaviors introduced by Specs 001 through 007.
- Capability-specific diagnostics, metrics, and readiness checks are present for implemented or enabled capabilities and are explicitly omitted or marked `not_enabled` or `not_configured` for disabled capabilities according to the stable endpoint contracts in this spec.
- Local development can run with lightweight observability enabled through `.env` configuration without requiring a dedicated tracing backend.
- Stale-work detection surfaces runs, jobs, node executions, or deliveries that have exceeded configured thresholds.

## Test Expectations
- Unit tests for telemetry field population, failure-category mapping, and redaction behavior
- Unit tests for readiness evaluation with different enabled or disabled dependency combinations
- Unit tests for diagnostics and health authorization behavior for internal and admin callers
- API tests for diagnostics access control, bounded pagination, filtering, and sanitized payloads
- Integration tests proving one `trace_id` propagates across gateway acceptance, worker execution, node execution, and outbound delivery telemetry
- Integration tests for phased observability rollout defaults, including local-mode exporters or no-op backends
- Integration tests for stale-work detection on runs, `outbox_jobs`, node executions, and deliveries
- Integration tests proving degraded continuity paths emit visible telemetry and appear in diagnostics without mutating canonical transcript state
