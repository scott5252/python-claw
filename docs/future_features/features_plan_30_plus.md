# Features Plan 030 Plus

## Purpose

This document evaluates whether the current codebase plus the planned roadmap in [`docs/features_plan018_29.md`](/docs/features_plan018_29.md) is enough to make `python-claw` a practical OpenClaw replacement, then proposes the additional specs needed after Spec 029.

This analysis is based on:

- the current `python-claw` implementation and specs through 029
- the current OpenClaw documentation at:
  - https://docs.openclaw.ai/
  - https://docs.openclaw.ai/start/clawd
  - https://docs.openclaw.ai/concepts/agent
  - https://docs.openclaw.ai/agent-workspace
  - https://docs.openclaw.ai/reference/AGENTS.default
  - https://docs.openclaw.ai/reference/templates/SOUL
  - https://docs.openclaw.ai/multi-agent
  - https://docs.openclaw.ai/cli/agents
  - https://docs.openclaw.ai/tools/subagents
  - https://docs.openclaw.ai/gateway/local-models

## Executive Summary

The answer is no: Specs 018 through 029 are not enough by themselves to make this system a full OpenClaw replacement.

The current roadmap is strong in these areas:

- operator auth and RBAC
- multi-tenancy
- contact management
- richer outbound interactions
- campaigns and proactive messaging
- external webhook integrations
- metering and quotas
- admin/operator console
- privacy/compliance
- safety evals
- replay and repair tooling

Those are valuable platform features, and in several areas they are more enterprise-oriented than the OpenClaw docs.

However, OpenClaw also documents a different set of capabilities that are still missing from the current code and from the 018–029 plan:

- a first-class personal assistant workspace model
- user-editable persona and instruction files such as `AGENTS.md`, `SOUL.md`, `IDENTITY.md`, and `USER.md`
- user-created isolated agents with separate workspaces, auth, routing, and sessions
- user-facing multi-agent routing controls
- user-facing sub-agent lifecycle controls such as spawn, inspect, steer, kill, and thread binding
- OpenClaw-style local model workflows and model failover ergonomics
- broader channel parity, especially WhatsApp, Discord, and iMessage
- plugin/extension parity
- voice/mobile/device-oriented assistant behaviors

So the right conclusion is:

- after Spec 029, this project could be a strong enterprise assistant platform
- it would not yet be a full OpenClaw replacement for the documented OpenClaw product experience

## Direct Answers

### 1. Are there any gaps in the current code structure and the future spec plans that will prevent the solution from providing the same functionality?

Yes. There are several important gaps.

The biggest gaps are:

- no first-class agent workspace model
- no first-class persona/instruction files
- no user-created isolated agent lifecycle comparable to `openclaw agents add`, bindings, and identity management
- no user-facing sub-agent control surface comparable to `/subagents`
- no broader OpenClaw channel parity
- no plugin/extension model comparable to OpenClaw’s documented plugin-based expansion
- no documented plan for OpenClaw-style local model ergonomics, model failover, or per-agent local/remote model management

These are not minor UI details. They are structural product capabilities in OpenClaw’s documented model.

### 2. OpenClaw documents a personal assistant setup and the ability to create persona and instructions. Will this solution have that ability after Spec 029?

Not in an equivalent or first-class way.

After Spec 029, this project will likely have:

- agent records
- model, tool, and policy profile management
- admin/operator UI

But based on the current roadmap, it will still not have a documented OpenClaw-style assistant identity system where a user can define and evolve assistant behavior through workspace files such as:

- `AGENTS.md`
- `SOUL.md`
- `IDENTITY.md`
- `USER.md`
- memory files

Today, prompt/personality behavior in this codebase is mostly hard-coded in runtime prompt builders and delegation packaging logic. The 018–029 roadmap does not add a replacement for that.

So the answer is:

- partial administrative configurability may exist
- OpenClaw-style personal assistant persona/instruction authoring will not be present unless new specs are added

### 3. Does OpenClaw use sub-agents and can the user create them? If so, will that be in this solution after Spec 029?

Yes, OpenClaw does use sub-agents, and yes, the user can create and control them.

OpenClaw documents:

- `sessions_spawn`
- `/subagents spawn`
- `/subagents list`
- `/subagents info`
- `/subagents log`
- `/subagents send`
- `/subagents steer`
- `/subagents kill`
- thread binding and focus controls

