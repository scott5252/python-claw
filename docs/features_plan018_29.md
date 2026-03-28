Missing Features for a Complete OpenClaw Replacement
After reviewing all 14 implemented specs, the 3 pending specs, and docs/features_plan.md, docs/future_features/future_features.md, and docs/supporting_docs/openclaw_spec_kit_program.md, the following capabilities are absent from the entire spec roadmap (001–017) and would prevent this from being a production-ready OpenClaw replacement:

Spec 018: Authentication, Authorization, and Role-Based Access Control
What is missing:
The platform has no identity layer for the humans who operate it. Spec 017 mentions "strengthen auth around diagnostics and admin routes" — that means hardening tokens that already exist, not building a proper auth system. There is no concept of an operator account, admin account, JWT issuance, OAuth integration, or role hierarchy. Any team deploying this in production would have no way to grant an engineer read-only access to diagnostics while giving a team lead approval authority.

Detailed scope:

Operator and admin account model: identity records, credential storage, password hashing, account states (active, suspended, pending)
JWT issuance and validation for gateway, diagnostics, admin, and node-runner APIs
OAuth/SSO integration surface for enterprise identity providers (OIDC-compatible)
API key management: generate, rotate, revoke API keys for programmatic integrations
Role definitions: viewer (read diagnostics), operator (manage sessions, process approvals), admin (configure agents, manage channels), super-admin (full platform control)
Permission boundary enforcement on all existing diagnostic, admin, and approval endpoints
Session-level access controls so an operator can only act on sessions they are assigned to or own
Approval authority scoping: only operators with specific roles can approve capability requests
Audit trail for authentication events: logins, key issuance, permission changes, failed auth attempts
Tests for unauthorized access, role boundary enforcement, expired tokens, and revoked keys
Why it comes here:
Nothing in specs 015–017 adds this. Without operator identity, any hardened auth in spec 017 is still shared-secret or bearer-token-only, which is not viable for multi-team production deployments.

Spec 019: Multi-Tenancy and Workspace Isolation
What is missing:
The platform is designed as a single-organization deployment. Every session, agent, channel, and policy configuration lives in one shared namespace. There is no concept of a tenant or workspace. Deploying this for multiple clients or business units on shared infrastructure would require separate deployments — a major operational burden and a commercial product blocker.

Detailed scope:

Tenant model: durable tenant records with display name, status, configuration, and lifecycle
Tenant-scoped data partitioning: sessions, messages, runs, approvals, agents, channels, and deliveries all belong to a tenant
Tenant-specific agent and channel configuration: each tenant configures its own agent profiles, model profiles, channel credentials, and policy profiles
Tenant resolution from inbound requests: channel adapter requests, API keys, and JWT claims must resolve to a tenant context before routing
Tenant-aware diagnostics and admin APIs: operators only see data for their authorized tenants
Tenant quota enforcement: per-tenant limits on active sessions, runs per hour, LLM token budgets, and storage
Tenant isolation for the node runner: sandbox profiles and execution allowlists are tenant-scoped
Tenant onboarding and offboarding flows: create, provision, suspend, and delete tenant workspaces
Cross-tenant isolation tests: prove one tenant cannot read or modify another tenant's data
Migrations that preserve existing single-tenant data under a bootstrapped default tenant
Why it comes here:
The future_features.md section 6.3 explicitly identifies this gap. Without it, the platform cannot be deployed as a SaaS product or shared infrastructure. Every real OpenClaw replacement in a commercial context is multi-tenant by default.

Spec 020: Contact and End-User Profile Management
What is missing:
The platform tracks conversations through sessions, but it has no persistent model of the humans having those conversations. Sessions are keyed by channel/peer identifiers but there is no contact record that unifies a person's identity across channels, accumulates metadata about them, or tracks their history over time. A customer service assistant platform without a contact layer is missing one of its most fundamental features.

Detailed scope:

