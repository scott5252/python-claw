# Features Plan

This document proposes the next implementation specs needed to move `python-claw` from the current Specs 001 through 008 foundation into a complete, working assistant platform. The order below is based on the code that already exists today:

- gateway-first inbound handling and routing
- durable sessions, messages, runs, artifacts, approvals, and diagnostics
- worker-owned execution and outbound dispatch
- rule-based model behavior in `src/providers/models.py`
- thin channel boundaries, attachment normalization, and remote execution contracts

The sequence is intentionally dependency-aware. Each spec is designed to integrate with the current services, database model, worker flow, and policy boundaries so the application stays runnable after every phase and ends in a coherent product rather than a disconnected set of features.

## Spec 009: Provider-Backed LLM Runtime

### What this spec should accomplish

Replace the current rule-based `ModelAdapter` with a provider-backed LLM path while preserving the existing graph and worker architecture. This spec should make natural-language conversation possible without bypassing the current persistence, approval, tool, and auditing boundaries.

### Detailed scope

- Extend `src/providers/models.py` with one or more real provider adapters that still return the existing `ModelTurnResult` and `ToolRequest` contracts.
- Add model-provider settings in `src/config/settings.py` for API keys, model names, timeouts, retry policy, and provider selection.
- Update prompt construction in `src/graphs/prompts.py` so the model receives durable transcript context, tool visibility, approval rules, and response formatting instructions.
- Keep deterministic policy enforcement in `src/policies/service.py`; the LLM may decide, but backend code still validates and enforces.
- Ensure `src/graphs/nodes.py` continues to own tool execution, approval creation, audit records, assistant message persistence, and context manifest persistence.
- Add failure handling for provider timeout, malformed tool-call output, provider unavailability, and partial degradation so worker retries and diagnostics remain accurate.
- Add tests for plain-answer turns, tool-using turns, approval-required turns, and model failure scenarios.

### Why it comes first

The largest missing product gap is that the current assistant is still driven by prefix rules. Real LLM integration is the foundation that makes the rest of the roadmap useful to end users.

## Spec 010: Typed Tool Schemas And Hybrid Intent Control

### What this spec should accomplish

Make tool usage reliable for LLM-driven turns by replacing loose argument handling with explicit schemas, while preserving deterministic handling for high-risk control commands like approvals and revocations.

### Detailed scope

- Introduce explicit Pydantic request models for the tools in `src/tools/local_safe.py`, `src/tools/messaging.py`, and `src/tools/remote_exec.py`.
- Extend `src/tools/registry.py` so tool definitions expose stable input schemas, descriptions, and validation behavior that can be passed to provider adapters.
- Keep deterministic parsing in `src/policies/service.py` for administrative commands such as `approve` and `revoke`.
- Use the LLM primarily for normal natural-language interpretation, but require backend validation before any tool executes.
- Standardize canonical argument serialization so approval matching, proposal hashing, and audit payloads remain stable.
- Improve error reporting so invalid tool arguments become user-visible assistant guidance instead of generic failures.
- Add tests for schema validation, approval matching, malformed LLM tool calls, and backward compatibility with current runtime behavior.

### Why it comes second

The current tool layer works for deterministic flows, but an LLM-backed assistant needs strict schemas before messaging and remote execution become dependable.

## Spec 011: Retrieval, Memory, And Attachment Understanding

### What this spec should accomplish

Turn the current continuity scaffolding into a real context system that can summarize long conversations, retrieve durable memory, and extract usable content from supported attachments.

### Detailed scope

- Extend `src/context/service.py` so context assembly can incorporate retrieved memory records in addition to transcript slices and summary snapshots.
- Add durable memory storage and retrieval components that integrate with existing session and message identity instead of replacing transcript truth.
- Build after-turn extraction jobs from the worker/outbox path so important facts and summaries are persisted without blocking the main request flow.
- Add attachment-content extraction for initial supported types such as text files, PDFs, and images, attaching derived metadata to normalized media records.
- Record which summaries, retrieval items, and attachment-derived content were used in `context_manifests` for inspectability.
- Ensure degradation paths still work when extraction or retrieval is unavailable.
- Add tests for context overflow, retrieval injection, summary rollover, and attachment-content availability in prompts.

### Why it comes third

Once the app can converse naturally, the next limit is context quality. This spec makes long-running sessions and uploaded content genuinely useful without changing the core gateway-worker model.

## Spec 012: Production Channel Integrations

### What this spec should accomplish

Replace the current thin/local channel behavior with real transport integrations so the application can function as an actual multi-channel assistant.

### Detailed scope

- Implement real provider adapters for the supported channels behind the existing dispatch boundary and adapter contracts.
- Add inbound webhook or polling flows that map cleanly into `POST /inbound/message` semantics instead of bypassing the gateway.
- Expand outbound delivery handling in `src/channels/dispatch.py` to cover provider identifiers, retryable failure mapping, rate limiting, and receipt updates.
- Preserve idempotency and dedupe guarantees already provided by `src/gateway/idempotency.py` and session routing.
- Support channel-specific capabilities incrementally, starting with text and basic reply threading before richer media features.
- Add end-to-end tests for inbound acceptance, outbound delivery, retry behavior, and provider error handling.

### Why it comes fourth

The app becomes truly usable once real users can talk to it over real transports. This spec depends on the assistant being able to understand natural language first.

## Spec 013: Streaming And Real-Time Delivery

### What this spec should accomplish

Add streaming or near-real-time response delivery so user-facing channels can show assistant progress before a full turn completes.

### Detailed scope

