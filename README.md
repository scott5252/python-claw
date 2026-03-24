# python-claw Project Guide

This document translates the current project knowledge into a format that works for both:

- technical non-developers who need to understand what the solution is
- developers who need to run it, inspect it, and extend it

This guide is intended to evolve as additional specs are completed. It reflects the project as it exists today and also highlights the next planned areas of growth, including LLM connectivity and future sub-agent support.

## 1. Overview

### What this project is

`python-claw` is a gateway-first assistant platform foundation written in Python. It is designed to receive inbound messages from external channels, route them into durable sessions, store the conversation history, run assistant logic, apply policy and approval checks, and record auditable execution results.

In simpler terms, this project is the backend skeleton for an AI assistant system that can:

- receive messages from channels such as Slack-like integrations
- keep long-lived conversation sessions
- decide what assistant action should happen next
- use approved tools in a controlled way
- queue work for asynchronous processing
- normalize inbound attachments into safe runtime-owned media records
- deliver completed outbound replies through channel-aware dispatch paths
- support remote execution through a separate internal node-runner boundary

### What it does today

The current implementation focuses on seven delivered capability areas:

1. Gateway sessions and deterministic routing
2. Runtime tools and typed tool execution
3. Capability governance and approval-gated actions
4. Context continuity and summary/outbox scaffolding
5. Async queueing with worker-owned execution runs
6. Remote node-runner execution with per-agent sandbox resolution
7. Channel-aware outbound delivery, chunking, and first-pass media normalization

### What it does not do yet

The project is still a foundation, not a finished end-user assistant platform. Important planned capabilities are still pending, including:

- real provider-backed LLM integrations
- real provider-backed transport APIs for Slack, Telegram, or web chat
- richer retrieval and memory indexing
- production-grade sandbox/container enforcement
- sub-agent orchestration
- operational observability and hardening

### Who should read this

- Non-developers: focus on this section, the architecture diagrams, and the Connections section.
- Developers: use the Architecture, Setup, and Connections sections as your working guide.

## 2. Architecture

### Architecture in plain language

The system is built around one main rule: all important work starts at the gateway.

That means the project keeps routing, session identity, policy decisions, persistence, and auditing centralized. Instead of letting each channel or tool call the assistant directly, the gateway acts as the front door and source of truth.

### Core building blocks

- Gateway API: receives inbound messages and exposes read/admin endpoints
- Routing service: decides which durable session a message belongs to
- Session service: orchestrates persistence and run creation
- Worker: claims queued runs and executes assistant turns
- Assistant graph/runtime: performs the assistant decision flow
- Media processor: normalizes accepted attachments before they enter turn context
- Tool registry and policy layer: controls which tools are visible and executable
- Outbound dispatcher: parses directives, chunks text, applies channel capability rules, and records delivery attempts
- Channel adapters: thin transport-specific send interfaces for `webchat`, `slack`, and `telegram`
- Database: stores sessions, messages, approvals, artifacts, runs, and audits
- Node runner: isolated internal execution boundary for remote command execution
- Sandbox service: resolves sandbox profile and workspace rules per agent/run

### High-level system diagram

```mermaid
flowchart LR
    A[External Channel or Client] --> B[Gateway API]
    B --> C[Routing Service]
    C --> D[(Sessions and Messages)]
    B --> E[Session Service]
    E --> F[(Execution Runs)]
    F --> G[Worker]
    G --> H[Media Processor]
    H --> D
    G --> I[Assistant Graph Runtime]
    I --> J[Policy Service]
    I --> K[Tool Registry]
    I --> L[Context Service]
    L --> D
    K --> M[Local Safe Tools]
    K --> N[Governed Remote Exec Tool]
    N --> O[Node Runner]
    O --> P[(Node Execution Audits)]
    G --> Q[Outbound Dispatcher]
    Q --> R[Channel Adapters]
    Q --> S[(Outbound Deliveries)]
    E --> T[(Governance and Artifacts)]
```

### Runtime sequence for a normal inbound message

```mermaid
sequenceDiagram
    participant Client
    participant Gateway
    participant DB
    participant Worker
    participant Runtime
    participant Channel

    Client->>Gateway: POST /inbound/message
    Gateway->>DB: validate payload, dedupe, resolve/create session
    Gateway->>DB: append user message
    Gateway->>DB: append canonical attachment inputs if present
    Gateway->>DB: create or reuse execution_run
    Gateway-->>Client: 202 Accepted + session_id + run_id
    Worker->>DB: claim queued run
    Worker->>DB: normalize attachments to terminal states
    Worker->>Runtime: execute assistant turn
    Runtime->>DB: append assistant message, artifacts, manifests, audits
    Worker->>DB: create outbound delivery records and attempts
    Worker->>Channel: send chunked text and bounded media instructions
    Worker->>DB: mark run terminal state
```