This project already has internal delegation and child-session orchestration from Specs 014 and 015, but it is not equivalent to OpenClaw’s documented user-facing sub-agent system.

After Spec 029, the roadmap still does not include:

- user-facing sub-agent spawn and control commands
- thread/session focus controls
- sub-agent steering controls
- agent/session workspace isolation at the OpenClaw level
- user-manageable nested sub-agent orchestration

So the answer is:

- OpenClaw: yes
- this solution after Spec 029: not yet in equivalent form

## Detailed Gap Analysis

## A. Personal Assistant “Brain” Model

### OpenClaw capability

OpenClaw documents a dedicated assistant workspace and bootstrap files:

- `AGENTS.md`
- `SOUL.md`
- `TOOLS.md`
- `BOOTSTRAP.md`
- `IDENTITY.md`
- `USER.md`
- memory files

These are central to assistant identity, tone, continuity, and instruction shaping.

### Current state in this project

This project has:

- durable agent profiles
- model profiles
- settings-backed tool/policy profiles
- prompt generation in code
- transcript/summaries/retrieval/memory

It does not have:

- per-agent editable workspace files
- persona files as a source of truth
- bootstrap rituals for assistant identity
- user-editable instruction files as a normal product feature

### Why this matters

This is one of the most important product differences. OpenClaw treats the assistant’s “mind” as durable, user-editable artifacts. This project currently treats behavior mostly as runtime configuration and code-defined prompts.

## B. User-Created Isolated Agents

### OpenClaw capability

OpenClaw documents:

- multi-agent routing
- per-agent workspaces
- per-agent auth/state/session directories
- CLI commands for creating and deleting agents
- routing bindings by channel/account/peer

### Current state in this project

This project has:

- durable `agent_profiles`
- durable session ownership
- child-agent delegation
- planned UI for configuring agents

It does not yet have a full isolated-agent lifecycle comparable to OpenClaw:

- no agent workspace per agent
- no per-agent auth store
- no per-agent session store isolation by filesystem/workspace concept
- no routing-bindings system that lets inbound traffic target a user-created agent by channel/account/peer rules

## C. User-Facing Sub-Agent Management

### OpenClaw capability

OpenClaw documents user-facing sub-agent workflows, including:

- spawn
- inspect
- log
- steer
- kill
- focus/unfocus
- nested depth controls

### Current state in this project

This project supports:

- internal typed delegation
- child sessions
- child runs
- child-to-parent result return
- approval-aware delegated work

It does not support:

- explicit user commands to create sub-agents
- interactive control of active sub-agents
- sub-agent thread binding
- user-controlled orchestration patterns

This is a major functional gap, not just a naming difference.

## D. Channel Parity

### OpenClaw capability

OpenClaw documents support for:

- WhatsApp
- Telegram
- Discord
- iMessage
- plugin-based Mattermost support

### Current state in this project

This project currently centers on:

- Slack
- Telegram
- Webchat

Even after Spec 029, the roadmap does not add the missing OpenClaw channels.

If “OpenClaw replacement” includes real product parity, channel coverage is a major gap.

## E. Local Models, Provider Ergonomics, and Failover

### OpenClaw capability

OpenClaw documents:

- local-model workflows
- OpenAI-compatible local endpoints
- model configuration by agent
- model quality/cost guidance
- model failover topics in the docs

### Current state in this project

This project already has a useful base:

- provider-backed runtime
- per-agent model profiles
- base URL overrides
- enough structure to route some agents to different model endpoints

But there are still gaps:

- only one provider-backed client path is implemented
- no first-class model failover plan
- no post-029 roadmap item for provider routing parity
- no user-facing model profile experience comparable to OpenClaw’s local-first setup guidance

This is closer than some other areas, but still incomplete.

## F. Plugin and Extension Model

### OpenClaw capability

OpenClaw documents plugin-based ecosystem expansion.

### Current state in this project

This project has:

- internal tools
- typed capabilities
- policy-aware execution

It does not yet have a documented plugin SDK or extension marketplace model in the roadmap through 029.

## G. Device, Voice, and Personal Agent Surface Area

### OpenClaw capability

OpenClaw documents:

- voice features
- mobile-node features
- richer personal assistant workflows

### Current state in this project

This project has partial media/channel work, but no roadmap through 029 that closes parity on:

