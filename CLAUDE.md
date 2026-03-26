# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Setup:**
```bash
uv sync --group dev
docker compose --env-file .env up -d   # Start PostgreSQL 17 + Redis 7
uv run alembic upgrade head            # Run migrations
```

**Run services:**
```bash
uv run uvicorn apps.gateway.main:app --reload                        # Gateway API (port 8000)
uv run uvicorn apps.node_runner.main:app --reload --port 8010        # Node runner (port 8010)
```

**Tests:**
```bash
uv run pytest                          # Full test suite
uv run pytest tests/test_api.py        # Single test file
uv run pytest tests/test_api.py::test_function_name  # Single test
```

**Database migrations:**
```bash
uv run alembic revision --autogenerate -m "description"  # New migration
uv run alembic upgrade head                              # Apply migrations
```

## Architecture

`python-claw` is a gateway-first AI assistant platform. All work enters through the Gateway API, is persisted durably, and executed by a background worker.

### Request lifecycle

1. `POST /inbound/message` → Gateway validates, dedupes, resolves/creates session, queues a run → returns `202` with `session_id`, `run_id`, `trace_id`
2. Worker calls `run_once()` → claims a run → normalizes attachments → executes an assistant turn
3. Assistant graph decides: generate text or invoke tools
4. Worker persists results and dispatches outbound messages via channel adapters

### Service boundaries

| Layer | Location | Role |
|-------|----------|------|
| Gateway API | `apps/gateway/` | Inbound validation, routing, session creation, run queuing |
| Worker | `apps/worker/jobs.py` | Polls queue, owns execution lifecycle |
| Node Runner | `apps/node_runner/` | Isolated execution service for privileged tools (signed requests) |
| Assistant Graph | `src/graphs/` | Decision flow — rule-based or provider-backed (OpenAI) LLM turns |
| Sessions | `src/sessions/` | Session + message persistence, concurrency control |
| Routing | `src/routing/` | Deterministic routing rules (channel/peer/group → session) |
| Jobs | `src/jobs/` | Run state machine, worker claim/lease logic |
| Tools | `src/tools/` | Registry, typed contracts, local/remote tool implementations |
| Policies | `src/policies/` | Approval-gated actions, capability governance |
| Channels | `src/channels/` | Channel-agnostic dispatcher + adapters (webchat, Slack, Telegram) |
| Media | `src/media/` | Attachment normalization and safe storage |
| Observability | `src/observability/` | Structured logging, audit, diagnostics, redaction, health |
| Providers | `src/providers/` | LLM backend abstraction (OpenAI integration) |
| Context | `src/context/` | Transcript summaries, manifests, outbox deferred work |
| Sandbox | `src/sandbox/` | Per-agent execution profile resolution |

### Key patterns

- **Idempotency:** Gateway tracks idempotency keys; duplicate messages are silently deduped (`src/gateway/idempotency.py`)
- **Lane-based concurrency:** Sessions are locked by "lane" to prevent concurrent runs on the same session (`src/sessions/concurrency.py`)
- **Backend-owned prompts:** In provider mode, `src/graphs/prompts.py` assembles the full prompt — the caller never controls prompt construction
- **Signed node-runner requests:** Requests to the node runner are HMAC-signed (`src/security/signing.py`) for isolation
- **Channel adapters:** All outbound delivery goes through `src/channels/dispatch.py` which routes to thin adapter implementations; adding a new channel means implementing `ChannelAdapter` base class

### Configuration

All settings are `PYTHON_CLAW_*` environment variables, modeled in `src/config/settings.py`. See `env_settings.md` for full documentation.

### Database

SQLAlchemy ORM models in `src/db/models.py`. Migrations in `migrations/` (Alembic). Key tables: `sessions`, `messages`, `execution_runs`, `tool_audit_events`, `outbound_deliveries`, `node_execution_audits`.

### Specifications

`specs/` contains the 9 progressive specs (001–009) that define what each phase delivered. When implementing new behavior, check if a relevant spec exists for design intent.
