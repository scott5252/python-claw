# Review 008: Observability, Diagnostics, and Operational Hardening

## Purpose
Review Spec 008 against the updated `README.md`, the delivered capability path in Specs 001 through 007, and the rewritten plan so this slice hardens the existing platform instead of reintroducing old placeholder scope such as presence or auth failover.

## Review Status
- Spec clarified: `yes`
- Plan analyzed: `yes`
- Constitution check passed: `yes`
- Ready for implementation: `yes`

## Final Gap Closures Applied
### 1. `trace_id` migration and run-reuse semantics are now explicit
- The spec package now defines how legacy pre-008 rows are handled instead of leaving reuse behavior to implementation guesswork.
- It requires additive backfill where practical and lazy repair when a reused `execution_run` still has a null `trace_id`.
- This closes the biggest correlation ambiguity in a repository that already persists runs before full observability hardening is delivered.

### 2. Diagnostics now have one concrete paging and payload contract
- The spec package now requires a shared cursor-based diagnostics envelope with typed endpoint-specific items.
- It also requires deterministic ordering and stable defaults rather than letting each endpoint invent its own page shape.
- This closes an API-consistency gap that would otherwise leak complexity into tests, operator tooling, and future specs.

### 3. Health exposure defaults are now fail-closed and deployment-friendly
- The spec package now distinguishes public-or-local liveness from internal-only readiness as the default posture.
- Diagnostics remain explicitly authenticated and deny by default.
- This fits the current repository state, where health is currently open and diagnostics authorization does not yet exist, while still moving the slice toward a safe production default.

### 4. Disabled-capability diagnostics behavior is now stable
- The spec package now keeps diagnostics routes present even when optional capabilities are disabled.
- Instead of disappearing routes or ambiguous empty payloads, endpoints return explicit typed `capability_status` values such as `enabled`, `not_enabled`, or `not_configured`.
- This preserves a predictable operator contract across deployments with different feature flags or infrastructure.

## Resolved Findings
### 1. Resolved: The stale presence and auth-failover scope has been removed
- The previous `tasks.md` still described `auth_profiles`, provider failover, and presence behavior that no longer exist in the updated spec or plan.
- The current spec now keeps the slice strictly focused on observability, diagnostics, health or readiness, and operational hardening for the capabilities already delivered in Specs 001 through 007.
- This restores a bounded vertical slice and keeps implementation effort attached to real current architecture seams.

### 2. Resolved: Observability is now anchored to the existing durable workflows
- The updated spec correctly treats Specs 001 through 007 as the substrate for this work rather than inventing new business-state ownership.
- `execution_runs`, `outbox_jobs`, `outbound_deliveries`, `outbound_delivery_attempts`, `node_execution_audits`, and attachment records now form the durable basis for telemetry and diagnostics.
- That matches the README's description of the current system as a gateway-owned, worker-executed, transcript-first service with queueing, node execution, and channel delivery already in place.

### 3. Resolved: The end-to-end correlation contract is explicit enough to implement
- The updated spec now makes `execution_runs.trace_id` the canonical identifier for one accepted run in this slice.
- The plan preserves that identifier through gateway acceptance, worker execution, continuity, governance, node execution, media normalization, and outbound delivery.
- This is the key contract that makes later diagnostics, metrics, and tracing coherent instead of fragmented by component-local IDs.

### 4. Resolved: Health and diagnostics boundaries are concrete and fail-closed
- Earlier placeholder material did not define how health differed from diagnostics or how operators should be authorized.
- The updated spec now separates:
  - `GET /health/live`
  - `GET /health/ready`
  - `/diagnostics/*` operator surfaces
- It also requires explicit admin or internal authorization and deny-by-default behavior, which is necessary because the current repo only has open read surfaces and a basic `GET /health`.

