# Environment Settings Guide

This document explains every setting in [.env.example](/Users/scottcornell/src/my-projects/python-claw/.env.example) and how it relates to the behavior described in the README and Specs 001 through 011.

## How configuration is loaded

- The app loads a project-root `.env` file through `python-dotenv`.
- Only variables prefixed with `PYTHON_CLAW_` are read by the application settings model in [src/config/settings.py](/Users/scottcornell/src/my-projects/python-claw/src/config/settings.py).
- Unknown `PYTHON_CLAW_` variables are ignored rather than failing startup.
- If the same setting exists in both the shell environment and `.env`, the already-exported shell environment value wins because dotenv is loaded with `override=False`.

## Format conventions

- Boolean values: use `true` or `false`
- Integer values: plain whole numbers like `30`
- Float values: decimal numbers like `0.2`
- List-like values: comma-separated strings with no brackets, such as `file,https`
- Paths: relative paths are resolved from the project working directory

## Application

### `PYTHON_CLAW_APP_NAME`

- Default: `python-claw-gateway`
- Type: string
- What it does: Sets the application name used by the service and observability surfaces.
- How to configure it: Keep the default unless you want logs, health responses, or deployment metadata to identify a different service name.
- Example:

```env
PYTHON_CLAW_APP_NAME=python-claw-gateway
```

### `PYTHON_CLAW_DEFAULT_AGENT_ID`

- Default: `default-agent`
- Type: string
- What it does: Supplies the fallback agent identifier used by the runtime when upstream routing has not yet resolved a multi-agent target. This lines up with Spec 002's requirement for an explicit configured agent id.
- How to configure it: Use a stable identifier that matches your default assistant persona or policy profile.
- Example:

```env
PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent
```

## Database And Local Infrastructure

### `PYTHON_CLAW_POSTGRES_DB`

- Default: `openassistant`
- Type: string
- What it does: Names the PostgreSQL database used by local infrastructure tooling such as `docker-compose`.
- How to configure it: Change it only if your local Postgres database name differs from the default.
- Example:

```env
PYTHON_CLAW_POSTGRES_DB=openassistant
```

### `PYTHON_CLAW_POSTGRES_USER`

- Default: `openassistant`
- Type: string
- What it does: Sets the local PostgreSQL username for containerized development infrastructure.
- How to configure it: Match this to the user embedded in `PYTHON_CLAW_DATABASE_URL`.
- Example:

```env
PYTHON_CLAW_POSTGRES_USER=openassistant
```

### `PYTHON_CLAW_POSTGRES_PASSWORD`

- Default: `openassistant`
- Type: string
- What it does: Sets the local PostgreSQL password for containerized development infrastructure.
- How to configure it: Use a simple value for local development; use a strong secret in shared or deployed environments.
- Example:

```env
PYTHON_CLAW_POSTGRES_PASSWORD=dev-postgres-password
```

### `PYTHON_CLAW_POSTGRES_PORT`

- Default: `5432`
- Type: integer
- What it does: Chooses which local host port PostgreSQL is exposed on.
- How to configure it: Change this if port `5432` is already taken on your machine.
- Example:

```env
PYTHON_CLAW_POSTGRES_PORT=5433
```

### `PYTHON_CLAW_REDIS_PORT`

- Default: `6379`
- Type: integer
- What it does: Chooses which local host port Redis is exposed on for local infrastructure. In the current codebase this is mainly for development tooling rather than a direct application settings dependency.
- How to configure it: Change it only if your local machine already uses port `6379`.
- Example:

```env
PYTHON_CLAW_REDIS_PORT=6380
```

### `PYTHON_CLAW_DATABASE_URL`

- Default: `postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant`
- Type: string
- What it does: Tells the app how to connect to its primary database. This is the most important persistence setting because Specs 001 through 009 all rely on durable database state.
- How to configure it: Point it at your real application database. For local development, the default Postgres URL is fine. Tests often override this with SQLite.
- Example:

```env
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
```

## Inbound Idempotency And API Paging

### `PYTHON_CLAW_DEDUPE_RETENTION_DAYS`

- Default: `30`
- Type: integer
- What it does: Controls how long inbound deduplication records should be retained. Spec 001 calls for an explicit 30-day retention policy unless a stricter platform rule overrides it.
- How to configure it: Increase it if upstream providers may replay old events late; decrease it if you want shorter dedupe history and accept older replayed events as new work.
- Example:

```env
PYTHON_CLAW_DEDUPE_RETENTION_DAYS=30
```

### `PYTHON_CLAW_DEDUPE_STALE_AFTER_SECONDS`

- Default: `300`
- Type: integer
- What it does: Defines when a previously claimed dedupe record is considered stale enough for bounded recovery. This supports the stale-claim behavior required by Spec 001.
- How to configure it: Use a value comfortably larger than normal request completion time, but small enough to recover from crashes without long delays.
- Example:

```env
PYTHON_CLAW_DEDUPE_STALE_AFTER_SECONDS=300
```

### `PYTHON_CLAW_MESSAGES_PAGE_DEFAULT_LIMIT`

