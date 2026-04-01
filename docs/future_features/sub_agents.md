# Sub-Agents

This document explains what would need to be implemented for `python-claw` to support sub-agents, including support for:

- a primary user-facing agent
- one or more delegated specialist sub-agents
- the ability for sub-agents to use the same LLM as the parent or different LLMs as needed

The design in this document assumes that the project keeps its current architectural rules:

- gateway-first execution
- durable sessions and transcript persistence
- worker-owned async execution
- policy and approval enforcement
- replay-safe and auditable durable state

## 1. What “Sub-Agents” Means In This Project

In this project, a sub-agent should not mean:

- a hidden chain of prompts inside one model call
- an untracked internal helper with no durable state
- a free-form model that spawns more models without policy control

In this project, a sub-agent should mean:

- a bounded specialist assistant
- started by the main agent through a typed, policy-controlled delegation path
- with its own identity, context boundary, tools, run records, and durable history

Examples:

- a coding specialist
- a research specialist
- a summarization specialist
- a documentation specialist
- an operations specialist

The user still talks to one main assistant. The sub-agent is an internal specialist worker.

## 2. Why The Current Architecture Is Compatible

The project already has several good foundations for sub-agents:

- durable sessions
- append-only messages
- execution runs
- policy-aware tool binding
- approval-gated actions
- remote execution as a separate boundary
- diagnostics and auditability

Relevant current files:

- [src/sessions/service.py](/src/sessions/service.py)
- [src/sessions/repository.py](/src/sessions/repository.py)
- [src/jobs/service.py](/src/jobs/service.py)
- [src/jobs/repository.py](/src/jobs/repository.py)
- [src/graphs/assistant_graph.py](/src/graphs/assistant_graph.py)
- [src/graphs/nodes.py](/src/graphs/nodes.py)
- [src/graphs/state.py](/src/graphs/state.py)
- [src/providers/models.py](/src/providers/models.py)

The biggest current limitation is:

- the system only has one default `agent_id` source today

That is enough for a single assistant, but not enough for a true parent/sub-agent system.

## 3. What Must Be Added

At a high level, sub-agents require six major additions:

1. A delegation model
2. Durable parent/child records
3. Child-session and child-run execution
4. Agent-specific tool and policy configuration
5. Agent-specific LLM selection
6. Read and control surfaces for operators and developers

## 4. Required New Concepts

## 4.1 Primary Agent vs Specialist Agent

Today, the runtime uses a configured default agent:

- `default_agent_id` in [src/config/settings.py](/src/config/settings.py)

To support sub-agents, the system needs explicit agent definitions, for example:

- `main-assistant`
- `research-agent`
- `coding-agent`
- `docs-agent`
- `ops-agent`

Each agent should have its own:

- `agent_id`
- role or purpose
- allowed tools
- default policy profile
- default LLM/model profile
- optional sandbox profile

This is the foundation for giving different agents different capabilities and different model choices.

## 4.2 Delegation As A Typed Capability

Sub-agents should not be started by raw prompt magic alone.

The main assistant should delegate through a typed capability such as:

- `spawn_sub_agent`
- `delegate_task`
- `start_specialist_task`

That tool would:

- create durable delegation state
- create a child session or child run
- return a structured reference to the parent agent

Why this matters:

- delegation becomes auditable
- policy can approve or deny delegation
- diagnostics can show what happened

## 4.3 Child Session As The Durable Boundary

The best fit for this project is:

- parent session for the main user-facing conversation
- child session for each specialist sub-agent thread

Why child session is better than hidden in-memory state:

- durable transcript
- replay-safe
- inspectable by operators
- bounded context for the specialist
- easy to attach its own runs, tools, approvals, and results

That also matches the current project’s session-first architecture.

## 4.4 Delegation Record As A First-Class Object

The system should not infer delegation by “just looking around” in transcripts.

It should add explicit durable delegation records.

Recommended new table:

- `delegations`

