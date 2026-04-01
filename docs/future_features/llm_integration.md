# LLM Integration

This document explains what would need to be implemented in `python-claw` to support a real LLM-driven chat experience, especially for turning normal user language into safe tool usage such as outbound messaging and remote execution.

The goal is not to replace the current architecture. The goal is to add an LLM to the existing gateway-first, approval-aware, worker-owned design.

## 1. Current State

Today, the project already has:

- durable session and message persistence
- async execution runs
- policy-aware tool binding
- approval-gated capabilities
- outbound delivery
- remote execution runtime and node runner
- diagnostics and auditability

What it does not yet have is a real LLM-driven conversational decision layer.

Right now, the default model adapter is rule-based:

- [src/providers/models.py](/src/providers/models.py)

It only understands a few hard-coded patterns:

- `echo ...`
- `send ...`
- otherwise return `Received: <text>`

That means the backend execution machinery exists, but the system does not yet understand natural user requests like:

- “Can you let the customer know the repair is finished?”
- “Check the workspace and tell me what files are there.”
- “Run a safe echo test on the node runner.”

## 2. What LLM Integration Needs To Achieve

A real LLM integration in this project would need to do five jobs well:

1. Understand normal user language
2. Decide whether to answer directly or use a tool
3. Generate structured tool requests that fit the existing contracts
4. Respect approvals and policy boundaries
5. Return useful, user-friendly responses based on tool outcomes

The key principle is:

- the LLM should decide and translate
- the existing backend should still enforce

In other words:

- the LLM is the interpreter
- the repositories, policy layer, approval records, runtime, dispatcher, and node runner remain the security and durability boundaries

## 3. High-Level Architecture Change

The smallest correct architecture change is:

1. Replace or extend the current rule-based model adapter with a real provider-backed LLM adapter.
2. Keep using the existing graph/runtime flow in:
   - [src/graphs/assistant_graph.py](/src/graphs/assistant_graph.py)
   - [src/graphs/nodes.py](/src/graphs/nodes.py)
3. Keep using the existing tool registry and policy service.
4. Keep using the existing approval and remote execution contracts.

That is important because this project already has strong boundaries:

- tool binding is already separate from transport
- remote execution is already separate from the gateway process
- approval state is already durable

The LLM should plug into those boundaries, not bypass them.

## 4. Main Areas That Need To Be Implemented

## 4.1 Provider-Backed Model Adapter

The first major addition is a real implementation of `ModelAdapter`.

Current interface:

- [src/providers/models.py](/src/providers/models.py)

What needs to be added:

- a new class such as `OpenAIModelAdapter` or similar
- provider configuration in settings
- model request formatting
- model response parsing
- retry, timeout, and failure handling

This adapter would need to:

- receive `AssistantState`
- receive the list of `available_tools`
- build an LLM prompt from session context, policy context, and instructions
- ask the LLM to either:
  - return plain assistant text
  - request one or more tool calls with structured arguments

Expected output shape must still map to the existing runtime contract:

- `ModelTurnResult`
- `ToolRequest`

That is critical because the graph already expects those objects.

## 4.2 Prompting And Tool-Selection Instructions

The current system already renders prompts through:

- [src/graphs/prompts.py](/src/graphs/prompts.py)

An LLM integration would need a much stronger prompt contract that teaches the model:

- what tools exist
- when to use them
- when not to use them
- what approvals mean
- how to explain approval requests to the user
- how to summarize tool results safely

This prompt layer must explain at least:

- normal answer-only behavior
- outbound messaging behavior
- approval-required behavior
- remote execution behavior
- refusal behavior

For remote execution specifically, the prompt should teach:

- do not invent raw shell commands casually
- use remote execution only when it is clearly relevant
- do not claim execution happened unless a tool result confirms it
- if approval is required, explain that clearly

Without prompt design, an LLM may hallucinate:

- nonexistent tool capability
- nonexistent approval
- execution success without an actual result

## 4.3 Structured Tool Calling

