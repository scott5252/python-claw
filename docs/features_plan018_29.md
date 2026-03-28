# Features Plan 018 Through 029

This document proposes the next implementation specs needed to move `python-claw` from the current roadmap in `docs/features_plan.md` into a production-ready OpenClaw replacement. These specs focus on the capabilities that are still absent after Specs 001 through 017:

- operator identity, authorization, and workspace isolation
- persistent contact management and richer channel-native interaction
- proactive messaging and external event integrations
- usage metering, management tooling, and response-quality feedback loops
- privacy, compliance, safety evaluation, and operator repair controls

The sequence below is intentionally dependency-aware. It preserves the existing gateway, worker, database, policy, and channel boundaries while filling the product and operational gaps that remain between a capable assistant runtime and a complete production platform.

## Spec 018: Authentication, Authorization, And Role-Based Access Control

### What this spec should accomplish

Add a real operator identity and authorization layer so the platform can support multiple human operators safely, with explicit account models, session-bound permissions, and role-based approval authority.

### Detailed scope

- Add operator and admin account models with identity records, credential storage, password hashing, and account states such as active, suspended, and pending.
- Add JWT issuance and validation for gateway, diagnostics, admin, and node-runner APIs.
- Add OAuth or SSO integration surfaces for OIDC-compatible enterprise identity providers.
- Add API key management for programmatic integrations, including key generation, rotation, and revocation.
- Define role tiers such as viewer, operator, admin, and super-admin.
- Enforce permission boundaries across existing diagnostics, admin, and approval endpoints.
- Add session-level access controls so operators can only act on sessions they own or are assigned to.
- Scope approval authority so only appropriately privileged operators can approve capability requests.
- Record authentication audit events such as logins, failed attempts, key issuance, and permission changes.
- Add tests for unauthorized access, role boundary enforcement, expired tokens, and revoked credentials.

### Why it comes first

Specs 015 through 017 improve platform capabilities and hardening, but they do not introduce real human identity. Without operator auth and RBAC, the platform cannot be deployed safely for multi-person operational use.

## Spec 019: Multi-Tenancy And Workspace Isolation

### What this spec should accomplish

Introduce tenant-aware isolation so the platform can support multiple customers or business units on shared infrastructure without mixing state, credentials, policies, or execution boundaries.

### Detailed scope

- Add a durable tenant model with display name, status, lifecycle state, and configuration.
- Partition sessions, messages, runs, approvals, agents, channels, deliveries, and related state by tenant.
- Add tenant-specific agent, model, channel, and policy configuration.
- Resolve tenant context from inbound requests using channel mappings, API keys, or JWT claims before routing.
- Make diagnostics and admin APIs tenant-aware so operators only see authorized workspaces.
- Add per-tenant quota enforcement for sessions, runs, tokens, storage, and related resource usage.
- Scope node-runner sandbox profiles and execution allowlists by tenant.
- Add tenant onboarding, suspension, offboarding, and deletion flows.
- Add cross-tenant isolation tests proving one tenant cannot read or modify another tenant's data.
- Add migrations that preserve existing single-tenant deployments under a bootstrapped default tenant.

### Why it comes second

Once operator identity exists, the next missing boundary is workspace isolation. Without this spec, the platform remains effectively single-organization and cannot serve as a shared commercial deployment.

## Spec 020: Contact And End-User Profile Management

### What this spec should accomplish

Add a durable contact layer so the platform can model the humans behind sessions, unify identity across channels, and provide cross-session history and metadata for support and operations workflows.

### Detailed scope

- Add durable contact records with canonical identity, display name, channel identifiers, metadata, tags, and status.
- Add cross-channel identity resolution so users on Slack, Telegram, and webchat can map to the same contact when appropriate.
- Link sessions to contacts so cross-session history is queryable.
- Store structured contact metadata such as timezone, language preference, opt-in state, and custom fields.
- Extract contact signals from inbound message metadata and persist them as enrichment data.
- Add contact history APIs for retrieving all sessions, messages, and events for a contact.
- Add operator-facing contact search and listing by name, identifier, tag, or channel account.
- Add contact merge workflows when duplicate records are discovered.
- Add privacy actions such as soft delete, hard delete, and anonymization, integrating with later compliance work.
- Add diagnostics surfaces for contact-to-session relationships and contact lifetime state.

### Why it comes third