### Execution architecture in more detail

#### Gateway

The gateway is the main API service. It currently exposes:

- `GET /health`
- `POST /inbound/message`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/governance/pending`
- `GET /runs/{run_id}`
- `GET /sessions/{session_id}/runs`

Its responsibilities are:

- validate inbound payloads
- enforce routing rules
- claim idempotency records
- persist inbound transcript messages
- persist canonical inbound attachment references
- create durable execution runs
- return quickly with `202 Accepted`

#### Worker and async runs

After the gateway accepts work, the worker becomes responsible for execution. This keeps the request path short and durable. The worker:

- claims queued runs
- applies lane and global concurrency rules
- performs first-pass attachment normalization for inbound-triggered runs
- invokes the assistant runtime
- dispatches outbound text and media after the assistant turn completes
- persists results, errors, and diagnostics

#### Assistant runtime

The current runtime is intentionally narrow and deterministic. It can:

- return plain assistant text
- call a safe local tool such as `echo_text`
- call approval-governed tools such as `send_message`
- prepare runtime-owned outbound intents that are dispatched after the turn
- prepare a remote execution request when governed access exists

The default model path today is a rule-based adapter, which means the architecture is ready for LLMs, but the default implementation is not yet provider-backed.

#### Governance and approvals

Some actions are intentionally gated. The system can persist:

- resource proposals
- immutable resource versions
- approvals
- active resources
- governance transcript events

This means risky or externally impactful actions can require explicit approval before execution.

#### Context continuity

The platform keeps transcript history as the main source of truth. It also supports additive continuity records such as:

- summary snapshots
- context manifests
- outbox jobs
- normalized attachment references used during a turn

This lets the system inspect how context was assembled for each turn and lays the groundwork for future summarization and retrieval workflows.

#### Channels, chunking, and media handling

The system now includes a shared outbound delivery layer for three supported channel kinds in this phase:

- `webchat`
- `slack`
- `telegram`

This layer is still gateway-owned and worker-driven. That means channel adapters remain thin. They do not invoke the graph, own orchestration, or parse assistant directives themselves.

In practical terms, the platform now supports:

- optional canonical `attachments` on `POST /inbound/message`
- worker-side normalization of accepted attachments into safe stored media records
- directive parsing for bounded reply and media instructions
- deterministic post-turn chunking for large outbound text
- append-only delivery and delivery-attempt auditing

This is an important distinction for both non-developers and developers: the system now behaves more like a real multi-channel assistant, but it still does not provide true token-by-token streaming or production provider integrations in this phase.

#### Remote node-runner and sandboxing

For privileged or host-execution scenarios, the project introduces a separate internal service boundary called the node runner. The gateway and worker construct signed execution requests; the node runner independently verifies and enforces policy before executing.

This separation is important because it prevents the main application path from being the same process that directly performs privileged execution.

### Internal service diagram

```mermaid
flowchart TB
    subgraph Gateway Side
        A[Gateway API]
        B[Session Service]
        C[Jobs Repository]
        D[Assistant Graph]
        E[Tool Registry]
        F[Policy Service]
        G[RemoteExecutionRuntime]
    end

    subgraph Data Layer
        H[(PostgreSQL)]
    end

    subgraph Execution Side
        I[Worker]
        J[Node Runner Policy]
        K[Node Runner Executor]
        L[Sandbox Service]
    end

    A --> B
    B --> H
    B --> C
    C --> H
    I --> C
    I --> D
    D --> E
    D --> F
    E --> G
    G --> J
    J --> L
    J --> H
    J --> K
    K --> H
