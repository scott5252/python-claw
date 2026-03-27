# Demo Guide: Spec 011 Retrieval, Memory, and Attachment Understanding

This guide shows a junior technical person how to:

1. Set up the application so Spec 011 behavior is active in a realistic workflow
2. Run the application through the normal gateway, worker, and after-turn enrichment path
3. Demonstrate same-run attachment understanding for a newly uploaded text document
4. Demonstrate after-turn summary, durable memory, and retrieval indexing
5. Demonstrate a later turn that still has useful context even when the attachment is not re-uploaded
6. Verify that transcript rows remain canonical while summary, memory, retrieval, and extraction stay additive derived state

The demo uses a real-world scenario:

- a bicycle repair shop employee uploads a repair intake note for customer Maya and later asks follow-up questions without reattaching the note

This is a good demo because it shows the main Spec 011 behaviors:

- worker-owned same-run attachment extraction for supported text content
- transcript-first context assembly with additive summary, memory, retrieval, and attachment-derived content
- after-turn enrichment jobs for summary rollover, memory extraction, retrieval indexing, and attachment extraction
- safe degradation when derived context is missing and recovery when it becomes available later
- durable manifests and derived records that explain what the runtime used

Important note about the current implementation:

- this demo builds on the provider-backed runtime from Specs 009 and 010
- the default runtime mode is still `rule_based`, so you must explicitly enable provider mode
- transcript rows are still the only canonical conversation record
- summary snapshots, durable memories, retrieval rows, and attachment extractions are additive derived state only
- the easiest way to prove the feature is to combine one natural-language chat flow with one small developer verification step that reads durable records after each stage

## 1. What You Will Run

For a successful local demo, you will run:

- PostgreSQL and Redis with Docker Compose
- database migrations
- the gateway API
- the local one-pass execution worker helper
- a small one-pass outbox enrichment helper
- a real provider-backed model call through the gateway and worker path

You do not need the node runner for this demo.

## 2. Before You Start

You need:

- Python 3.11+
- `uv`
- Docker Desktop or another Docker runtime
- a valid OpenAI API key or another compatible endpoint that works with the current provider adapter settings

You should work from the project root:

```bash
cd /Users/scottcornell/src/my-projects/python-claw
```

## 3. Setup The Application

### Step 1: Prepare the environment file

If `.env` does not already exist, create it from `.env.example`:

```bash
cp .env.example .env
```

For this demo, make sure these values exist in `.env`:

```text
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=change-me
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=change-me-internal
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true

PYTHON_CLAW_RUNTIME_MODE=provider
PYTHON_CLAW_LLM_PROVIDER=openai
PYTHON_CLAW_LLM_API_KEY=replace-with-your-real-key
PYTHON_CLAW_LLM_MODEL=gpt-4o-mini
PYTHON_CLAW_LLM_TIMEOUT_SECONDS=30
PYTHON_CLAW_LLM_MAX_RETRIES=1
PYTHON_CLAW_LLM_TEMPERATURE=0.2
PYTHON_CLAW_LLM_MAX_OUTPUT_TOKENS=512
PYTHON_CLAW_LLM_TOOL_CALL_MODE=auto
PYTHON_CLAW_LLM_DISABLE_TOOLS=false

PYTHON_CLAW_RUNTIME_TRANSCRIPT_CONTEXT_LIMIT=2
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
PYTHON_CLAW_ATTACHMENT_SAME_RUN_MAX_BYTES=262144
PYTHON_CLAW_ATTACHMENT_SAME_RUN_PDF_PAGE_LIMIT=5
PYTHON_CLAW_ATTACHMENT_SAME_RUN_TIMEOUT_SECONDS=2
```

Optional if you use an OpenAI-compatible endpoint instead of the default API URL:

```text
PYTHON_CLAW_LLM_BASE_URL=https://your-compatible-endpoint.example/v1
```

What is happening in the system:

- the app loads configuration from `.env`
- provider mode enables a real model response so the attachment-derived context is visible in normal language
- the small transcript window makes it easier to demonstrate summary rollover and non-transcript context reuse
- retrieval, durable memory, and attachment extraction are enabled explicitly
- the same-run fast path is enabled for bounded text and PDF extraction

Important fail-closed behavior:

- if provider mode is selected and `PYTHON_CLAW_LLM_API_KEY` is missing, startup fails clearly
- if retrieval or attachment settings are contradictory, startup fails instead of silently enabling unbounded behavior

### Step 2: Install Python dependencies

Run:

```bash
uv sync --group dev
```

What is happening in the system:

- `uv` creates or updates the local virtual environment
- Python packages needed by the gateway, worker, tests, FastAPI, SQLAlchemy, and the provider SDK are installed

### Step 3: Start local infrastructure

Run:

```bash
docker compose --env-file .env up -d
```

Optional checks:

```bash
docker compose ps
docker compose logs postgres
docker compose logs redis
```

What is happening in the system:

- PostgreSQL starts and becomes the durable store for transcript rows, manifests, summary snapshots, durable memories, retrieval rows, attachment extractions, and run state
- Redis also starts because it is part of the local development stack, even though this demo path does not depend on it directly

### Step 4: Apply the database schema

Run:

```bash
uv run alembic upgrade head
```

What is happening in the system:

- Alembic creates all current tables through Spec 011
- after this step, the gateway can persist inbound messages and the worker plus outbox path can produce the new derived context records

### Step 5: Create the real-world attachment file

Create a local text file that represents a repair intake note:

```bash
cat > /tmp/demo011-maya-intake.txt <<'EOF'
Customer: Maya Patel
Repair order: BR-1042
Bike: Blue commuter bike
Requested pickup window: after 3 PM today
Shop promise: hold completed repairs until 6 PM
Preferred contact: text message
Special note: remind Maya to bring her rear light mount for fitting
EOF
```

What is happening in the system:

- this file will be sent as a normal inbound attachment
- because it is a small text file, it qualifies for the bounded same-run extraction fast path

## 4. Run The Application

Use four terminals for the main demo.

### Terminal A: Start the gateway API

Run:

```bash
uv run uvicorn apps.gateway.main:app --reload
```

What is happening in the system:

- FastAPI starts on `http://127.0.0.1:8000`
- the app builds shared services for sessions, execution runs, context assembly, memory extraction, retrieval indexing, and attachment extraction

### Terminal B: Keep a run worker terminal ready

You will run this command after each user message:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What is happening in the system when you run it:

- the helper opens a database session
- it claims at most one eligible `execution_runs` row
- it normalizes any inbound attachments
- it attempts same-run bounded extraction for supported text or PDF attachments
- it assembles transcript plus additive context
- it invokes the provider-backed runtime
- it persists the assistant turn and exits

### Terminal C: Keep an outbox enrichment terminal ready

You will run this command after each assistant turn when the guide tells you to:

```bash
uv run python - <<'PY'
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import get_settings
from src.context.outbox import OutboxWorker
from src.db.session import DatabaseSessionManager
from src.media.extraction import MediaExtractionService
from src.memory.service import MemoryService
from src.retrieval.service import RetrievalService
from src.sessions.repository import SessionRepository

settings = get_settings()
manager = DatabaseSessionManager(settings.database_url)
worker = OutboxWorker(
    repository=SessionRepository(),
    memory_service=MemoryService(strategy_id=settings.memory_strategy_id),
    retrieval_service=RetrievalService(
        strategy_id=settings.retrieval_strategy_id,
        chunk_chars=settings.retrieval_chunk_chars,
        min_score=settings.retrieval_min_score,
    ),
    attachment_extraction_service=MediaExtractionService(
        storage_root=Path(settings.media_storage_root),
        strategy_id=settings.attachment_extraction_strategy_id,
        same_run_max_bytes=settings.attachment_same_run_max_bytes,
        same_run_pdf_page_limit=settings.attachment_same_run_pdf_page_limit,
        same_run_timeout_seconds=settings.attachment_same_run_timeout_seconds,
    ),
)
with manager.session() as db:
    print(worker.run_pending(db, now=datetime.now(timezone.utc), limit=20))
    db.commit()
PY
```

What is happening in the system when you run it:

- the helper claims pending outbox jobs
- it generates summary snapshots when enough transcript exists
- it creates durable memory rows from transcript or summaries
- it builds retrieval rows from canonical source artifacts
- it performs asynchronous attachment extraction for any remaining supported attachments

### Terminal D: Use curl to simulate the user chat

Set these helpful variables:

```bash
BASE=http://127.0.0.1:8000
AUTH='Authorization: Bearer change-me'
```

Verify the gateway is live:

```bash
curl $BASE/health/live
```

Verify readiness:

```bash
curl $BASE/health/ready -H "$AUTH"
```

## Main Demo

This section is the primary end-to-end demo for most audiences. It shows same-run attachment understanding first, then later-turn continuity from summary, memory, and retrieval without reattaching the original note.

### Scenario

A bike shop employee is helping customer Maya. The employee uploads the repair intake note once, asks for advice, then continues the conversation later without uploading the note again.

We will demonstrate five stages:

1. Upload the intake note and ask a question about it.
2. Prove the same-run attachment content was available to the model.
3. Run after-turn enrichment to build summary, memory, and retrieval rows.
4. Ask a later question without reattaching the note.
5. Verify that the backend used additive derived context while keeping transcript canonical.

## Part A: Demonstrate Same-Run Attachment Understanding

### Step 1: Submit the first user message with the attachment

In Terminal D, run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "bike-shop-demo",
    "external_message_id": "demo011-msg-1",
    "sender_id": "employee-alex",
    "content": "Please read this repair intake note and tell me the best pickup reminder plan for Maya.",
    "peer_id": "customer-maya",
    "attachments": [
      {
        "source_url": "file:///tmp/demo011-maya-intake.txt",
        "mime_type": "text/plain",
        "filename": "maya-intake.txt",
        "byte_size": 260,
        "provider_metadata": {}
      }
    ]
  }'
```

Expected result:

- HTTP 202
- JSON with `session_id`, `message_id`, `run_id`, `status`, and `trace_id`

Write down:

- `session_id`
- `message_id`

Postman-friendly version:

- this endpoint accepts plain JSON, so you can send the same request from Postman without multipart upload
- set a Postman variable such as `INTAKE_FILE_URL=file:///tmp/demo011-maya-intake.txt`
- the variable format is a literal URL string that the gateway machine can read
- for a local file on the same machine as the gateway, use `file:///absolute/path/to/file.txt`
- example local values:
  - `file:///tmp/demo011-maya-intake.txt`
  - `file:///Users/scottcornell/Documents/maya-intake.txt`
- if the gateway is running on another machine, use an HTTPS URL instead, for example `https://example.com/demo011-maya-intake.txt`
- use this raw JSON body in Postman:

```json
{
  "channel_kind": "webchat",
  "channel_account_id": "bike-shop-demo",
  "external_message_id": "demo011-msg-1",
  "sender_id": "employee-alex",
  "content": "Please read this repair intake note and tell me the best pickup reminder plan for Maya.",
  "peer_id": "customer-maya",
  "attachments": [
    {
      "source_url": "{{INTAKE_FILE_URL}}",
      "mime_type": "text/plain",
      "filename": "maya-intake.txt",
      "byte_size": 260,
      "provider_metadata": {}
    }
  ]
}
```

Important note:

- Postman can send the JSON, but the gateway still reads the attachment from the server-visible `source_url`
- for local demos, `file:///tmp/demo011-maya-intake.txt` works when the gateway is running on the same machine
- if the gateway runs elsewhere, host the file at an `https://...` URL instead because the current implementation accepts `file` and `https` attachment schemes

What is happening in the system:

1. The gateway validates the inbound message.
2. It stores the canonical attachment input but does not read the file inline.
3. It appends the user message to `messages`.
4. It creates one queued execution run and returns quickly.

### Step 2: Process the queued run

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What is happening in the system:

1. The worker claims the queued run.
2. It normalizes the attachment into a stored media record.
3. Because this file is a small text document, the worker extracts the text before prompt assembly and persists an `attachment_extractions` row.
4. `ContextService` assembles transcript plus the already-persisted attachment-derived content.
5. The provider-backed runtime answers using the attachment content.
6. The worker persists the assistant message and queues after-turn enrichment jobs.

### Step 3: Read the assistant response

In Terminal D, run:

```bash
curl -s $BASE/sessions/$SESSION_ID/messages
```

Before you run it, set:

```bash
SESSION_ID=replace-with-your-session-id
```

Expected result:

- the latest assistant message should mention details from the uploaded note
- a good response usually mentions at least:
  - pickup after 3 PM
  - hold until 6 PM
  - preferred contact by text
  - the reminder about the rear light mount

This proves the first turn understood the newly uploaded attachment in the same run.

## Part B: Build Durable Summary, Memory, and Retrieval

### Step 4: Run the outbox enrichment helper

In Terminal C, run the outbox helper once:

```bash
uv run python - <<'PY'
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import get_settings
from src.context.outbox import OutboxWorker
from src.db.session import DatabaseSessionManager
from src.media.extraction import MediaExtractionService
from src.memory.service import MemoryService
from src.retrieval.service import RetrievalService
from src.sessions.repository import SessionRepository

settings = get_settings()
manager = DatabaseSessionManager(settings.database_url)
worker = OutboxWorker(
    repository=SessionRepository(),
    memory_service=MemoryService(strategy_id=settings.memory_strategy_id),
    retrieval_service=RetrievalService(
        strategy_id=settings.retrieval_strategy_id,
        chunk_chars=settings.retrieval_chunk_chars,
        min_score=settings.retrieval_min_score,
    ),
    attachment_extraction_service=MediaExtractionService(
        storage_root=Path(settings.media_storage_root),
        strategy_id=settings.attachment_extraction_strategy_id,
        same_run_max_bytes=settings.attachment_same_run_max_bytes,
        same_run_pdf_page_limit=settings.attachment_same_run_pdf_page_limit,
        same_run_timeout_seconds=settings.attachment_same_run_timeout_seconds,
    ),
)
with manager.session() as db:
    print(worker.run_pending(db, now=datetime.now(timezone.utc), limit=20))
    db.commit()
PY
```

