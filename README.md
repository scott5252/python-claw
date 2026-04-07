# python-claw

`python-claw` is a gateway-first assistant platform foundation in Python. It accepts inbound channel messages, routes them into durable sessions, persists the transcript, queues execution runs, assembles runtime context, executes tools behind policy and approval controls, and delivers outbound replies through channel adapters.

The codebase now reflects Specs `001` through `017`. This README is intended to help a developer or operator do two things quickly:

1. understand the current architecture and code structure
2. configure, run, test, and deploy the system

## Example Guides

If you want the fastest path to seeing the system work end-to-end, start with [`example/example.md`](/example/example.md). It walks through the full local demo: browser-based webchat, Dockerized gateway/worker/node-runner services, OpenAI-backed execution, approval-gated `remote_exec`, child-agent delegation, webhook callbacks, generated deployment artifacts, and MailDev-based email delivery. The guide is scenario-driven, so it is the best fit when you want to understand what the example is demonstrating and run the complete workflow in order.

Pair that with [`example/quick_start.md`](/example/quick_start.md), which focuses on the exact configuration needed to make the example succeed. In practice, the normal starting path is: copy `.env.demo` to `.env`, set `PYTHON_CLAW_LLM_API_KEY`, keep the provider/webchat/node-runner/delegation settings from `.env.demo`, then launch the stack with fresh volumes if you previously ran a different mode. If you are new to the repo, read `quick_start.md` first for the critical setup guardrails, then use `example.md` for the full walkthrough.

## Documentation Guide

### [`docs/Database.md`](/docs/Database.md)

This document maps the durable database schema to the feature set delivered through Specs `001` to `017`. It explains which tables exist, why they exist, how canonical and derived records differ, and how runtime features like approvals, delivery, delegation, collaboration, and recovery are represented in persisted state.

### [`docs/env_settings.md`](/docs/env_settings.md)

This is the detailed configuration reference for the `PYTHON_CLAW_` environment model. It explains how settings are loaded, the expected format for each value type, and how important options such as policy profiles, tool profiles, agent overrides, runtime mode, and other operational controls affect startup and runtime behavior.

### [`docs/initial_design.md`](/docs/initial_design.md)

This document captures the original architectural translation from OpenClaw concepts into a Python-first design using FastAPI, LangChain, LangGraph, PostgreSQL, Redis, and a separate node-runner layer. It is the best high-level reference if you want to understand the intended service boundaries, why the gateway owns routing, and how the major subsystems were meant to fit together.

### [`docs/agents_sub_agents_v2.md`](/docs/agents_sub_agents_v2.md)

This guide explains how agents and delegated child agents work in the current codebase, including bootstrap, runtime profile binding, delegation packaging, child-session creation, and parent/child run coordination. It also compares the implemented behavior to OpenClaw concepts so you can see which multi-agent features are already present, which are partial, and where the current design is intentionally narrower.

### [`docs/architecture_change.md`](/docs/architecture_change.md)

This document describes a specific architecture fix for the approval-continuation bug in delegated child runs. It explains the original deduplication collision, the introduction of an `AWAITING_APPROVAL` delegation state plus a separate `delegation_approval_prompt` trigger, and the tests that verify the parent now receives both the approval prompt and the final child result correctly.

### [`docs/message_flow.md`](docs/message_flow.md)

This guide walks step by step through how a user request moves through the current system: gateway ingress, routing, session and transcript persistence, run creation, worker claiming, context assembly, AI/model execution, tool and approval handling, delegation, delivery, streaming, and after-turn enrichment. It is written for junior developers and calls out the main code modules, durable tables, architecture diagrams, and sequence diagrams involved at each phase.

## What Is Implemented

The current repository includes these major slices from the spec set:

- `001` gateway ingress, routing, sessions, transcript persistence, idempotent inbound handling
- `002` assistant runtime, graph assembly, tool registry, append-only tool and assistant artifacts
- `003` approval-governed capabilities and activation checks
- `004` context continuity, summaries, memories, retrieval records, outbox scaffolding
- `005` async execution runs, leases, worker claiming, retry/backoff foundations
- `006` node-runner boundary, signed remote execution, sandbox resolution
- `007` channel-aware delivery, media normalization, delivery auditing
- `008` health, readiness, diagnostics, failure classification, redaction
- `009` provider-backed LLM runtime behind backend-owned orchestration
- `010` typed tool schemas and hybrid deterministic approval control
- `011` retrieval, memory, attachment extraction, context manifests
- `012` production-style channel ingress for Slack, Telegram, and webchat
- `013` durable webchat streaming and SSE replay
- `014` agent profiles, model profiles, durable session ownership, per-run profile binding
- `015` sub-agent delegation and child-session orchestration
- `016` human takeover, pause/resume, assignment, operator notes, approval UX
- `017` production hardening: auth boundaries, quota/rate limits, recovery, retries, safer diagnostics

## System Overview

At a high level the platform works like this:

1. A channel or client sends a message to the gateway.
2. The gateway validates the payload, resolves the canonical session, persists the user turn, and creates an `execution_run`.
3. A worker claims the run and normalizes any inbound attachments.
4. The runtime assembles context from transcript plus additive derived state such as summaries, memories, retrieval rows, and attachment extractions.
5. The assistant graph executes using a rule-based or provider-backed model adapter.
6. Tool calls are validated through typed schemas and filtered through policy/tool profiles.
7. Approval-gated actions are persisted as proposals rather than executed immediately.
8. Outbound replies and media are dispatched through channel adapters and audited as durable delivery records.
9. Diagnostics, health, quotas, recovery, and collaboration state remain backend-owned and inspectable.

## Architecture

### Main services

- `gateway`: FastAPI app for ingress, provider callbacks, admin reads, diagnostics, approvals, and collaboration APIs
- `worker`: background execution loop that claims runs and processes after-turn work
- `node-runner`: internal execution boundary for governed shell/process execution
- `postgres`: primary durable store
- `redis`: deployment dependency included by Compose for stack parity

### Core runtime flow

```mermaid
flowchart LR
    A[Client or Channel] --> B[Gateway API]
    B --> C[Routing + Session Service]
    C --> D[(PostgreSQL)]
    C --> E[(execution_runs)]
    E --> F[Worker]
    F --> G[Media Processor]
    F --> H[Context Service]
    F --> I[Assistant Graph Runtime]
    I --> J[Policy + Tool Registry]
    J --> K[Local Tools]
    J --> L[Remote Exec Tool]
    L --> M[Node Runner]
    F --> N[Dispatch Layer]
    N --> O[Slack / Telegram / Webchat]
```

### Architectural rules

- The gateway is the only canonical message ingress path.
- Transcript state is append-only.
- Execution is worker-owned, not request-thread owned.
- Models never execute tools directly; the backend validates and executes them.
- Approvals, deliveries, node executions, collaboration state, and diagnostics are durable records, not only logs.
- Session ownership and runtime profile binding are durable, per-session and per-run concepts.

## Code Structure

### App entrypoints

- [`apps/gateway/main.py`](/apps/gateway/main.py) creates the main FastAPI app and wires all gateway routers and services.
- [`apps/node_runner/main.py`](/apps/node_runner/main.py) creates the internal node-runner service.
- [`scripts/worker_loop.py`](/scripts/worker_loop.py) runs the continuous worker poll loop.

### API layer