- voice-first assistant flows
- mobile-node/device integration
- personal assistant device actions

## What the 018–029 Roadmap Does Well

To avoid overstating the gap, it is important to note that `docs/features_plan018_29.md` adds many capabilities OpenClaw replacement work would need anyway.

These planned specs are highly valuable and should remain:

- Spec 018: operator auth and RBAC
- Spec 019: tenant isolation
- Spec 020: contact management
- Spec 021: richer interactive content
- Spec 022: proactive messaging and campaigns
- Spec 023: webhooks and event subscriptions
- Spec 024: metering and quotas
- Spec 025: operator/admin console
- Spec 026: feedback loops
- Spec 027: privacy and compliance
- Spec 028: safety evaluation
- Spec 029: replay and repair

These move the platform toward a serious production system.

The issue is not that the roadmap is weak. The issue is that it is pointed more toward enterprise assistant operations than toward OpenClaw’s documented personal-agent and multi-agent runtime model.

## Additional Specs Needed After 029

The following specs are recommended to close the OpenClaw-replacement gap.

## Spec 030: Agent Workspace, Persona Files, and Bootstrap Identity System

### Goal

Introduce a first-class per-agent workspace model and make user-editable files the durable source of assistant persona, identity, standing instructions, and memory bootstrap.

### Why this spec is needed

Without this spec, the solution will still lack the most recognizable OpenClaw capability: a user-shaped assistant “mind” defined by editable workspace artifacts instead of only admin/runtime configuration.

### Detailed scope

- Add a durable agent workspace concept with one workspace root per primary agent.
- Define first-class workspace files, at minimum:
  - `AGENTS.md`
  - `SOUL.md`
  - `IDENTITY.md`
  - `USER.md`
  - `TOOLS.md`
  - `MEMORY.md` or equivalent canonical memory file
- Add bootstrap creation for missing workspace files from templates.
- Add prompt assembly changes so these files influence runtime prompts in a deterministic, bounded, auditable way.
- Add precedence rules between:
  - system defaults
  - agent profile data
  - workspace instruction files
  - session transcript/context
- Add safety and size limits so workspace files cannot silently explode prompt budgets.
- Add diagnostics showing which workspace files and file revisions contributed to a given run.
- Add APIs and UI for viewing and editing workspace files.
- Add tests proving:
  - persona changes take effect deterministically
  - prompt input stays bounded
  - concurrent edits are handled safely
  - runtime behavior is reproducible from transcript plus workspace revision state

### Key design decisions this spec should settle

- whether workspace files are stored only on disk, mirrored into the database, or both
- whether file revision history is Git-backed, database-backed, or hybrid
- whether child agents inherit any workspace material from parents

## Spec 031: User-Created Multi-Agent Lifecycle and Routing Bindings

### Goal

Let users and operators create isolated agents with their own workspaces, identity, routing, auth boundaries, and inbound traffic bindings.

### Why this spec is needed

`agent_profiles` today are execution identities, not full OpenClaw-style user-created agents.

### Detailed scope

- Add durable agent lifecycle APIs for:
  - create agent
  - disable/enable agent
  - archive agent
  - delete agent
- Add per-agent workspace configuration and validation.
- Add per-agent state/config separation.
- Add inbound routing bindings by:
  - channel
  - channel account
  - peer/direct sender
  - group/thread/channel container
- Add deterministic binding precedence rules.
- Add fallback/default-agent rules per tenant or workspace.
- Add agent cloning from templates.
- Add UI/CLI flows for adding and binding agents.
- Add tests proving:
  - inbound traffic routes to the intended agent
  - bindings cannot cross tenants improperly
  - agent disablement fails closed
  - session continuity rules remain deterministic

### Key design decisions this spec should settle

- whether agents are tenant-scoped or globally scoped with tenant mappings
- how routing bindings interact with current canonical session identity
- whether existing sessions can or cannot migrate between agents

## Spec 032: User-Facing Sub-Agent Control and Orchestration UX

### Goal

Extend internal delegation into a user-visible sub-agent system with spawn, inspect, steer, focus, and kill controls.

### Why this spec is needed

OpenClaw does not just use sub-agents internally. It exposes them as a controllable runtime feature.

### Detailed scope

- Add user/operator command and API surfaces for:
  - list sub-agents
  - spawn sub-agent
  - inspect sub-agent
  - view sub-agent transcript/log
  - send message to sub-agent
  - steer active sub-agent
  - kill one or all sub-agents
