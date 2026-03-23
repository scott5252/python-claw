# Tokens And Model Runtime In `python-claw`

## Purpose

This document explains:

1. how models should be set up and changed once the solution is running
2. how the system should monitor token usage and model-driven execution
3. how the system should allow expensive or extensive token-use processes to be shut down

It also identifies which parts are already supported by the current design and which parts need to be added to the project specs before implementation.

## Short Answer

The current design already includes some of the foundation for this topic:

- a model-provider abstraction
- a gateway-owned runtime
- token-budget-aware context assembly
- append-only transcript persistence
- observability as a planned feature area
- `token_count` as a planned transcript field

But the current design does **not yet fully specify**:

- runtime model switching and model routing rules
- complete token accounting for every run and tool-heavy turn
- operator or user controls to stop expensive runs in progress
- hard token budgets, spend budgets, or automatic cutoffs

So this area is **partially present in the architecture**, but it still needs explicit spec work before it should be considered complete.

## 1. How Models Will Be Set Up And Changed Once The Solution Is Running

## What The Current Design Already Supports

The architecture already assumes a model-provider layer rather than hard-coding the model directly into the gateway. The documents describe:

- `src/providers/models.py` as the provider boundary
- graph execution calling a model adapter rather than mixing provider details into transport
- settings-driven default model selection
- pluggable providers as part of the broader capability architecture

That is the right starting point because it means the application can separate:

- gateway execution
- graph orchestration
- model-provider selection
- policy and audit behavior

## Recommended Runtime Model Setup

Once the solution is running, model setup should work as a layered configuration system.

### Base model configuration

The application should have a default model profile in configuration, for example:

- default provider
- default model name
- temperature or reasoning configuration
- max output token settings
- timeout settings
- retry policy

This is the baseline for all sessions unless a higher-priority rule overrides it.

### Per-agent model configuration

Each agent should be able to declare its own model profile, such as:

- general assistant model
- coding model
- summarization model
- retrieval-compression model
- low-cost fallback model

This matters because different tasks should not always consume the same model or token budget.

### Per-workflow or per-task overrides

Specific operations should be allowed to choose a different model at runtime, such as:

- summary generation
- compaction
- memory extraction
- sub-agent specialist work
- tool planning versus final response generation

This should happen through explicit routing rules, not ad hoc prompt text.

### Runtime change behavior

Once the application is live, model changes should be applied through controlled configuration or admin workflows, not direct code edits. A strong design would allow:

- changing the default model for new runs
- rotating to a backup model if a provider fails
- assigning cheaper models to background work
- limiting premium models to approved workflows

The important rule is that model changes should affect **future runs**, while preserving clear audit records about which provider and model handled each completed run.

## What Is Missing From The Current Design

The current docs do not fully define:

- a durable `model_profiles` or equivalent configuration model
- runtime admin APIs for changing model assignments
- model routing rules by agent, workflow, or capability
- provider failover tied to token or cost policy
- per-run persistence of provider name, model name, and token totals

## Specs Needed For Full Model Runtime Support

This should be added through either:

- an extension to `Spec 2 — LangGraph runtime and typed tool registry`
- an extension to `Spec 8 — Observability, auth failover, presence, and operational hardening`

Or, more cleanly, a dedicated new spec such as:

`Spec 009 — Model Profiles, Token Accounting, And Run Controls`

That spec should define:

- model profile data structures
- provider and model selection precedence
- runtime reload or configuration change behavior
- per-agent and per-workflow model routing
- audit fields for provider and model identity
- fallback and failover behavior

## 2. How It Will Monitor Token Usage And Model Execution

## What The Current Design Already Supports

The current documents already support several important parts of token monitoring:

- context assembly is explicitly token-budget aware
- compaction is triggered when context limits are approached
- transcript events include a planned `token_count` field
- observability specs already require metrics, logs, traces, and operator diagnostics
- the architecture expects recovery and stuck-run diagnostics

This means the design already recognizes that token usage is an operational concern, not just an implementation detail.

## Recommended Token Monitoring Model

Token monitoring should happen at three levels.

### 1. Request and run level

For every model turn, the system should record:

- provider
- model
- session id
- run id
- prompt tokens
- completion tokens
- total tokens
- cached tokens if supported by provider
- request start time
- request end time
- latency
- finish reason
- failure reason

This is the minimum needed to understand runtime cost and behavior.

### 2. Session and workflow level

The system should aggregate usage by:

- session
- agent
- workflow type
- background job kind
- channel
- day or billing window

This makes it possible to detect patterns such as:

- one session consuming abnormal token volume
- one background job producing runaway cost
- one agent using a more expensive model than expected

### 3. Operational alerting level

The observability layer should emit alerts for cases like:

- repeated turns exceeding budget thresholds
- compaction happening too often
- summary jobs with very high token usage
- sudden spikes in token consumption per minute
- repeated provider timeouts or quota failures
- sessions that never converge and keep retrying

## Monitoring "Code" And Execution

Your request mentions monitoring token usage and code. In this architecture, that should be interpreted as monitoring the execution path around model-driven work, especially when the assistant is performing coding or tool-heavy tasks.

That should include:

- which graph nodes executed
- which tools were called
- whether a tool call expanded context size significantly
- whether code-generation or coding workflows are consuming abnormal tokens
- whether retries or loops are increasing token usage unexpectedly

This is less about reading source code directly and more about monitoring the runtime behavior of code-related agent tasks.

## Recommended Data Additions

