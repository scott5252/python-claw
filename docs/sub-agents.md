# Sub-Agents In `python-claw`

## Purpose

This document explains how sub-agents should be added to `python-claw` after the core application is complete, how that model aligns with OpenClaw-style delegation, whether sub-agents are already part of the committed project scope, and which API calls would start or support that process.

## Short Answer

`python-claw` is architecturally compatible with sub-agents, but sub-agent orchestration is **not currently a committed core feature** in the active project specs.

The current design already supports the foundations needed for it:

- gateway-first execution
- durable sessions and append-only transcripts
- LangGraph orchestration
- typed tool registration
- policy and approval boundaries
- context and memory services

However, the spec documents explicitly list **multi-agent delegation** as a non-goal in the currently defined delivery slices. That means sub-agents should be treated as a **future feature that must be added to the project specs before implementation**.

## What "Sub-Agents" Means Here

In this project, a sub-agent should mean a bounded specialist runtime that is started by the primary assistant to complete a narrow task such as:

- coding
- research
- data cleanup
- document drafting
- planning
- operations work

The main assistant remains the user-facing coordinator. The sub-agent is a worker with:

- a clear task
- a limited context window
- a typed capability set
- its own run record
- its own transcript or child-session history

This is the safest model for an OpenClaw-style system because it preserves the same core rule used elsewhere in the architecture: the gateway and session system remain the source of truth, not an untracked internal model chain.

## How This Relates To OpenClaw

The project documents already point to the OpenClaw concepts that make sub-agents possible:

- agent-to-agent messaging as an explicit allowed capability
- spawned sessions or specialist subgraphs with smaller local contexts
- LangGraph as the control layer for future multi-agent extensions

That means the right interpretation is not "the model freely spawns hidden assistants." The better OpenClaw-style interpretation is:

1. A user request enters through the gateway.
2. The primary assistant decides delegation is needed.
3. Delegation is only allowed through a typed, policy-controlled capability.
4. The system creates a child run or child session for the specialist agent.
5. The specialist agent works inside bounded context and allowed tools.
6. Results come back to the primary assistant.
7. Any durable outcome is written back through the normal transcript and memory pipeline.

This keeps delegation observable, replayable, and auditable.

## Is This Already A Core Feature?

No. It is better described as a **supported future extension** than a current core feature.

### What the current docs already support

The current architecture already supports the prerequisites:

- the gateway is the single execution entrypoint
- sessions are first-class and durable
- the graph runtime is separate from transport
- tools are exposed through stable registry contracts
- background and automated work should re-enter the same gateway lifecycle

These are the right building blocks for sub-agents.

### What the current specs do not yet commit to

The spec program explicitly marks `multi-agent delegation` as out of scope in the earlier feature slices. Because of that, sub-agent support should be added as a **new spec** or a clearly named extension to a later spec before implementation starts.

## Recommendation For The Spec Program

Add a new future spec such as:

`Spec 009 — Sub-Agent Delegation And Child Session Orchestration`

That spec should define:

- when the main agent may delegate
- whether delegation requires approval
- how child agents are identified
- how child sessions are created and linked to parent sessions
- which tools each specialist agent may use
- how results are returned to the parent agent
- what gets written to the canonical transcript
- how durable memory is updated
- concurrency, retry, timeout, and cancellation behavior
- audit and observability requirements

Without that spec work, implementation would be possible, but not well-governed.

## Recommended Runtime Design

The safest implementation is to add sub-agents as a gateway-managed delegation feature, not as direct model freedom.

### 1. Delegation trigger

The primary assistant graph decides that a task should be delegated. It does that by calling a typed tool such as:

- `delegate_to_agent`
- `start_specialist_task`
- `spawn_sub_agent`

This should be a registry-controlled tool, not a raw model instruction.

### 2. Delegation policy check

Before a child agent is started, the policy layer should validate:

- parent agent identity
- target agent type
- allowed task category
- tool/resource permissions
- approval requirements
- max depth of delegation
- max concurrent child runs

### 3. Child session creation

The gateway or session service should create a child session linked to the parent session. Suggested data additions:

- `parent_session_id`
- `delegation_id`
- `delegated_by_agent_id`
- `delegation_status`
- `delegation_purpose`
- `delegation_depth`

This child session should have its own append-only transcript.

### 4. Child execution

The child agent runs through the same core lifecycle as a normal turn:

- session resolution
- context assembly
- policy-aware tool binding
- graph execution
- transcript persistence
- after-turn jobs

This is important. A sub-agent should not bypass the standard gateway, memory, or audit flow.

### 5. Result return

When the child run completes, the result should be returned as structured output to the parent agent, for example:

- final summary
- artifacts produced
- confidence or status
- tool actions taken
- follow-up needs

The parent agent then decides what to tell the user.

### 6. Durable persistence

Only the necessary durable outcomes should be promoted back into:

- the parent transcript
- memory extraction pipelines
- summaries or continuity artifacts

The child transcript should remain available for inspection, but it should not automatically flood the parent context window.

## Should Sub-Agents Be Sessions, Runs, Or Subgraphs?

For this project, the best default is:

- use a **child session** for durable and inspectable specialist work
- use a **specialist graph** for the child agent runtime
- treat each execution as a **run** within that child session

