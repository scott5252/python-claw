# Future Features

This document describes the major future features that would make `python-claw` a more complete, production-ready assistant platform.

It is intentionally broader than the currently implemented Specs 001 through 008 and also broader than the separate design documents for:

- LLM integration
- sub-agents

The purpose of this document is to answer:

1. What important capabilities are still missing?
2. Why do they matter?
3. How do they relate to the current architecture?
4. What is the best build order?

## 1. Current Baseline

Today, the system already has a strong platform foundation:

- gateway-first inbound handling
- durable sessions and transcript persistence
- append-only runtime artifacts
- approval-gated capabilities
- async execution runs and worker ownership
- context continuity scaffolding
- attachment normalization
- outbound delivery auditing
- remote execution policy and node-runner contracts
- diagnostics, health, and operational visibility

That means the project is already more than a toy chatbot backend. It has many of the durable control-plane and audit features needed for a serious assistant platform.

The next stage is about adding richer product behavior and stronger production readiness.

## 2. Feature Categories

The future features fit into four major groups:

1. Product features
2. Platform and intelligence features
3. Safety and control features
4. Operations and enterprise features

## 3. Product Features

These are the features users would most directly notice.

## 3.0 Chat Interfaces

One common question is whether the future roadmap supports a real chat interface like Telegram.

The answer is yes.

The current architecture already has the right shape for chat interfaces because it includes:

- inbound message acceptance
- session routing
- outbound delivery
- channel adapter boundaries

That means the platform is already structured to support interfaces such as:

- Telegram
- Slack
- web chat
- future chat-style channels

What is missing today is not the overall architecture. What is missing is the production-grade implementation behind those channel boundaries.

The most important future features for a real Telegram-like or Slack-like experience are:

- real channel integrations
- true streaming or near-real-time updates
- richer outbound content
- attachment understanding
- optional human handoff

In practical terms:

- `telegram` support is conceptually part of the roadmap already
- but it becomes a true user-facing chat product only after the transport adapter grows from a thin local implementation into a real provider integration

## 3.1 Real LLM Integration

Current state:

- the model layer is rule-based
- normal user language is not interpreted by a live provider model

Why it matters:

- this is what makes the system feel like a real assistant instead of a deterministic command router
- it unlocks natural tool selection, better answers, and more flexible workflows

What it would enable:

- natural language understanding
- more human assistant responses
- dynamic tool use
- better summarization and explanation

Related file:

- [src/providers/models.py](/Users/scottcornell/src/my-projects/python-claw/src/providers/models.py)

## 3.2 Sub-Agents

Current state:

- not part of the committed feature set yet
- architecture is compatible

Why it matters:

- lets the main assistant delegate to specialist agents
- helps scale complex tasks
- enables different models and tool profiles per specialist

Examples:

- coding specialist
- research specialist
- docs specialist
- operations specialist

This is covered in more detail in:

- [sub_agents.md](/Users/scottcornell/src/my-projects/python-claw/sub_agents.md)

## 3.3 Real Channel Integrations

Current state:

- channel adapters are thin local implementations
- they do not yet behave like full provider clients

Why it matters:

- the system cannot be a real multi-channel assistant product without true transport integrations

Needed additions:

- real Slack API support
- real Telegram API support
- real webchat/websocket or browser delivery support
- auth and token handling
- retries and rate-limit behavior
- provider delivery receipts and error mapping

Relevant files:

- [src/channels/adapters/webchat.py](/Users/scottcornell/src/my-projects/python-claw/src/channels/adapters/webchat.py)
- [src/channels/adapters/slack.py](/Users/scottcornell/src/my-projects/python-claw/src/channels/adapters/slack.py)
- [src/channels/adapters/telegram.py](/Users/scottcornell/src/my-projects/python-claw/src/channels/adapters/telegram.py)

## 3.4 True Streaming

Current state:

- outbound delivery uses post-turn chunking
- token-by-token streaming is not implemented

Why it matters:

- users increasingly expect live responses in chat products
- streaming improves perceived speed and interactivity

Needed additions:

- streaming-aware assistant runtime
- streaming-safe transport APIs
- delivery contracts for partial output
- retry and interruption behavior
- transcript rules for partial versus final assistant output

This is especially useful for:

- web chat UIs
- long-form answers
- coding or analysis interfaces

## 3.5 Attachment Understanding

Current state:

- attachments can be accepted, normalized, stored, and referenced
- but the system does not yet understand their contents

Why it matters:

- real users often need the assistant to read PDFs, images, screenshots, and audio

Needed additions:

- OCR for images and PDFs
- audio transcription
- semantic extraction from documents
- indexing extracted content for retrieval
- prompts that explain which attachment content was used