After tenant and operator boundaries are in place, the next major product gap is the lack of an end-user identity model. Sessions alone are not enough for real customer-service or operations use cases.

## Spec 021: Richer Outbound Content And Interactive Messages

### What this spec should accomplish

Expand channel delivery from plain text into native interactive experiences so approvals, guided actions, and structured responses can be handled directly from supported channel surfaces.

### Detailed scope

- Define a channel-agnostic structured outbound content model for cards, buttons, selects, and confirmation dialogs.
- Add a Slack Block Kit adapter for outbound rich content and inbound block action callbacks.
- Add Telegram inline keyboard and reply keyboard support for outbound content and callback handling.
- Add webchat rich-content rendering contracts for the frontend.
- Integrate rich interactive approvals so approval-required actions can render approve and reject controls directly in supported channels.
- Route button clicks, callback payloads, and menu selections back through the gateway as typed inbound events linked to the originating message and run.
- Preserve reply-thread behavior for rich content on channels that support it.
- Add graceful fallback to plain text when a channel does not support the requested interaction type.
- Add tests for content serialization, callback routing, approval card behavior, and fallback handling.

### Why it comes fourth

Production channel integrations are much more useful when they feel native. This spec builds directly on Spec 012 and makes approval and operator workflows usable from actual channel surfaces instead of only through text commands.

## Spec 022: Proactive Messaging, Event Triggers, And Campaign Orchestration

### What this spec should accomplish

Add product-level proactive messaging so operators and system workflows can schedule, trigger, and broadcast outbound messages instead of remaining purely reactive to inbound conversation.

### Detailed scope

- Add APIs for one-time and recurring scheduled outbound messages to a session or contact.
- Add reminder and follow-up sequences with branching based on whether a user replied.
- Add event-triggered outbound messaging for platform events such as approval completion, delegation completion, or prolonged user inactivity.
- Add audience targeting for broadcast or campaign messaging based on channel, agent, tag, or contact attributes.
- Add campaign lifecycle states such as draft, preview, schedule, send, pause, cancel, and archive.
- Add rate limiting and pacing controls for large sends.
- Tie campaign-originated deliveries back to campaign records for diagnostics.
- Respect contact-level suppression and opt-out states during delivery.
- Add diagnostics for campaign status, send timing, bounce behavior, and delivery outcomes.
- Integrate with the existing scheduler and outbound dispatcher infrastructure.

### Why it comes fifth

The scheduler foundation already exists, but the platform still lacks proactive product behavior. This spec turns backend scheduling into a user-facing messaging capability.

## Spec 023: Outbound Webhooks And External Event Subscription API

### What this spec should accomplish

Add an event subscription and webhook delivery system so external products can react to platform activity in real time without polling the APIs.

### Detailed scope

- Define a catalog of subscribable platform events such as session created, message received, run completed, approval required, approval granted, delegation completed, and delivery failed.
- Add webhook endpoint registration scoped by tenant and optionally by agent or channel.
- Deliver signed JSON payloads to subscribed endpoints when matching events occur.
- Add HMAC signatures for receiver-side authenticity verification.
- Add retry with exponential backoff and durable delivery-attempt history.
- Add dead-letter handling after retry exhaustion and surface failures in diagnostics.
- Add activation and deactivation controls for subscriptions.
- Add CRUD and test-delivery APIs for event subscriptions.
- Extend inbound webhook normalization so generic third-party webhooks can also route through the gateway as inbound events where appropriate.
- Add tests for event fanout, HMAC verification, retries, and dead-letter behavior.

### Why it comes sixth

Once the platform can proactively message users, the next missing integration surface is proactive messaging to other systems. Webhooks are the standard boundary for enterprise workflow integration.

## Spec 024: Usage Metering, Cost Attribution, And Quota Enforcement

### What this spec should accomplish

Add accurate usage and cost accounting so the platform can measure LLM and channel spend, attribute consumption across tenants and agents, and enforce configurable budgets.

### Detailed scope

- Capture input and output token counts for every LLM provider call and persist them against runs, sessions, agents, and tenants.
- Map usage to estimated cost with configurable per-model pricing.
- Add daily, weekly, and monthly rollups for usage and spend by tenant, agent, and model.
- Add configurable quota definitions for token budgets, run counts, or spend limits.
- Enforce quotas before LLM execution and fail closed with user-visible errors when limits would be exceeded.
- Add quota warning thresholds such as 80 percent of monthly budget.
- Expose usage dashboards and remaining-budget views through diagnostic APIs.
- Track per-delivery costs for channels that charge by message.
- Add usage-export endpoints for reconciliation and billing workflows.
- Add tests for token capture accuracy, quota enforcement, and cost rollup correctness.