The LLM must not return free-form text and expect the backend to guess what it meant.

Instead, it should produce structured tool requests that map to the existing tool registry:

- [src/tools/registry.py](/src/tools/registry.py)
- [src/tools/local_safe.py](/src/tools/local_safe.py)
- [src/tools/messaging.py](/src/tools/messaging.py)
- [src/tools/remote_exec.py](/src/tools/remote_exec.py)

That means the LLM integration needs:

- a schema for each tool’s arguments
- validation of tool-call payloads
- conversion from LLM tool-call output into `ToolRequest`

For example:

- outbound send tool:
  - `{"text": "Hello Maya, your order is ready for pickup."}`
- remote exec tool:
  - `{"text": "hello from demo"}`
  - plus internal fields like `tool_call_id` and `execution_attempt_number` when needed by the runtime

The LLM should not be allowed to produce arbitrary undeclared arguments that bypass typed action controls.

## 4.4 Better Tool Schemas

To make LLM tool use reliable, the tool interfaces likely need stronger schemas than the current loose `dict[str, object]` style.

Recommended additions:

- explicit Pydantic models for tool inputs
- explicit Pydantic models for tool outputs where useful
- JSON schema generation for prompt/tool registration

Why this matters:

- LLMs are much more reliable when the expected tool arguments are precise
- validation errors become easier to explain and recover from
- approval hashing and policy matching work better when parameter shape is stable

This is especially important for `remote_exec`, because exact approval matching depends on canonical parameters.

## 4.5 Intent Classification Beyond Hard-Coded Rules

Right now, turn classification is implemented in:

- [src/policies/service.py](/src/policies/service.py)

It currently uses simple string prefixes like:

- `send `
- `approve `
- `revoke `

That is not enough for natural conversation.

To support LLM-based interaction, one of these patterns needs to be added:

1. Keep `classify_turn()` for administrative control phrases like `approve` and `revoke`, but let the LLM decide most normal tool usage.
2. Add an LLM-assisted intent classification step before tool selection.
3. Use a hybrid approach:
   - deterministic parsing for critical control commands
   - LLM interpretation for normal user requests

The hybrid approach is probably best.

Why:

- approval commands should stay deterministic
- normal conversational requests benefit from LLM interpretation

## 4.6 Approval-Aware Conversation Design

One of the most important missing pieces is how the LLM should behave when a requested action needs approval.

The backend already supports:

- `resource_proposals`
- `resource_versions`
- `resource_approvals`
- `active_resources`
- `governance_transcript_events`

Relevant code:

- [src/sessions/repository.py](/src/sessions/repository.py)
- [src/capabilities/activation.py](/src/capabilities/activation.py)
- [src/graphs/nodes.py](/src/graphs/nodes.py)

What needs to be added is the LLM-side behavior:

- when a user asks for a gated capability, the assistant should not pretend it can execute immediately
- it should ask for approval in a human-friendly way
- once approved, it should know to retry or invite the user to retry

Examples of desired user experience:

- “I can do that, but it requires approval because it sends an external message. I’ve prepared a request for approval.”
- “That command requires remote execution approval. Once approved, I can run it safely.”

The current backend already supports the state changes. The missing piece is conversational fluency around those states.

## 4.7 Remote Execution Request Mapping

This is the specific feature the user has been asking about.

The backend already supports remote execution through:

- [src/tools/remote_exec.py](/src/tools/remote_exec.py)
- [src/execution/runtime.py](/src/execution/runtime.py)
- [apps/node_runner/main.py](/apps/node_runner/main.py)
- [apps/node_runner/policy.py](/apps/node_runner/policy.py)
- [apps/node_runner/executor.py](/apps/node_runner/executor.py)

What is missing is the front-end conversation mapping.

To let a normal user ask for remote execution, the system would need:

1. A remote-exec-capable prompt policy
2. An LLM that recognizes remote execution intent from normal language
3. A safe mapping from user request to approved invocation parameters
4. A good explanation back to the user