- [`apps/gateway/api/inbound.py`](/apps/gateway/api/inbound.py): canonical `POST /inbound/message`
- [`apps/gateway/api/slack.py`](/apps/gateway/api/slack.py): Slack provider ingress
- [`apps/gateway/api/telegram.py`](/apps/gateway/api/telegram.py): Telegram webhook ingress
- [`apps/gateway/api/webchat.py`](/apps/gateway/api/webchat.py): webchat send, poll, stream, approval interactions
- [`apps/gateway/api/admin.py`](/apps/gateway/api/admin.py): sessions, runs, agents, profiles, diagnostics, collaboration/operator reads and actions
- [`apps/gateway/api/health.py`](/apps/gateway/api/health.py): health and readiness
- [`apps/node_runner/api/internal.py`](/apps/node_runner/api/internal.py): signed internal exec API

### Domain and persistence

- [`src/db/models.py`](/src/db/models.py): SQLAlchemy models for sessions, messages, runs, governance, deliveries, agents, context, collaboration, quotas, and more
- [`src/db/session.py`](/src/db/session.py): database session manager
- [`migrations/versions`](/migrations/versions): Alembic migrations
- [`src/domain/schemas.py`](/src/domain/schemas.py): typed request/response and domain contracts

### Session, routing, and queueing

- [`src/routing/service.py`](/src/routing/service.py): canonical session-key resolution
- [`src/sessions/service.py`](/src/sessions/service.py): inbound persistence, session ownership, run creation
- [`src/sessions/repository.py`](/src/sessions/repository.py): session/message persistence
- [`src/jobs/service.py`](/src/jobs/service.py): run claiming, execution, retries, recovery interactions
- [`src/jobs/repository.py`](/src/jobs/repository.py): `execution_runs`, leases, and queue records
- [`src/gateway/idempotency.py`](/src/gateway/idempotency.py): inbound dedupe handling

### Runtime, tools, and policies

- [`src/graphs/assistant_graph.py`](/src/graphs/assistant_graph.py): graph assembly
- [`src/graphs/nodes.py`](/src/graphs/nodes.py): node logic for thinking, tool execution, persistence, approvals, delegation handling
- [`src/graphs/state.py`](/src/graphs/state.py): assistant state contract
- [`src/execution/runtime.py`](/src/execution/runtime.py): runtime orchestration
- [`src/tools/registry.py`](/src/tools/registry.py): tool registry and binding
- [`src/tools/local_safe.py`](/src/tools/local_safe.py): safe local tools
- [`src/tools/messaging.py`](/src/tools/messaging.py): outbound message tooling
- [`src/tools/remote_exec.py`](/src/tools/remote_exec.py): governed remote execution tool
- [`src/tools/delegation.py`](/src/tools/delegation.py): child-agent delegation tool
- [`src/tools/typed_actions.py`](/src/tools/typed_actions.py): canonical action identity and schemas
- [`src/policies/service.py`](/src/policies/service.py): policy checks, approvals, deterministic approve/revoke flows
- [`src/policies/quota.py`](/src/policies/quota.py): rate limiting and quota service

### Context, media, and delivery

- [`src/context/service.py`](/src/context/service.py): context assembly from transcript and derived records
- [`src/context/outbox.py`](/src/context/outbox.py): after-turn work orchestration
- [`src/memory/service.py`](/src/memory/service.py): durable memory extraction/storage
- [`src/retrieval/service.py`](/src/retrieval/service.py): retrieval rows and selection
- [`src/media/processor.py`](/src/media/processor.py): attachment normalization and storage
- [`src/media/extraction.py`](/src/media/extraction.py): attachment text extraction
- [`src/channels/dispatch.py`](/src/channels/dispatch.py): outbound dispatch and delivery persistence
- [`src/channels/adapters/webchat.py`](/src/channels/adapters/webchat.py): poll/stream capable adapter
- [`src/channels/adapters/slack.py`](/src/channels/adapters/slack.py): Slack adapter
- [`src/channels/adapters/telegram.py`](/src/channels/adapters/telegram.py): Telegram adapter

### Agents, delegation, sandboxing, and security

