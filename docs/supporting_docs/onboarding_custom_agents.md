# Onboarding: Custom Agents and Sub-Agents

## Purpose

This document explains how `python-claw` currently supports agents and sub-agents, how new custom agents can be added today, what is still missing, and how that changes across the planned roadmap.

The specific end goal is:

- users can create custom agents from the UI
- users can enable or disable those agents
- users can define what each agent can and cannot do
- users can create and control sub-agents in a first-class way

## Executive Summary

Today, the system already has a real internal agent model:

- durable `agent_profiles`
- durable `model_profiles`
- per-session `owner_agent_id`
- per-run bound model, policy, and tool profile keys
- internal sub-agent delegation via child sessions and child runs

Today, the system does **not** yet have a full user-facing custom-agent product:

- no agent create/update/delete write API
- no UI for creating agents
- no first-class user-created agent workspace
- no per-agent editable prompt/persona files
- no user-facing sub-agent lifecycle controls
- no direct user control over thread focus or sub-agent steering

So the accurate current state is:

- **custom agent execution identities exist**
- **internal sub-agent orchestration exists**
- **user-facing custom-agent management does not yet exist**

## Current Architecture

### 1. What an “agent” means today

In the current codebase, an agent is primarily an execution identity resolved from durable and settings-backed configuration:

- durable identity lives in `agent_profiles`
- durable model selection lives in `model_profiles`
- policy behavior is selected by `policy_profile_key`
- tool visibility is selected by `tool_profile_key`
- session ownership lives on `sessions.owner_agent_id`
- execution binding is snapshotted onto `execution_runs`

The main implementation files are:

- `src/agents/bootstrap.py`
- `src/agents/repository.py`
- `src/agents/service.py`
- `src/sessions/service.py`
- `src/jobs/service.py`
- `src/config/settings.py`

### 2. What a “sub-agent” means today

A sub-agent is not a separate runtime process with its own user-facing lifecycle. It is an internally delegated child session owned by another agent.

The current implementation path is:

1. the parent agent emits `delegate_to_agent`
2. `src/tools/delegation.py` validates the request
3. `src/delegations/service.py` creates a `delegations` row
4. `src/sessions/repository.py` creates a child session with `session_kind="child"`
5. a child system message is written with the delegation package
6. a child execution run is queued with `trigger_kind="delegation_child"`
7. when the child completes, a parent-side follow-up run is queued with either:
   - `delegation_result`
   - `delegation_approval_prompt`

This is real sub-agent orchestration, but it is internal orchestration, not a user-facing sub-agent control surface.

## What Specs 001 Through 017 Contribute

The custom-agent story is cumulative. Specs 014 and 015 are the direct agent specs, but they rely on foundations from 001 through 013 and the operational controls from 016 through 017.

| Spec | Contribution to custom agents and sub-agents |
| --- | --- |
| 001 | Creates the durable session and transcript foundation that all agent ownership depends on. |
| 002 | Adds the runtime graph and typed tool registry that agents use to act. |
| 003 | Adds capability governance and approval matching, which is the base for agent permission control. |
| 004 | Adds context continuity, summaries, and recovery, which lets agent work persist across turns. |
| 005 | Adds queued run execution and worker orchestration, which makes agent and child-agent runs durable. |
| 006 | Adds remote execution and per-agent sandbox linkage, which becomes part of agent-specific execution control. |
| 007 | Adds channel and media delivery so primary sessions can interact with real channels while child sessions stay internal. |
| 008 | Adds diagnostics and observability needed to inspect agent and delegation behavior. |
| 009 | Adds provider-backed model runtime so different agents can bind to different model profiles. |
| 010 | Adds typed tool schemas, which makes tool exposure and approval identity deterministic per agent. |
| 011 | Adds retrieval, memory, and attachment understanding so agent runs have richer context. |
| 012 | Adds production channel integration, which is the delivery surface for primary agent sessions. |
| 013 | Adds streaming delivery, which affects how primary-agent output is surfaced. |
| 014 | Introduces durable agent profiles, model profiles, session ownership, and execution binding. This is the core custom-agent foundation. |
| 015 | Introduces durable delegation records, child sessions, child runs, and child-to-parent continuation. This is the core internal sub-agent foundation. |
| 016 | Adds human handoff and approval UX, including how paused child work resumes after approval. |
| 017 | Adds production hardening, quotas, auth boundaries, and operational safeguards that make multi-agent behavior safer in real deployments. |

## What Exists Today

### Durable agent identity

Implemented primarily by Spec 014.

Current tables and fields:

- `agent_profiles`
- `model_profiles`
- `sessions.owner_agent_id`
- `sessions.session_kind`
- `sessions.parent_session_id`
- `execution_runs.agent_id`
- `execution_runs.model_profile_key`
- `execution_runs.policy_profile_key`
- `execution_runs.tool_profile_key`

This means the runtime already supports:

- more than one agent identity
- different sessions owned by different agents
- different child sessions owned by child agents
- durable model/profile binding per run

### Runtime binding

`src/agents/service.py` resolves an `AgentExecutionBinding` before execution. That binding includes:

- agent id
- session kind
- model profile key
- policy profile key
- tool profile key
- resolved model configuration
- resolved policy profile
- resolved tool profile
- allowed capabilities

This is the main contract that turns a durable agent record into executable runtime behavior.

### Permissions and “what an agent can do”

Implemented mostly by Specs 003, 006, 010, 014, and 015.

Today, the strongest permission controls are:

- `tool_profile_key`
  - allowlists visible capabilities
- `policy_profile_key`
  - can deny capabilities
  - can enable or disable remote execution
  - can enable or disable delegation
  - can limit delegation depth
  - can allowlist child agent ids
  - can limit active delegations per run and per session
- approval matching
  - exact approval matching remains scoped to `agent_id`
- sandbox resolution
  - remote execution uses the current run’s `agent_id`

This means the system already supports a meaningful form of:

- what this agent can do
- what this agent cannot do
- which child agents this agent may call

But this control is currently configured through settings and data seeding, not through a user-facing creation experience.

### Internal sub-agent orchestration

Implemented primarily by Spec 015.

Today the system supports:

- bounded async delegation via `delegate_to_agent`
- durable `delegations`
- child sessions
- child runs
- parent result handoff
- child approval pause and continuation
- nested delegation when enabled by policy and tool profiles

This is enough to say the backend supports sub-agents internally today.

### Read-only admin visibility

Current read surfaces already expose useful inspection endpoints:

- `GET /agents`
- `GET /agents/{agent_id}`
- `GET /agents/{agent_id}/sessions`
- `GET /agents/{agent_id}/delegations`
- `GET /model-profiles`
- `GET /model-profiles/{profile_key}`
- delegation detail and event inspection endpoints

These came from Specs 014, 015, 016, and 017.

## How to Add a New Custom Agent Today

Today, adding a new agent is a backend/operator task, not a UI workflow.

### Current process

At a minimum:

1. create or seed a `model_profiles` row
2. create or seed an `agent_profiles` row that references that model profile
3. choose a valid `policy_profile_key`
4. choose a valid `tool_profile_key`
5. if needed, add settings-backed policy or tool profiles in `src/config/settings.py` configuration
6. if the agent should be picked up by bootstrap or historical backfill logic, add the relevant override settings
7. if the agent needs remote execution templates, add `remote_exec_agent_templates`

If the agent should be usable as a child agent:

1. parent policy must have `delegation_enabled=true`
2. parent tool profile must include `delegate_to_agent`
3. parent policy must include the child id in `allowed_child_agent_ids`
4. delegation depth and active delegation limits must allow the call

### Important current limitation

The codebase currently has:

- read APIs for agents and model profiles
- runtime support for agent bindings

The codebase does **not** currently have:

- agent create API
- agent update API
- agent delete or archive API
- model profile create/update UI
- policy profile create/update UI
- tool profile create/update UI

So “creating a custom agent” is currently done by:

- migration
- seed script
- direct SQL
- settings/config changes
- custom internal code path

## What Is Missing Today

### Missing product features

The system does not yet provide:

- a UI for creating agents
- a UI for enabling or disabling agents
- a UI for editing model, policy, and tool profiles
- a user-facing command or UI to spawn a sub-agent directly
- a user-facing command or UI to inspect, steer, or kill a sub-agent
- thread binding or focus controls for sub-agent sessions
- per-agent workspace files such as `AGENTS.md`, `SOUL.md`, `IDENTITY.md`, or `USER.md`
- per-agent auth isolation
- template-based agent creation

### Missing prompt and persona controls

Agent profile fields like:

- `display_name`
- `role_kind`
- `description`

exist durably, but are not currently first-class prompt inputs.

Prompt behavior is still mainly defined in code:

- `src/graphs/prompts.py`
- `src/delegations/service.py`

So today, a new agent can have different model/tool/policy behavior, but not a true first-class persona authoring workflow.

### Missing user-facing sub-agent lifecycle

Sub-agents exist internally, but users cannot yet:

- create them directly
- list them directly as a first-class feature
- steer them while they are active
- bind future messages to them
- kill one or all active sub-agents through a supported UX

## What Specs 018 Through 029 Change