### 5. Resolved: Capability-aware observability now matches current project maturity
- The README says the repository has seven delivered capability areas, but not every signal described in the spec is equally available in every deployment.
- The updated capability matrix handles this correctly by making observability mandatory now for implemented flows and conditional for disabled or later-enabled infrastructure.
- This prevents fake healthy signals for features that are stubbed, disabled, or not configured.

## Architecture Alignment
- The slice stays aligned with the gateway-first architecture described in [README.md](/README.md): gateway acceptance remains the front door, workers own queued execution, node-runner remains internal, and observability instruments those flows instead of redefining them.
- Transcript-first durability is preserved because diagnostics and telemetry are derived from canonical records and additive instrumentation rather than becoming a second mutable state system.
- The plan's module list fits the current repo structure, including existing gateway, worker, node-runner, queueing, media, execution, and `src/observability/` seams already present in the codebase.

## Constitution Check
- Gateway-first execution is preserved. Diagnostics are read-only and observability does not create a bypass around gateway-owned acceptance or worker-owned execution.
- Transcript-first durability is preserved. The spec extends durable operational records but does not replace transcript, queue, governance, or delivery ownership from earlier specs.
- Approval and privileged execution boundaries are preserved. Governance, node-runner, and diagnostics remain fail-closed, and observability cannot become an alternate write path.
- Bounded, inspectable operations are preserved. The updated spec requires pagination, deterministic ordering, redaction, bounded previews, and bounded metric-cardinality rules.

## Plan Analysis
- The migration order is now sensible: extend durable records first, introduce shared observability contracts second, wire correlation and structured logging third, then add health and diagnostics surfaces, and only then layer metrics and tracing on top.
- The implementation shape matches the actual repo better than the stale tasks did. The current code already has gateway health and admin routes, queueing records, node-runner execution, media normalization, and a starter observability module, so this slice can be implemented incrementally instead of as a speculative rewrite.
- The biggest risks are operational rather than architectural:
  - accidental secret leakage in logs or diagnostics
  - inconsistent `trace_id` propagation across async boundaries
  - unbounded diagnostics queries turning into production hot paths
  - partial observability rollout that reports healthy status for disabled capabilities
- The updated plan addresses those risks directly with redaction helpers, bounded query contracts, additive indexes, explicit authorization, and capability-aware readiness rules.

## Applied Decisions
- Decision: Canonical run correlation identity
  - Selection: `execution_runs.trace_id`
  - Impact: one accepted run can be followed across gateway, worker, runtime, node execution, media, and delivery without component-local root IDs
- Decision: Health surface split
  - Selection: separate `GET /health/live` and `GET /health/ready`
  - Impact: infrastructure supervision and readiness gating no longer rely on one overloaded endpoint
- Decision: Diagnostics authorization
  - Selection: explicit admin bearer token and internal service token with deny-by-default behavior
  - Impact: operator visibility can be exposed safely without turning diagnostics into an unauthenticated side channel
- Decision: Capability-aware dependency reporting
  - Selection: omit disabled capability signals or report `not_enabled` or `not_configured`
  - Impact: operators are not misled by synthetic healthy status for absent features
- Decision: Observability data source
  - Selection: canonical durable tables plus additive instrumentation only
  - Impact: logs, metrics, tracing, and diagnostics remain explainable from persisted truth

## Implementation Gate
- Implementation may begin. The current spec, plan, tasks, and review now align with the README, the earlier updated specs, and the existing codebase, and the rewritten tasks can be executed in a phased order without hidden scope or unresolved contract ambiguity.

## Sign-Off
- Reviewer: `Codex`
- Date: `2026-03-24`
- Decision: `approved`
- Summary: Spec 008 is now a coherent observability and hardening slice for the platform that actually exists in this repository. It replaces the outdated presence and auth-failover scope with concrete contracts for correlation, structured logging, health or readiness, diagnostics, metrics, tracing, stale-work visibility, fail-closed operator access, legacy correlation repair, stable diagnostics paging, and explicit disabled-capability behavior.