Relevant current files:

- [src/media/processor.py](/Users/scottcornell/src/my-projects/python-claw/src/media/processor.py)
- [src/context/service.py](/Users/scottcornell/src/my-projects/python-claw/src/context/service.py)

## 3.6 Richer Outbound Content

Current state:

- text, reply directives, and bounded media references are supported
- rich blocks and advanced provider-native layout systems are not

Why it matters:

- real products often need buttons, cards, templates, and richer message layouts

Possible future additions:

- Slack block kit support
- Telegram richer media templates
- structured action buttons
- interactive approval UX from the channel itself

## 3.7 Human Handoff And Collaboration

Current state:

- the assistant is the only active participant in the main experience

Why it matters:

- support and operations use cases often need human escalation
- enterprise workflows often need shared ownership

Possible features:

- human takeover mode
- assignment to a human operator
- pause assistant replies
- add internal notes
- transfer sessions between queues or agents

## 4. Platform And Intelligence Features

These features make the system smarter and more capable internally.

## 4.1 Retrieval And Long-Term Memory

Current state:

- summary snapshots and continuity scaffolding exist
- full retrieval-backed memory is not yet implemented

Why it matters:

- long conversations need more than transcript replay
- retrieval improves relevance and context quality

Needed additions:

- embeddings
- vector or hybrid search
- document chunking and indexing
- memory extraction rules
- retrieval ranking and freshness rules

This would build naturally on:

- [src/context/service.py](/Users/scottcornell/src/my-projects/python-claw/src/context/service.py)
- `summary_snapshots`
- `outbox_jobs`
- `context_manifests`

## 4.2 Better Prompt And Context Assembly

Current state:

- context assembly is deterministic and solid
- but still intentionally narrow

Why it matters:

- once LLMs, retrieval, and attachments grow, prompt size and quality become critical

Needed additions:

- token-aware prompt budgeting
- selective context inclusion
- summarization layering
- better artifact prioritization
- context explanation and replay guarantees

## 4.3 Agent Routing

Current state:

- one default `agent_id`

Why it matters:

- future systems often need multiple agent personas or specialist roles even before full sub-agents

Possible future additions:

- route messages to different primary agents
- choose different default agents by channel or tenant
- channel-account-specific agent mapping

## 4.4 Tool Ecosystem Expansion

Current state:

- the tool set is intentionally small

Why it matters:

- the value of an assistant platform grows with useful safe capabilities

Potential future tools:

- structured search tools
- CRM or ticketing integrations
- calendar integrations
- knowledge-base search
- file and repo operations
- workflow automation tools

Important note:

- every new tool should still fit the same typed action, approval, and audit model

## 4.5 Workflow Automation

Current state:

- queueing and scheduling foundations exist
- product-facing automation is minimal

Why it matters:

- assistants become much more useful when they can do recurring or event-driven work

Future additions:

- user-authored schedules
- recurring reminders
- follow-up workflows
- trigger rules based on messages, runs, or external events

## 5. Safety And Control Features

These features reduce risk as the system becomes more powerful.

## 5.1 Stronger Sandbox Enforcement

Current state:

- remote execution policies and auditability are stronger than the actual sandbox backend

Why it matters:

- once remote execution is real, sandboxing becomes one of the most important safety boundaries

Needed additions:

- real container isolation
- explicit filesystem boundaries
- stronger environment isolation
- network policy control
- resource quotas
- sandbox lifecycle management

Relevant current files:

- [src/sandbox/service.py](/Users/scottcornell/src/my-projects/python-claw/src/sandbox/service.py)
- [apps/node_runner/policy.py](/Users/scottcornell/src/my-projects/python-claw/apps/node_runner/policy.py)
- [apps/node_runner/executor.py](/Users/scottcornell/src/my-projects/python-claw/apps/node_runner/executor.py)

## 5.2 Richer Approval Models

Current state:

- approvals are exact-match and intentionally narrow

Why it matters:

- this is safe, but sometimes too rigid for real product workflows

Future possibilities:

- time-bounded reusable approvals
- approval families for low-risk repeated actions
- human approval inbox UI
- approval explanations and risk scoring

Important caution:

- this should only be expanded carefully, because the current exact-match model is one of the system’s strongest safety properties

## 5.3 Safety Evaluations And Policy Testing

Current state:

- there are tests for many functional paths
- there is not yet a mature LLM safety/evals layer because the system does not yet use a real LLM

Why it matters:

- once LLMs and sub-agents are introduced, safety regressions become much easier

Needed additions:

- prompt-injection tests
- policy bypass tests
- approval circumvention tests
- tool misuse regression tests
- remote execution misuse tests
- dataset-driven evals

