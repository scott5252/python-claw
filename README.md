# python-claw

`python-claw` is the foundation for a gateway-first assistant runtime inspired by the `001-gateway-sessions`, `002-runtime-tools`, and `003-capability-governance` specs in [`/specs/001-gateway-sessions/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/001-gateway-sessions/spec.md), [`/specs/002-runtime-tools/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/002-runtime-tools/spec.md), and [`/specs/003-capability-governance/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/003-capability-governance/spec.md). The current implementation focuses on these things:

- a single FastAPI gateway entrypoint
- deterministic routing into durable sessions
- append-only transcript persistence
- PostgreSQL-safe idempotency semantics for inbound messages
- a gateway-owned single-turn assistant runtime
- a typed, policy-aware local tool registry
- append-only storage for tool artifacts and audit events
- exact-match capability approvals for governed actions
- transcript-linked governance events plus normalized approval and activation state

This README is written for a developer who needs to understand what was implemented, how to run it, and how to test it locally.

## Current Implementation At A Glance

The application exposes:

- `GET /health`
- `POST /inbound/message`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/messages`

The implemented flow for `POST /inbound/message` is:

1. validate and normalize routing input
2. claim the dedupe identity for `(channel_kind, channel_account_id, external_message_id)`
3. resolve or create the canonical session
4. append one inbound `user` message
5. finalize the dedupe record with the resulting `session_id` and `message_id`
6. invoke the gateway-owned single-turn assistant runtime
7. append one assistant transcript message
8. persist any runtime tool artifacts and audit events created during the turn

That behavior is implemented across:

- gateway app bootstrap: [`apps/gateway/main.py`](/Users/scottcornell/src/projects/python-claw/apps/gateway/main.py)
- inbound/admin endpoints: [`apps/gateway/api/inbound.py`](/Users/scottcornell/src/projects/python-claw/apps/gateway/api/inbound.py), [`apps/gateway/api/admin.py`](/Users/scottcornell/src/projects/python-claw/apps/gateway/api/admin.py)
- routing rules: [`src/routing/service.py`](/Users/scottcornell/src/projects/python-claw/src/routing/service.py)
- orchestration service: [`src/sessions/service.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/service.py)
- graph runtime: [`src/graphs/state.py`](/Users/scottcornell/src/projects/python-claw/src/graphs/state.py), [`src/graphs/nodes.py`](/Users/scottcornell/src/projects/python-claw/src/graphs/nodes.py), [`src/graphs/assistant_graph.py`](/Users/scottcornell/src/projects/python-claw/src/graphs/assistant_graph.py)
- tool and policy wiring: [`src/tools/registry.py`](/Users/scottcornell/src/projects/python-claw/src/tools/registry.py), [`src/tools/local_safe.py`](/Users/scottcornell/src/projects/python-claw/src/tools/local_safe.py), [`src/tools/messaging.py`](/Users/scottcornell/src/projects/python-claw/src/tools/messaging.py), [`src/policies/service.py`](/Users/scottcornell/src/projects/python-claw/src/policies/service.py)
- typed capability governance: [`src/tools/typed_actions.py`](/Users/scottcornell/src/projects/python-claw/src/tools/typed_actions.py), [`src/capabilities/activation.py`](/Users/scottcornell/src/projects/python-claw/src/capabilities/activation.py)
- model adapter contract: [`src/providers/models.py`](/Users/scottcornell/src/projects/python-claw/src/providers/models.py)
- audit sink: [`src/observability/audit.py`](/Users/scottcornell/src/projects/python-claw/src/observability/audit.py)
- persistence layer: [`src/sessions/repository.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/repository.py)
- idempotency lifecycle: [`src/gateway/idempotency.py`](/Users/scottcornell/src/projects/python-claw/src/gateway/idempotency.py)
- database schema: [`src/db/models.py`](/Users/scottcornell/src/projects/python-claw/src/db/models.py)
- migrations: [`migrations/versions/20260322_001_gateway_sessions.py`](/Users/scottcornell/src/projects/python-claw/migrations/versions/20260322_001_gateway_sessions.py), [`migrations/versions/20260322_002_runtime_tools.py`](/Users/scottcornell/src/projects/python-claw/migrations/versions/20260322_002_runtime_tools.py), [`migrations/versions/20260322_003_capability_governance.py`](/Users/scottcornell/src/projects/python-claw/migrations/versions/20260322_003_capability_governance.py)

## Spec 002 Runtime Tools

Spec 002 adds the first assistant execution path to the project. The key idea is that the gateway still owns the request lifecycle, but after the inbound user message is stored it now invokes a single-turn runtime that can either:

- return plain assistant text
- call a safe local tool
- prepare a runtime-owned outbound intent without calling a transport directly

The runtime is intentionally narrow in this spec:

- one turn only
- local tools only
- no background workflows
- no remote execution
- no transport dispatch from the graph

### What A Developer Needs To Know

The important implementation boundary is:

- `SessionService` is still the entry point for inbound work
- `AssistantGraph` is invoked from the service layer, not from FastAPI routes directly
- `ModelAdapter` returns a typed `ModelTurnResult`
- `ToolRegistry` binds tools per turn using `ToolRuntimeContext`
- `SessionRepository` persists assistant messages plus append-only runtime artifacts
- `ToolAuditSink` records execution attempts and outcomes separately from transcript rows

In the current workspace, the default runtime behavior is intentionally simple:

- `echo <text>` invokes `echo_text`
- `send <text>` invokes `send_message`
- anything else returns `Received: <text>`

That behavior lives in [`src/providers/models.py`](/Users/scottcornell/src/projects/python-claw/src/providers/models.py). It is a local rule-based adapter used to prove the runtime contracts and test paths before a real provider is introduced.

### Runtime Flow

For each accepted inbound message, the application now does this:

1. normalize routing and claim dedupe
2. reuse or create the session
3. append the inbound `user` message
4. finalize the dedupe record
5. build `AssistantState` from the current turn and recent transcript history
6. bind policy-allowed tools for this runtime context
7. execute any requested tools and record append-only artifacts
8. append the final `assistant` message

The append-only runtime records introduced by Spec 002 are:

- `session_artifacts` for `tool_proposal`, `tool_result`, and `outbound_intent`
- `tool_audit_events` for execution attempt and result auditing

### Files To Read First

If you want the shortest path to understanding Spec 002, read:

1. [`specs/002-runtime-tools/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/002-runtime-tools/spec.md)
2. [`src/sessions/service.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/service.py)
3. [`src/graphs/nodes.py`](/Users/scottcornell/src/projects/python-claw/src/graphs/nodes.py)
4. [`src/tools/registry.py`](/Users/scottcornell/src/projects/python-claw/src/tools/registry.py)
5. [`src/sessions/repository.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/repository.py)
6. [`tests/test_runtime.py`](/Users/scottcornell/src/projects/python-claw/tests/test_runtime.py) and [`tests/test_integration.py`](/Users/scottcornell/src/projects/python-claw/tests/test_integration.py)

## Spec 003 Capability Governance

Spec 003 adds a capability-governance layer on top of the single-turn runtime from Spec 002. The key idea is that the gateway still owns the turn lifecycle, but some capabilities are now treated as governed typed actions that cannot be exposed or executed until the user has approved the exact action and parameter payload.

The runtime is still intentionally narrow in this spec:

- approval is exact-match only
- approval scope is session-and-agent scoped
- activation stays on the gateway-owned path
- governed waits are persisted before the turn exits
- revocation affects future visibility and future execution

### What A Developer Needs To Know

The important implementation boundary is:

- `PolicyService` now classifies turns before gated tool exposure
- `typed_actions.py` defines which capabilities are governed typed actions
- `SessionRepository` persists proposals, versions, approvals, active resources, and governance transcript events
- `ActivationController` is the sole activation path for approved capabilities
- `AssistantGraph` and graph nodes exit into persisted approval wait when governance blocks execution
- tool visibility is rebuilt from current approval state on each turn
- execution still re-checks approval even when a governed tool is visible

In the current workspace, the governance behavior is intentionally concrete:

- `echo_text` remains a safe, always-available local action
- `send_message` is the governed action used to prove the approval flow
- `send <text>` creates a proposal when no matching approval exists
- `approve <proposal_id>` approves and activates that exact proposal
- `revoke <proposal_id>` revokes it for later turns

### Runtime Flow

For a governed request without approval, the application now does this:

1. normalize routing and claim dedupe
2. reuse or create the session
3. append the inbound `user` message
4. finalize the dedupe record
5. classify the turn before gated tool exposure
6. persist a resource proposal, immutable version, and governance transcript events
7. append an `assistant` message explaining that approval is required

For a later approval turn, the application now does this:

1. classify `approve <proposal_id>` as an approval decision
2. persist the exact approval record
3. activate the approved resource through `ActivationController`
4. append governance transcript events for approval and activation
5. append an `assistant` message confirming approval and activation

For a later retry of the original request, the application now does this:

1. rebuild policy context from active approvals
2. expose the governed tool only if the exact approval matches
3. re-check the approval at execution time
4. persist normal runtime artifacts such as `tool_proposal`, `outbound_intent`, and `tool_result`

The governance records introduced by Spec 003 are:

- `governance_transcript_events` for proposal creation, approval request, approval decision, activation result, and revocation result
- `resource_proposals` for proposal state
- `resource_versions` for immutable proposed content versions
- `resource_approvals` for exact approval matching and revocation state
- `active_resources` for activation and revocation state

### Files To Read First

If you want the shortest path to understanding Spec 003, read:

1. [`specs/003-capability-governance/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/003-capability-governance/spec.md)
2. [`src/tools/typed_actions.py`](/Users/scottcornell/src/projects/python-claw/src/tools/typed_actions.py)
3. [`src/policies/service.py`](/Users/scottcornell/src/projects/python-claw/src/policies/service.py)
4. [`src/sessions/repository.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/repository.py)
5. [`src/graphs/nodes.py`](/Users/scottcornell/src/projects/python-claw/src/graphs/nodes.py)
6. [`tests/test_runtime.py`](/Users/scottcornell/src/projects/python-claw/tests/test_runtime.py) and [`tests/test_integration.py`](/Users/scottcornell/src/projects/python-claw/tests/test_integration.py)

## How To Read The Code

If you want the fastest path through the codebase, read it in this order:

1. [`specs/001-gateway-sessions/spec.md`](/Users/scottcornell/src/projects/python-claw/specs/001-gateway-sessions/spec.md) for the intended contract.
2. [`apps/gateway/main.py`](/Users/scottcornell/src/projects/python-claw/apps/gateway/main.py) to see how the FastAPI app is assembled.
3. [`apps/gateway/api/inbound.py`](/Users/scottcornell/src/projects/python-claw/apps/gateway/api/inbound.py) to see the main write path.
4. [`src/sessions/service.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/service.py) to understand the business flow.
5. [`src/routing/service.py`](/Users/scottcornell/src/projects/python-claw/src/routing/service.py) for deterministic routing and session-key composition.
6. [`src/gateway/idempotency.py`](/Users/scottcornell/src/projects/python-claw/src/gateway/idempotency.py) for `claimed` vs `completed` dedupe behavior.
7. [`src/sessions/repository.py`](/Users/scottcornell/src/projects/python-claw/src/sessions/repository.py) and [`src/db/models.py`](/Users/scottcornell/src/projects/python-claw/src/db/models.py) for storage details.
8. [`tests/`](/Users/scottcornell/src/projects/python-claw/tests) to see the expected behavior end to end.

### Request Lifecycle

For a direct message:

- routing input is trim-normalized
- `channel_kind` must already be lowercase
- exactly one of `peer_id` or `group_id` must be present
- direct conversations always map to scope `direct` and scope name `main`
- the canonical direct session key is `{channel_kind}:{channel_account_id}:direct:{peer_id}:main`

For a group message:

- scope is `group`
- scope name is the `group_id`
- the canonical group session key is `{channel_kind}:{channel_account_id}:group:{group_id}`

### Persistence Model

The current database tables are:

- `sessions`: canonical session identity and routing metadata
- `messages`: append-only transcript rows
- `inbound_dedupe`: persisted idempotency claims and replay metadata
- `session_artifacts`: append-only runtime artifact rows
- `tool_audit_events`: append-only execution audit rows
- `governance_transcript_events`: append-only transcript-linked governance history
- `resource_proposals`: proposal lifecycle state
- `resource_versions`: immutable proposed content versions
- `resource_approvals`: exact-match approval and revocation state
- `active_resources`: activation and revocation state

Important current behaviors:

- duplicate deliveries return the original `session_id` and `message_id`
- a fresh duplicate that hits an in-progress non-stale claim returns `409`
- stale `claimed` dedupe rows are recoverable after `dedupe_stale_after_seconds`
- transcript pagination is cursor-based with `before_message_id`

## Environment Setup

### 1. Python And `uv`

This project requires Python `3.11+` and now uses `uv` for environment and dependency management.

```bash
uv python install 3.11
uv sync --group dev
```

If you already have a compatible Python `>=3.11` installed, `uv sync --group dev` is enough. `uv` will create and manage the local `.venv` automatically.

If you prefer an activated shell after syncing, use:

```bash
source .venv/bin/activate
```

### 2. Project `.env`

This project uses `python-dotenv` to load configuration from a project-root `.env` file for application runtime and Alembic migrations.

A starter [`.env`](/Users/scottcornell/src/projects/python-claw/.env) is included with local development defaults:

```dotenv
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
PYTHON_CLAW_POSTGRES_DB=openassistant
PYTHON_CLAW_POSTGRES_USER=openassistant
PYTHON_CLAW_POSTGRES_PASSWORD=openassistant
PYTHON_CLAW_POSTGRES_PORT=5432
PYTHON_CLAW_REDIS_PORT=6379
```

Update that file before running the stack if you want different local ports, credentials, or database names.

For a brand new checkout, the quickest happy path is:

```bash
uv sync --group dev
docker compose --env-file .env up -d
uv run alembic upgrade head
uv run uvicorn apps.gateway.main:app --reload
```

### 3. PostgreSQL And Redis

A local `docker-compose.yml` is included for developer infrastructure:

- PostgreSQL `17`
- Redis `7`

Start both services with the project `.env` file:

```bash
docker compose --env-file .env up -d
```

Useful checks:

```bash
docker compose ps
docker compose logs postgres
docker compose logs redis
```

The default container credentials are:

- PostgreSQL database: `openassistant`
- PostgreSQL user: `openassistant`
- PostgreSQL password: `openassistant`
- PostgreSQL port: `5432`
- Redis port: `6379`

The matching SQLAlchemy PostgreSQL URL is:

```bash
postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
```

Note on current status: Redis is provisioned for the wider architecture, but this spec implementation does not yet use Redis in the request path. Right now the gateway uses the configured SQL database plus in-process FastAPI services.

### 4. Application Configuration

Settings are defined in [`src/config/settings.py`](/Users/scottcornell/src/projects/python-claw/src/config/settings.py) and load from the project `.env` file through `python-dotenv`, using environment variable names prefixed with `PYTHON_CLAW_`.

The main variables you will care about are:

- `PYTHON_CLAW_DATABASE_URL`
- `PYTHON_CLAW_DEDUPE_RETENTION_DAYS`
- `PYTHON_CLAW_DEDUPE_STALE_AFTER_SECONDS`
- `PYTHON_CLAW_MESSAGES_PAGE_DEFAULT_LIMIT`
- `PYTHON_CLAW_MESSAGES_PAGE_MAX_LIMIT`

Compose-specific values in the same `.env` file are:

- `PYTHON_CLAW_POSTGRES_DB`
- `PYTHON_CLAW_POSTGRES_USER`
- `PYTHON_CLAW_POSTGRES_PASSWORD`
- `PYTHON_CLAW_POSTGRES_PORT`
- `PYTHON_CLAW_REDIS_PORT`

If you do not set `PYTHON_CLAW_DATABASE_URL`, the app now defaults to:

```bash
postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
```

That matches the bundled Docker Compose PostgreSQL service, so the application and Alembic target the same local database by default.

## Database Setup

Alembic is configured in [`alembic.ini`](/Users/scottcornell/src/projects/python-claw/alembic.ini) and [`migrations/env.py`](/Users/scottcornell/src/projects/python-claw/migrations/env.py).

Alembic now reads the database URL from the same project `.env` file as the application and falls back to the same PostgreSQL local-development URL when the variable is unset. For local Docker Compose, the default [`.env`](/Users/scottcornell/src/projects/python-claw/.env) already points at:

```bash
postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
```

With PostgreSQL running, apply the schema:

```bash
uv run alembic upgrade head
```

After the migration runs, the database should contain:

- `sessions`
- `messages`
- `inbound_dedupe`
- `session_artifacts`
- `tool_audit_events`

## How To Run The Application

With dependencies synced, `.env` configured, and Docker services running:

```bash
uv run uvicorn apps.gateway.main:app --reload
```

By default the app will be available at:

```text
http://127.0.0.1:8000
```

Quick smoke checks:

```bash
curl http://127.0.0.1:8000/health
```

Example inbound request for a direct conversation:

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

Example response:

```json
{
  "session_id": "2f9f0d1f-1ab2-4d55-a4d8-0fcbf0fd1df7",
  "message_id": 1,
  "dedupe_status": "accepted"
}
```

Runtime smoke test using the built-in local echo tool:

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

Runtime smoke test using the outbound-intent tool:

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

Read back the session metadata:

```bash
curl http://127.0.0.1:8000/sessions/<session_id>
```

Read back transcript history:

```bash
curl "http://127.0.0.1:8000/sessions/<session_id>/messages?limit=50"
```

## How To Test The Code

Sync dev dependencies first:

```bash
uv sync --group dev
```

Run the full test suite:

```bash
uv run pytest
```

The tests currently use temporary SQLite databases created by pytest fixtures, so they do not require local PostgreSQL or Redis to pass.

### What The Tests Cover

- [`tests/test_routing.py`](/Users/scottcornell/src/projects/python-claw/tests/test_routing.py): routing normalization, lowercase `channel_kind`, and session-key composition
- [`tests/test_idempotency.py`](/Users/scottcornell/src/projects/python-claw/tests/test_idempotency.py): first-claim, finalize, duplicate replay, conflict, and stale-claim recovery
- [`tests/test_repository.py`](/Users/scottcornell/src/projects/python-claw/tests/test_repository.py): session reuse, append-order message paging, and append-only runtime artifacts
- [`tests/test_runtime.py`](/Users/scottcornell/src/projects/python-claw/tests/test_runtime.py): graph branching, policy-aware tool binding, and no fabricated success on tool failure
- [`tests/test_api.py`](/Users/scottcornell/src/projects/python-claw/tests/test_api.py): inbound acceptance, duplicate replay, invalid routing, session history with assistant replies, and dedupe isolation across channels
- [`tests/test_integration.py`](/Users/scottcornell/src/projects/python-claw/tests/test_integration.py): restart-safe session reuse, replay after restart, stale recovery, tool-use flows, outbound intent creation, policy denial, and failure-path runtime behavior

Useful commands during development:

```bash
uv run pytest tests/test_runtime.py
uv run pytest tests/test_api.py
uv run pytest tests/test_integration.py
uv run pytest tests/test_routing.py -q
```

## Current Limitations

This repository is intentionally still at the foundation stage of the broader architecture. In its current form:

- the assistant runtime is single-turn only
- the default model is a local rule-based adapter, not a provider-backed model
- tools are local and safe only; there is no remote execution or approval workflow yet
- outbound messaging stops at persisted intent creation; no transport dispatch layer exists yet
- Redis is provisioned, but not yet used by the application code
- tests validate behavior mostly against SQLite fixtures rather than a live PostgreSQL instance

That means the code is already useful for validating routing, session identity, transcript persistence, idempotent webhook handling, and the first runtime/tooling slice, but it is not yet a full multi-provider, multi-turn assistant platform.