Contact model: durable contact records with canonical identity, display name, channel identifiers, metadata, tags, and status
Cross-channel identity resolution: link a Slack user, Telegram user, and webchat user to the same contact record when identifiable
Contact-to-session linkage: sessions reference the contact they belong to, enabling cross-session history
User-level metadata and preferences: store structured contact attributes (language preference, timezone, opt-in/opt-out states, custom fields)
Contact enrichment from inbound messages: extract and persist contact-identifying signals from channel headers and message metadata
Contact history API: retrieve all sessions, messages, and events associated with a contact
Contact search and listing for operators: find contacts by identifier, name, tag, or channel account
Contact merge: when two contact records are discovered to be the same person, merge their session history
Privacy controls on contacts: soft delete, hard delete, anonymize for compliance with spec 027
Diagnostics surfaces for contact-session relationships and contact lifetime
Why it comes here:
Without contact records, the platform cannot answer "what has this customer asked before?" or "which agent is responsible for this user?" — questions that are central to any support or operations use case.

Spec 021: Richer Outbound Content and Interactive Messages
What is missing:
Specs 007 and 012 add production channel integrations with text delivery and reply threading. But real Slack and Telegram integrations need native interactive content: Slack Block Kit messages with buttons and selects, Telegram inline keyboards, action menus, approval cards with accept/reject controls. Without these, the platform produces plain text in channels that support rich interactive layouts, making it feel significantly inferior to native integrations.

Detailed scope:

Structured outbound content model: define a channel-agnostic rich content contract (cards, buttons, selects, confirmation dialogs) that maps to provider-native formats
Slack Block Kit adapter: translate rich content directives into Slack Block Kit JSON for outbound delivery; parse block action payloads from Slack webhook callbacks into inbound message events
Telegram inline keyboard and reply keyboard adapter: translate rich content into Telegram InlineKeyboardMarkup; parse callback_query payloads as inbound events
Webchat rich content: translate structured content into webchat-renderable JSON for the frontend
Approval UX integration: approval-required actions in spec 003 can produce rich approval cards in supported channels, with approve/reject buttons that drive inbound callback events
Action routing: button clicks, menu selections, and callback events from channel providers route back through the gateway as typed inbound events linked to the originating message and run
Reply thread management: send rich content as replies within existing threads on Slack/Telegram
Failure and fallback: degrade gracefully to text when a channel does not support the requested rich content type
Tests for block/keyboard serialization, callback routing, approval card rendering, and fallback behavior
Why it comes here:
Interactive messages are the UX layer that makes channel integrations feel native rather than limited. Without them, the approval workflow (spec 003) and human handoff (spec 016) cannot be driven from channel surfaces — operators must always fall back to raw text commands.

Spec 022: Proactive Messaging, Event Triggers, and Campaign Orchestration
What is missing:
Spec 005 adds a durable scheduler that fires system-level jobs back through the gateway. That is infrastructure. What is missing is the product-level proactive messaging layer: operators and the assistant itself should be able to schedule messages to users, set up reminder sequences, trigger outbound messages based on events (a run completing, a user going silent for N hours, an external webhook arriving), and broadcast to a set of contacts. This is a core capability for assistant platforms used in operations or support contexts.

Detailed scope:

Operator-authored message schedules: an API for operators to schedule one-time or recurring outbound messages to a session or contact
Reminder and follow-up sequences: define multi-step sequences with conditional branching based on whether a user replied
Event-triggered proactive messages: configure rules that fire an outbound message when a platform event occurs (e.g., approval granted, delegation completed, no user activity for N hours)
Audience targeting for broadcasts: send a message to all sessions matching a filter (channel, agent, tag, contact attribute)
Campaign lifecycle: draft, preview, schedule, send, pause, cancel, and archive campaigns
Rate limiting and pacing for broadcasts: avoid overwhelming a channel's send rate limits
Delivery tracking for campaign messages: tie campaign-originated deliveries back to the campaign record
Opt-out and suppression: respect contact-level opt-out states when delivering campaign messages
Diagnostics for campaign delivery status, bounce rates, and send timing
Integration with the existing scheduler infrastructure (spec 005) and outbound dispatcher (spec 007/012)
Why it comes here:
Without proactive messaging, the platform is purely reactive — it only responds to inbound messages. Any real support or operations platform needs to reach out to users, remind them of pending items, and broadcast important updates.

Spec 023: Outbound Webhooks and External Event Subscription API
What is missing:
The platform has no way to notify external systems when things happen. There is no webhook delivery layer, no event subscription registry, and no way for a third-party CRM, ticketing system, or workflow engine to react to platform events in real time. This prevents the platform from being the central orchestration hub for enterprise workflows, which is one of the defining capabilities of an OpenClaw-class assistant platform.