- [`src/agents/service.py`](/src/agents/service.py): agent/model/tool/policy profile lookup
- [`src/agents/bootstrap.py`](/src/agents/bootstrap.py): profile bootstrap/seeding
- [`src/delegations/service.py`](/src/delegations/service.py): child-session orchestration and delegation lifecycle
- [`src/sandbox/service.py`](/src/sandbox/service.py): sandbox selection and workspace rules
- [`src/security/signing.py`](/src/security/signing.py): request signing/verification
- [`apps/node_runner/policy.py`](/apps/node_runner/policy.py): node-runner admission checks
- [`apps/node_runner/executor.py`](/apps/node_runner/executor.py): command execution and audit recording

### Collaboration and observability

- [`src/sessions/collaboration.py`](/src/sessions/collaboration.py): takeover, pause/resume, assignment, notes
- [`src/observability/health.py`](/src/observability/health.py): liveness and readiness helpers
- [`src/observability/diagnostics.py`](/src/observability/diagnostics.py): operator diagnostics reads
- [`src/observability/audit.py`](/src/observability/audit.py): structured audit events
- [`src/observability/redaction.py`](/src/observability/redaction.py): masking/redaction
- [`src/observability/metrics.py`](/src/observability/metrics.py): metrics facade
- [`src/observability/tracing.py`](/src/observability/tracing.py): tracing facade

### Tests

- [`tests/test_api.py`](/tests/test_api.py): gateway and route behavior
- [`tests/test_runtime.py`](/tests/test_runtime.py): graph/runtime behavior
- [`tests/test_integration.py`](/tests/test_integration.py): end-to-end integration slices
- [`tests/test_provider_runtime.py`](/tests/test_provider_runtime.py): provider mode
- [`tests/test_spec_011.py`](/tests/test_spec_011.py) through [`tests/test_spec_017.py`](/tests/test_spec_017.py): later-spec coverage

## Important Persisted Records

The database contains the main durable system state in tables such as:

- sessions and messages
- inbound dedupe records
- execution runs and run leases
- tool audit events
- governance proposals, versions, approvals, and active resources
- outbound deliveries, attempts, and stream events
- agent profiles and model profiles
- attachment records and extraction rows
- summary snapshots, session memories, retrieval records, and context manifests
- delegation records and child-session links
- collaboration events and operator notes
- quota counters and stale-work recovery metadata
- node execution audits

The exact schema lives in [`src/db/models.py`](/src/db/models.py) and the migration history in [`migrations/versions`](/migrations/versions).

## Configuration

The application loads environment variables from a project-root `.env` file using the `PYTHON_CLAW_` prefix. The canonical settings model is [`src/config/settings.py`](/src/config/settings.py).

### Minimal local `.env`

This is enough for local development with the rule-based runtime:

```dotenv
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent

PYTHON_CLAW_RUNTIME_MODE=rule_based

PYTHON_CLAW_ADMIN_READS_REQUIRE_AUTH=true
PYTHON_CLAW_DIAGNOSTICS_REQUIRE_AUTH=true
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true
PYTHON_CLAW_OPERATOR_AUTH_BEARER_TOKEN=change-me
PYTHON_CLAW_INTERNAL_SERVICE_AUTH_TOKEN=change-me-internal
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=change-me
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=change-me-internal

PYTHON_CLAW_CHANNEL_ACCOUNTS=[{"channel_account_id":"acct","channel_kind":"slack","mode":"fake"},{"channel_account_id":"acct","channel_kind":"telegram","mode":"fake"},{"channel_account_id":"acct","channel_kind":"webchat","mode":"fake"}]
```

### Provider-backed runtime

To switch from the deterministic local runtime to an LLM-backed runtime:

```dotenv
PYTHON_CLAW_RUNTIME_MODE=provider
PYTHON_CLAW_LLM_PROVIDER=openai
PYTHON_CLAW_LLM_API_KEY=YOUR_KEY
PYTHON_CLAW_LLM_MODEL=gpt-4o-mini
PYTHON_CLAW_LLM_TIMEOUT_SECONDS=30
PYTHON_CLAW_LLM_MAX_RETRIES=1
PYTHON_CLAW_LLM_TEMPERATURE=0.2
PYTHON_CLAW_LLM_MAX_OUTPUT_TOKENS=700
PYTHON_CLAW_LLM_TOOL_CALL_MODE=auto
PYTHON_CLAW_LLM_MAX_TOOL_REQUESTS_PER_TURN=4
PYTHON_CLAW_LLM_DISABLE_TOOLS=false
```

If `provider` mode is selected without the required credentials, startup is expected to fail closed.

### Agent, policy, and tool profile binding

These settings became important once agent profiles and delegation landed:

```dotenv
PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent
PYTHON_CLAW_POLICY_PROFILES=[{"key":"default","remote_execution_enabled":false,"denied_capability_names":[],"delegation_enabled":false}]
PYTHON_CLAW_TOOL_PROFILES=[{"key":"default","allowed_capability_names":["echo_text","remote_exec","send_message"]}]
PYTHON_CLAW_HISTORICAL_AGENT_PROFILE_OVERRIDES=[]
```

What they control:

- which agent owns newly created sessions
- whether remote execution is allowed
- whether delegation is allowed
- which tools are exposed to a given agent
- how historical agent IDs are mapped onto explicit runtime profiles

### Channel accounts

`PYTHON_CLAW_CHANNEL_ACCOUNTS` is a JSON array of typed account definitions:

```dotenv
PYTHON_CLAW_CHANNEL_ACCOUNTS=[
  {"channel_account_id":"webchat-demo","channel_kind":"webchat","mode":"fake"},
  {"channel_account_id":"slack-demo","channel_kind":"slack","mode":"fake"},
  {"channel_account_id":"telegram-demo","channel_kind":"telegram","mode":"fake"}
]
```

Rules:

- `mode=fake` is intended for local development and CI.
- `mode=real` requires channel-specific credentials.
- real Slack accounts require `outbound_token` and `signing_secret`
- real Telegram accounts require `outbound_token` and `webhook_secret`
- real webchat accounts require `webchat_client_token`

### Remote execution and node-runner

For local in-process behavior the defaults are enough. For the separate `node-runner` service used by Docker examples and production-style deployment, set:

```dotenv
PYTHON_CLAW_REMOTE_EXECUTION_ENABLED=true
PYTHON_CLAW_NODE_RUNNER_MODE=http
PYTHON_CLAW_NODE_RUNNER_BASE_URL=http://node-runner:8010
PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID=local-demo-key
PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET=local-demo-signing-secret
PYTHON_CLAW_NODE_RUNNER_INTERNAL_BEARER_TOKEN=local-demo-node-token
PYTHON_CLAW_NODE_RUNNER_REQUEST_TTL_SECONDS=30
PYTHON_CLAW_NODE_RUNNER_TIMEOUT_CEILING_SECONDS=30
PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES=/usr/bin/curl,/bin/echo,/usr/bin/env,/usr/local/bin/python3
```

Key point: local development can use `in_process`, but the Compose-based deployment example uses `http` mode with a dedicated node-runner service.

### Retrieval, memory, and attachment understanding

```dotenv
PYTHON_CLAW_RETRIEVAL_ENABLED=true
PYTHON_CLAW_RETRIEVAL_STRATEGY_ID=lexical-v1
PYTHON_CLAW_RETRIEVAL_TOTAL_ITEMS=4
PYTHON_CLAW_RETRIEVAL_MEMORY_ITEMS=2
PYTHON_CLAW_RETRIEVAL_ATTACHMENT_ITEMS=2
PYTHON_CLAW_RETRIEVAL_OTHER_ITEMS=2
PYTHON_CLAW_MEMORY_ENABLED=true
PYTHON_CLAW_MEMORY_STRATEGY_ID=memory-v1
PYTHON_CLAW_ATTACHMENT_EXTRACTION_ENABLED=true
PYTHON_CLAW_ATTACHMENT_EXTRACTION_STRATEGY_ID=attachment-v1
PYTHON_CLAW_ATTACHMENT_SAME_RUN_FAST_PATH_ENABLED=true
```