```

### Main persisted records

The database currently stores the system's durable state in tables such as:

- `sessions`
- `messages`
- `inbound_dedupe`
- `inbound_message_attachments`
- `message_attachments`
- `session_artifacts`
- `tool_audit_events`
- `governance_transcript_events`
- `resource_proposals`
- `resource_versions`
- `resource_approvals`
- `active_resources`
- `execution_runs`
- `session_run_leases`
- `global_run_leases`
- `scheduled_jobs`
- `scheduled_job_fires`
- `outbound_deliveries`
- `outbound_delivery_attempts`
- `agent_sandbox_profiles`
- `node_execution_audits`
- `summary_snapshots`
- `outbox_jobs`
- `context_manifests`

### Current implementation boundaries

Implemented now:

- gateway-owned inbound acceptance
- durable sessions and transcript persistence
- idempotency and duplicate replay protection
- worker-owned queued execution
- approval-gated capability execution
- canonical inbound attachment acceptance
- worker-owned attachment normalization and safe local media staging
- shared outbound dispatch with directive stripping and deterministic chunking
- append-only outbound delivery auditing for `webchat`, `slack`, and `telegram`
- signed internal node-runner requests
- audit persistence for remote execution

Planned or partial:

- true LLM provider integration
- retrieval indexing and retrieval-assisted context assembly
- production transport API integrations beyond the current thin channel adapters
- stronger production sandbox isolation
- richer operator diagnostics and presence surfaces

## 3. Setup

### Prerequisites

You need:

- Python `3.11+`
- `uv`
- Docker Desktop or another Docker runtime

Optional but useful:

- `curl`
- PostgreSQL client tools
- Redis client tools

### Step 1: Install Python and dependencies

```bash
uv python install 3.11
uv sync --group dev
```

If Python `3.11+` is already installed, this is enough:

```bash
uv sync --group dev
```

### Step 2: Review the environment configuration

The application loads configuration from a project-root `.env` file using environment variables prefixed with `PYTHON_CLAW_`.

Key variables include:

- `PYTHON_CLAW_DATABASE_URL`
- `PYTHON_CLAW_DEDUPE_RETENTION_DAYS`
- `PYTHON_CLAW_DEDUPE_STALE_AFTER_SECONDS`
- `PYTHON_CLAW_RUNTIME_TRANSCRIPT_CONTEXT_LIMIT`
- `PYTHON_CLAW_EXECUTION_RUN_GLOBAL_CONCURRENCY`
- `PYTHON_CLAW_MEDIA_STORAGE_ROOT`
- `PYTHON_CLAW_MEDIA_STORAGE_BUCKET`
- `PYTHON_CLAW_MEDIA_RETENTION_DAYS`
- `PYTHON_CLAW_MEDIA_ALLOWED_SCHEMES`
- `PYTHON_CLAW_MEDIA_ALLOWED_MIME_PREFIXES`
- `PYTHON_CLAW_MEDIA_MAX_BYTES`
- `PYTHON_CLAW_REMOTE_EXECUTION_ENABLED`
- `PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID`
- `PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET`
- `PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES`

Docker-related variables include:

- `PYTHON_CLAW_POSTGRES_DB`
- `PYTHON_CLAW_POSTGRES_USER`
- `PYTHON_CLAW_POSTGRES_PASSWORD`
- `PYTHON_CLAW_POSTGRES_PORT`
- `PYTHON_CLAW_REDIS_PORT`

The default local database URL is:

```text
postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
```

### Step 3: Start local infrastructure

This repository includes a `docker-compose.yml` that starts:

- PostgreSQL 17
- Redis 7

Start them with:

```bash
docker compose --env-file .env up -d
```

Useful checks:

```bash
docker compose ps
docker compose logs postgres
docker compose logs redis
```

### Step 4: Run database migrations

Apply the schema with:

```bash
uv run alembic upgrade head
```

This creates the currently migrated database tables needed by the gateway, queueing, governance, media normalization, outbound delivery auditing, and node-runner flows.

### Step 5: Start the gateway API

```bash
uv run uvicorn apps.gateway.main:app --reload
```

The gateway will be available at:

```text
http://127.0.0.1:8000
```

### Step 6: Start the node runner when working on remote execution

If you are testing the remote execution path from Spec 006, start the node runner separately:

```bash
uv run uvicorn apps.node_runner.main:app --reload --port 8010
```

### Step 7: Process queued runs

Inbound requests create queued runs. To execute one worker pass locally, use:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once

print(run_once())
PY
```

For local development, the usual flow is:

1. Send an inbound message to the gateway
2. Receive a `run_id`
3. Run the worker pass
4. Inspect the session messages, attachment state, and run state
5. If relevant, inspect outbound delivery records in the database

### Step 8: Run tests

Run the full suite with:

```bash
uv run pytest
```

Useful targeted commands:

```bash
uv run pytest tests/test_api.py
uv run pytest tests/test_runtime.py
uv run pytest tests/test_integration.py
uv run pytest tests/test_async_queueing_coverage.py
uv run pytest tests/test_node_sandbox.py
uv run pytest tests/test_channels_media.py
```

Note: the tests primarily use temporary SQLite fixtures, so they do not require local PostgreSQL or Redis to pass.

### Setup checklist