Specs 018 through 029 improve the platform around agents, but they do not fully solve user-created custom agents.

### Important improvements from 018 through 029

| Spec | Relevance to custom agents |
| --- | --- |
| 018 | Adds real auth and RBAC, which is required before safe multi-user agent administration. |
| 019 | Adds tenant isolation, which is required before agents can be safely scoped per tenant or workspace. |
| 023 | Adds webhooks and event subscriptions, which can expose agent and delegation lifecycle externally. |
| 024 | Adds usage and cost accounting by tenant, agent, and model. |
| 025 | Adds the management console and explicitly plans configuration UIs for agents, model profiles, policy profiles, and tool profiles. |
| 028 | Adds safety testing for prompt injection, approval circumvention, and sub-agent isolation. |
| 029 | Adds operator replay and repair tools that matter for stuck or failed agent/sub-agent state. |

### What 018 through 029 still do not provide

Even after Spec 029, the roadmap still does not guarantee:

- first-class user-created agent lifecycle
- per-agent workspace files
- user-facing sub-agent spawn, steer, and kill controls
- thread focus and binding
- per-agent auth stores
- agent templates

So after Spec 029, the likely state is:

- agents are more operable
- agents are more secure
- agents are more visible in the console
- agents are still not fully OpenClaw-style user-created “brains”

## What Needs To Happen After 029

The post-029 roadmap in `docs/future_features/features_plan_30_plus.md` is the roadmap that turns the current internal agent architecture into a real user-facing custom-agent product.

### Most important follow-on specs

| Spec | Why it matters |
| --- | --- |
| 030 | Adds per-agent workspace files and makes persona/instruction artifacts first-class. |
| 031 | Adds true user-created multi-agent lifecycle and routing bindings. |
| 032 | Adds user-facing sub-agent control and orchestration UX. |
| 033 | Adds thread binding, focus controls, and session targeting. |
| 038 | Adds per-agent auth profiles and credential isolation. |
| 039 | Adds reusable templates for creating agents and sub-agents. |

### How the product changes once these specs exist

After those specs, the system changes from:

- internal agent identities managed by operators and configuration

to:

- user-creatable agents with their own workspaces, identity, permissions, and routing

And it changes from:

- internal child-session delegation only

to:

- a first-class user-visible sub-agent system

## Recommended End-State For The Goal In This Project

If the goal is specifically:

- create custom agents in the UI
- configure what they can and cannot do
- create and manage sub-agents through the UI

then the minimum spec set is not just one spec.

### Required foundation

- Spec 018 for identity and RBAC
- Spec 019 for tenant isolation
- Spec 025 for the management console

### Required custom-agent specs

- Spec 030 for workspace and persona files
- Spec 031 for create/enable/disable/archive/delete lifecycle and routing bindings
- Spec 032 for user-facing sub-agent controls
- Spec 033 for thread binding and focus behavior
- Spec 038 for per-agent credential isolation
- Spec 039 for templates and guided creation

### Optional but strongly related

- Spec 034 for better per-agent provider and local model behavior
- Spec 040 for compatibility and migration support

## Gap Assessment Against The Stated Goal

### Goal: users create custom agents from the UI

Current state:

- not supported directly

Needed specs:

- 018
- 019
- 025
- 031
- 039

### Goal: users configure agent persona and instructions

Current state:

- only partly supported through code edits and indirect profile fields

Needed specs:

- 030
- 037

### Goal: users define what the agent can and cannot do

Current state:

- partially supported in backend through policy profiles, tool profiles, approval scope, delegation allowlists, and sandbox rules
- not yet supported as a polished user-facing feature

Needed specs:

- 025
- 031
- 038

### Goal: users create and control sub-agents

Current state:

- internal orchestration exists
- user-facing control does not

Needed specs:

- 032
- 033
- 039

## Bottom Line

The current system already contains the backend foundations for custom agents and internal sub-agents:

- Spec 014 gives the durable agent model
- Spec 015 gives the durable sub-agent delegation model
- Specs 003, 006, 010, 016, and 017 provide the major safety and control boundaries

However, the current implementation is still an operator- and code-driven model, not a user-facing custom-agent product.

The roadmap through Spec 029 makes the system much more secure and operable, especially through auth, tenancy, and a management console. But the capabilities needed for users to create their own custom agents and govern their permissions through the UI are mainly delivered by the post-029 specs, especially:

- Spec 030
- Spec 031
- Spec 032
- Spec 033
- Spec 038
- Spec 039

If those specs land, the system can evolve from “durable internal agent orchestration” into “user-created custom agents and sub-agents with UI-managed behavior and boundaries.”
