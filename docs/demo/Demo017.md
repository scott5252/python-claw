# Demo Guide: Spec 017 Production Hardening and Enterprise Readiness

This guide shows how to demo Spec 017 in a way that works for:

1. a non-developer who wants to see that the application is now safer to operate in a production-style environment
2. a developer who wants to verify the exact authentication, authorization, rate-limit, redaction, and node-runner transport-hardening behavior added in this spec

The demo covers:

1. enabling the new Spec 017 authentication, quota, and node-runner settings needed for a clean local demo
2. starting the gateway, worker helper, and optional node-runner service with deterministic local settings
3. proving that `/health/live` stays public while `/health/ready` is protected
4. proving that admin and transcript reads now require operator authentication
5. proving that diagnostics and readiness can be read by a trusted internal-service caller
6. proving that internal-service credentials cannot perform operator-style reads or operator-authored mutations
7. demonstrating application-owned rate limiting on inbound traffic and admin or diagnostics reads
8. demonstrating that secrets are not returned raw in app-facing surfaces and are redacted by the shared redaction helpers
9. optionally demonstrating the new node-runner HTTP transport-auth boundary
10. giving developers a short validation path through the Spec 017 tests and startup checks

The demo uses one simple real-world story:

- a support team runs the assistant in a production-like environment
- customer traffic still enters through the normal inbound gateway
- operators can inspect sessions and transcripts, but only when properly authenticated
- trusted automation can read readiness and diagnostics, but it cannot impersonate a human operator
- the backend now rate-limits high-volume or abusive traffic before durable side effects happen
- node-runner HTTP routes no longer trust the network boundary alone and require internal transport auth

Important note about this demo:

- this walkthrough is intentionally deterministic and local-first
- it does not require live provider credentials, live Slack, or live Telegram accounts
- the easiest way to show Spec 017 cleanly is to keep the main demo in `rule_based` mode and focus on the production-hardening boundaries around that flow
- the optional node-runner HTTP section is included because it is one of the most important new production boundaries in this spec

## 1. What You Will Run

For the main local demo, you will run:

- PostgreSQL with Docker Compose
- database migrations
- the gateway API
- the worker helper
- `curl` commands for customer, operator, and internal-service traffic

For the optional advanced node-runner section, you will also run:

- the node-runner API on a separate local port

You do not need live LLM provider credentials for this demo.

## 2. Before You Start

You need:

- Python 3.11+
- `uv`
- Docker Desktop or another Docker runtime

Work from the project root:

```bash
cd /Users/scottcornell/src/my-projects/python-claw
```

## 3. Real-World Scenario You Will Demonstrate

You will act out this workflow:

1. a customer sends normal inbound traffic to the gateway
2. the gateway accepts and processes that work normally
3. a non-sensitive liveness probe still succeeds publicly
4. a readiness probe now requires trusted credentials
5. an authenticated operator can inspect session, message, and run history
6. an authenticated internal-service caller can read diagnostics, but cannot read operator-only session history
7. the app rejects repeated inbound traffic and repeated admin reads with `429` once the configured quota is exceeded
8. the app avoids exposing raw secrets through normal health and diagnostics surfaces
9. the optional node-runner HTTP surface rejects unauthenticated internal calls before execution is even considered

This is what Spec 017 adds to the application:

- one shared operator versus internal-service auth contract
- operator-only admin and transcript reads
- machine-safe diagnostics and readiness reads for trusted internal-service callers
- durable PostgreSQL-backed quota counters and route rate limiting
- `429` responses with `Retry-After`
- stronger redaction for auth tokens, provider keys, and node-runner secrets
- explicit node-runner `in_process` versus `http` modes
- node-runner HTTP transport auth that is separate from signed execution payloads

## 4. Setup The Application

### Step 1: Prepare `.env`

If `.env` does not exist yet:

```bash
cp .env.example .env
```

For this demo, make sure these values exist in `.env`.

These are the minimum values you should set for a clean Spec 017 demo:

```text
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant

PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent
PYTHON_CLAW_RUNTIME_MODE=rule_based

PYTHON_CLAW_ADMIN_READS_REQUIRE_AUTH=true
PYTHON_CLAW_DIAGNOSTICS_REQUIRE_AUTH=true
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true
PYTHON_CLAW_AUTH_FAIL_CLOSED_IN_PRODUCTION=true

PYTHON_CLAW_OPERATOR_AUTH_BEARER_TOKEN=change-me
PYTHON_CLAW_INTERNAL_SERVICE_AUTH_TOKEN=change-me-internal
PYTHON_CLAW_OPERATOR_PRINCIPAL_HEADER_NAME=X-Operator-Id
PYTHON_CLAW_INTERNAL_SERVICE_PRINCIPAL_HEADER_NAME=X-Internal-Service-Principal

PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=change-me
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=change-me-internal

PYTHON_CLAW_RATE_LIMITS_ENABLED=true
PYTHON_CLAW_INBOUND_REQUESTS_PER_MINUTE_PER_CHANNEL_ACCOUNT=5
PYTHON_CLAW_ADMIN_REQUESTS_PER_MINUTE_PER_OPERATOR=3
PYTHON_CLAW_APPROVAL_ACTION_REQUESTS_PER_MINUTE_PER_SESSION=10
PYTHON_CLAW_PROVIDER_TOKENS_PER_HOUR_PER_AGENT=200000
PYTHON_CLAW_PROVIDER_REQUESTS_PER_MINUTE_PER_MODEL=120
PYTHON_CLAW_QUOTA_COUNTER_RETENTION_DAYS=7

PYTHON_CLAW_PROVIDER_RETRY_BASE_SECONDS=1.0
PYTHON_CLAW_PROVIDER_RETRY_MAX_SECONDS=16.0
PYTHON_CLAW_PROVIDER_RETRY_JITTER_SECONDS=0.25

PYTHON_CLAW_REMOTE_EXECUTION_ENABLED=false
PYTHON_CLAW_NODE_RUNNER_MODE=in_process
PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID=demo-node-key
PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET=demo-node-secret
PYTHON_CLAW_NODE_RUNNER_INTERNAL_BEARER_TOKEN=demo-node-internal-token

PYTHON_CLAW_CHANNEL_ACCOUNTS=[{"channel_account_id":"acct","channel_kind":"slack","mode":"fake"},{"channel_account_id":"acct","channel_kind":"telegram","mode":"fake"},{"channel_account_id":"acct","channel_kind":"webchat","mode":"fake"},{"channel_account_id":"acct-1","channel_kind":"slack","mode":"fake"},{"channel_account_id":"acct-1","channel_kind":"telegram","mode":"fake"},{"channel_account_id":"acct-1","channel_kind":"webchat","mode":"fake"}]
```

What each important setting does in this demo:

- `PYTHON_CLAW_OPERATOR_AUTH_BEARER_TOKEN=change-me`
  - this is the human operator token used for protected admin reads and mutations
- `PYTHON_CLAW_INTERNAL_SERVICE_AUTH_TOKEN=change-me-internal`
  - this is the machine token used for readiness and diagnostics reads
- `PYTHON_CLAW_ADMIN_READS_REQUIRE_AUTH=true`
  - operator-facing session, message, governance, and run reads are protected
- `PYTHON_CLAW_DIAGNOSTICS_REQUIRE_AUTH=true`
  - diagnostics reads require operator or internal-service auth
- `PYTHON_CLAW_RATE_LIMITS_ENABLED=true`
  - the app enforces the durable quota service instead of just accepting everything
- `PYTHON_CLAW_INBOUND_REQUESTS_PER_MINUTE_PER_CHANNEL_ACCOUNT=5`
  - this low value makes it easy to demonstrate inbound `429` behavior without a long load test
- `PYTHON_CLAW_ADMIN_REQUESTS_PER_MINUTE_PER_OPERATOR=3`
  - this low value makes it easy to demonstrate operator read throttling with one short loop
- `PYTHON_CLAW_NODE_RUNNER_MODE=in_process`
  - the main app demo stays simple and deterministic
- `PYTHON_CLAW_NODE_RUNNER_INTERNAL_BEARER_TOKEN=demo-node-internal-token`
  - this is used later in the optional HTTP node-runner demo

One practical demo note:

- the inbound and admin quota values are intentionally low so you can show `429` behavior quickly
- if you repeat the same section several times in under one minute, you may hit the limiter earlier than expected
- if that happens, wait 60 seconds and rerun the step

Important formatting notes:

- `PYTHON_CLAW_CHANNEL_ACCOUNTS` must be valid JSON
- safest option: keep each JSON value on one line exactly as shown above
- if you already have older diagnostics token names in `.env`, keep them aligned with the new shared tokens so the demo stays easy to reason about