### Why it comes seventh

Multi-tenant and proactive systems need visibility into cost and consumption. Without metering and quotas, the platform cannot support commercial governance or reliable abuse prevention.

## Spec 025: Admin And Operator Management Console

### What this spec should accomplish

Add a web-based management console so operators can manage sessions, approvals, agents, channels, contacts, campaigns, and system health without relying on direct API calls or database inspection.

### Detailed scope

- Add a session management UI for searching, filtering, inspecting, closing, and reassigning sessions.
- Add an approval queue UI for reviewing and actioning pending approvals.
- Add run inspection views for execution state, tool calls, results, diagnostics, and stuck-run cancellation.
- Add configuration UIs for agents, model profiles, policy profiles, and tool profiles.
- Add channel configuration UIs for credentials, webhook registrations, and delivery settings.
- Add contact management UIs for search, history inspection, tags, and compliance actions.
- Add campaign composition, scheduling, preview, and monitoring UIs.
- Add usage and cost dashboards that visualize quota status and spend trends.
- Add system-health dashboards for observability signals, stuck-run counts, delivery failures, and provider health.
- Make the console RBAC-aware and integrate it with the auth system from Spec 018.

### Why it comes eighth

Once the platform has tenanting, contact data, campaigns, and quotas, operators need a first-class interface to use them. Otherwise the system remains effectively developer-only.

## Spec 026: Feedback Collection And Response Quality Signals

### What this spec should accomplish

Add structured quality feedback so users and operators can signal response quality, sessions can be flagged for review, and the platform can measure whether changes are improving outcomes.

### Detailed scope

- Add user-facing feedback primitives such as thumbs-up and thumbs-down at the assistant-message level.
- Add optional CSAT collection after session closure or task completion.
- Add operator annotations with quality notes, severity labels, and follow-up flags.
- Add rules for automatically flagging responses that received negative feedback or caused escalation.
- Add a review queue for flagged sessions and messages.
- Add quality metrics APIs that aggregate positive rate, negative rate, CSAT, and escalation rate by agent, model, and time period.
- Persist feedback actions as first-class transcript events for auditability.
- Link feedback to the run and model output that produced the relevant response.
- Add export surfaces for reporting, offline analysis, or dataset curation.
- Add tests for feedback submission, review queue population, and metrics aggregation.

### Why it comes ninth

Once there is an operator console, the next missing loop is quality measurement. Without explicit feedback signals, operators cannot tell whether model, prompt, or policy changes are helping.

## Spec 027: Data Retention, Privacy, And Compliance

### What this spec should accomplish

Add formal data-retention and privacy controls so the platform can satisfy deletion, export, retention, and PII-handling requirements needed for legal and regulated deployment.

### Detailed scope

- Add tenant-level retention policy definitions for messages, attachments, runs, audit events, deliveries, and context artifacts.
- Add automated enforcement jobs for soft-delete and hard-delete based on configured retention windows.
- Add right-to-erasure workflows that find and purge or anonymize all contact-linked data across the platform.
- Add data-portability export flows for contacts or sessions in structured formats.
- Add PII detection for inbound content and attachment-derived text, with policy-driven flagging, redaction, or quarantine behavior.
- Add anonymization modes that preserve behavioral data while replacing direct identifiers.
- Add compliance audit logs for erasure requests, export requests, retention actions, and PII detections.
- Add legal-hold controls that exempt selected sessions or contacts from retention enforcement.
- Add tests for erasure completeness, retention accuracy, PII detection coverage, and legal-hold handling.

### Why it comes tenth

By this point the platform holds operator data, tenant data, contact data, campaigns, and feedback. Privacy and compliance controls become a hard deployment requirement rather than an optional hardening pass.

## Spec 028: Safety Evaluations And Adversarial Testing Framework

### What this spec should accomplish

Add a systematic safety-evaluation harness so the platform can prove that policy enforcement, approval gating, and agent boundaries hold up against prompt injection, jailbreaks, and adversarial misuse.

### Detailed scope