Expected result:

- output should include job kinds such as:
  - `summary_generation`
  - `memory_extraction`
  - `retrieval_index`
  - sometimes `attachment_extraction` if any asynchronous extraction remains pending

What is happening in the system:

- the summary job compacts enough transcript to create a summary snapshot
- memory extraction creates additive durable memory rows with provenance
- retrieval indexing creates session-scoped retrieval rows from canonical source artifacts
- none of this mutates transcript truth

### Step 5: Verify the durable records exist

Run this developer verification command:

```bash
uv run python - <<'PY'
from sqlalchemy import text

from src.config.settings import get_settings
from src.db.session import DatabaseSessionManager

settings = get_settings()
manager = DatabaseSessionManager(settings.database_url)

queries = {
    "summary_snapshots": "select id, session_id, through_message_id from summary_snapshots order by id desc limit 5",
    "session_memories": "select id, session_id, source_kind, status, derivation_strategy_id from session_memories order by id desc limit 5",
    "retrieval_records": "select id, session_id, source_kind, chunk_index, derivation_strategy_id from retrieval_records order by id desc limit 5",
    "attachment_extractions": "select id, session_id, attachment_id, status, extractor_kind from attachment_extractions order by id desc limit 5",
}

with manager.session() as db:
    for name, sql in queries.items():
        print(f"\n== {name} ==")
        for row in db.execute(text(sql)):
            print(row)
PY
```

Expected result:

- at least one `summary_snapshots` row
- at least one `session_memories` row with `status='active'`
- at least one `retrieval_records` row
- at least one `attachment_extractions` row with `status='completed'`

## Part C: Demonstrate Later-Turn Continuity Without Reuploading The Note

### Step 6: Submit a follow-up question without any attachment

In Terminal D, run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "bike-shop-demo",
    "external_message_id": "demo011-msg-2",
    "sender_id": "employee-alex",
    "content": "I do not have the intake note open anymore. What pickup time did Maya prefer, what is the repair order number, and what extra reminder should I include?",
    "peer_id": "customer-maya"
  }'
```

Expected result:

- HTTP 202
- a new queued run for the same `session_id`

### Step 7: Process the later turn

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What is happening in the system:

1. The worker claims the second run.
2. There is no new attachment this time.
3. `ContextService` assembles recent transcript plus whatever valid summary, memory, retrieval, and attachment-derived records already exist.
4. The model can answer the later question without rereading the raw file directly.

### Step 8: Read the later response

In Terminal D, run:

```bash
curl -s $BASE/sessions/$SESSION_ID/messages
```

Expected result:

- one of these two outcomes is currently valid:
  - best case: the later assistant message still mentions:
    - Maya prefers pickup after 3 PM
    - the repair order is `BR-1042`
    - the reminder about the rear light mount
  - degraded case: the later assistant message says `I could not safely fit the required session context into the model window for this turn. Continuity repair has been queued.`

How to interpret the degraded case:

- this demo intentionally sets `PYTHON_CLAW_RUNTIME_TRANSCRIPT_CONTEXT_LIMIT=2`
- after the first completed turn, the session usually has only two transcript rows, which is not enough for the current summary generation path to create a summary snapshot
- when the second user message arrives, the worker may have more transcript than it can safely fit and no valid summary yet, so it emits the degraded continuity-repair message
- this is still a valid Spec 011 behavior because the system fails closed and queues repair work instead of silently dropping context

If you get the degraded message, continue with this recovery proof:

### Step 8A: Run the outbox enrichment helper again

In Terminal C, run:

```bash
uv run python - <<'PY'
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import get_settings
from src.context.outbox import OutboxWorker
from src.db.session import DatabaseSessionManager
from src.media.extraction import MediaExtractionService
from src.memory.service import MemoryService
from src.retrieval.service import RetrievalService
from src.sessions.repository import SessionRepository