### Streaming and webchat

```dotenv
PYTHON_CLAW_RUNTIME_STREAMING_ENABLED=true
PYTHON_CLAW_RUNTIME_STREAMING_CHUNK_CHARS=24
PYTHON_CLAW_WEBCHAT_SSE_ENABLED=true
PYTHON_CLAW_WEBCHAT_SSE_REPLAY_LIMIT=100
```

### Collaboration, auth, and production hardening

The later specs added important fail-closed settings:

```dotenv
PYTHON_CLAW_ADMIN_READS_REQUIRE_AUTH=true
PYTHON_CLAW_DIAGNOSTICS_REQUIRE_AUTH=true
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true
PYTHON_CLAW_AUTH_FAIL_CLOSED_IN_PRODUCTION=true
PYTHON_CLAW_OPERATOR_AUTH_BEARER_TOKEN=operator-token
PYTHON_CLAW_INTERNAL_SERVICE_AUTH_TOKEN=internal-token
PYTHON_CLAW_OPERATOR_PRINCIPAL_HEADER_NAME=X-Operator-Id
PYTHON_CLAW_INTERNAL_SERVICE_PRINCIPAL_HEADER_NAME=X-Internal-Service-Principal

PYTHON_CLAW_RATE_LIMITS_ENABLED=true
PYTHON_CLAW_INBOUND_REQUESTS_PER_MINUTE_PER_CHANNEL_ACCOUNT=20
PYTHON_CLAW_ADMIN_REQUESTS_PER_MINUTE_PER_OPERATOR=30
PYTHON_CLAW_APPROVAL_ACTION_REQUESTS_PER_MINUTE_PER_SESSION=20
PYTHON_CLAW_PROVIDER_TOKENS_PER_HOUR_PER_AGENT=200000
PYTHON_CLAW_PROVIDER_REQUESTS_PER_MINUTE_PER_MODEL=120
```

## Local Development Setup

### Prerequisites

- Python `3.11+`
- `uv`
- Docker / Docker Compose

### 1. Install dependencies

```bash
uv sync --group dev
```

### 2. Create `.env`

If the repository includes an example env file, start from it. Otherwise create `.env` manually using the minimal local settings above.

### 3. Start infrastructure

[`docker-compose.yml`](/docker-compose.yml) starts only PostgreSQL and Redis:

```bash
docker compose --env-file .env up -d
```

It defines:

- `postgres` on `${PYTHON_CLAW_POSTGRES_PORT:-5432}`
- `redis` on `${PYTHON_CLAW_REDIS_PORT:-6379}`

### 4. Run migrations

```bash
uv run alembic upgrade head
```

### 5. Start the gateway

```bash
uv run uvicorn apps.gateway.main:app --reload
```

Gateway URL:

```text
http://127.0.0.1:8000
```

### 6. Start the node-runner if you are testing remote execution

```bash
uv run uvicorn apps.node_runner.main:app --reload --port 8010
```

### 7. Process queued runs

Single-pass worker execution:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Continuous worker loop:

```bash
uv run python scripts/worker_loop.py
```

### 8. Smoke-check the service

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready -H 'Authorization: Bearer change-me'
curl http://127.0.0.1:8000/diagnostics/runs -H 'Authorization: Bearer change-me'
```

## Docker Deployment Setup

There are two Compose files and they are meant to be used together.

### `docker-compose.yml`

[`docker-compose.yml`](/docker-compose.yml) defines infrastructure only:

- `postgres`
- `redis`

### `docker-compose.app.yml`

[`docker-compose.app.yml`](/docker-compose.app.yml) defines application services:

- `gateway` on port `8000`
- `worker`
- `node-runner` on port `8010`

All three app services build from the repository `Dockerfile`, load `.env`, and override `PYTHON_CLAW_DATABASE_URL` to point at the Compose `postgres` service.

### Bring up the full stack

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml up -d --build
```