Suggested fields:

- `id`
- `parent_session_id`
- `parent_message_id`
- `parent_execution_run_id`
- `parent_agent_id`
- `child_session_id`
- `child_agent_id`
- `delegation_kind`
- `purpose`
- `status`
- `depth`
- `input_payload_json`
- `result_summary_json`
- `error_detail`
- `trace_id`
- `created_at`
- `updated_at`
- `completed_at`

Suggested statuses:

- `pending`
- `queued`
- `running`
- `completed`
- `failed`
- `cancelled`
- `timed_out`

This table becomes the main durable control point for sub-agent orchestration.

## 5. Database Changes

## 5.1 Session Linking

The current `sessions` table has no parent/child relationship.

To support sub-agents well, the schema should add either:

1. New columns on `sessions`
2. Or a separate link table

Recommended simple approach:

Add to `sessions`:

- `parent_session_id` nullable foreign key to `sessions.id`
- `session_kind` such as `primary`, `child`, `system`
- `owner_agent_id`

Possible benefits:

- easy traversal from child to parent
- easy filtering in diagnostics
- explicit distinction between user-facing and specialist sessions

## 5.2 Delegation Table

Add:

- `delegations`

Purpose:

- durable lifecycle record for each sub-agent task

This table should connect:

- parent session
- child session
- parent run
- child run
- parent agent
- child agent

## 5.3 Optional Agent Registry Table

Right now agent identity is mostly configuration-driven.

For sub-agents, it would help to add a durable agent profile table, for example:

- `agent_profiles`

Suggested fields:

- `agent_id`
- `display_name`
- `role_kind`
- `default_model_profile_id`
- `policy_profile_key`
- `tool_profile_key`
- `enabled`
- `created_at`
- `updated_at`

This gives the system a real registry of known agents.

## 5.4 Optional Model Profile Table

To let sub-agents use the same or different LLMs, the system likely needs explicit model profiles.

Recommended table:

- `model_profiles`

Suggested fields:

- `id`
- `profile_key`
- `provider`
- `model_name`
- `temperature`
- `max_input_tokens`
- `max_output_tokens`
- `timeout_seconds`
- `tool_calling_enabled`
- `json_mode_enabled`
- `enabled`
- `created_at`
- `updated_at`

Then each agent profile can point to one default model profile.

This is the cleanest way to support:

- same model for all agents
- different model per agent
- future fallback or tiered routing

## 5.5 Optional Delegation Event Table

The project already uses append-only governance and artifact history.

A similar append-only event table would help here, for example:

- `delegation_events`

This could store:

- delegation created
- child session created
- child run queued
- child run started
- child result returned
- delegation cancelled
- delegation failed

That would improve replay and diagnostics.

## 6. Execution Model

## 6.1 Recommended Lifecycle

The safest sub-agent lifecycle in this project is:

1. User sends a message into the parent session.
2. Parent run is created in `execution_runs`.
3. Parent graph decides to delegate.
4. Parent calls a typed delegation tool.
5. Delegation service creates:
   - a `delegations` row
   - a child `sessions` row
   - a child trigger message
   - a child `execution_runs` row
6. A worker processes the child run.
7. Child graph executes with the child agent’s policy, tools, and model profile.
8. Child result is written durably.
9. Parent run resumes or later reads the child result.
10. Parent agent decides what to tell the user.

This keeps each specialist task as normal durable work, not a hidden internal prompt chain.

## 6.2 Parent Run Waiting Strategy

The system must choose how a parent run behaves while a child run executes.

There are three main options:

1. Synchronous wait inside the parent run
2. Persist and resume later
3. Fire-and-observe background style

Recommended default:

- persist and resume later

Why:

- fits the current async queue design
- avoids holding one worker hostage for long sub-agent work
- makes retries and recovery cleaner

Practical approach:

- parent run writes delegation state and returns an assistant message like:
  - “I’m asking a specialist agent to work on that.”
