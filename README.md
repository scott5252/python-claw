# python-claw Project Guide

This document translates the current project knowledge into a format that works for both:

- technical non-developers who need to understand what the solution is
- developers who need to run it, inspect it, and extend it

This guide is intended to evolve as additional specs are completed. It reflects the project as it exists today and also highlights the next planned areas of growth, including deeper LLM capabilities and future sub-agent support.

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
- expose health, readiness, and operator diagnostics for the durable workflows it owns

### What it does today

The current implementation focuses on nine delivered capability areas:

1. Gateway sessions and deterministic routing
2. Runtime tools and typed tool execution
3. Capability governance and approval-gated actions
4. Context continuity and summary/outbox scaffolding
5. Async queueing with worker-owned execution runs
6. Remote node-runner execution with per-agent sandbox resolution
7. Channel-aware outbound delivery, chunking, and first-pass media normalization
8. Observability, diagnostics, health or readiness, and operational hardening
9. Provider-backed LLM runtime with backend-owned prompt assembly and approval-safe tool routing

### What it does not do yet

The project is still a foundation, not a finished end-user assistant platform. Important planned capabilities are still pending, including:

- real provider-backed transport APIs for Slack, Telegram, or web chat
- richer retrieval and memory indexing
- production-grade sandbox/container enforcement
- sub-agent orchestration
- full production telemetry backends and alerting integrations

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
- Observability layer: emits structured events, redacts sensitive fields, classifies failures, and supports diagnostics queries
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
    Gateway-->>Client: 202 Accepted + session_id + run_id + trace_id
    Worker->>DB: claim queued run
    Worker->>DB: normalize attachments to terminal states
    Worker->>Runtime: execute assistant turn
    Runtime->>DB: append assistant message, artifacts, manifests, audits
    Worker->>DB: create outbound delivery records and attempts
    Worker->>Channel: send chunked text and bounded media instructions
    Worker->>DB: mark run terminal state
    Note over Gateway,Worker: health, readiness, and diagnostics now expose correlated operational state
```

### Execution architecture in more detail

#### Gateway

The gateway is the main API service. It currently exposes:

- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `POST /inbound/message`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/governance/pending`
- `GET /runs/{run_id}`
- `GET /sessions/{session_id}/runs`
- `GET /diagnostics/runs`
- `GET /diagnostics/runs/{run_id}`
- `GET /diagnostics/sessions/{session_id}/continuity`
- `GET /diagnostics/outbox-jobs`
- `GET /diagnostics/node-executions`
- `GET /diagnostics/deliveries`
- `GET /diagnostics/attachments`

Its responsibilities are:

- validate inbound payloads
- enforce routing rules
- claim idempotency records
- persist inbound transcript messages
- persist canonical inbound attachment references
- create durable execution runs with stable per-run correlation
- return quickly with `202 Accepted`

The gateway now also owns the default operator-facing read boundary for service health and diagnostics. In practical terms, `GET /health/live` is the cheap process check, `GET /health/ready` is the deployment-readiness check, and `/diagnostics/*` routes are authenticated inspection surfaces for operators or internal services.

#### Worker and async runs

After the gateway accepts work, the worker becomes responsible for execution. This keeps the request path short and durable. The worker:

- claims queued runs
- applies lane and global concurrency rules
- performs first-pass attachment normalization for inbound-triggered runs
- invokes the assistant runtime
- dispatches outbound text and media after the assistant turn completes
- persists results, errors, and diagnostics
- preserves the parent run `trace_id` when follow-on work creates additional operational records

#### Assistant runtime

The current runtime is intentionally narrow and deterministic. It can:

- return plain assistant text
- call a safe local tool such as `echo_text`
- call approval-governed tools such as `send_message`
- prepare runtime-owned outbound intents that are dispatched after the turn
- prepare a remote execution request when governed access exists

The runtime now supports two execution modes behind the same model adapter seam:

- a default `rule_based` mode that remains safe for local development and CI
- an explicit provider-backed mode that uses backend-authored prompt payloads, bounded provider retries, and translation back into the existing `ModelTurnResult` and `ToolRequest` contracts

Even in provider-backed mode, tool execution, approval creation, artifact persistence, context-manifest ownership, and outbound dispatch all remain backend-owned. The model may suggest tools, but it does not execute them directly.

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

With Spec 008, continuity is also easier to inspect operationally. Developers can now use diagnostics to see whether context assembly degraded, whether outbox follow-up work is pending or failed, and how recent runs for a session behaved without manually reconstructing the state from raw SQL alone.

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

Spec 008 builds on that separation by making node execution easier to trace. Node execution audits now participate in the same broader run-correlation model, so operators can connect a privileged execution attempt back to the parent assistant run more directly.

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

Several of these records now also carry observability metadata such as `trace_id`, failure classification, or degraded-state fields. That is important because the platform's diagnostics are built on canonical durable records, not on a separate shadow state system.

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
- stable run correlation with `trace_id`
- authenticated diagnostics for runs, continuity, outbox jobs, node executions, deliveries, and attachments
- structured health and readiness surfaces
- structured operator-facing failure visibility and redaction

Planned or partial:

- retrieval indexing and retrieval-assisted context assembly
- production transport API integrations beyond the current thin channel adapters
- stronger production sandbox isolation
- richer metrics exporters, tracing backends, and alerting integrations
- presence or real-time end-user activity surfaces

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
- `PYTHON_CLAW_RUNTIME_MODE`
- `PYTHON_CLAW_LLM_PROVIDER`
- `PYTHON_CLAW_LLM_API_KEY`
- `PYTHON_CLAW_LLM_BASE_URL`
- `PYTHON_CLAW_LLM_MODEL`
- `PYTHON_CLAW_LLM_TIMEOUT_SECONDS`
- `PYTHON_CLAW_LLM_MAX_RETRIES`
- `PYTHON_CLAW_LLM_TEMPERATURE`
- `PYTHON_CLAW_LLM_MAX_OUTPUT_TOKENS`
- `PYTHON_CLAW_LLM_TOOL_CALL_MODE`
- `PYTHON_CLAW_LLM_MAX_TOOL_REQUESTS_PER_TURN`
- `PYTHON_CLAW_LLM_DISABLE_TOOLS`
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
- `PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN`
- `PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN`
- `PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH`
- `PYTHON_CLAW_OBSERVABILITY_LOG_CONTENT_PREVIEW`
- `PYTHON_CLAW_OBSERVABILITY_LOG_CONTENT_PREVIEW_CHARS`
- `PYTHON_CLAW_DIAGNOSTICS_PAGE_DEFAULT_LIMIT`
- `PYTHON_CLAW_DIAGNOSTICS_PAGE_MAX_LIMIT`
- `PYTHON_CLAW_EXECUTION_RUN_STALE_AFTER_SECONDS`
- `PYTHON_CLAW_OUTBOX_JOB_STALE_AFTER_SECONDS`
- `PYTHON_CLAW_OUTBOUND_DELIVERY_STALE_AFTER_SECONDS`
- `PYTHON_CLAW_NODE_EXECUTION_STALE_AFTER_SECONDS`

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

For local diagnostics and readiness testing, you will usually also want to set explicit tokens in `.env`, for example:

```text
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=change-me
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=change-me-internal
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true
```

For local scaffold mode, leave `PYTHON_CLAW_RUNTIME_MODE=rule_based`.

To enable provider-backed turns, set at minimum:

```text
PYTHON_CLAW_RUNTIME_MODE=provider
PYTHON_CLAW_LLM_PROVIDER=openai
PYTHON_CLAW_LLM_API_KEY=your-key
PYTHON_CLAW_LLM_MODEL=gpt-4o-mini
```

If provider mode is selected without the required credentials, startup fails closed rather than silently falling back to the rule-based adapter.

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