Example future flow:

1. User says: “Can you run a quick echo test and show me the result?”
2. LLM decides: this is a `remote_exec` request
3. LLM generates a structured tool request like:
   - capability: `remote_exec`
   - arguments: `{"text": "hello from test"}`
4. Policy layer checks whether exact approval exists
5. If not approved:
   - proposal is created
   - assistant explains approval is required
6. After approval:
   - tool executes
   - node runner returns result
   - assistant explains stdout in human language

That conversational bridge is what does not exist yet.

## 4.8 Provider Configuration And Settings

The settings module would need new fields for LLM integration.

Current settings file:

- [src/config/settings.py](/src/config/settings.py)

Likely additions:

- provider name
- model name
- API key
- timeout
- retry count
- max input tokens
- max output tokens
- temperature
- tool-calling mode toggle
- optional fallback model

Examples:

- `PYTHON_CLAW_LLM_PROVIDER`
- `PYTHON_CLAW_LLM_MODEL`
- `PYTHON_CLAW_LLM_API_KEY`
- `PYTHON_CLAW_LLM_TIMEOUT_SECONDS`
- `PYTHON_CLAW_LLM_MAX_OUTPUT_TOKENS`

Operationally, the gateway or worker should fail clearly when LLM integration is enabled but required provider settings are missing.

## 4.9 Error Handling And Recovery

A real LLM integration introduces a new failure domain:

- provider unavailable
- timeout
- malformed tool call output
- too-large prompt
- model returns invalid JSON/schema

The worker path in:

- [src/jobs/service.py](/src/jobs/service.py)

already has retry and failure handling for runs. The LLM adapter should integrate with that cleanly.

Needed behavior:

- retry transient provider failures
- do not retry deterministic schema failures forever
- classify failures into useful categories
- surface enough detail in diagnostics without leaking secrets

## 4.10 Observability For LLM Calls

Specs 008 already established observability patterns.

Relevant code:

- [src/observability/logging.py](/src/observability/logging.py)
- [src/observability/failures.py](/src/observability/failures.py)
- [src/observability/diagnostics.py](/src/observability/diagnostics.py)

LLM integration should add observability for:

- model request started
- model request completed
- model request failed
- tool-call parse success/failure
- token usage
- latency
- prompt overflow/degraded mode

But it must avoid logging:

- raw secrets
- full unredacted prompts if they contain sensitive material
- raw provider credentials

Ideally, diagnostics should eventually expose bounded LLM execution metadata without storing entire prompts as a new shadow transcript.

## 4.11 Context Window Management

The project already has continuity logic in:

- [src/context/service.py](/src/context/service.py)

This becomes more important with a real LLM.

Why:

- real provider-backed models will have real token limits
- tool outputs and governance state will make prompts larger
- remote execution results may add more text to the conversation

Needed improvements:

- token-aware prompt estimation
- better selection of transcript rows
- eventual summary generation and retrieval integration
- rules for truncating or summarizing tool output safely

Without this, LLM integration will work for short chats but fail badly on long sessions.

## 4.12 Better Result Synthesis

Today, successful tool execution often turns directly into assistant text by simple concatenation.

With an LLM, the system should do a better second pass:

- tool runs
- tool returns structured result
- LLM summarizes the result for the user

Example:

- remote execution stdout: `hello from demo`
- assistant response:
  - “The remote execution completed successfully. The command returned: `hello from demo`.”

This is a user experience improvement, but also a safety improvement:

- the assistant can explain what happened
- the user gets a clear distinction between raw tool output and assistant explanation

## 4.13 Testing Strategy

LLM integration would require a larger testing surface.

Needed tests:

- unit tests for prompt construction
- unit tests for tool-call parsing
- unit tests for provider adapter response handling
- unit tests for invalid tool-call rejection
- integration tests for answer-only turns
- integration tests for approval-required turns
- integration tests for approved outbound messaging
- integration tests for approved remote execution
- failure-mode tests for provider timeout and malformed output