- child run executes separately
- parent can resume when the child result is available, either automatically or on the next user-visible turn

If a synchronous wait option is ever added, it should be tightly bounded by timeout.

## 6.3 Child Run Creation

The project already has a durable queue:

- `execution_runs`

Sub-agent work should reuse it.

Recommended behavior:

- child work is just another `execution_runs` row
- but it points at the child session
- and carries the child agent’s `agent_id`

This means current worker infrastructure can mostly be reused.

## 7. How Different LLMs Would Work

This is a major part of the request.

Sub-agents should be able to use:

- the same model as the parent
- a different model than the parent
- a different provider entirely if needed

## 7.1 Why Different Agents May Need Different Models

Examples:

- main assistant:
  - strong conversational model
  - better for user-facing clarity
- coding specialist:
  - stronger coding/tool-use model
- summarization specialist:
  - cheaper fast model
- research specialist:
  - model optimized for longer synthesis

So the system should not assume one global model is always best.

## 7.2 Model Profile Routing

Recommended design:

- each agent has a default model profile
- the execution layer resolves model choice from the current `agent_id`

For example:

- `main-assistant` -> `gpt-main`
- `coding-agent` -> `gpt-coder`
- `research-agent` -> `gpt-research`
- `docs-agent` -> `gpt-fast-docs`

The routing logic should live near graph/model construction, likely around:

- [apps/gateway/deps.py](/apps/gateway/deps.py)

Instead of always doing:

- `RuleBasedModelAdapter()`

the system would resolve:

- the correct model adapter for the current agent

## 7.3 Same Provider, Different Models

Simplest first step:

- one provider
- multiple model names

Example:

- parent uses `provider=openai, model=gpt-main`
- coding child uses `provider=openai, model=gpt-coder`

This is operationally simpler because:

- one auth setup
- one client library
- easier observability

## 7.4 Different Providers

The architecture should also allow:

- parent uses one provider
- child uses another

That requires:

- provider abstraction in the model adapter layer
- provider-specific auth and timeout handling
- consistent output normalization into the existing `ModelTurnResult` shape

This is feasible, but should come after single-provider multi-model support.

## 7.5 Model Fallbacks

Later, the system may want:

- primary model per agent
- fallback model per agent

Example:

- if the specialist coding model times out, retry once with a fallback

If implemented, fallback should be:

- explicit
- logged
- bounded

It should not silently change providers in a way that makes debugging impossible.

## 8. Prompt And Context Design For Sub-Agents

Sub-agents should not receive the parent’s full transcript by default.

Instead, they should get:

- the task description
- the minimum relevant context
- explicit constraints
- expected output format

For example, a coding sub-agent might receive:

- parent user request summary
- relevant file paths
- current task objective
- tool restrictions
- desired answer format

Why:

- lower token cost
- less confusion
- clearer role boundaries
- better performance

## 8.1 Delegation Brief

Each sub-agent invocation should include a structured delegation brief.

Suggested shape:

- `task_type`
- `goal`
- `constraints`
- `input_context`
- `expected_output`
- `delegated_by_agent_id`
- `delegation_id`

This brief should be stored durably in the `delegations` row and used to seed the child session.

## 8.2 Child Result Contract

Each sub-agent should return structured output, not only free-form text.

Suggested result shape:

- `summary`
- `status`
- `artifacts`
- `recommendations`
- `follow_up_needed`
- `error`

The parent agent can then:

- summarize it to the user
- decide to ask another specialist
- request approval if a risky next action is needed

## 9. Tool And Policy Boundaries

One of the most important implementation requirements is:

- sub-agents must not automatically inherit all tools from the parent

Instead, tool visibility should be resolved per child agent.

This fits well with the current tool binding model:

- [src/tools/registry.py](/src/tools/registry.py)
- [src/policies/service.py](/src/policies/service.py)

## 9.1 Agent-Specific Tool Profiles

Recommended:

- `main-assistant`
  - broad orchestration tools