Detailed scope:

Event catalog: define the set of subscribable platform events (session created, message received, run completed, approval required, approval granted, delegation completed, delivery failed, etc.)
Webhook endpoint registration: operators register HTTPS endpoints to receive specific event types, scoped to tenant and optionally to agent or channel
Outbound webhook delivery: when a subscribed event fires, deliver a signed JSON payload to the registered endpoint
HMAC signature on outbound payloads: receivers can verify payload authenticity
Retry with exponential backoff: retry failed webhook deliveries up to a configurable limit; record delivery attempts and outcomes
Dead-letter state: after max retries, mark the delivery as failed and surface it in diagnostics
Webhook activation and deactivation: operators can pause and resume subscriptions
Event subscription management API: CRUD for subscriptions, test delivery (send a sample event), delivery history
Inbound webhook normalization: extend existing channel adapter patterns so that generic third-party webhooks can be registered and routed through the gateway as inbound events (not just Slack/Telegram)
Tests for event fanout, delivery retry, HMAC verification, and dead-letter behavior
Why it comes here:
Enterprise integrations depend on event-driven notification. Without outbound webhooks, every downstream system must poll the platform's APIs, which is inefficient and creates tight coupling.

Spec 024: Usage Metering, Cost Attribution, and Quota Enforcement
What is missing:
Spec 017 mentions "quota controls" at the gateway rate-limiting level (requests per second, burst limits). That is traffic management, not usage metering. There is no tracking of LLM token consumption per session, per agent, or per tenant. There is no cost attribution to provider calls. There is no enforcement of budget limits. For any commercial deployment, billing and cost visibility are non-negotiable.

Detailed scope:

Token usage tracking: capture input and output token counts from every LLM provider call and persist them against the execution run, session, agent, and tenant
Provider cost attribution: map token usage to estimated cost using configurable per-model pricing rates; store cost estimates with each run
Usage aggregation: daily, weekly, and monthly rollup tables for usage and cost per tenant, per agent, and per model
Quota definitions: operators define maximum token budgets, run counts, or cost limits per time period, scoped to tenant or agent
Quota enforcement: before dispatching an LLM call, check whether the relevant quota would be exceeded; fail closed with a user-visible error if so
Quota alerts: emit warnings when usage reaches configurable thresholds (e.g., 80% of monthly budget)
Usage dashboards via diagnostic API: expose current usage, historical rollups, and remaining quota
Per-session delivery cost tracking: record per-delivery costs for channel providers that charge per message (e.g., SMS, WhatsApp)
Usage export: provide a usage report export endpoint for billing reconciliation
Tests for token capture accuracy, quota enforcement at limits, and cost aggregation correctness
Why it comes here:
Without metering, the platform has no visibility into how much it costs to run. This is a prerequisite for any commercial deployment, multi-tenant pricing, or abuse prevention.

Spec 025: Admin and Operator Management Console
What is missing:
Every operator interaction with the platform today requires direct API calls or database inspection. The diagnostic APIs from spec 008 are read-only and JSON-based. There is no web-based management interface for the humans who operate the platform. The future_features.md section 6.1 explicitly identifies this as a major operational gap.

Detailed scope:

Session management UI: search, filter, and inspect sessions; view transcript, run history, attachment list, and delivery records for a session; manually close or reassign a session
Approval queue UI: view pending approval requests across all sessions; approve or reject from the interface; see approval history and governance events
Run inspection UI: view execution run state, associated messages, tool calls, tool results, and diagnostics; cancel a stuck run
Agent configuration UI: view and edit agent profiles, model profiles, policy profiles, and tool profiles without database access
Channel configuration UI: manage channel credentials, inbound webhook registrations, and delivery settings per channel
Contact management UI: search contacts, view cross-session history, manage tags, and trigger compliance actions (from spec 027)
Campaign and proactive message UI: compose, schedule, preview, and monitor campaigns (from spec 022)
Usage and cost dashboard: visualize token usage, cost trends, and quota status (from spec 024)
System health and diagnostics dashboard: surfacing key observability signals, stuck run counts, delivery failure rates, and provider health
RBAC-aware rendering: UI surfaces respect the operator's role (viewer, operator, admin); unauthorized actions are hidden or disabled
Authentication integration with spec 018 auth system
Why it comes here:
The platform cannot realistically be adopted by non-developer operators without a management UI. Every serious OpenClaw-class deployment expects an operator console.