- Default: `50`
- Type: integer
- What it does: Sets the default page size for `GET /sessions/{session_id}/messages`.
- How to configure it: Keep it moderate so read APIs stay bounded and predictable.
- Example:

```env
PYTHON_CLAW_MESSAGES_PAGE_DEFAULT_LIMIT=50
```

### `PYTHON_CLAW_MESSAGES_PAGE_MAX_LIMIT`

- Default: `100`
- Type: integer
- What it does: Caps the largest allowed transcript page size for message history requests.
- How to configure it: Raise it only if operators really need larger pages and the database can handle the heavier query shape.
- Example:

```env
PYTHON_CLAW_MESSAGES_PAGE_MAX_LIMIT=100
```

### `PYTHON_CLAW_SESSION_RUNS_PAGE_DEFAULT_LIMIT`

- Default: `20`
- Type: integer
- What it does: Sets the default page size for session run listings introduced with Spec 005.
- How to configure it: Use a smaller default than message pages because run records are more operational than conversational.
- Example:

```env
PYTHON_CLAW_SESSION_RUNS_PAGE_DEFAULT_LIMIT=20
```

### `PYTHON_CLAW_SESSION_RUNS_PAGE_MAX_LIMIT`

- Default: `50`
- Type: integer
- What it does: Caps the maximum number of runs returned in one session runs page.
- How to configure it: Increase carefully if operators need broader inspection windows.
- Example:

```env
PYTHON_CLAW_SESSION_RUNS_PAGE_MAX_LIMIT=50
```

## Execution Runs And Worker Behavior

### `PYTHON_CLAW_RUNTIME_TRANSCRIPT_CONTEXT_LIMIT`

- Default: `20`
- Type: integer
- What it does: Limits how many transcript messages are pulled into the immediate runtime context before any compaction or continuity logic. This supports the bounded context assembly behavior from Specs 004 and 009.
- How to configure it: Raise it for richer conversational continuity, lower it if prompts are getting too large or expensive.
- Example:

```env
PYTHON_CLAW_RUNTIME_TRANSCRIPT_CONTEXT_LIMIT=20
```

### `PYTHON_CLAW_RUNTIME_MODE`

- Default: `rule_based`
- Type: string
- Allowed values: `rule_based`, `provider`
- What it does: Chooses whether the system uses the safe local scaffold adapter or the provider-backed LLM adapter from Spec 009.
- How to configure it: Use `rule_based` for local scaffolding and CI; use `provider` only when you also configure provider credentials.
- Example:

```env
PYTHON_CLAW_RUNTIME_MODE=provider
```

### `PYTHON_CLAW_LLM_PROVIDER`

- Default: `openai`
- Type: string
- What it does: Names the provider implementation used when `runtime_mode=provider`.
- How to configure it: Keep `openai` unless the provider module is extended to support additional backends.
- Example:

```env
PYTHON_CLAW_LLM_PROVIDER=openai
```

### `PYTHON_CLAW_LLM_API_KEY`

- Default: empty
- Type: string or empty
- What it does: Supplies the provider API credential. `runtime_mode=provider` fails validation if this is missing.
- How to configure it: Set a real secret in your shell or secret manager. Do not commit live keys into `.env.example`.
- Example:

```env
PYTHON_CLAW_LLM_API_KEY=sk-your-provider-key
```

### `PYTHON_CLAW_LLM_BASE_URL`

- Default: empty
- Type: string or empty
- What it does: Overrides the provider base URL. This is useful for compatible gateways, proxies, or test endpoints.
- How to configure it: Leave blank for the provider default; set it only when you intentionally route requests through another endpoint.
- Example:

```env
PYTHON_CLAW_LLM_BASE_URL=https://api.openai.com/v1
```

### `PYTHON_CLAW_LLM_MODEL`

- Default: `gpt-4o-mini`
- Type: string
- What it does: Selects the provider model name used for natural-language turns.
- How to configure it: Pick a model that matches your cost, latency, and quality requirements and is compatible with the provider configured above.
- Example:

```env
PYTHON_CLAW_LLM_MODEL=gpt-4o-mini
```

### `PYTHON_CLAW_LLM_TIMEOUT_SECONDS`

- Default: `30`
- Type: integer
- Validation: must be greater than `0`
- What it does: Limits how long one provider call may run before it is treated as a timeout.
- How to configure it: Use a shorter value for low-latency systems and a larger one only if your provider or model regularly needs more time.
- Example:

```env
PYTHON_CLAW_LLM_TIMEOUT_SECONDS=30
```

### `PYTHON_CLAW_LLM_MAX_RETRIES`

- Default: `1`
- Type: integer
- Validation: must be greater than or equal to `0`
- What it does: Allows the provider adapter to retry retryable transport-class failures inside a single worker attempt. Spec 009 requires this to stay bounded.
- How to configure it: Keep this low so provider retries do not multiply too much with worker retries.
- Example:

```env
PYTHON_CLAW_LLM_MAX_RETRIES=1
```

### `PYTHON_CLAW_LLM_TEMPERATURE`