### Step 2: Install Python dependencies

Run:

```bash
uv sync --group dev
```

What the system is doing:

- `uv` creates or updates the local virtual environment
- FastAPI, Alembic, SQLAlchemy, and the test helpers are installed
- no application data is created yet

### Step 3: Start local infrastructure

Run:

```bash
docker compose --env-file .env up -d
```

Optional checks:

```bash
docker compose ps
docker compose logs postgres
```

What the system is doing:

- Docker starts PostgreSQL from `docker-compose.yml`
- the durable queue, admin reads, diagnostics, and quota counters all use that database

### Step 4: Apply database migrations

Run:

```bash
uv run alembic upgrade head
```

Why this matters for Spec 017:

- the app needs the latest schema before you demonstrate protected operational reads
- the app needs the quota counter table before you demonstrate rate limiting
- the app needs the latest queue, delivery, and diagnostics tables before you inspect operational state

## 5. Run The Application

Use three terminals for the main demo and a fourth terminal only for the optional node-runner HTTP section.

### Terminal A: Start the gateway

Run:

```bash
uv run uvicorn apps.gateway.main:app --reload
```

The gateway starts on `http://127.0.0.1:8000`.

Expected startup behavior:

- the application loads `.env`
- settings validation confirms the new auth, quota, and node-runner settings are valid
- bootstrap creates or validates the default agent records

### Terminal B: Keep the worker helper ready

Run this command each time the guide tells you to process queued work:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What this worker helper does:

- it claims the next eligible run from the durable queue
- it processes exactly one run
- it commits the result

Why this is manual in the demo:

- it keeps each queue transition easy to explain
- it makes rate-limit and protected-read behavior easier to isolate

### Terminal C: Use `curl`

Set these shell variables once:

```bash
BASE=http://127.0.0.1:8000
AUTH='Authorization: Bearer change-me'
INTERNAL='X-Internal-Service-Token: change-me-internal'
OP='X-Operator-Id: operator-alex'
INTERNAL_PRINCIPAL='X-Internal-Service-Principal: deploy-checker'
```

Verify the service:

```bash
curl $BASE/health/live
curl -i $BASE/health/ready
curl $BASE/health/ready -H "$INTERNAL" -H "$INTERNAL_PRINCIPAL"
```

Expected result:

- `GET /health/live` returns HTTP `200`
- `GET /health/ready` without credentials returns HTTP `401`
- `GET /health/ready` with the internal-service token returns HTTP `200`

What this means:

- liveness is still safe to expose publicly
- readiness is treated as an internal operational surface
- the new internal-service caller path is active

## 6. Demonstrate Normal Customer Traffic

### Step 1: Send one normal inbound message

Run:

```bash
curl -sS -X POST $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind":"slack",
    "channel_account_id":"acct-1",
    "external_message_id":"demo017-msg-1",
    "sender_id":"customer-1",
    "content":"hello from a production hardening demo",
    "peer_id":"peer-1"
  }'
```

Expected result:

- the gateway returns HTTP `202`
- the response includes `session_id`, `message_id`, `run_id`, `status`, and `trace_id`

### Step 2: Process the queued run

Run the Terminal B worker helper once.

Expected result:

- the helper prints the processed `run_id`
- the run completes normally

### Step 3: Show that protected session reads now require operator auth

First try the read without credentials:

```bash
curl -i $BASE/sessions/<SESSION_ID>
```

Then try again with operator auth:

```bash
curl $BASE/sessions/<SESSION_ID> -H "$AUTH" -H "$OP"
curl $BASE/sessions/<SESSION_ID>/messages?limit=10 -H "$AUTH" -H "$OP"
curl $BASE/sessions/<SESSION_ID>/runs -H "$AUTH" -H "$OP"
```

Replace `<SESSION_ID>` with the value returned from the inbound response.

Expected result:

- the unauthenticated request returns `401`
- the authenticated operator reads return `200`
- the session message history shows the customer message and the assistant reply

What a non-developer should take away:

- the app still works normally for the customer
- internal session history is no longer open to anonymous callers

What a developer should take away:

- operator-only read classification is active for session, transcript, and run history routes

## 7. Demonstrate Operator Versus Internal-Service Separation

### Step 1: Show that internal-service callers can read diagnostics

Run:

```bash
curl $BASE/diagnostics/runs -H "$INTERNAL" -H "$INTERNAL_PRINCIPAL"
curl $BASE/diagnostics/sessions/<SESSION_ID>/continuity -H "$INTERNAL" -H "$INTERNAL_PRINCIPAL"
```

Expected result:

- both routes return HTTP `200`
- the diagnostics payload includes bounded operational state

### Step 2: Show that internal-service callers cannot read operator-only session history

Run:

```bash
curl -i $BASE/sessions/<SESSION_ID> -H "$INTERNAL" -H "$INTERNAL_PRINCIPAL"
curl -i $BASE/sessions/<SESSION_ID>/messages?limit=10 -H "$INTERNAL" -H "$INTERNAL_PRINCIPAL"
```

Expected result:

- both routes return HTTP `403`

What this means:

- internal-service credentials are real credentials
- but they do not have the same authorization ceiling as an operator

### Step 3: Show that internal-service callers cannot perform an operator-authored mutation

Run:

```bash
curl -i -X POST $BASE/sessions/<SESSION_ID>/notes \
  -H 'Content-Type: application/json' \
  -H "$INTERNAL" \
  -H "$INTERNAL_PRINCIPAL" \
  -d '{"note_kind":"internal","body":"this should not be accepted as an operator note"}'
```

Expected result:

- the route returns HTTP `403`

Now perform the same note write correctly as an operator:

```bash
curl $BASE/sessions/<SESSION_ID>/notes \
  -X POST \
  -H 'Content-Type: application/json' \
  -H "$AUTH" \
  -H "$OP" \
  -d '{"note_kind":"internal","body":"operator-authored note for demo017"}'
```

Expected result:

- the route returns HTTP `200`
- the returned note is attributed to the operator principal you sent in `X-Operator-Id`

Developer verification:

```bash
curl $BASE/sessions/<SESSION_ID>/notes -H "$AUTH" -H "$OP"
```

You should see the operator-authored note in the append-only notes list.

## 8. Demonstrate Admin And Diagnostics Rate Limiting

This section proves that the application now rejects excess traffic with backend-owned quotas.

### Step 1: Trigger the operator read quota

Use a fresh operator principal so this test is isolated from earlier reads:

```bash
for i in 1 2 3 4; do
  echo "Request $i"
  curl -i $BASE/diagnostics/runs \
    -H 'Authorization: Bearer change-me' \
    -H 'X-Operator-Id: operator-rate-test'
  echo
done
```

Expected result:

- the first three requests should succeed
- the fourth request should return HTTP `429`
- the response should include a `Retry-After` header

What this means:

- the app is enforcing the durable admin-read quota
- the limiter is keyed by the authenticated operator principal

### Step 2: Trigger the inbound rate limit

Use five quick requests that should succeed, then a sixth that should fail:

```bash
for i in 1 2 3 4 5 6; do
  echo "Inbound $i"
  curl -i -X POST $BASE/inbound/message \
    -H 'Content-Type: application/json' \
    -d "{
      \"channel_kind\":\"slack\",
      \"channel_account_id\":\"acct-1\",
      \"external_message_id\":\"demo017-rate-$i\",
      \"sender_id\":\"customer-rate\",
      \"content\":\"rate-limit test $i\",
      \"peer_id\":\"peer-rate\"
    }"
  echo
done
```

Expected result:

- the early requests return `202`
- the final request returns `429`
- the rejected response includes `Retry-After`

What a non-developer should take away:

- the system now protects itself against bursts instead of just accepting everything

What a developer should take away:

- the rate-limit decision happens before normal inbound mutation flow
- the backend, not an external proxy alone, owns this decision

Optional deeper developer verification:

```bash
docker compose exec postgres psql -U openassistant -d openassistant -c "select scope_kind, scope_key, window_seconds, count from rate_limit_counters order by id desc limit 10;"
```

You should see recently created durable quota rows for the operator and channel-account scopes.

## 9. Demonstrate Secret Redaction And Safe Operational Surfaces

### Step 1: Confirm that health and diagnostics reads do not return raw tokens

Run:

```bash
curl $BASE/health/ready -H "$INTERNAL" -H "$INTERNAL_PRINCIPAL"
curl $BASE/diagnostics/runs -H "$INTERNAL" -H "$INTERNAL_PRINCIPAL"
```

Expected result:

- both responses return operational data
- neither response includes your operator token, internal-service token, or node-runner secret