This creates the currently migrated database tables needed by the gateway, queueing, governance, media normalization, outbound delivery auditing, node-runner flows, and observability metadata used by diagnostics.

### Step 5: Start the gateway API

```bash
uv run uvicorn apps.gateway.main:app --reload
```

The gateway will be available at:

```text
http://127.0.0.1:8000
```

Once the gateway is running, the most useful operator checks are:

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready -H 'Authorization: Bearer change-me'
curl http://127.0.0.1:8000/diagnostics/runs -H 'Authorization: Bearer change-me'
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
2. Receive a `run_id` and `trace_id`
3. Run the worker pass
4. Inspect the session messages, attachment state, run state, and diagnostics routes
5. If relevant, inspect outbound delivery or node execution records in the database

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
uv run pytest tests/test_provider_runtime.py
uv run pytest tests/test_async_queueing_coverage.py
uv run pytest tests/test_node_sandbox.py
uv run pytest tests/test_channels_media.py
```

Note: the tests primarily use temporary SQLite fixtures and provider fakes, so they do not require local PostgreSQL, Redis, or live provider credentials to pass.

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
- `GET /health/live`
- `GET /health/ready`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/governance/pending`
- `GET /runs/{run_id}`
- `GET /sessions/{session_id}/runs`
- `GET /diagnostics/runs`
- `GET /diagnostics/runs/{run_id}`
- `GET /diagnostics/sessions/{session_id}/continuity`
- `GET /diagnostics/outbox-jobs`
- `GET /diagnostics/node-executions`
- `GET /diagnostics/deliveries`
- `GET /diagnostics/attachments`

The internal execution boundary for remote execution is:

- `POST /internal/node/exec`
- `GET /internal/node/exec/{request_id}`

These node-runner endpoints are internal system endpoints, not general external client APIs.

The practical distinction between these surfaces is:

- session and run routes are narrower product-facing read APIs
- health routes are service-supervision endpoints
- diagnostics routes are operator-facing inspection endpoints with explicit authorization

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
  "trace_id": "run-trace-id",
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

Read operator diagnostics:

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready -H "Authorization: Bearer change-me"
curl http://127.0.0.1:8000/diagnostics/runs -H "Authorization: Bearer change-me"
curl http://127.0.0.1:8000/diagnostics/runs/<run_id> -H "Authorization: Bearer change-me"
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

- the default assistant behavior remains `rule_based` unless configuration explicitly selects provider mode
- the first provider-backed path is intentionally bounded: no token streaming, no retrieval, no attachment-content understanding, and no multi-provider orchestration yet
- Redis is provisioned but not yet central to the request path
- outbound delivery is channel-aware and audited, but current adapters are still thin local implementations rather than production provider clients
- media handling is limited to normalization, classification, safe storage references, and bounded outbound media dispatch
- true incremental streaming is not implemented; this phase uses post-turn chunked delivery
- remote execution policy and auditing are implemented more fully than sandbox enforcement

### Future specs and planned growth

The roadmap already points toward several next-stage capabilities.

#### LLM integration

The project now has a provider-backed model path behind the existing adapter contract in `src/providers/models.py`.

Today that LLM layer includes:

- explicit runtime selection between `rule_based` and provider-backed execution
- backend-owned typed prompt assembly in `src/graphs/prompts.py`
- bounded provider execution metadata persisted through context manifests and observability surfaces
- provider-suggested tool requests translated back into backend-owned contracts
- approval-safe handling where governed model-suggested tools create proposals instead of executing without exact approval

Future work is still expected in areas such as:

- richer retrieval and memory-aware prompt assembly
- streaming responses and partial output persistence
- additional provider support and auth-profile management
- attachment-content understanding and multimodal reasoning

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
- LLM runtime behavior, settings, or provider support changes materially
- sub-agent orchestration becomes part of the committed scope

Until then, treat this guide as the human-readable companion to the evolving specs and codebase.