Run migrations inside the app image:

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml \
  run --rm gateway uv run alembic upgrade head
```

Inspect containers:

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml ps
docker logs -f python-claw-worker
```

This is the correct deployment flow to reference when running the app stack in Docker.

## Running a Test Solution

For the most complete example, use [`example/examplev5.md`](/example/examplev5.md). That document demonstrates a full local Docker-based scenario with:

- webchat UI
- provider-backed agents
- delegation
- approval-gated remote execution
- node-runner execution
- callback continuation
- generated artifacts
- email notification

The short version of that flow is:

1. configure `.env` for `provider` mode and `NODE_RUNNER_MODE=http`
2. start MailDev and the local webhook receiver on the host
3. start the combined Compose stack
4. run migrations in the gateway container
5. open the browser webchat UI
6. send a deployment-style request
7. approve the proposed `remote_exec`
8. send the callback
9. request the generated report and follow-up notification

Reference commands from the example:

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml up -d --build
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml run --rm gateway uv run alembic upgrade head
docker logs -f python-claw-worker
```

If you want the exact end-to-end walkthrough, including the sample `.env`, chat prompts, and callback steps, use [`example/examplev5.md`](/example/examplev5.md) directly.

## Main HTTP Surfaces

### Core ingress

- `POST /inbound/message`

### Provider ingress

- `POST /providers/slack/events`
- `POST /providers/telegram/webhook/{channel_account_id}`
- `POST /providers/webchat/accounts/{channel_account_id}/messages`

### Webchat reads

- `GET /providers/webchat/accounts/{channel_account_id}/stream`
- `GET /providers/webchat/accounts/{channel_account_id}/poll`

### Session, run, and operator reads

- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/governance/pending`
- `GET /runs/{run_id}`
- `GET /sessions/{session_id}/runs`
- `GET /agents`
- `GET /agents/{agent_id}`
- `GET /agents/{agent_id}/sessions`
- `GET /model-profiles`
- `GET /model-profiles/{profile_key}`

### Diagnostics and health

- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /diagnostics/runs`
- `GET /diagnostics/runs/{run_id}`
- `GET /diagnostics/sessions/{session_id}/continuity`
- `GET /diagnostics/outbox-jobs`
- `GET /diagnostics/node-executions`
- `GET /diagnostics/deliveries`
- `GET /diagnostics/attachments`

### Internal node-runner

- `POST /internal/node/exec`
- `GET /internal/node/exec/{request_id}`

## Running Tests

Run the full suite:

```bash
uv run pytest
```

Useful targeted runs:

```bash
uv run pytest tests/test_api.py
uv run pytest tests/test_runtime.py
uv run pytest tests/test_integration.py
uv run pytest tests/test_provider_runtime.py
uv run pytest tests/test_typed_tool_schemas.py
uv run pytest tests/test_spec_011.py
uv run pytest tests/test_spec_014.py
uv run pytest tests/test_spec_015.py
uv run pytest tests/test_spec_016.py
uv run pytest tests/test_spec_017.py
```

The tests primarily rely on local fixtures, SQLite-style temporary state, and fakes, so they do not require a live provider account.

## Spec Reference

The repository specs are in [`specs`](/specs). The current code structure maps broadly like this:

- `001-005`: ingress, sessions, runtime, governance, queueing
- `006-008`: node-runner, channels/media, observability
- `009-011`: provider runtime, typed tools, retrieval/memory/attachments
- `012-013`: production channel integration and streaming
- `014-015`: agent profiles and delegation
- `016-017`: human handoff, auth hardening, quotas, retries, recovery

When in doubt, the code is authoritative, the migrations describe durable shape, and the specs explain why the system is structured that way.
