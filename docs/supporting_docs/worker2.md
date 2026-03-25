# Worker Operations

This document explains what is needed to keep background work running continuously in this project.

## Short Answer

Today, this repo ships a one-shot worker entrypoint:

- `apps/worker/jobs.py::run_once()`

That function claims at most one eligible `execution_runs` row, processes it, commits, and exits.

So if you want the worker running all the time, you need a long-lived process that repeatedly calls `run_once()` instead of invoking it manually from the terminal.

## What The Worker Does

The gateway accepts inbound work and stores it durably in PostgreSQL.
The worker is responsible for:

- claiming queued `execution_runs`
- enforcing per-session and global concurrency leases
- rebuilding runtime state from durable transcript data
- running the assistant graph
- dispatching outbound messages
- recording completion, failure, or retry state

This is queue-consumer behavior, not request/response web-server behavior.

## Is This A Cron Job Like OpenClaw?

Not exactly.

There are two different background patterns in this codebase:

1. A continuous execution worker
2. A scheduler for time-based jobs

The execution worker is not a cron system. It should behave like a durable queue consumer that polls for eligible work and processes it as soon as it appears.

The scheduler side is the cron-like part. This project already has scheduler concepts such as:

- `scheduled_jobs`
- `scheduled_job_fires`
- `apps/worker/scheduler.py::submit_job_once()`

That scheduler path is meant for time-based triggers. It creates work that eventually becomes a normal queued `execution_runs` row. In other words:

- scheduler = "create work at a scheduled time"
- worker = "consume queued work continuously"

That is broadly similar to OpenClaw's separation of scheduler-triggered work from worker execution.

## What Is Missing Today

The current repo does not appear to include a built-in always-on worker command yet.

It has:

- a one-shot execution worker entrypoint in `apps/worker/jobs.py`
- a one-shot scheduler submission helper in `apps/worker/scheduler.py`

It does not currently provide:

- a long-running worker loop
- a packaged service command like `uv run python -m apps.worker.run`
- a process supervisor config in the repo for `systemd`, `launchd`, or `supervisord`

## What You Need For A Continuous Worker

To run the worker all the time, you need these pieces:

### 1. Shared durable infrastructure

The worker needs the same backing services as the gateway:

- PostgreSQL
- the same `.env` configuration
- applied Alembic migrations

At minimum, the worker must be able to load:

- `PYTHON_CLAW_DATABASE_URL`

And if your runs can use those features, it also needs the same settings for:

- remote execution
- media storage
- signing keys
- diagnostics and observability

### 2. A long-lived worker loop

You need a small process that:

- loads settings once
- repeatedly opens a DB session
- calls `run_once()`
- sleeps briefly when no run is available
- logs exceptions instead of dying silently
- handles shutdown signals cleanly

Conceptually:

```python
while True:
    run_id = run_once()
    if run_id is None:
        sleep(short_interval)
```

That is the missing runtime wrapper around the existing worker logic.

### 3. A process supervisor

Once you have a long-lived worker command, it should be managed by something that restarts it if it crashes.

Typical choices:

- `systemd` on Linux
- `launchd` on macOS
- `supervisord`
- a Docker Compose service
- a container orchestrator such as Kubernetes

For local development, a simple terminal loop is enough.
For anything persistent, use a supervisor.

### 4. Optional horizontal scaling

This design supports multiple workers because run claiming is backed by database state and lease tables.

The main relevant setting is:

- `PYTHON_CLAW_EXECUTION_RUN_GLOBAL_CONCURRENCY`

Even with multiple worker processes, the app still uses durable claim and lease logic to avoid unsafe overlap.

## Recommended Operating Model

For a fuller always-on setup, the intended shape is:

- one gateway API process
- one or more continuous execution workers
- a scheduler process for time-based jobs
- a node runner when remote execution is enabled

There is also an outbox path in the codebase for summary and continuity follow-up work. If that becomes operationally important, it should eventually run as its own continuous worker too rather than being treated as manual maintenance.

## Local Development Options

If you only want a lightweight local solution, you have two options:

### Option 1: Keep using manual runs

This is the current demo flow.
It is simple and good for understanding the system.

### Option 2: Add a small polling wrapper

This is the shortest path to an always-on local worker.
You would add a new entrypoint that loops over `run_once()` and then start it in a separate terminal.

That would give you a development-time background worker without changing the queueing model.

## Bottom Line

This project is not currently using a cron-like system for ordinary queued turn execution.

What it needs for "always on" execution is:

- a long-running polling worker process
- a supervisor to keep that process alive
- optionally a separate scheduler process for time-based jobs

So the closest OpenClaw comparison is:

- normal turn processing: long-lived queue worker
- scheduled automations: scheduler that creates queued work

The current repo already has the durable queue and scheduler concepts.
What it still needs is the always-on worker wrapper and the process-management story around it.
