# PR Review Guide: Spec 002 Runtime Tools

## Why this file exists
This guide helps a developer review the implementation of Spec 002 without reverse-engineering the runtime from scratch. The goal is to make it easy to answer four questions:

- what changed in this spec
- where those changes live in the codebase
- how a tool-enabled turn now executes
- how to run and test the feature locally

## What Spec 002 adds
Spec 002 turns the project from a session-only gateway into a gateway-owned runtime that can execute one assistant turn after an inbound user message is stored.

At a high level, the new behavior is:

1. The gateway still accepts and deduplicates the inbound message.
2. The user message is appended to the session transcript.
3. The gateway-owned `SessionService` invokes a single-turn assistant graph.
4. The graph assembles typed runtime state from persisted conversation history.
5. A model adapter returns a typed `ModelTurnResult`.
6. The runtime binds only policy-allowed tools for the current turn.
7. Tool proposals, outbound intents, tool results, and audit events are recorded append-only.
8. The runtime appends the final assistant message to the transcript.

The important architectural boundary is unchanged: HTTP adapters do not call tools or graph nodes directly. The gateway service owns orchestration.

## Current status in this workspace
The implementation for this spec is present in the workspace, including:

- new graph/runtime modules under `src/graphs/`
- a typed tool registry under `src/tools/`
- policy, model, and audit support modules
- additive persistence for `session_artifacts` and `tool_audit_events`
- integration and unit tests for the runtime paths

There are also unrelated local edits in the worktree. Review this spec by focusing on the runtime, persistence, and tests listed below rather than assuming every modified file belongs to the same change set.

## Best review order
Read in this order:

1. [`spec.md`](./spec.md)
2. [`plan.md`](./plan.md)
3. [`tasks.md`](./tasks.md)
4. [`src/sessions/service.py`](../../src/sessions/service.py)
5. [`src/graphs/state.py`](../../src/graphs/state.py)
6. [`src/graphs/nodes.py`](../../src/graphs/nodes.py)
7. [`src/graphs/assistant_graph.py`](../../src/graphs/assistant_graph.py)
8. [`src/tools/registry.py`](../../src/tools/registry.py)
9. [`src/tools/local_safe.py`](../../src/tools/local_safe.py)
10. [`src/tools/messaging.py`](../../src/tools/messaging.py)
11. [`src/providers/models.py`](../../src/providers/models.py)
12. [`src/policies/service.py`](../../src/policies/service.py)
13. [`src/observability/audit.py`](../../src/observability/audit.py)
14. [`src/sessions/repository.py`](../../src/sessions/repository.py)
15. [`src/db/models.py`](../../src/db/models.py)
16. [`migrations/versions/20260322_002_runtime_tools.py`](../../migrations/versions/20260322_002_runtime_tools.py)
17. runtime-focused tests in `tests/`

Why this order works:

- start with the orchestration entry point
- then read the typed graph contracts and nodes
- then inspect tool binding and execution
- finish with persistence and proof via tests

## Spec-to-code map

| Spec area | Main files |
| --- | --- |
| Gateway-owned runtime entry | `src/sessions/service.py`, `apps/gateway/deps.py` |
| Typed single-turn graph state | `src/graphs/state.py` |
| Graph assembly and execution | `src/graphs/nodes.py`, `src/graphs/assistant_graph.py` |
| Provider-agnostic turn result | `src/providers/models.py` |
| Policy-aware tool binding | `src/tools/registry.py`, `src/policies/service.py` |
| Safe local tool | `src/tools/local_safe.py` |
| Runtime-owned outbound intent tool | `src/tools/messaging.py` |
| Append-only runtime artifact storage | `src/sessions/repository.py`, `src/db/models.py` |
| Tool audit sink | `src/observability/audit.py`, `src/db/models.py` |
| Database migration | `migrations/versions/20260322_002_runtime_tools.py` |
| Evidence that behavior works | `tests/test_runtime.py`, `tests/test_repository.py`, `tests/test_api.py`, `tests/test_integration.py` |