settings = get_settings()
manager = DatabaseSessionManager(settings.database_url)
worker = OutboxWorker(
    repository=SessionRepository(),
    memory_service=MemoryService(strategy_id=settings.memory_strategy_id),
    retrieval_service=RetrievalService(
        strategy_id=settings.retrieval_strategy_id,
        chunk_chars=settings.retrieval_chunk_chars,
        min_score=settings.retrieval_min_score,
    ),
    attachment_extraction_service=MediaExtractionService(
        storage_root=Path(settings.media_storage_root),
        strategy_id=settings.attachment_extraction_strategy_id,
        same_run_max_bytes=settings.attachment_same_run_max_bytes,
        same_run_pdf_page_limit=settings.attachment_same_run_pdf_page_limit,
        same_run_timeout_seconds=settings.attachment_same_run_timeout_seconds,
    ),
)
with manager.session() as db:
    print(worker.run_pending(db, now=datetime.now(timezone.utc), limit=20))
    db.commit()
PY
```

Expected result:

- output should include `continuity_repair` and usually `summary_generation`

### Step 8B: Ask the follow-up one more time after repair

In Terminal D, run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "bike-shop-demo",
    "external_message_id": "demo011-msg-3",
    "sender_id": "employee-alex",
    "content": "Now that continuity repair has run, remind me of Maya'\''s preferred pickup time, the repair order number, and the extra reminder.",
    "peer_id": "customer-maya"
  }'
```

Then in Terminal B, process the queued run again:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Finally, read the session messages again:

```bash
curl -s $BASE/sessions/$SESSION_ID/messages
```

Expected recovery result:

- the newest assistant message should mention:
  - Maya prefers pickup after 3 PM
  - the repair order is `BR-1042`
  - the reminder about the rear light mount

This proves the system can preserve useful context after the original attachment is no longer on the current message, either immediately or after the queued continuity-repair path completes.

## Part D: Prove The Backend Used Additive Derived Context

### Step 9: Inspect the session continuity summary

Run:

```bash
curl -s $BASE/diagnostics/sessions/$SESSION_ID/continuity -H "$AUTH"
```

Expected result:

- `summary_snapshot_count` should be greater than or equal to `1`
- `context_manifest_count` should be greater than or equal to `2`
- `pending_outbox_jobs` should be low or `0` after the enrichment helper has run

What this proves:

- continuity is inspectable through the existing operator surface
- the backend knows whether derived work exists and whether context degraded

### Step 10: Inspect the latest context manifest

Run this developer verification command:

```bash
uv run python - <<'PY'
import json
from sqlalchemy import text

from src.config.settings import get_settings
from src.db.session import DatabaseSessionManager

settings = get_settings()
manager = DatabaseSessionManager(settings.database_url)

with manager.session() as db:
    row = db.execute(
        text("select manifest_json from context_manifests order by id desc limit 1")
    ).one()
    manifest = json.loads(row[0])
    print(json.dumps(manifest, indent=2, sort_keys=True))
PY
```

Expected result:

- the manifest should show:
  - `summary_snapshot_ids`
  - `memory_ids`
  - `retrieval_ids`
  - `attachment_extraction_ids`
  - `retrieval_strategy`
  - `assembly_budget`
  - `attachment_fallbacks` when applicable

What this proves:

- the backend can explain which additive sources were used
- manifests are durable diagnostics for one turn
- the system is not turning summaries or memories into fake transcript rows

### Step 11: Confirm transcript is still canonical

Run this final check:

```bash
uv run python - <<'PY'
from sqlalchemy import text

from src.config.settings import get_settings
from src.db.session import DatabaseSessionManager

settings = get_settings()
manager = DatabaseSessionManager(settings.database_url)

with manager.session() as db:
    print("messages:")
    for row in db.execute(text("select id, role, content from messages order by id asc limit 20")):
        print(row)
PY
```

Expected result:

- the original user and assistant turns are still in `messages`
- summaries, memories, retrieval rows, and attachment extractions live in separate tables

This proves the main safety property of Spec 011:

- transcript truth remains canonical
- all retrieval, memory, and attachment-understanding state remains additive and rebuildable

## 5. What To Say During The Demo

If you are presenting live, this short explanation works well:

- “The first turn proves the worker can understand a newly uploaded attachment in the same run for small text documents.”
- “The outbox step proves that summary, memory, retrieval, and extraction are durable follow-up work, not gateway-time shortcuts.”
- “The later turn proves the assistant can still answer correctly without reuploading the document.”
- “The final verification proves transcript is still the only canonical conversation record and everything else is additive derived state.”

## 6. Cleanup

When you are done, stop the gateway and shut down Docker services:

```bash
docker compose --env-file .env down
```

Optional cleanup:

```bash
rm -f /tmp/demo011-maya-intake.txt
```