- Default: `0.2`
- Type: float
- What it does: Controls model randomness when provider mode is enabled.
- How to configure it: Use a lower value for deterministic assistant behavior and a higher value if you want more varied phrasing.
- Example:

```env
PYTHON_CLAW_LLM_TEMPERATURE=0.2
```

### `PYTHON_CLAW_LLM_MAX_OUTPUT_TOKENS`

- Default: `512`
- Type: integer or empty
- Validation: when set, must be greater than `0`
- What it does: Caps the model's response size for one turn.
- How to configure it: Increase it for longer answers, lower it to bound latency and cost. Leave unset only if your provider path supports that cleanly.
- Example:

```env
PYTHON_CLAW_LLM_MAX_OUTPUT_TOKENS=512
```

### `PYTHON_CLAW_LLM_TOOL_CALL_MODE`

- Default: `auto`
- Type: string
- Allowed values: `auto`, `none`
- What it does: Controls whether the provider is allowed to see and suggest backend-authorized tools. Spec 009 requires this to be an explicit backend-owned setting.
- How to configure it: Use `auto` for normal tool-enabled turns. Use `none` to force text-only model behavior even if tools exist.
- Example:

```env
PYTHON_CLAW_LLM_TOOL_CALL_MODE=auto
```

### `PYTHON_CLAW_LLM_MAX_TOOL_REQUESTS_PER_TURN`

- Default: `4`
- Type: integer
- Validation: must be greater than `0`
- What it does: Caps how many tool requests a provider response may propose in a single turn.
- How to configure it: Keep this low unless you intentionally want multi-tool planning in one response.
- Example:

```env
PYTHON_CLAW_LLM_MAX_TOOL_REQUESTS_PER_TURN=4
```

### `PYTHON_CLAW_LLM_DISABLE_TOOLS`

- Default: `false`
- Type: boolean
- What it does: Disables tool exposure at runtime even if tool calling is otherwise available.
- How to configure it: Set this to `true` when debugging plain conversational behavior or when you want provider-backed text generation without any tool path.
- Example:

```env
PYTHON_CLAW_LLM_DISABLE_TOOLS=true
```

### `PYTHON_CLAW_LLM_MAX_INPUT_TOKENS`

- Default: `4000`
- Type: integer
- What it does: Provides the runtime with a rough upper bound for prompt input sizing.
- How to configure it: Match it to the practical provider input budget you want the backend to target.
- Example:

```env
PYTHON_CLAW_LLM_MAX_INPUT_TOKENS=4000
```

### `PYTHON_CLAW_LLM_PROMPT_CHAR_TOKEN_RATIO`

- Default: `4`
- Type: integer
- What it does: Supplies the character-to-token estimation ratio used when sizing prompt payloads conservatively.
- How to configure it: Leave it at `4` unless you have measured a better heuristic for your prompt format and models.
- Example:

```env
PYTHON_CLAW_LLM_PROMPT_CHAR_TOKEN_RATIO=4
```

### `PYTHON_CLAW_EXECUTION_RUN_LEASE_SECONDS`

- Default: `60`
- Type: integer
- What it does: Controls how long a worker run claim stays valid before another worker may treat it as recoverable.
- How to configure it: Set it longer than your usual run startup and refresh interval, but not so long that crashed workers block recovery for minutes.
- Example:

```env
PYTHON_CLAW_EXECUTION_RUN_LEASE_SECONDS=60
```

### `PYTHON_CLAW_EXECUTION_RUN_MAX_ATTEMPTS`

- Default: `5`
- Type: integer
- What it does: Caps total worker attempts for one execution run before it becomes terminal.
- How to configure it: Keep it modest to prevent endless retries on bad inputs or broken infrastructure.
- Example:

```env
PYTHON_CLAW_EXECUTION_RUN_MAX_ATTEMPTS=5
```

### `PYTHON_CLAW_EXECUTION_RUN_BACKOFF_SECONDS`

- Default: `5`
- Type: integer
- What it does: Sets the base retry delay for failed execution runs.
- How to configure it: Use a small value for quick transient recovery and a larger one if downstream dependencies need more time to recover.
- Example:

```env
PYTHON_CLAW_EXECUTION_RUN_BACKOFF_SECONDS=5
```

### `PYTHON_CLAW_EXECUTION_RUN_BACKOFF_MAX_SECONDS`

- Default: `300`
- Type: integer
- What it does: Caps the largest retry delay for execution runs.
- How to configure it: Raise this if you want slower exponential backoff under repeated failure.
- Example:

```env
PYTHON_CLAW_EXECUTION_RUN_BACKOFF_MAX_SECONDS=300
```

### `PYTHON_CLAW_EXECUTION_RUN_GLOBAL_CONCURRENCY`

- Default: `4`
- Type: integer
- What it does: Limits how many execution runs may be actively running system-wide at once. Spec 005 requires a global concurrency cap.
- How to configure it: Tune this based on CPU, database, and provider capacity.
- Example:

```env
PYTHON_CLAW_EXECUTION_RUN_GLOBAL_CONCURRENCY=4
```