- Extend the model/runtime path to support incremental token or chunk emission without breaking durable final transcript writes.
- Add streaming-safe delivery contracts at the channel adapter layer, with clear handling for partial output, finalization, interruption, and retries.
- Define how partial assistant output is represented in delivery records versus persisted transcript messages.
- Preserve the worker-owned run lifecycle so streaming does not bypass execution runs, audit records, or diagnostics.
- Ensure non-streaming channels still work through the existing post-turn dispatch path.
- Add tests for partial delivery, stream completion, cancellation, and failure recovery.

### Why it comes fifth

Streaming improves user experience, but it should be built after real LLMs and real channels exist so the interface and failure model are grounded in actual runtime behavior.

## Spec 014: Agent Profiles And Delegation Foundation

### What this spec should accomplish

Create the durable agent model needed for specialist assistants and future sub-agent work, without yet implementing full delegation orchestration.

### Detailed scope

- Add durable agent profile records or an equivalent registry so the system no longer depends only on `default_agent_id`.
- Introduce model-profile and policy-profile linkage so different agents can use different LLMs, tool sets, and sandbox profiles.
- Extend session ownership data so a session clearly identifies which agent owns it and whether it is primary, child, or system-scoped.
- Update run creation, context assembly, and graph invocation so they consistently use the owning agent profile.
- Add diagnostics and admin read surfaces for agent profiles and agent-to-session relationships.
- Add migrations and tests covering agent lookup, disabled agents, model selection, and policy scoping.

### Why it comes sixth

Sub-agents are not safe to add until agent identity, model selection, and policy ownership are first-class concepts in the database and runtime.

## Spec 015: Sub-Agent Delegation And Child Session Orchestration

### What this spec should accomplish

Add bounded, auditable specialist delegation so the primary assistant can create and manage child-agent work inside the existing session/run architecture.

### Detailed scope

- Add first-class delegation records linking parent session, parent run, parent message, child session, and child agent.
- Implement a typed delegation capability in the tool layer rather than hidden prompt-only delegation.
- Create child-session and child-run creation flows that reuse `src/sessions/service.py`, `src/jobs/service.py`, and existing worker infrastructure.
- Define bounded context-sharing rules from parent to child and explicit result-return behavior from child to parent.
- Enforce delegation depth, allowed child agents, and tool restrictions through policy controls.
- Add diagnostics for delegation lineage, timing, status, and failure causes.
- Add tests for successful delegation, child failure, cancellation, retry, and audit visibility.

### Why it comes seventh

This is a higher-complexity orchestration feature that depends on a stable LLM layer, validated tools, and first-class agent identity.

## Spec 016: Human Handoff, Collaboration, And Approval UX

### What this spec should accomplish

Add the operator workflows needed for real support or operations use cases, including human takeover, session collaboration, and better approval handling from channel surfaces.

### Detailed scope

- Add session states and routing controls for assistant-active, human-takeover, paused, and reassignment flows.
- Expand governance and outbound UX so approval-required actions can be explained and, where supported, approved from user-facing channels.
- Add operator notes, assignment metadata, and audit-safe collaboration records.
- Ensure worker execution respects takeover state and does not continue automatic replies when a session is in human control.
- Extend diagnostics/admin APIs for queue ownership, assignment state, and collaboration history.
- Add tests for handoff transitions, approval UX, and conflict prevention between humans and automated runs.

### Why it comes eighth

Once the assistant can act across real channels and delegate internally, human collaboration becomes the next necessary product control layer.

## Spec 017: Production Hardening And Enterprise Readiness

### What this spec should accomplish

Finish the platform with the operational safeguards required for reliable production use.

### Detailed scope

- Strengthen auth around diagnostics, admin routes, node-runner communication, and channel/provider credentials.
- Expand observability with production metrics, tracing, alertable failure signals, and retention-aware audit queries.
- Add rate limiting, quota controls, provider backoff strategies, and stale-run recovery refinements across gateway, worker, and dispatcher flows.
- Harden media retention, sandbox isolation, and remote execution controls for safer real-world deployment.
- Add disaster-recovery and migration guidance for database-backed state and background work continuity.
- Build integration and smoke-test suites that validate the full application path: inbound message, context assembly, LLM decision, tool execution, approval gating, outbound delivery, and diagnostics.

### Why it comes last

This spec closes the gap between “feature complete” and “production ready.” It should validate and reinforce all prior specs rather than forcing architectural rewrites late in the roadmap.

## Recommended Implementation Order

1. Spec 009: Provider-Backed LLM Runtime
2. Spec 010: Typed Tool Schemas And Hybrid Intent Control
3. Spec 011: Retrieval, Memory, And Attachment Understanding
4. Spec 012: Production Channel Integrations
5. Spec 013: Streaming And Real-Time Delivery
6. Spec 014: Agent Profiles And Delegation Foundation
7. Spec 015: Sub-Agent Delegation And Child Session Orchestration
8. Spec 016: Human Handoff, Collaboration, And Approval UX
9. Spec 017: Production Hardening And Enterprise Readiness

## End-State Goal

If implemented in this order, the application should finish with these properties:

- natural-language LLM-driven turns that still respect durable policy enforcement
- validated and auditable tool execution for messaging and remote execution
- durable long-term context through summaries, retrieval, and attachment understanding
- real inbound and outbound chat integrations
- responsive streaming user experience where channels support it
- specialist agent delegation built on explicit agent ownership and child sessions
- human collaboration controls for operational use cases
- production-grade observability, security, and reliability

That end state fits the current codebase instead of replacing it: the gateway remains the front door, the worker remains the executor, the database remains the durable source of truth, and policy plus approvals remain the enforcement layer.