## The most important invariants to review

### 1. The gateway still owns orchestration
Look at [`src/sessions/service.py`](../../src/sessions/service.py) and [`apps/gateway/deps.py`](../../apps/gateway/deps.py).

Things to confirm:

- the inbound path still claims dedupe before doing transcript work
- the user message is persisted before graph invocation
- `SessionService` invokes `assistant_graph`
- adapters do not import graph nodes or tools directly
- `agent_id` comes from configured runtime wiring, not inferred inside graph nodes

Why this matters:

- this spec should add runtime behavior without collapsing service boundaries

### 2. Graph execution is typed and deterministic
Look at [`src/graphs/state.py`](../../src/graphs/state.py), [`src/graphs/nodes.py`](../../src/graphs/nodes.py), and [`src/providers/models.py`](../../src/providers/models.py).

Things to confirm:

- `AssistantState` matches the minimal single-turn contract
- `ModelTurnResult` carries `needs_tools`, `tool_requests`, and `response_text`
- graph branching is driven by typed results, not provider-native payload parsing
- prior conversation context is loaded from the repository, not fabricated in-memory

Why this matters:

- deterministic tests depend on a stable contract between model, graph, and tools

### 3. Tools are bound through the registry and filtered by policy
Look at [`src/tools/registry.py`](../../src/tools/registry.py) and [`src/policies/service.py`](../../src/policies/service.py).

Things to confirm:

- graph nodes do not instantiate concrete tools ad hoc
- factories receive `ToolRuntimeContext`
- denied capabilities are omitted from the bound tool set
- missing or denied tools fail closed during execution

Why this matters:

- later capability growth will be much harder if tool exposure is not centralized now

### 4. Tool outcomes must be recorded before the assistant reports them
Look at [`src/graphs/nodes.py`](../../src/graphs/nodes.py) and [`src/sessions/repository.py`](../../src/sessions/repository.py).

Things to confirm:

- every requested tool call creates a `tool_proposal` artifact
- successful and failed executions both create `tool_result` artifacts
- `send_message` also creates an `outbound_intent` artifact
- tool attempt and result audit rows are written
- when all tool executions fail, the assistant returns the fallback failure message instead of claiming success

Why this matters:

- the highest-risk regression in this spec is a transcript that implies successful execution without persisted evidence

## End-to-end walkthrough

### Step 1: inbound request enters the existing gateway path
[`apps/gateway/api/inbound.py`](../../apps/gateway/api/inbound.py)

The API still opens a claim DB session and a work DB session, then delegates to `SessionService.process_inbound(...)`.

### Step 2: dedupe and inbound transcript persistence still happen first
[`src/sessions/service.py`](../../src/sessions/service.py)

The service:

1. normalizes routing
2. claims idempotency
3. reuses or creates the session
4. appends the inbound `user` message
5. finalizes the dedupe record

Only after those steps does it invoke the assistant runtime.

### Step 3: the assistant graph assembles turn state
[`src/graphs/assistant_graph.py`](../../src/graphs/assistant_graph.py) and [`src/graphs/nodes.py`](../../src/graphs/nodes.py)

The graph loads recent conversation messages through the repository and creates `AssistantState` with:

- `session_id`
- `agent_id`
- `channel_kind`
- `sender_id`
- `user_text`
- `messages`

### Step 4: tools are bound for this runtime context
[`src/graphs/nodes.py`](../../src/graphs/nodes.py) and [`src/tools/registry.py`](../../src/tools/registry.py)

The runtime creates `ToolRuntimeContext`, asks the policy service which capabilities are allowed, and binds only those tool factories.

In the default app wiring, the available tools are:

- `echo_text`
- `send_message`

### Step 5: the model returns a typed turn result
[`src/providers/models.py`](../../src/providers/models.py)

The default model in this workspace is a simple rule-based adapter:

- `echo <text>` requests `echo_text`
- `send <text>` requests `send_message`
- anything else returns plain assistant text

That adapter is intentionally simple so the runtime and persistence contracts can be tested without a provider dependency.

### Step 6: tool artifacts and audit rows are recorded append-only
[`src/sessions/repository.py`](../../src/sessions/repository.py) and [`src/observability/audit.py`](../../src/observability/audit.py)

For each requested tool, the runtime records:

- a `tool_proposal` artifact
- an `attempt` audit row
- optionally an `outbound_intent` artifact
- a `tool_result` artifact
- a `result` audit row

### Step 7: the assistant message is appended last
[`src/graphs/nodes.py`](../../src/graphs/nodes.py)

The final assistant reply is stored as a normal transcript message after tool execution is complete.

Current behavior to know while reviewing:

- if at least one tool succeeds, the assistant response is built from successful tool result content
- if tool execution is requested but every tool fails or is unavailable, the runtime stores `I could not complete that tool request.`
- when no tools are needed, the runtime stores `ModelTurnResult.response_text`

## Database review checklist
Check [`src/db/models.py`](../../src/db/models.py) against [`migrations/versions/20260322_002_runtime_tools.py`](../../migrations/versions/20260322_002_runtime_tools.py).

You want the ORM models and migration to agree on:

- `session_artifacts` exists
- `tool_audit_events` exists
- both tables are linked to `sessions`
- both tables use append-order indexes on `(session_id, id)`
- payloads are stored as JSON text, not mutable transcript columns

## Test review checklist

### Runtime unit tests
[`tests/test_runtime.py`](../../tests/test_runtime.py)

Confirms:

- graph branching without tools
- policy-aware tool filtering
- failure paths do not fabricate successful assistant output

### Repository tests
[`tests/test_repository.py`](../../tests/test_repository.py)

Confirms:

- runtime artifacts are stored append-only and in order

### API tests
[`tests/test_api.py`](../../tests/test_api.py)

Confirms:

- the public session history now includes assistant replies created by the runtime

### Integration tests
[`tests/test_integration.py`](../../tests/test_integration.py)

Confirms:

- tool-using turns record artifacts and audit events
- denied tools fail closed
- outbound intent creation does not require transport dispatch
- tool failures produce recorded failure instead of fabricated success

## How to run the new feature locally

### Environment setup

```bash
uv sync --group dev
docker compose --env-file .env up -d
uv run alembic upgrade head
```

### Start the gateway

```bash
uv run uvicorn apps.gateway.main:app --reload
```

### Manual smoke tests

Plain assistant response:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H "Content-Type: application/json" \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-1",
    "external_message_id": "msg-plain-1",
    "sender_id": "sender-1",
    "content": "hello runtime",
    "peer_id": "peer-1"
  }'
```

Tool-backed echo response:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H "Content-Type: application/json" \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-1",
    "external_message_id": "msg-echo-1",
    "sender_id": "sender-1",
    "content": "echo runtime hello",
    "peer_id": "peer-1"
  }'
```

Outbound-intent preparation path:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H "Content-Type: application/json" \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-1",
    "external_message_id": "msg-send-1",
    "sender_id": "sender-1",
    "content": "send hello channel",
    "peer_id": "peer-1"
  }'
```

After any of those calls, inspect transcript history with:

```bash
curl "http://127.0.0.1:8000/sessions/<session_id>/messages?limit=20"
```

## How to test this spec
Run the tests that prove the runtime behavior:

```bash
uv run pytest tests/test_runtime.py
uv run pytest tests/test_repository.py
uv run pytest tests/test_api.py
uv run pytest tests/test_integration.py
```

Or run the full suite:

```bash
uv run pytest
```

## Review summary
If the implementation is correct, you should see:

- existing gateway/session behavior preserved
- a single-turn assistant runtime invoked from the service layer
- tool execution routed through a typed registry
- append-only storage for runtime artifacts and audit rows
- assistant text that never claims a successful tool result without recorded evidence