## Attachment Intake And Media Normalization

### `PYTHON_CLAW_INBOUND_ATTACHMENT_MAX_METADATA_CHARS`

- Default: `2000`
- Type: integer
- What it does: Caps how much attachment metadata the inbound API accepts. This keeps attachment payloads bounded as required by Spec 007.
- How to configure it: Increase only if your upstream channel supplies larger safe metadata blobs you truly need.
- Example:

```env
PYTHON_CLAW_INBOUND_ATTACHMENT_MAX_METADATA_CHARS=2000
```

### `PYTHON_CLAW_MEDIA_STORAGE_ROOT`

- Default: `.claw-media`
- Type: path string
- What it does: Sets the local root directory where normalized media is stored.
- How to configure it: Use a writable location with enough disk space. Relative paths stay under the project working directory.
- Example:

```env
PYTHON_CLAW_MEDIA_STORAGE_ROOT=.claw-media
```

### `PYTHON_CLAW_MEDIA_STORAGE_BUCKET`

- Default: `local-media`
- Type: string
- What it does: Names the logical storage bucket for media records. In local mode this is mostly descriptive metadata, but it prepares the system for object-storage-backed implementations.
- How to configure it: Keep the default locally; set it to your real bucket name in deployed environments.
- Example:

```env
PYTHON_CLAW_MEDIA_STORAGE_BUCKET=local-media
```

### `PYTHON_CLAW_MEDIA_RETENTION_DAYS`

- Default: `30`
- Type: integer
- What it does: Defines the intended retention window for normalized media artifacts.
- How to configure it: Match it to your privacy, compliance, and storage cost requirements.
- Example:

```env
PYTHON_CLAW_MEDIA_RETENTION_DAYS=30
```

### `PYTHON_CLAW_MEDIA_ALLOWED_SCHEMES`

- Default: `file,https`
- Type: comma-separated string
- What it does: Restricts which URL schemes attachment normalization will accept. Spec 007 requires scheme allowlisting.
- How to configure it: Keep the list tight. Add schemes only if you have a real trusted source and matching validation.
- Example:

```env
PYTHON_CLAW_MEDIA_ALLOWED_SCHEMES=file,https
```

### `PYTHON_CLAW_MEDIA_ALLOWED_MIME_PREFIXES`

- Default: `image/,audio/,text/,application/pdf`
- Type: comma-separated string
- What it does: Restricts accepted attachment MIME types or prefixes during normalization.
- How to configure it: Include only the media families your app is prepared to handle safely.
- Example:

```env
PYTHON_CLAW_MEDIA_ALLOWED_MIME_PREFIXES=image/,application/pdf
```

### `PYTHON_CLAW_MEDIA_MAX_BYTES`

- Default: `5242880`
- Type: integer
- What it does: Sets the maximum allowed attachment size in bytes. The default is 5 MiB.
- How to configure it: Raise it only if you are ready for larger files, longer processing times, and more storage use.
- Example:

```env
PYTHON_CLAW_MEDIA_MAX_BYTES=5242880
```

### `PYTHON_CLAW_RETRIEVAL_ENABLED`

- Default: `true`
- Type: boolean
- What it does: Enables the Spec 011 retrieval layer that can inject bounded durable-memory, attachment-derived, and other non-transcript context into prompt assembly.
- How to configure it: Leave this enabled for normal Spec 011 behavior. Set it to `false` if you want transcript-plus-summary continuity only or need to isolate retrieval-related issues.
- Example:

```env
PYTHON_CLAW_RETRIEVAL_ENABLED=true
```

### `PYTHON_CLAW_RETRIEVAL_STRATEGY_ID`

- Default: `lexical-v1`
- Type: string
- Validation: must not be empty
- What it does: Names the retrieval derivation and ranking strategy. This identifier participates in deterministic rebuild and duplicate-suppression behavior for Spec 011 retrieval records.
- How to configure it: Use a stable versioned identifier such as `lexical-v1`. Change it when you intentionally ship a materially different retrieval strategy and want fresh derived rows.
- Example:

```env
PYTHON_CLAW_RETRIEVAL_STRATEGY_ID=lexical-v1
```

### `PYTHON_CLAW_RETRIEVAL_TOTAL_ITEMS`

- Default: `4`
- Type: integer
- Validation: must be greater than or equal to `0`
- What it does: Caps the total number of retrieval-derived context items `ContextService` may include in one assembled turn.
- How to configure it: Raise it only if you have prompt budget for more retrieved context. Keep it small so transcript-first assembly stays bounded and predictable.
- Example:

```env
PYTHON_CLAW_RETRIEVAL_TOTAL_ITEMS=4
```

### `PYTHON_CLAW_RETRIEVAL_MEMORY_ITEMS`

- Default: `2`
- Type: integer
- Validation: must be greater than or equal to `0`
- What it does: Caps how many retrieved durable-memory items may be included in one assembled turn.
- How to configure it: Increase this if memory recall is more important than attachment or other retrieved context for your workload. The sum of the per-source caps must cover `PYTHON_CLAW_RETRIEVAL_TOTAL_ITEMS`.
- Example:

```env
PYTHON_CLAW_RETRIEVAL_MEMORY_ITEMS=2
```

### `PYTHON_CLAW_RETRIEVAL_ATTACHMENT_ITEMS`

- Default: `2`
- Type: integer
- Validation: must be greater than or equal to `0`
- What it does: Caps how many retrieved attachment-derived items may be included in one assembled turn.
- How to configure it: Raise this only if attachment understanding is a primary use case and you have room in the prompt budget. The sum of the per-source caps must cover `PYTHON_CLAW_RETRIEVAL_TOTAL_ITEMS`.
- Example:

```env
PYTHON_CLAW_RETRIEVAL_ATTACHMENT_ITEMS=2
```

### `PYTHON_CLAW_RETRIEVAL_OTHER_ITEMS`

- Default: `2`
- Type: integer
- Validation: must be greater than or equal to `0`
- What it does: Caps how many non-memory, non-attachment retrieval items, such as transcript- or summary-derived retrieval rows, may be included in one assembled turn.
- How to configure it: Tune this alongside the other per-source caps so the mix of retrieved context matches your priorities. The sum of the per-source caps must cover `PYTHON_CLAW_RETRIEVAL_TOTAL_ITEMS`.
- Example:

```env
PYTHON_CLAW_RETRIEVAL_OTHER_ITEMS=2
```

### `PYTHON_CLAW_RETRIEVAL_CHUNK_CHARS`

- Default: `280`
- Type: integer
- Validation: must be greater than `0`
- What it does: Sets the target chunk size used when building bounded retrieval records from canonical source artifacts.
- How to configure it: Keep this relatively small so retrieved snippets stay focused. Increase it if the current chunks are too fragmented to be useful.
- Example:

```env
PYTHON_CLAW_RETRIEVAL_CHUNK_CHARS=280
```

### `PYTHON_CLAW_RETRIEVAL_MIN_SCORE`

- Default: `1.0`
- Type: float
- What it does: Sets the minimum retrieval score a candidate must meet before it can be considered for prompt assembly.
- How to configure it: Lower it if retrieval feels too sparse; raise it if low-value matches are crowding out better context.
- Example:

```env
PYTHON_CLAW_RETRIEVAL_MIN_SCORE=1.0
```

### `PYTHON_CLAW_MEMORY_ENABLED`

- Default: `true`
- Type: boolean
- What it does: Enables durable-memory extraction and use for Spec 011. Transcript rows remain canonical even when this is enabled.
- How to configure it: Leave it on for normal long-running continuity. Set it to `false` if you want to disable durable-memory derivation while keeping transcript and summary continuity intact.
- Example:

```env
PYTHON_CLAW_MEMORY_ENABLED=true
```

### `PYTHON_CLAW_MEMORY_STRATEGY_ID`

- Default: `memory-v1`
- Type: string
- Validation: must not be empty
- What it does: Names the durable-memory extraction strategy so memory derivation, retry dedupe, and rebuild behavior stay explicit and versionable.
- How to configure it: Use a stable version string and change it only when you intentionally revise the memory-extraction logic in a way that should produce new derived state.
- Example:

```env
PYTHON_CLAW_MEMORY_STRATEGY_ID=memory-v1
```

### `PYTHON_CLAW_ATTACHMENT_EXTRACTION_ENABLED`

- Default: `true`
- Type: boolean
- What it does: Enables durable attachment-content extraction for normalized files so prompt assembly can use extracted content when it is already available.
- How to configure it: Leave it enabled for Spec 011 attachment understanding. Set it to `false` if you want attachments to remain metadata-only.
- Example:

```env
PYTHON_CLAW_ATTACHMENT_EXTRACTION_ENABLED=true
```

### `PYTHON_CLAW_ATTACHMENT_EXTRACTION_STRATEGY_ID`

- Default: `attachment-v1`
- Type: string
- Validation: must not be empty
- What it does: Names the attachment extraction strategy version used for durable extraction records, retries, and rebuild decisions.
- How to configure it: Keep a stable versioned identifier and bump it when PDF parsing, text extraction, or similar extraction behavior changes materially.
- Example:

```env
PYTHON_CLAW_ATTACHMENT_EXTRACTION_STRATEGY_ID=attachment-v1
```

### `PYTHON_CLAW_ATTACHMENT_SAME_RUN_FAST_PATH_ENABLED`

- Default: `true`
- Type: boolean
- Validation: requires `PYTHON_CLAW_ATTACHMENT_EXTRACTION_ENABLED=true`
- What it does: Allows the worker-owned same-run fast path for supported text files and text-extractable PDFs after normalization and before context assembly.
- How to configure it: Leave it enabled if you want bounded same-turn attachment understanding. Set it to `false` to make all attachment extraction asynchronous and later-turn only.
- Example:

```env
PYTHON_CLAW_ATTACHMENT_SAME_RUN_FAST_PATH_ENABLED=true
```

### `PYTHON_CLAW_ATTACHMENT_SAME_RUN_MAX_BYTES`