To make monitoring real, the system should persist either a `runs` table or an equivalent run-event model with fields such as:

- `run_id`
- `session_id`
- `agent_id`
- `provider_name`
- `model_name`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `status`
- `started_at`
- `completed_at`
- `failure_kind`
- `trigger_type`

If the project wants richer diagnostics, also add:

- `run_steps`
- `provider_attempts`
- `token_budget_events`

## Current Spec Coverage

This topic is only partially covered today.

- `Spec 4` helps with token budgeting inside context continuity.
- `Spec 8` helps with metrics, logs, traces, and diagnostics.

But neither one fully defines end-to-end token accounting.

## Specs Needed For Full Token Monitoring

This should be added by either:

- extending `Spec 4` to define token-budget accounting inside context assembly
- extending `Spec 8` to define token metrics, alerts, and diagnostics

Or by using the dedicated new spec described earlier:

`Spec 009 — Model Profiles, Token Accounting, And Run Controls`

That spec should explicitly require:

- per-run token usage capture
- per-session and per-agent aggregation
- metrics and alerts for abnormal token consumption
- admin read APIs for usage inspection
- audit retention rules

## 3. How It Will Allow Extensive Token Use Processes To Be Shut Down

## What The Current Design Already Supports

The current design already gives some indirect support for this:

- the gateway owns execution entry
- the graph runtime is centralized
- async execution and stuck-run diagnostics are planned
- observability and admin diagnostics are planned
- the architecture already acknowledges timeout, quota, and provider-failure handling in places

These are useful building blocks, but they do **not** yet equal a full shutdown or kill-switch feature.

## What Is Missing Right Now

The current docs do not yet fully define:

- run cancellation semantics
- user-triggered cancellation APIs
- operator kill-switch APIs
- token-spend threshold enforcement
- per-run maximum token ceilings
- automatic abort behavior for loops or repeated retries
- queue cancellation for background model work

So this feature is **not yet fully in the design**.

## Recommended Shutdown Model

There should be three shutdown layers.

### 1. Soft limits

Before a run becomes expensive, the system should prevent runaway growth using:

- context token budgets
- per-turn max output tokens
- max tool-loop count
- max retry count
- model timeout settings
- per-session token ceilings over a rolling window

These reduce the chance that a hard kill is needed.

### 2. Automatic abort rules

The runtime should automatically stop a run when conditions are met, such as:

- projected token usage exceeds the policy limit
- compaction fails and no bounded context can be assembled
- the run exceeds timeout
- repeated provider retries exceed limit
- tool loops exceed safe iteration count
- daily or session token quota is exhausted

When this happens, the system should persist a clear terminal state such as:

- `cancelled`
- `quota_exceeded`
- `budget_exceeded`
- `timed_out`

### 3. Manual shutdown controls

Operators, and optionally users, should be able to stop work in progress through explicit APIs. Recommended APIs include:

- `POST /runs/{run_id}/cancel`
- `POST /sessions/{session_id}/cancel-active-run`
- `POST /admin/runs/{run_id}/terminate`

For background or scheduled work:

- `POST /jobs/{job_id}/cancel`

For emergency cost control:

- `POST /admin/runtime/pause-model-execution`
- `POST /admin/runtime/resume-model-execution`

These controls should be policy-gated and audited.

## How Shutdown Should Work Internally

A safe internal design would include:

- a durable run state machine
- cooperative cancellation checks between graph nodes
- cancellation flags stored in durable state or fast shared state
- provider request timeouts
- queue-worker support for cancelling queued or in-flight work

The runtime should check for cancellation:

- before model invocation
- after each tool execution
- before retrying a failed provider call
- before background continuation steps

## Specs Needed For Shutdown Controls

This feature needs explicit spec coverage. The cleanest options are:

- extend `Spec 5 — Async execution, scheduler re-entry, and concurrency lanes`
- extend `Spec 8 — Observability, auth failover, presence, and operational hardening`

Or include it in the dedicated future spec:

`Spec 009 — Model Profiles, Token Accounting, And Run Controls`

That spec should define:

- run lifecycle states
- cancellation and termination semantics
- API contracts for cancelling active runs
- automatic abort thresholds
- queue and worker cancellation behavior
- audit logging for stop actions

## Recommended API Summary

If this capability is implemented cleanly, the API surface should likely include:

- existing trigger: `POST /inbound/message`
- read usage: `GET /sessions/{session_id}/usage`
- read run history: `GET /sessions/{session_id}/runs`
- read run detail: `GET /runs/{run_id}`
- cancel run: `POST /runs/{run_id}/cancel`
- cancel active session work: `POST /sessions/{session_id}/cancel-active-run`
- operator pause: `POST /admin/runtime/pause-model-execution`
- operator resume: `POST /admin/runtime/resume-model-execution`

The current project does not expose these token or run-control APIs yet.

## Final Conclusion

The current `python-claw` design already has the right architectural base for model management and token governance because it includes a provider boundary, token-budget-aware context assembly, gateway-owned execution, and an observability roadmap.

But the requested features are only **partially covered** today.

- model setup exists in basic form, but runtime model switching is not fully specified
- token awareness exists, but full token accounting and usage APIs are not yet specified
- shutdown control is not yet fully designed and needs explicit run-control semantics

To implement this properly, the project should add a new spec focused on model profiles, token accounting, and run controls, or explicitly extend Specs 2, 4, 5, and 8 so these behaviors become part of the committed delivery plan.