```text
[ ] uv sync --group dev
[ ] docker compose --env-file .env up -d
[ ] uv run alembic upgrade head
[ ] uv run uvicorn apps.gateway.main:app --reload
[ ] optional: uv run uvicorn apps.node_runner.main:app --reload --port 8010
[ ] send a test inbound message
[ ] run one worker pass
[ ] inspect session and run state
```

## 4. Connections

### How to connect to the system today

Today, the main way to interact with the system is through the gateway HTTP API.

The primary write entrypoint is:

- `POST /inbound/message`

The main read/inspection entrypoints are:

- `GET /health`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/governance/pending`
- `GET /runs/{run_id}`
- `GET /sessions/{session_id}/runs`

The internal execution boundary for remote execution is:

- `POST /internal/node/exec`
- `GET /internal/node/exec/{request_id}`

These node-runner endpoints are internal system endpoints, not general external client APIs.

### Example: connect through the gateway

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Send a direct-message style inbound event:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H "Content-Type: application/json" \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-1",
    "external_message_id": "msg-1",
    "sender_id": "sender-1",
    "content": "hello",
    "peer_id": "peer-1"
  }'
```

Send an inbound event with a canonical attachment:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H "Content-Type: application/json" \
  -d '{
    "channel_kind": "telegram",
    "channel_account_id": "acct-1",
    "external_message_id": "msg-attachment-1",
    "sender_id": "sender-1",
    "content": "please review this file",
    "peer_id": "peer-1",
    "attachments": [
      {
        "source_url": "file:///absolute/path/to/example.pdf",
        "mime_type": "application/pdf",
        "filename": "example.pdf",
        "provider_metadata": {
          "provider": "manual-test"
        }
      }
    ]
  }'
```

Important behavior note:

- the gateway accepts and persists the attachment reference immediately
- the worker performs normalization after the request has already returned `202 Accepted`
- only normalized `stored` attachments are exposed back into turn context or outbound media sends

Expected response shape:

```json
{
  "session_id": "session-uuid",
  "message_id": 1,
  "run_id": "run-uuid",
  "status": "queued",
  "dedupe_status": "accepted"
}
```

Inspect the created session:

```bash
curl http://127.0.0.1:8000/sessions/<session_id>
```

Read transcript history:

```bash
curl "http://127.0.0.1:8000/sessions/<session_id>/messages?limit=50"
```

Read run diagnostics:

```bash
curl http://127.0.0.1:8000/runs/<run_id>
curl http://127.0.0.1:8000/sessions/<session_id>/runs
```

### Example: use the `webchat` adapter locally

The current `webchat` adapter is a thin local channel adapter, not a full browser chat frontend. In local development, the easiest way to use it is to treat `webchat` as another `channel_kind` on the same gateway API and send messages through `POST /inbound/message`.

This is useful when you want to test:

- a browser-like direct-message channel identity
- outbound chunking through a non-Slack, non-Telegram adapter
- the shared dispatcher and adapter contracts without involving an external provider

Send a basic `webchat` message:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H "Content-Type: application/json" \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "local-webchat",
    "external_message_id": "web-msg-1",
    "sender_id": "browser-user-1",
    "content": "hello from webchat",
    "peer_id": "browser-user-1"
  }'
```

Expected local flow:

1. The gateway accepts the `webchat` message and returns `202 Accepted`.
2. The worker later claims the queued run and executes the assistant turn.
3. If the turn produces an outbound intent, the shared dispatcher routes it to the `webchat` adapter.
4. Delivery is recorded in `outbound_deliveries` and `outbound_delivery_attempts`.

In other words, `webchat` is currently exercised through the same gateway surface as the other channels. There is not yet a separate browser transport server, WebSocket feed, or UI bundle in this repository.

### Webchat adapter flow

```mermaid
sequenceDiagram
    participant Browser as Browser or Web Client
    participant Gateway
    participant DB
    participant Worker
    participant Runtime
    participant Dispatcher
    participant Webchat as Webchat Adapter

    Browser->>Gateway: POST /inbound/message (channel_kind=webchat)
    Gateway->>DB: persist inbound message and queued run
    Gateway-->>Browser: 202 Accepted + session_id + run_id
    Worker->>DB: claim queued run
    Worker->>Runtime: execute assistant turn
    Runtime->>DB: persist assistant message and outbound intent
    Worker->>Dispatcher: dispatch completed turn output
    Dispatcher->>Webchat: send text chunk or media instruction
    Dispatcher->>DB: persist outbound delivery and attempt rows
```

### Example interaction patterns

Safe local tool example:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H "Content-Type: application/json" \
  -d '{
    "channel_kind": "slack",
    "channel_account_id": "acct-1",
    "external_message_id": "msg-echo-1",
    "sender_id": "sender-1",
    "content": "echo hello runtime",
    "peer_id": "peer-1"
  }'