### Step 2: Show the shared redaction helper masking secrets

Run:

```bash
uv run python - <<'PY'
from src.observability.redaction import redact_value

examples = {
    "operator_auth_bearer_token": "super-secret-operator-token",
    "internal_service_auth_token": "super-secret-internal-token",
    "node_runner_internal_bearer_token": "super-secret-node-token",
    "llm_api_key": "sk-example-secret",
}

for key, value in examples.items():
    print(key, "=>", redact_value(key, value))
PY
```

Expected result:

- every printed value should be `[redacted]`

What this means:

- the same shared redaction posture used by the application knows about the new Spec 017 secrets
- operators and developers can verify the behavior without reading app source code line by line

## 10. Optional Advanced Demo: Node-Runner HTTP Transport Auth

This is the clearest short demo of the new node-runner HTTP transport boundary.

Use a fourth terminal for this section.

### Step 1: Start the node-runner in HTTP mode

Run:

```bash
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant \
PYTHON_CLAW_NODE_RUNNER_MODE=http \
PYTHON_CLAW_NODE_RUNNER_BASE_URL=http://127.0.0.1:8100 \
PYTHON_CLAW_NODE_RUNNER_INTERNAL_BEARER_TOKEN=demo-node-internal-token \
PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID=demo-node-key \
PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET=demo-node-secret \
uv run uvicorn apps.node_runner.main:app --port 8100 --reload
```

Expected result:

- the node-runner starts on `http://127.0.0.1:8100`

### Step 2: Show that health is reachable

Run:

```bash
curl http://127.0.0.1:8100/health/live
```

Expected result:

- the node-runner liveness route returns `200`

### Step 3: Show that the internal execution route rejects unauthenticated traffic

Run:

```bash
curl -i -X POST http://127.0.0.1:8100/internal/node/exec \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Expected result:

- the route returns HTTP `401`

What this proves:

- the node-runner no longer trusts the HTTP boundary alone
- transport auth is enforced before execution can even be considered

Important note:

- a full signed remote execution payload is intentionally more technical than this guide needs
- the repository tests cover the signed request path in detail
- this live demo focuses on the most visible new security boundary: the required internal bearer auth on the HTTP node-runner surface

## 11. Developer Validation Path

If you are demonstrating this to a technical reviewer, finish with these checks.

### Step 1: Run the Spec 017-focused tests

Run:

```bash
PYTHON_CLAW_DATABASE_URL=sqlite:// uv run pytest -q tests/test_spec_017.py
```

What this proves:

- auth boundaries are enforced
- internal-service callers cannot perform operator-only reads or mutations
- rate limiting returns `429`
- node-runner HTTP transport auth is protected
- new secret redaction behavior is covered

### Step 2: Run the full test suite

Run:

```bash
PYTHON_CLAW_DATABASE_URL=sqlite:// uv run pytest -q
```

What this proves:

- the hardening changes did not break the existing feature set
- the production-hardening slice is compatible with the repo’s earlier specs

### Step 3: Run a simple startup check

Run:

```bash
PYTHON_CLAW_DATABASE_URL=sqlite:// uv run python - <<'PY'
from apps.gateway.main import create_app
from apps.node_runner.main import create_app as create_node_runner_app

create_app()
create_node_runner_app()
print("startup-ok")
PY
```

Expected result:

- the script prints `startup-ok`

## 12. What Success Looks Like

At the end of this demo, a non-developer should understand:

1. the app still works for normal customer traffic
2. internal operational surfaces are no longer casually open
3. operators and internal automation now have different access boundaries
4. the app protects itself against burst traffic with `429` responses
5. internal secrets are treated more carefully than before

At the end of this demo, a developer should have verified:

1. `/health/live` is public while `/health/ready` is protected
2. session, transcript, governance, and run reads require operator authentication
3. diagnostics and readiness accept internal-service authentication
4. internal-service callers are denied on operator-only reads and operator-authored writes
5. rate limiting is app-owned, durable, and visible through the `rate_limit_counters` table
6. the shared redaction helpers cover the new Spec 017 secret-bearing fields
7. the node-runner HTTP surface requires transport auth

## 13. Cleanup

When you are done:

1. stop the gateway and optional node-runner processes with `Ctrl+C`
2. stop Docker services:

```bash
docker compose --env-file .env down
```

3. if you used demo tokens such as `change-me`, replace or remove them before using the same environment for anything beyond local development