- Default: `262144`
- Type: integer
- Validation: must be greater than `0`
- What it does: Caps the maximum attachment size eligible for same-run fast-path extraction. The default is 256 KiB.
- How to configure it: Raise it cautiously if you need same-turn extraction for larger text or PDF files and can tolerate the added latency.
- Example:

```env
PYTHON_CLAW_ATTACHMENT_SAME_RUN_MAX_BYTES=262144
```

### `PYTHON_CLAW_ATTACHMENT_SAME_RUN_PDF_PAGE_LIMIT`

- Default: `5`
- Type: integer
- Validation: must be greater than `0`
- What it does: Caps how many pages of a PDF may be considered for same-run fast-path extraction.
- How to configure it: Keep this low so same-turn extraction stays bounded. Increase it only if short PDFs are not enough for your workflow.
- Example:

```env
PYTHON_CLAW_ATTACHMENT_SAME_RUN_PDF_PAGE_LIMIT=5
```

### `PYTHON_CLAW_ATTACHMENT_SAME_RUN_TIMEOUT_SECONDS`

- Default: `2`
- Type: integer
- Validation: must be greater than `0`
- What it does: Limits how long the same-run attachment fast path may spend extracting supported content before it degrades safely to metadata-only context.
- How to configure it: Keep this short so accepted runs stay responsive. Raise it only if you intentionally want to spend more latency budget on same-turn attachment understanding.
- Example:

```env
PYTHON_CLAW_ATTACHMENT_SAME_RUN_TIMEOUT_SECONDS=2
```

## Remote Execution And Node Runner

### `PYTHON_CLAW_REMOTE_EXECUTION_ENABLED`

- Default: `false`
- Type: boolean
- What it does: Enables the remote node execution capability introduced in Spec 006.
- How to configure it: Leave this off unless you have the node-runner service and approval flow set up.
- Example:

```env
PYTHON_CLAW_REMOTE_EXECUTION_ENABLED=false
```

### `PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID`

- Default: `local-dev`
- Type: string
- What it does: Identifies which signing key the gateway uses when creating node-runner execution requests.
- How to configure it: Use a stable non-secret identifier that matches the verifier configuration on the node-runner side.
- Example:

```env
PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID=prod-node-key-2026-01
```

### `PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET`

- Default: `local-dev-secret`
- Type: string
- What it does: Supplies the shared secret used to sign node-runner requests.
- How to configure it: Replace this with a strong secret everywhere outside local development and rotate it carefully.
- Example:

```env
PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET=replace-with-a-long-random-secret
```

### `PYTHON_CLAW_NODE_RUNNER_REQUEST_TTL_SECONDS`

- Default: `30`
- Type: integer
- What it does: Limits how old a signed node-runner request may be before it is rejected as stale. This supports the bounded freshness contract in Spec 006.
- How to configure it: Keep it short to reduce replay risk, but long enough for normal internal request transit.
- Example:

```env
PYTHON_CLAW_NODE_RUNNER_REQUEST_TTL_SECONDS=30
```

### `PYTHON_CLAW_NODE_RUNNER_TIMEOUT_CEILING_SECONDS`

- Default: `30`
- Type: integer
- What it does: Caps the maximum execution timeout the gateway may request from the node runner.
- How to configure it: Set this to the longest remote command runtime you are willing to allow.
- Example:

```env
PYTHON_CLAW_NODE_RUNNER_TIMEOUT_CEILING_SECONDS=30
```

### `PYTHON_CLAW_NODE_RUNNER_ALLOW_OFF_MODE`

- Default: `false`
- Type: boolean
- What it does: Controls whether the system may intentionally allow sandbox mode `off` for node execution.
- How to configure it: Keep this `false` unless you are deliberately permitting unsandboxed execution in a tightly controlled environment.
- Example:

```env
PYTHON_CLAW_NODE_RUNNER_ALLOW_OFF_MODE=false
```

### `PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES`

- Default: `/bin/echo,/usr/bin/env`
- Type: comma-separated string
- What it does: Restricts which executables the node-runner path may invoke. This is part of the fail-closed command enforcement model from Spec 006.
- How to configure it: Keep the list explicit and minimal. Use absolute paths.
- Example:

```env
PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES=/bin/echo,/usr/bin/env,/usr/bin/python3
```

## Sandbox Defaults

### `PYTHON_CLAW_SANDBOX_WORKSPACE_ROOT`

- Default: `.claw-sandboxes`
- Type: path string
- What it does: Defines the base directory where sandbox workspaces are created or resolved.
- How to configure it: Point it at a writable filesystem location with enough room for per-agent or shared sandboxes.
- Example:

```env
PYTHON_CLAW_SANDBOX_WORKSPACE_ROOT=.claw-sandboxes
```

### `PYTHON_CLAW_SANDBOX_SHARED_BASE_KEY`

- Default: `shared-default`
- Type: string
- What it does: Supplies the stable key used for shared sandbox resolution when the policy chooses a shared sandbox mode.
- How to configure it: Use a predictable value that maps cleanly to your shared sandbox naming convention.
- Example:

```env
PYTHON_CLAW_SANDBOX_SHARED_BASE_KEY=shared-default
```

## Observability, Health, And Diagnostics

### `PYTHON_CLAW_OBSERVABILITY_JSON_LOGS`

- Default: `true`
- Type: boolean
- What it does: Enables JSON-formatted logs, which is the preferred structured logging mode for the observability work described in Spec 008.
- How to configure it: Keep this enabled for machine-readable logs; disable it only if you want simpler console output locally.
- Example:

```env
PYTHON_CLAW_OBSERVABILITY_JSON_LOGS=true
```

### `PYTHON_CLAW_OBSERVABILITY_LOG_CONTENT_PREVIEW`

- Default: `false`
- Type: boolean
- What it does: Controls whether logs may include bounded previews of content payloads.
- How to configure it: Leave this off in most environments to reduce leakage risk. Turn it on only for local debugging when you understand the privacy tradeoff.
- Example:

```env
PYTHON_CLAW_OBSERVABILITY_LOG_CONTENT_PREVIEW=false
```

### `PYTHON_CLAW_OBSERVABILITY_LOG_CONTENT_PREVIEW_CHARS`

- Default: `160`
- Type: integer
- What it does: Sets the maximum number of preview characters logged when content previews are enabled.
- How to configure it: Keep this short so debugging remains useful without exposing too much user content.
- Example:

```env
PYTHON_CLAW_OBSERVABILITY_LOG_CONTENT_PREVIEW_CHARS=160
```

### `PYTHON_CLAW_DIAGNOSTICS_ENABLED`

- Default: `true`
- Type: boolean
- What it does: Enables the diagnostics API surface added in Spec 008.
- How to configure it: Leave this on unless you intentionally want to suppress operator diagnostics routes.
- Example:

```env
PYTHON_CLAW_DIAGNOSTICS_ENABLED=true
```

### `PYTHON_CLAW_DIAGNOSTICS_PAGE_DEFAULT_LIMIT`

- Default: `20`
- Type: integer
- What it does: Sets the default page size for diagnostics list endpoints.
- How to configure it: Keep it small so operational queries remain bounded.
- Example:

```env
PYTHON_CLAW_DIAGNOSTICS_PAGE_DEFAULT_LIMIT=20
```

### `PYTHON_CLAW_DIAGNOSTICS_PAGE_MAX_LIMIT`

- Default: `50`
- Type: integer
- What it does: Caps the largest page size allowed on diagnostics list endpoints.
- How to configure it: Increase cautiously if operators truly need larger pages.
- Example:

```env
PYTHON_CLAW_DIAGNOSTICS_PAGE_MAX_LIMIT=50
```

### `PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN`

- Default: empty in code, sample value `change-me`
- Type: string or empty
- What it does: Supplies the bearer token for human operator access to `/diagnostics/*` routes.
- How to configure it: Set a strong secret in any environment where diagnostics are reachable. Replace the placeholder immediately.
- Example:

```env
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=replace-with-a-real-admin-token
```

### `PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN`

- Default: empty in code, sample value `change-me-internal`
- Type: string or empty
- What it does: Supplies the bearer token for trusted internal-service access to diagnostics and related internal surfaces.
- How to configure it: Use a different secret from the admin token so human and machine access stay separable, as required by Spec 008.
- Example:

```env
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=replace-with-a-real-internal-token
```

### `PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH`

- Default: `true`
- Type: boolean
- What it does: Controls whether `GET /health/ready` requires authentication. Spec 008 says readiness should be treated as an internal deployment surface by default.
- How to configure it: Keep this `true` for most environments. Set it to `false` only if your deployment intentionally exposes readiness publicly.
- Example:

```env
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true
```

### `PYTHON_CLAW_OBSERVABILITY_METRICS_ENABLED`

- Default: `false`
- Type: boolean
- What it does: Enables the metrics endpoint or exporter path for observability.
- How to configure it: Turn it on when you want metrics scraping in local or deployed environments.
- Example:

```env
PYTHON_CLAW_OBSERVABILITY_METRICS_ENABLED=true
```

### `PYTHON_CLAW_OBSERVABILITY_METRICS_PATH`

- Default: `/metrics`
- Type: string
- What it does: Sets the HTTP path used for metrics exposure when metrics are enabled.
- How to configure it: Leave the default unless your reverse proxy or deployment standard needs a different path.
- Example:

```env
PYTHON_CLAW_OBSERVABILITY_METRICS_PATH=/metrics
```

### `PYTHON_CLAW_OBSERVABILITY_TRACING_ENABLED`

- Default: `false`
- Type: boolean
- What it does: Enables trace instrumentation for the causal flow from gateway acceptance through worker completion and node-runner calls.
- How to configure it: Turn it on when you have a tracing backend or want local trace-compatible instrumentation.
- Example:

```env
PYTHON_CLAW_OBSERVABILITY_TRACING_ENABLED=true
```

### `PYTHON_CLAW_EXECUTION_RUN_STALE_AFTER_SECONDS`