## 5.4 Secret And Data Governance

Current state:

- redaction and bounded logging exist

Why it matters:

- future integrations will introduce more sensitive data and credentials

Possible additions:

- tenant-specific key management
- stronger secret storage strategy
- data retention controls
- data deletion workflows
- audit export and compliance reporting

## 6. Operations And Enterprise Features

These features help teams actually run the system at scale.

## 6.1 Admin UI / Operator Console

Current state:

- diagnostics exist as APIs only

Why it matters:

- many operators are more effective with visual tooling than raw API calls

Possible additions:

- session inspection UI
- run inspection UI
- approval queue UI
- node execution audit UI
- delivery and attachment dashboards
- continuity health views

## 6.2 Replay And Repair Tooling

Current state:

- durable records exist for many workflows
- manual replay/repair tooling is still limited

Why it matters:

- production systems need operator-friendly repair actions

Possible additions:

- rerun a failed outbox job
- retry a failed delivery
- rebuild continuity for one session
- inspect and repair summary or attachment state
- replay from durable transcript

## 6.3 Multi-Tenancy

Current state:

- the current repository reads as a single-deployment system

Why it matters:

- real products often support multiple customers, workspaces, or business units

Needed additions:

- tenant-aware session partitioning
- tenant-specific auth
- tenant-specific policy and agent configuration
- tenant-aware diagnostics and quotas

## 6.4 Authentication And RBAC

Current state:

- some diagnostics and readiness routes are protected by bearer or internal tokens
- broader user/operator auth is still limited

Why it matters:

- enterprise usage needs clearer identity and permissions

Future additions:

- user authentication
- operator roles
- admin roles
- session-level access controls
- approval authority scopes

## 6.5 Usage Metering And Cost Visibility

Current state:

- this is not yet a billing-oriented system

Why it matters:

- once LLMs, retrieval, storage, and remote execution grow, cost tracking becomes important

Possible additions:

- per-session token usage
- per-agent model cost tracking
- delivery cost or provider usage tracking
- per-tenant cost dashboards

## 6.6 Alerting And Production Telemetry

Current state:

- health, diagnostics, and structured logs exist
- full telemetry backend integration is still future work

Why it matters:

- production systems need proactive alerting, not just manual inspection

Future additions:

- metrics export backends
- tracing backends
- alert rules for stuck runs, dead-letter growth, delivery failures, sandbox denials, and provider outages

## 7. Nice-To-Have Features

These are not the first priorities, but may become valuable later.

Examples:

- conversation branching
- user-visible drafts before send
- collaborative approvals
- versioned prompt packs
- configurable agent personas
- localization and translation layers
- analytics on conversation outcomes
- external plugin ecosystem

## 8. Recommended Build Order

This is the recommended order after the current baseline.

### Tier 1: Highest Priority

1. Real LLM integration
2. Retrieval and long-term memory
3. Real channel/provider integrations

Why:

- these create the biggest product value and make the system feel real to end users

### Tier 2: Power And Safety

4. Stronger sandbox/container enforcement
5. Attachment understanding
6. Better prompt/context management

Why:

- these make the system safer and more useful as capabilities become stronger

### Tier 3: Scale And Product Expansion

7. Sub-agents
8. Workflow automation and richer scheduling
9. Human handoff and collaboration

Why:

- these expand the system from “assistant backend” to “assistant work platform”

### Tier 4: Enterprise And Operations

10. Admin UI
11. Replay and repair tooling
12. RBAC and multi-tenancy
13. Usage metering and alerting

Why:

- these are essential once the system is used by real teams or customers at larger scale

## 9. Good Next Documents Or Specs

If the team wants to plan these features formally, the next useful design documents or specs would be:

- `Spec 009 — Provider-Backed LLM Integration`
- `Spec 010 — Retrieval And Long-Term Memory`
- `Spec 011 — Real Transport Provider Integrations`
- `Spec 012 — Strong Sandbox Enforcement`
- `Spec 013 — Attachment Understanding`
- `Spec 014 — Sub-Agent Delegation`
- `Spec 015 — Operator Console And Replay Tooling`

## 10. Final Summary

Beyond LLM integration and sub-agents, the biggest future opportunities are:

- real transport integrations
- retrieval and memory
- stronger sandboxing
- attachment understanding
- true streaming
- richer operator tooling
- enterprise auth and tenancy

The strongest pattern to preserve is the one the current project already uses well:

- durable state first
- gateway-owned orchestration
- worker-owned execution
- explicit approvals and audit trails

If future features keep those rules, the platform can become much more capable without losing the safety and inspectability that already make the current design strong.