- Build an adversarial test dataset covering prompt injection, jailbreak attempts, approval circumvention, tool misuse, and malformed tool-call payloads.
- Add regression suites that prove backend policy enforcement cannot be bypassed by prompt content.
- Add approval circumvention tests proving approval-gated actions cannot execute without valid matching approval records.
- Add sub-agent isolation tests ensuring child agents cannot escalate privileges or inherit approvals they were not given.
- Add a configurable prompt-injection detection layer ahead of the LLM path, with block-or-flag behavior for suspicious content.
- Add an eval harness that runs scenario batches and scores results against safety thresholds.
- Integrate safety evals into CI for model-configuration and system-prompt changes.
- Add red-team facilitation tooling so authorized testers can submit adversarial scenarios and inspect response paths.
- Add coverage reporting for evaluated safety categories.
- Add tests for the safety framework itself so detection logic catches known attacks without overblocking legitimate traffic.

### Why it comes eleventh

The more product surfaces and automation the platform gains, the more important it becomes to verify safety properties continuously rather than relying only on ordinary feature tests.

## Spec 029: Operator Replay, Repair, And State Recovery Tooling

### What this spec should accomplish

Add operator-friendly recovery tools so failed runs, deliveries, summaries, retrieval jobs, and lane state can be replayed or repaired without direct database intervention.

### Detailed scope

- Add an operator API to rerun failed or completed execution runs with optional parameter overrides.
- Add targeted retry flows for failed outbound deliveries without disturbing already successful attempts.
- Add reprocessing flows for failed summary generation, retrieval indexing, and memory extraction jobs.
- Add continuity rebuild operations that reconstruct summary snapshots, context manifests, and retrieval indexes from the canonical transcript.
- Add transcript replay flows that re-run context assembly against a session to verify or repair derived state.
- Add forced release of stuck session-lane locks when the owning run is no longer valid.
- Add drain and termination controls for running or stuck execution runs, with operator-supplied reasons persisted in run records.
- Add durable audit records for all repair actions, including operator identity, target resource, action, and outcome.
- Add safety guards so destructive repairs require confirmation and are blocked during incompatible states such as active human handoff or active delegation.
- Add tests for repair-path behavior, idempotency, and audit accuracy.

### Why it comes last

This spec closes the operational loop. Once the platform is feature-complete and safety-evaluated, operators still need trustworthy repair controls for the production incidents that inevitably happen.

## Recommended Implementation Order

1. Spec 018: Authentication, Authorization, And Role-Based Access Control
2. Spec 019: Multi-Tenancy And Workspace Isolation
3. Spec 020: Contact And End-User Profile Management
4. Spec 021: Richer Outbound Content And Interactive Messages
5. Spec 022: Proactive Messaging, Event Triggers, And Campaign Orchestration
6. Spec 023: Outbound Webhooks And External Event Subscription API
7. Spec 024: Usage Metering, Cost Attribution, And Quota Enforcement
8. Spec 025: Admin And Operator Management Console
9. Spec 026: Feedback Collection And Response Quality Signals
10. Spec 027: Data Retention, Privacy, And Compliance
11. Spec 028: Safety Evaluations And Adversarial Testing Framework
12. Spec 029: Operator Replay, Repair, And State Recovery Tooling

## Critical Deployment Gaps

The most serious blockers to a production-ready OpenClaw replacement are:

- Spec 018, because multi-operator deployment is not safe without real identity, auth, and RBAC.
- Spec 019, because the platform remains single-organization without tenant isolation.
- Spec 027, because privacy, retention, erasure, and compliance requirements block deployment in many enterprise and regulated environments.

## End-State Goal

If implemented in this order, the application should finish with these properties:

- secure multi-operator access with explicit identity, roles, and approval authority
- tenant-aware isolation for data, configuration, quotas, and execution boundaries
- durable contact records and cross-session user history
- rich native channel interactions instead of plain-text-only delivery
- proactive outbound messaging, campaigns, and external event integrations
- measurable usage, cost attribution, and quota enforcement
- a full operator console for day-to-day platform management
- durable quality signals for monitoring and improving assistant behavior
- privacy and compliance controls suitable for regulated deployment
- repeatable safety evaluation against adversarial misuse
- operator repair and replay tooling for production incident recovery

That end state extends the current architecture instead of replacing it: the gateway remains the front door, the worker remains the executor, the database remains the durable source of truth, and policy plus approvals remain the enforcement layer while the product surface becomes complete enough for real operational deployment.