- `research-agent`
  - retrieval/search tools
- `coding-agent`
  - file and remote-exec tools if approved
- `docs-agent`
  - document-writing tools only

This requires:

- a way to resolve tool profile by `agent_id`
- policy checks that understand both agent role and session context

## 9.2 Approval Scope Must Stay Exact

Current approvals are already exact-match scoped by:

- session
- agent
- resource version
- typed action
- canonical parameter hash

That is a very good foundation.

For sub-agents, it becomes even more important:

- the parent’s approval should not automatically mean the child has blanket approval

A sub-agent should execute an approval-gated action only if:

- the approval explicitly applies to that `agent_id`
- or a future spec defines safe delegated approval propagation rules

Recommended initial rule:

- no automatic approval inheritance from parent to child

That is much safer.

## 9.3 Remote Execution For Sub-Agents

If a child agent uses remote execution:

- it should go through the same `remote_exec` capability
- it should have its own `agent_id`
- sandbox resolution should include that child `agent_id`

This works naturally with current code:

- [src/tools/remote_exec.py](/src/tools/remote_exec.py)
- [src/execution/runtime.py](/src/execution/runtime.py)
- [src/sandbox/service.py](/src/sandbox/service.py)

In fact, sub-agents make agent-specific sandboxing more valuable, not less.

## 10. API And Service Additions

The user-facing entrypoint can still remain:

- `POST /inbound/message`

But the system will need new internal services and likely new read APIs.

## 10.1 Internal Services

Recommended new service:

- `DelegationService`

Likely methods:

- `create_delegation(...)`
- `create_child_session(...)`
- `queue_child_run(...)`
- `record_child_result(...)`
- `fail_delegation(...)`
- `cancel_delegation(...)`
- `list_child_sessions(...)`

## 10.2 New Read APIs

Recommended operator/developer APIs:

- `GET /sessions/{session_id}/delegations`
- `GET /sessions/{session_id}/delegations/{delegation_id}`
- `GET /sessions/{session_id}/delegations/{delegation_id}/messages`
- `GET /sessions/{session_id}/children`
- `GET /delegations/{delegation_id}/runs`

Optional control APIs:

- `POST /delegations/{delegation_id}/cancel`
- `POST /delegations/{delegation_id}/retry`

These are especially important for debugging and demos.

## 11. Context Continuity And Memory

Sub-agents create a continuity problem if their transcripts are treated carelessly.

The system must answer:

- what child history belongs only to the child?
- what child result should be promoted into parent context?
- what should be summarized?

Recommended rule:

- child transcript stays in child session
- parent session gets only promoted summary/result artifacts

This avoids flooding the parent session with every internal step the specialist took.

The current continuity model already supports the right pattern:

- canonical transcript first
- additive summary and manifest artifacts

Sub-agents should extend that, not replace it.

## 12. Observability And Diagnostics

Sub-agent support should be highly inspectable.

At minimum, diagnostics should answer:

- which parent session spawned the child?
- which agent was used?
- what model profile was used?
- what tools were bound?
- when did the child start and finish?
- what was returned to the parent?
- did it fail, retry, or time out?

Recommended diagnostics additions:

- delegation list endpoint
- delegation detail endpoint
- child-session continuity endpoint
- child-run diagnostics filtering by `parent_session_id` or `delegation_id`

Operational fields to persist:

- `trace_id` carried from parent to child
- `parent_execution_run_id`
- `delegation_id`
- `parent_agent_id`
- `child_agent_id`
- `model_profile_key`

## 13. Failure, Retry, And Cancellation

Sub-agents add more coordination failure modes.

The system must define:

- what if child run fails?
- what if child times out?
- what if parent is cancelled?
- what if parent session receives a new user message while child is still running?

Recommended initial rules:

- child failure is persisted on `delegations`
- parent receives a structured failure result, not silent disappearance
- cancellation of parent can optionally cascade to child
- new parent user messages do not erase child state