Spec 026: Feedback Collection and Response Quality Signals
What is missing:
There is no mechanism for users or operators to signal whether a response was good or bad. There is no thumbs-up/down at the message level, no CSAT collection, no escalation flagging, and no review queue for low-quality responses. Without quality signals, there is no feedback loop for improving the assistant, no way to measure whether it is actually helping users, and no way to detect regressions after a model change.

Detailed scope:

User-facing feedback primitives: thumbs-up/down at the assistant message level, delivered through channel-appropriate mechanisms (webchat UI buttons, Slack reactions, Telegram inline buttons)
CSAT collection: after a session closes or a task is completed, optionally solicit a satisfaction rating from the user
Operator annotation: operators can annotate any session or message with internal quality notes, severity tags, and follow-up flags
Low-quality response detection: configurable rules for flagging responses that received negative feedback or triggered escalation
Review queue: an operator-accessible queue of flagged sessions and messages requiring human review
Quality metrics API: aggregate feedback statistics per agent, per model, per time period — positive rate, negative rate, CSAT average, escalation rate
Feedback event in the transcript: persist user feedback actions as first-class transcript events so they are auditable and replayable
Feedback-to-run linkage: associate feedback with the specific execution run and model call that produced the response
Export and reporting: feedback data exportable for offline analysis or fine-tuning dataset construction
Tests for feedback submission through each channel type, review queue population, and metric aggregation accuracy
Why it comes here:
Quality measurement is the operational foundation for improving an AI assistant. Without it, operators have no objective signal about whether the system is performing well after changes to models, prompts, or policies.

Spec 027: Data Retention, Privacy, and Compliance
What is missing:
The platform has no configurable data retention policies, no right-to-erasure capability, no data portability export, and no PII-aware anonymization layer. Spec 008 introduced log redaction for structured logs, and spec 017 mentions "audit retention queries" — but those are narrow operational concerns. Complying with GDPR, CCPA, or sector-specific regulations requires a dedicated privacy control layer. Without it, the platform cannot be legally deployed in the EU or regulated industries.

Detailed scope:

Retention policy definitions: operators configure how long different data categories are retained (messages, attachments, execution runs, tool audit events, deliveries, context manifests) at the tenant level
Automated retention enforcement: background jobs that soft-delete or hard-delete records past their retention period according to configured policy
Right-to-erasure workflow: a formal erasure request process that identifies all data belonging to a contact, purges or anonymizes it across all tables (sessions, messages, attachments, memory rows, retrieval indexes, outbound deliveries, contact records), and produces a completion receipt
Data portability export: export all data belonging to a contact or session in a structured format (JSON or CSV) for portability requests
PII detection layer: scan inbound message content and attachment-extracted text for common PII patterns; flag, redact, or quarantine based on configured policy
Anonymization mode: replace identifying values with pseudonymous identifiers in transcript records for analysis purposes while preserving behavioral data
Compliance audit log: durable record of all erasure requests, export requests, retention enforcement actions, and PII detection events
Retention override for legal hold: mark specific sessions or contacts as under legal hold, exempting them from retention enforcement until the hold is lifted
Tests for erasure completeness, retention enforcement accuracy, PII detection coverage, and legal hold behavior
Why it comes here:
Data privacy is a legal prerequisite for deployment in many markets. This cannot be bolted on after the platform is in production — it requires schema-level hooks and enforcement across every data store.

Spec 028: Safety Evaluations and Adversarial Testing Framework
What is missing:
With a real LLM (spec 009), sub-agents (spec 015), and external channel integrations (spec 012), the attack surface for prompt injection, policy bypass, approval circumvention, and tool misuse grows substantially. The platform has unit tests for functional paths but no systematic adversarial test harness, no dataset-driven eval framework, and no automated regression suite for safety properties. The future_features.md section 5.3 explicitly identifies this as a critical gap for post-LLM deployment.

Detailed scope:

Adversarial test dataset: curated test cases covering prompt injection attempts, jailbreak patterns, approval circumvention attempts, tool misuse attempts, and malformed tool-call payloads
Policy bypass regression suite: tests that prove policy enforcement cannot be bypassed through LLM-generated tool calls, regardless of prompt content
Approval circumvention tests: tests that prove the system cannot be convinced to execute an approval-gated action without a valid matching approval record
Sub-agent isolation tests (post-spec 015): tests that prove a child agent cannot escalate its own privileges or inherit parent approvals it was not explicitly granted
Prompt injection detection layer: a configurable pre-processing step that classifies inbound messages for injection patterns before they are passed to the LLM; block or flag suspicious content
Eval harness: a framework for running a batch of test scenarios against the live system and scoring results, with configurable pass/fail thresholds per safety category
Regression CI integration: the safety eval suite runs in CI on every model configuration change or system prompt change
Red-team facilitation tooling: an API surface that allows authorized security testers to submit adversarial scenarios and inspect the system's full response path
Coverage reporting: track which safety categories are covered by tests and surface gaps
Tests for the test framework itself: prove the injection detection layer catches known patterns without blocking legitimate messages
Why it comes here:
The more capable the platform becomes, the easier it is to exploit if safety properties are not systematically verified. An eval framework is the difference between "we believe it's safe" and "we can prove it is."

Spec 029: Operator Replay, Repair, and State Recovery Tooling
What is missing:
The platform maintains durable records of everything — execution runs, outbox jobs, deliveries, context manifests, summary snapshots, delegation records. But when something goes wrong in production, an operator has no friendly tools to intervene. Spec 017 includes "stale-run recovery refinements" at the worker level (automated timeouts), but that is background cleanup, not operator-driven repair. The future_features.md section 6.2 explicitly calls this out as a gap.

Detailed scope:

Rerun a failed execution run: an operator API that clones a completed or failed run and re-queues it for execution, with the ability to override run parameters
Retry a failed outbound delivery: re-enqueue a failed delivery attempt for a specific message and channel, skipping already-completed attempts
Reprocess a failed outbox job: for failed summary generation, retrieval indexing, or memory extraction jobs, allow an operator to trigger reprocessing for a specific session or message range
Rebuild continuity for a session: reconstruct summary snapshots, context manifests, and retrieval indexes from the canonical transcript for a session that has corrupted or missing derived state
Replay transcript from a session: re-feed a session's transcript through the context assembly pipeline to verify or repair derived artifacts
Force-release a stuck session lane: break a stuck concurrency lane lock for a session where the owning run has already failed or been terminated
Drain and inspect a specific run: force a running or stuck execution run into a terminal state with an operator-provided reason, persisted in the run record
Operator audit for repair actions: all repair operations produce an audit entry identifying the operator, the target resource, the action, and the outcome
Safety guards on repair operations: destructive repairs require confirmation and are blocked for sessions currently under human handoff or active delegation
Tests for each repair path, idempotency of reprocessing operations, and audit record accuracy
Why it comes here:
Production systems break in unpredictable ways. Without operator-friendly repair tooling, every incident requires a developer with database access, which is slow, risky, and unscalable.

Summary Table
Spec	Feature Area	Severity
018	Authentication, Authorization, and RBAC	Critical — no safe multi-operator deployment without it
019	Multi-Tenancy and Workspace Isolation	Critical — single-org only without it
020	Contact and End-User Profile Management	High — no persistent user identity model
021	Richer Outbound Content and Interactive Messages	High — channels feel limited without native interactive elements
022	Proactive Messaging, Event Triggers, and Campaigns	High — platform is purely reactive without it
023	Outbound Webhooks and External Event Subscription API	High — no enterprise integration surface
024	Usage Metering, Cost Attribution, and Quota Enforcement	High — no cost visibility or abuse prevention
025	Admin and Operator Management Console	High — developer-only tooling without it
026	Feedback Collection and Response Quality Signals	Medium-High — no quality measurement loop
027	Data Retention, Privacy, and Compliance	Critical for regulated markets
028	Safety Evaluations and Adversarial Testing Framework	High — safety regressions undetectable without it
029	Operator Replay, Repair, and State Recovery Tooling	Medium-High — production incidents require database access without it
The most critical blockers — specs 018 (auth/RBAC), 019 (multi-tenancy), and 027 (data privacy/compliance) — would prevent production deployment entirely in most enterprise contexts. The remaining specs represent the gap between a capable developer tool and a complete product.