- Add nested sub-agent limits:
  - max depth
  - max children per parent
  - max global concurrent sub-agents
- Add orchestration controls for whether a child is:
  - one-shot run
  - persistent bound session
- Add parent-child announce and result-delivery UX contracts.
- Add UI support for monitoring active sub-agents.
- Add tests covering:
  - spawn idempotency
  - steering while active
  - cascade cancellation
  - nested orchestration
  - bounded announce behavior

### Key design decisions this spec should settle

- whether this feature is exposed as chat commands, UI-only controls, APIs, or all three
- whether sub-agent steering appends transcript rows or mutates queued instructions
- whether users can directly create persistent child sessions

## Spec 033: Thread Binding, Focus Controls, and Session Targeting

### Goal

Add explicit thread/session binding controls so user follow-up messages can target a chosen agent or sub-agent session predictably.

### Why this spec is needed

OpenClaw documents focus/unfocus and thread-bound sub-agent sessions. The current roadmap does not.

### Detailed scope

- Add bindings between channel threads and internal sessions.
- Add commands or UI actions for:
  - focus
  - unfocus
  - inspect current binding
- Add idle timeout and max-age controls for temporary bindings.
- Add channel-specific support contracts for platforms that support threads.
- Add diagnostics for bound session targets and expiration state.
- Add tests proving:
  - bound follow-up messages route correctly
  - idle expiry cleans up safely
  - thread binding cannot hijack unrelated sessions

## Spec 034: Provider Matrix, Local Model Routing, and Failover

### Goal

Upgrade model runtime support so the system can match OpenClaw’s practical local-model and multi-provider operating model.

### Why this spec is needed

The current structure is close, but the roadmap through 029 does not guarantee OpenClaw-level usability for local models and per-agent model strategies.

### Detailed scope

- Add first-class provider adapter abstraction by provider type.
- Support OpenAI-compatible local endpoints as a first-class runtime mode.
- Add explicit Ollama-compatible or generic local provider support.
- Add model failover chains:
  - primary
  - fallback
  - timeout and retry policy
- Add per-agent and per-sub-agent model strategy config.
- Add diagnostics showing model selection and failover decisions.
- Add tests for:
  - failover correctness
  - provider isolation
  - local endpoint compatibility
  - per-agent routing

### Key design decisions this spec should settle

- whether local providers are treated as OpenAI-compatible adapters or unique provider types
- how failover affects prompt/tool compatibility and usage accounting

## Spec 035: Channel Parity Expansion and Plugin SDK

### Goal

Close the major channel and extensibility gap relative to OpenClaw.

### Why this spec is needed

Without WhatsApp, Discord, iMessage, and a plugin model, this solution will still not be a realistic OpenClaw replacement for many documented use cases.

### Detailed scope

- Add first-class channel support roadmap for:
  - WhatsApp
  - Discord
  - iMessage
- Add a plugin/extension SDK for adding channels and runtime integrations.
- Define stable plugin boundaries for:
  - inbound event normalization
  - outbound delivery
  - auth/config storage
  - capability injection
- Add plugin safety and signing rules.
- Add operational diagnostics for plugin state and failures.
- Add tests for plugin isolation and channel adapter contracts.

### Key design decisions this spec should settle

- whether channels are core modules or plugins by default
- what plugin permissions are allowed
- how plugin lifecycle/versioning is managed

## Spec 036: Personal Assistant Device and Voice Surface

### Goal

Add the personal-assistant interaction layer that OpenClaw emphasizes beyond text chat.

### Why this spec is needed

OpenClaw’s documented value includes voice and device-oriented assistant experiences, not only text chat.

### Detailed scope

- Add voice-note ingestion and transcription contracts.
- Add outbound voice/audio response support where channels allow it.
- Add assistant-side device action abstractions for supported clients/nodes.
- Add capability governance for high-risk device actions.
- Add diagnostics and audit for device-originated commands.
- Add tests for voice/media/device flows.

### Key design decisions this spec should settle

- whether device integration is core, plugin-based, or app-specific
- whether voice actions are just media workflows or a separate conversational mode

## Spec 037: Personal Assistant Onboarding, Memory Rituals, and Guided Setup

### Goal

Provide an OpenClaw-like personal assistant setup experience instead of only operator/admin configuration.