Retries should be:

- durable
- bounded
- visible in diagnostics

## 14. Testing Requirements

Sub-agents should not be added without a serious test plan.

Needed tests:

- child session creation and deterministic linking
- delegation record creation
- child run queueing
- agent-specific model resolution
- agent-specific tool binding
- parent/child trace correlation
- no accidental approval inheritance
- child failure and retry behavior
- cancellation behavior
- continuity behavior with parent and child transcripts
- diagnostics visibility for delegation state

Especially important:

- prove that child agents do not bypass policy
- prove that remote execution still requires exact approval in child context

## 15. Recommended Implementation Phases

## Phase 1: Durable Delegation Skeleton

Implement:

- session linking
- `delegations` table
- `DelegationService`
- child-session creation
- child-run queueing

Goal:

- durable orchestration skeleton without changing many tools yet

## Phase 2: Agent Profiles And Model Profiles

Implement:

- `agent_profiles`
- `model_profiles`
- agent-to-model resolution
- same-model and different-model support

Goal:

- multiple agent identities with explicit LLM selection

## Phase 3: Delegation Tool And Parent/Child Result Contract

Implement:

- typed delegation tool
- delegation brief format
- child result format
- parent summary behavior

Goal:

- natural bounded delegation flow

## Phase 4: Policy, Tool, And Approval Hardening

Implement:

- agent-specific tool profiles
- exact approval handling for child agents
- remote-exec-safe child behavior

Goal:

- safe specialist execution

## Phase 5: Diagnostics And Operator Surfaces

Implement:

- delegation diagnostics
- child-session inspection
- failure and retry visibility

Goal:

- support production debugging

## 16. Files Most Likely To Change

Likely existing files to update:

- [src/db/models.py](/src/db/models.py)
- [src/sessions/repository.py](/src/sessions/repository.py)
- [src/sessions/service.py](/src/sessions/service.py)
- [src/jobs/repository.py](/src/jobs/repository.py)
- [src/jobs/service.py](/src/jobs/service.py)
- [src/graphs/state.py](/src/graphs/state.py)
- [src/graphs/nodes.py](/src/graphs/nodes.py)
- [src/providers/models.py](/src/providers/models.py)
- [src/policies/service.py](/src/policies/service.py)
- [src/context/service.py](/src/context/service.py)
- [src/observability/diagnostics.py](/src/observability/diagnostics.py)
- [apps/gateway/deps.py](/apps/gateway/deps.py)
- [README.md](/README.md)

Likely new files:

- `src/delegation/service.py`
- `src/delegation/repository.py`
- `src/delegation/models.py` or equivalent additions to DB models
- specialist graph builder modules
- agent/model profile resolution helpers

## 17. What Success Looks Like

When sub-agent support is complete, the system should be able to do something like this:

1. User asks a broad question or gives a complex task.
2. Main assistant decides a specialist is needed.
3. Main assistant delegates through a typed tool.
4. A child session and child run are created durably.
5. The specialist agent uses:
   - its own model
   - its own tool profile
   - its own context boundary
6. The child result comes back as structured output.
7. The parent assistant explains the result to the user.
8. Operators can inspect every step through durable records and diagnostics.

And if needed:

- one child agent could use the same LLM as the parent
- another could use a different model
- another could use a different provider

All without losing:

- durability
- replayability
- approvals
- auditability

## 18. Final Summary

To support sub-agents correctly, `python-claw` needs more than “spawn another model.”

It needs:

- durable parent/child session structure
- delegation records
- child runs on the existing queue
- agent-specific tools and policy
- agent-specific model routing
- explicit result contracts
- diagnostics and failure handling

The good news is that the current project already has the right bones for this.

The most important design rule is:

- sub-agents should be first-class durable participants in the system, not hidden prompt tricks

If that rule is preserved, the project can support specialist agents using the same or different LLMs while still staying consistent with the current gateway-first and audit-first architecture.