Testing should use:

- deterministic fixtures
- mocked provider responses
- schema validation tests

Production confidence should not depend on manually talking to a live model during tests.

## 4.14 Security Requirements

The most important rule is:

- LLM integration must not weaken existing safety boundaries

That means:

- the LLM must not bypass `PolicyService`
- the LLM must not bypass approval matching
- the LLM must not directly call transports
- the LLM must not directly execute shell commands
- the LLM must not invent that approval already exists

The secure path must remain:

1. user asks
2. LLM interprets
3. runtime generates structured request
4. policy checks execute
5. approval is required when needed
6. tool/runtime executes only if allowed
7. durable audit state is written

The LLM can help choose actions. It must not become the action authority.

## 5. Concrete Implementation Plan

This is a practical, incremental way to build the feature.

### Phase 1: Add a real LLM adapter without changing approvals

Implement:

- provider-backed `ModelAdapter`
- settings for provider configuration
- prompt construction from `AssistantState`
- plain answer-only response path

Goal:

- replace `Received: <text>` with normal conversational responses

### Phase 2: Add structured tool calling for existing simple tools

Implement:

- LLM-generated tool calls for `echo_text`
- LLM-generated tool calls for `send_message`
- schema validation for tool arguments

Goal:

- prove the LLM can reliably choose between answer-only and tool use

### Phase 3: Make approval-aware tool requests conversational

Implement:

- prompt instructions for approval-required actions
- good assistant explanations for pending approvals
- retry flow after approval

Goal:

- natural user experience around approvals without changing the existing governance tables

### Phase 4: Add normal-language remote execution requests

Implement:

- prompt/tool support for `remote_exec`
- schema for remote-exec arguments
- user-facing explanation before approval
- user-facing explanation after execution

Goal:

- let a user ask for a safe remote action in normal language

### Phase 5: Improve long-session context and observability

Implement:

- token-aware context assembly
- better summary use
- richer LLM telemetry
- bounded diagnostic visibility for LLM activity

Goal:

- make the feature reliable in production-like sessions

## 6. Files Most Likely To Change

The main files likely to be updated are:

- [src/providers/models.py](/src/providers/models.py)
- [src/config/settings.py](/src/config/settings.py)
- [src/graphs/prompts.py](/src/graphs/prompts.py)
- [src/graphs/nodes.py](/src/graphs/nodes.py)
- [src/policies/service.py](/src/policies/service.py)
- [src/tools/registry.py](/src/tools/registry.py)
- [src/tools/remote_exec.py](/src/tools/remote_exec.py)
- [src/tools/messaging.py](/src/tools/messaging.py)
- [src/context/service.py](/src/context/service.py)
- [src/observability/logging.py](/src/observability/logging.py)
- [src/observability/diagnostics.py](/src/observability/diagnostics.py)
- [apps/gateway/deps.py](/apps/gateway/deps.py)

Additional new files are likely:

- a provider-specific adapter module
- tool input/output schema module
- LLM prompt templates or prompt-builder helpers
- provider client wrappers

## 7. What Success Looks Like

When LLM integration is complete, a normal user should be able to say things like:

- “Tell Maya her order is ready for pickup.”
- “Check the workspace and tell me what files are there.”
- “Run a safe echo test for me.”

And the system should:

1. understand the request naturally
2. choose the right action
3. require approval when appropriate
4. execute only through existing safe backend paths
5. explain the result clearly
6. leave behind durable transcript, approval, execution, and diagnostic records

That is the target state.

## 8. Final Summary

The backend foundation for LLM integration is already mostly here.

What is missing is the conversational layer:

- a real provider-backed model adapter
- strong prompts
- structured tool calling
- better schemas
- approval-aware conversation behavior
- natural-language mapping for remote execution

The most important design rule is simple:

- add LLM intelligence without removing backend enforcement

If that rule is preserved, `python-claw` can evolve from a rule-based platform skeleton into a real conversational assistant without losing the safety and auditability already built into the project.