### Why this spec is needed

OpenClaw explicitly documents personal-assistant onboarding and first-run identity shaping. The current roadmap does not.

### Detailed scope

- Add first-run assistant setup flows for:
  - agent identity
  - persona
  - user preferences
  - standing boundaries
- Add guided bootstrap prompts that populate workspace/persona files.
- Add explicit memory-writing surfaces for durable preferences and standing instructions.
- Add setup and migration flows for moving an assistant between machines or environments.
- Add tests proving onboarding outputs deterministic persisted state.

## Spec 038: Per-Agent Auth Profiles, Credential Isolation, and Sharing Rules

### Goal

Make agent isolation complete enough to support the OpenClaw model of multiple separate “brains” with different credentials and tool access.

### Why this spec is needed

OpenClaw documents per-agent auth stores and non-shared credentials by default. The current roadmap through 029 does not define equivalent behavior.

### Detailed scope

- Add per-agent auth profile storage and lookup.
- Add optional credential sharing or inheritance rules with explicit operator approval.
- Add diagnostics showing which credentials were available to which agent.
- Add policy constraints on cross-agent credential reuse.
- Add tests proving one agent cannot silently use another agent’s credentials.

## Spec 039: Agent and Sub-Agent Template Library

### Goal

Make it easy to create new agents and sub-agents from reusable templates for persona, tools, and model strategy.

### Why this spec is needed

Once agent creation becomes user-facing, templates become necessary for usability and consistency.

### Detailed scope

- Add reusable templates for:
  - personal assistant
  - coding agent
  - research agent
  - notification agent
  - delegate/on-behalf-of agent
- Allow templates to define:
  - workspace starter files
  - model profile defaults
  - policy/tool defaults
  - routing defaults
  - sub-agent permissions
- Add UI/API support for template-driven creation.
- Add versioning and upgrade rules for templates.

## Spec 040: OpenClaw Compatibility and Migration Layer

### Goal

Provide a practical bridge for users who think in OpenClaw concepts and may want to migrate configuration or workflows.

### Why this spec is needed

If the product goal is “OpenClaw replacement,” a compatibility layer reduces adoption friction and makes the product easier to position.

### Detailed scope

- Add import/export tooling for core concepts analogous to:
  - agent identities
  - workspaces/persona files
  - routing bindings
  - model settings
  - sub-agent defaults
- Add a compatibility vocabulary in docs and UI where appropriate.
- Add a gap report tool that explains what can and cannot be migrated.
- Add tests for compatibility import validation and safe fallback behavior.

## Recommended Priority Order After 029

If the goal is specifically “become an OpenClaw replacement,” the recommended order is:

1. Spec 030: Agent Workspace, Persona Files, and Bootstrap Identity System
2. Spec 031: User-Created Multi-Agent Lifecycle and Routing Bindings
3. Spec 032: User-Facing Sub-Agent Control and Orchestration UX
4. Spec 033: Thread Binding, Focus Controls, and Session Targeting
5. Spec 034: Provider Matrix, Local Model Routing, and Failover
6. Spec 038: Per-Agent Auth Profiles, Credential Isolation, and Sharing Rules
7. Spec 035: Channel Parity Expansion and Plugin SDK
8. Spec 037: Personal Assistant Onboarding, Memory Rituals, and Guided Setup
9. Spec 039: Agent and Sub-Agent Template Library
10. Spec 036: Personal Assistant Device and Voice Surface
11. Spec 040: OpenClaw Compatibility and Migration Layer

## Minimum Post-029 Set Needed for Credible Replacement Positioning

If the team wants the smallest possible set of follow-on specs to credibly claim OpenClaw replacement direction, the minimum set is:

- Spec 030
- Spec 031
- Spec 032
- Spec 034
- Spec 035

Without those, the product will still miss too much of OpenClaw’s documented runtime model.

## Final Recommendation

Keep the existing 018–029 roadmap. It fills real production and enterprise gaps.

But if the intended destination is true OpenClaw replacement, the roadmap needs a second track beginning at Spec 030 that adds:

- assistant workspace and identity files
- user-created isolated agents
- user-facing sub-agent controls
- richer provider/local-model ergonomics
- channel/plugin parity

That is the point where this platform starts matching not only the backend reliability of OpenClaw-adjacent systems, but also the user-facing product model described in the OpenClaw docs.