This gives the cleanest separation:

- session = durable continuity boundary
- graph = execution logic
- run = one invocation inside the session

That also aligns best with the rest of the project, which already centers durable sessions and gateway-owned lifecycle control.

## API Calls That Would Initiate Or Support This

The current backend already exposes:

- `POST /inbound/message`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/governance/pending`

Those current read APIs do **not** expose child-agent or delegation state yet.

### Current API That Would Initiate The Process

If sub-agents are added in the recommended way, the main trigger would still begin with the existing user-facing API:

- `POST /inbound/message`

That endpoint already starts the full gateway-managed turn lifecycle. After implementation, a normal inbound user message could cause the main assistant to invoke a delegation tool internally. In other words:

- the user calls `POST /inbound/message`
- the main graph runs
- the graph chooses to delegate
- the system creates and runs a child session or child run

So the **first initiating API call is still `POST /inbound/message`**.

### Internal Service Calls Likely Needed

Inside the application, the following new internal service actions would likely be added:

- `DelegationService.create_child_session(...)`
- `DelegationService.start_child_run(...)`
- `DelegationService.complete_child_run(...)`
- `DelegationService.fail_child_run(...)`
- `DelegationService.cancel_child_run(...)`

These could be implemented as service-layer methods before being exposed as external APIs.

### Recommended New External APIs

The project does not strictly need a public API to let the model spawn a sub-agent, because the main graph can trigger delegation internally after `POST /inbound/message`.

Even so, the system will benefit from read and control APIs such as:

- `GET /sessions/{session_id}/delegations`
- `GET /sessions/{session_id}/delegations/{delegation_id}`
- `GET /sessions/{session_id}/delegations/{delegation_id}/messages`
- `POST /sessions/{session_id}/delegations/{delegation_id}/cancel`
- `POST /sessions/{session_id}/delegations/{delegation_id}/retry`

Optional admin or power-user APIs could include:

- `POST /sessions/{session_id}/delegations`
- `POST /agents/{agent_id}/runs`

Those would be useful only if you want explicit human-initiated delegation outside the normal assistant decision flow.

## API Flow Examples

### Normal user-driven delegation

1. Client sends `POST /inbound/message`.
2. Gateway persists the inbound turn.
3. Main assistant graph evaluates the request.
4. Main assistant calls a typed delegation tool.
5. Delegation service creates a child session and child run.
6. Specialist graph executes in that child session.
7. Result is written to child transcript and summarized back to parent.
8. Parent assistant appends the final user-facing response.

### Explicit UI inspection flow

1. Client sends `POST /inbound/message`.
2. UI receives the parent `session_id`.
3. UI calls `GET /sessions/{session_id}/delegations`.
4. UI opens a child delegation record.
5. UI calls `GET /sessions/{session_id}/delegations/{delegation_id}/messages`.

## What Needs To Be Added To The Data Model

At minimum, sub-agents likely need new durable records such as:

- `delegations`
- `delegation_runs`
- `delegation_events`

Suggested fields include:

- `delegation_id`
- `parent_session_id`
- `child_session_id`
- `parent_message_id`
- `parent_agent_id`
- `child_agent_id`
- `status`
- `task_type`
- `task_payload_json`
- `result_summary`
- `created_at`
- `started_at`
- `completed_at`
- `failed_at`

This makes delegation inspectable and testable.

## Policy And Safety Requirements

Sub-agents should never be unrestricted. The project should preserve the same approval and governance style used elsewhere.

Required controls should include:

- explicit allowlists for which agents can delegate to which agents
- maximum delegation depth, ideally starting at `1`
- per-agent tool restrictions
- approval gates for dangerous capabilities
- timeout and cancellation rules
- transcript and audit logging for every delegation event
- bounded context transfer from parent to child

If remote execution is later involved, the child agent should still use the same policy and node-execution controls already planned elsewhere in the architecture.

## Context And Memory Behavior

Sub-agents should not inherit the entire parent transcript by default.

Instead, the parent should pass a bounded context packet such as:

- task objective
- relevant recent messages
- selected memory items
- allowed tools
- completion criteria

After completion:

- the child transcript remains durable in its own session
- the parent receives a compact result
- durable memory updates are derived from transcript and artifacts, not copied blindly

This matches the existing project direction that memory is reconstructable durable state, not hidden model state.

## Testing Requirements For A Future Spec

Any sub-agent implementation should prove:

- delegation only occurs through a typed capability
- child sessions are created deterministically and linked correctly
- parent and child transcripts remain append-only
- failed child runs do not corrupt the parent session
- retries are idempotent
- child context is bounded
- governance rules are enforced before privileged child tools execute
- cancellation and timeout behavior are observable

## Final Conclusion

Sub-agents fit the architecture of `python-claw` very well, and they align with the OpenClaw-style ideas already referenced in the project documents. The current system already has the right structural foundations for them.

But sub-agent orchestration is **not yet part of the committed core feature set**. The present specs explicitly defer multi-agent delegation, so this should be added as a future spec before implementation.

When implemented, the normal initiating API call should still be `POST /inbound/message`, with delegation happening inside the gateway-managed runtime through a typed tool and a new delegation service. Additional read and control APIs should then be added to inspect, retry, and cancel child-agent work.