```

Governed action example:

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

In the governed case, the system may require approval before the action can be used or completed.

Large outbound responses are now sent through the shared dispatcher after the assistant turn completes. If the text exceeds a channel's configured limit, it is split into deterministic chunks before send. The current phase supports bounded reply and media directives internally, but those directives are parsed and stripped by shared runtime code rather than being passed through as visible adapter commands.

If you want to test this specifically with `webchat`, send the same kinds of inbound messages shown above, but use `"channel_kind": "webchat"` and then inspect the resulting transcript, run status, and outbound delivery rows after the worker executes.

### How sessions are determined

The platform uses deterministic routing rules:

- direct conversations map to scope `direct` with scope name `main`
- group conversations map to scope `group` with scope name equal to `group_id`
- a canonical session key is derived from channel identity plus peer/group scope

This means repeated messages for the same routing identity land in the same durable session.

### How idempotency works

Inbound duplicates are tracked using:

- `channel_kind`
- `channel_account_id`
- `external_message_id`

If the same external message is delivered more than once, the system can:

- return the original accepted result when already completed
- reject in-progress duplicates with `409`
- recover stale claims after the configured timeout

This behavior is important for webhook-style or retry-prone integrations.

### How to interact as a non-developer

If you are not writing code, the simplest way to understand system behavior is:

1. Send a test message to `POST /inbound/message`
2. Capture the returned `session_id` and `run_id`
3. Ask a developer or operator to run the worker pass if needed
4. Use the read endpoints to inspect the session history and run outcome

### How developers should interact

Developers will usually interact at three levels:

- API level: send inbound requests and inspect sessions/runs
- code level: modify routing, runtime, policies, tools, media processing, or channel dispatch components
- persistence level: inspect durable state in PostgreSQL when debugging, including attachment and outbound delivery records

Recommended starting files for developers:

- `apps/gateway/main.py`
- `apps/gateway/api/inbound.py`
- `apps/gateway/api/admin.py`
- `src/sessions/service.py`
- `src/jobs/service.py`
- `src/graphs/assistant_graph.py`
- `src/graphs/nodes.py`
- `src/media/processor.py`
- `src/channels/dispatch.py`
- `src/channels/adapters/`
- `src/policies/service.py`
- `src/tools/registry.py`
- `apps/node_runner/main.py`

If you are specifically working on adapter behavior, start with:

- `src/channels/adapters/webchat.py`
- `src/channels/adapters/slack.py`
- `src/channels/adapters/telegram.py`
- `src/channels/adapters/base.py`

## Additional Useful Information

### Current limitations

The current repository is intentionally narrow. A few important limitations to keep in mind:

- the default assistant behavior is rule-based, not backed by a live LLM provider
- Redis is provisioned but not yet central to the request path
- outbound delivery is channel-aware and audited, but current adapters are still thin local implementations rather than production provider clients
- media handling is limited to normalization, classification, safe storage references, and bounded outbound media dispatch
- true incremental streaming is not implemented; this phase uses post-turn chunked delivery
- remote execution policy and auditing are implemented more fully than sandbox enforcement

### Future specs and planned growth

The roadmap already points toward several next-stage capabilities.

#### LLM integration

The project already has a model adapter contract in `src/providers/models.py`. Today it uses a rule-based adapter, but this boundary is where future provider-backed LLM integrations will plug in. Future specs are expected to expand:

- provider authentication and model selection
- richer prompt/context assembly
- tool-calling with real model providers
- fallback, retry, and auth-profile handling

#### Observability and operational hardening

Spec 008 is aimed at operator needs, including:

- presence/status surfaces
- structured logging and tracing
- auth profile failover
- diagnostics for stuck work and failed runs

#### Sub-agents

Sub-agents are not a current committed feature, but the architecture is compatible with them. The recommended future approach is:

- keep delegation gateway-managed
- create child sessions for specialist agents
- give each sub-agent bounded context and controlled tools
- persist child runs and results as first-class durable records

In practical terms, a likely future spec would add:

- parent/child session links
- delegation records and statuses
- specialist-agent graphs
- delegation policy, depth, timeout, and retry rules
- read APIs for child-agent inspection

### Document maintenance guidance

This document should be updated whenever:

- a new spec is completed
- a new API surface is added
- the setup flow changes
- LLM support becomes provider-backed
- sub-agent orchestration becomes part of the committed scope

Until then, treat this guide as the human-readable companion to the evolving specs and codebase.