- Default: `300`
- Type: integer
- What it does: Defines when execution runs should be treated as stale in diagnostics or recovery logic.
- How to configure it: Set it somewhat higher than the normal expected active lease window so healthy long-running work is not mislabeled too quickly.
- Example:

```env
PYTHON_CLAW_EXECUTION_RUN_STALE_AFTER_SECONDS=300
```

### `PYTHON_CLAW_OUTBOX_JOB_STALE_AFTER_SECONDS`

- Default: `300`
- Type: integer
- What it does: Defines the staleness threshold for outbox jobs related to continuity repair and follow-up processing from Spec 004.
- How to configure it: Use a value that reflects how long those jobs normally take before you want them flagged for inspection.
- Example:

```env
PYTHON_CLAW_OUTBOX_JOB_STALE_AFTER_SECONDS=300
```

### `PYTHON_CLAW_SCHEDULED_JOB_FIRE_STALE_AFTER_SECONDS`

- Default: `300`
- Type: integer
- What it does: Defines when scheduled job fires should be considered stale for observability and diagnostics.
- How to configure it: Keep it aligned with your scheduler cadence and operator expectations.
- Example:

```env
PYTHON_CLAW_SCHEDULED_JOB_FIRE_STALE_AFTER_SECONDS=300
```

### `PYTHON_CLAW_OUTBOUND_DELIVERY_STALE_AFTER_SECONDS`

- Default: `300`
- Type: integer
- What it does: Defines when outbound delivery records should be flagged as stale in the delivery diagnostics surfaces from Specs 007 and 008.
- How to configure it: Set it based on expected channel delivery timing.
- Example:

```env
PYTHON_CLAW_OUTBOUND_DELIVERY_STALE_AFTER_SECONDS=300
```

### `PYTHON_CLAW_NODE_EXECUTION_STALE_AFTER_SECONDS`

- Default: `300`
- Type: integer
- What it does: Defines when node execution audit records should be treated as stale for diagnostics and health reporting.
- How to configure it: Use a threshold that fits your remote execution timeout and expected completion behavior.
- Example:

```env
PYTHON_CLAW_NODE_EXECUTION_STALE_AFTER_SECONDS=300
```

### `PYTHON_CLAW_ATTACHMENT_STALE_AFTER_SECONDS`

- Default: `300`
- Type: integer
- What it does: Defines when attachment normalization work should be flagged as stale in attachment diagnostics.
- How to configure it: Keep it longer than normal attachment normalization latency but short enough to expose stuck media processing quickly.
- Example:

```env
PYTHON_CLAW_ATTACHMENT_STALE_AFTER_SECONDS=300
```

## Recommended Local Profiles

### Minimal local scaffold profile

Use this when you want the project to run without live LLM credentials:

```env
PYTHON_CLAW_RUNTIME_MODE=rule_based
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=change-me
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=change-me-internal
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true
PYTHON_CLAW_REMOTE_EXECUTION_ENABLED=false
```

### Local provider-backed profile

Use this when you want natural-language model responses through the Spec 009 provider path:

```env
PYTHON_CLAW_RUNTIME_MODE=provider
PYTHON_CLAW_LLM_PROVIDER=openai
PYTHON_CLAW_LLM_API_KEY=sk-your-provider-key
PYTHON_CLAW_LLM_MODEL=gpt-4o-mini
PYTHON_CLAW_LLM_TIMEOUT_SECONDS=30
PYTHON_CLAW_LLM_MAX_RETRIES=1
PYTHON_CLAW_LLM_TOOL_CALL_MODE=auto
PYTHON_CLAW_LLM_DISABLE_TOOLS=false
```

### Local media-and-diagnostics heavy profile

Use this when you are testing attachments, diagnostics, and operator APIs:

```env
PYTHON_CLAW_MEDIA_STORAGE_ROOT=.claw-media
PYTHON_CLAW_MEDIA_ALLOWED_SCHEMES=file,https
PYTHON_CLAW_MEDIA_ALLOWED_MIME_PREFIXES=image/,audio/,text/,application/pdf
PYTHON_CLAW_MEDIA_MAX_BYTES=5242880
PYTHON_CLAW_DIAGNOSTICS_ENABLED=true
PYTHON_CLAW_OBSERVABILITY_JSON_LOGS=true
PYTHON_CLAW_OBSERVABILITY_LOG_CONTENT_PREVIEW=false
```

## Notes And Caveats

- `PYTHON_CLAW_POSTGRES_*` and `PYTHON_CLAW_REDIS_PORT` are primarily local infrastructure helpers; the application itself connects through `PYTHON_CLAW_DATABASE_URL`.
- `PYTHON_CLAW_LLM_MAX_INPUT_TOKENS` and `PYTHON_CLAW_LLM_PROMPT_CHAR_TOKEN_RATIO` appear in `.env.example` as prompt-budget controls even though the current settings validator does not apply extra constraints to them.
- Placeholder values like `change-me`, `change-me-internal`, and `local-dev-secret` are for local development only and should not be used in shared environments.
