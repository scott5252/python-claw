# Quick Start For `example`

This guide was prepared by reviewing Specs `001` through `017`, [`docs/env_settings.md`](/docs/env_settings.md), and [`example/example.md`](/example/example.md). The current codebase is a gateway-first, database-backed assistant platform with durable sessions, queued worker execution, approval-gated remote execution, child-agent delegation, webchat delivery, and audited diagnostics.

For `example`, the important takeaway is this: the demo is not driven by one setting. It depends on a coordinated `.env` profile that turns on provider-backed LLM execution, webchat ingress, durable approvals, delegation to specialist agents, HTTP node-runner remote execution, and the bootstrap templates that teach each child agent how to call `remote_exec`.

## What You Actually Need To Change

If you start from [` .env.demo `](/.env.demo), the only value you normally must replace is:

```env
PYTHON_CLAW_LLM_API_KEY=YOUR_OPENAI_API_KEY
```

Everything else in `.env.demo` is already shaped for `example`. Still, those other values are required, because they control runtime mode, agent profiles, child-agent permissions, node-runner access, and webchat behavior.

One webchat detail is easy to miss: the bundled browser client still sends a client token even when the `webchat-demo` account runs in fake mode. The gateway expects `X-Webchat-Client-Token: fake-webchat-token` for fake webchat accounts, which is why [`example/webchat.html`](/example/webchat.html) works out of the box.

## Step-By-Step `.env` Setup

1. Copy [` .env.demo `](/.env.demo) to `.env`.
2. Replace `PYTHON_CLAW_LLM_API_KEY` with a valid OpenAI API key.
3. Keep `PYTHON_CLAW_RUNTIME_MODE=provider` so the worker uses the provider-backed model instead of the rule-based fallback.
4. Keep `PYTHON_CLAW_LLM_PROVIDER=openai` and `PYTHON_CLAW_LLM_MODEL=gpt-4o-mini` unless you intentionally want a different OpenAI model.
5. Keep `PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@postgres:5432/openassistant` exactly as-is for Docker Compose. The hostname `postgres` is correct inside the Compose network.
6. Keep `PYTHON_CLAW_NODE_RUNNER_MODE=http` and `PYTHON_CLAW_NODE_RUNNER_BASE_URL=http://node-runner:8010` so remote execution goes through the separate node-runner container.
7. Keep `PYTHON_CLAW_NODE_RUNNER_INTERNAL_BEARER_TOKEN`, `PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID`, and `PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET` populated. The gateway and node-runner both need them to trust each other.
8. Keep `PYTHON_CLAW_REMOTE_EXECUTION_ENABLED=true`, and keep the `deploy-agent`, `code-agent`, and `notify-agent` policy/tool profiles enabled through `PYTHON_CLAW_POLICY_PROFILES`, `PYTHON_CLAW_TOOL_PROFILES`, and `PYTHON_CLAW_HISTORICAL_AGENT_PROFILE_OVERRIDES`.
9. Keep `PYTHON_CLAW_REMOTE_EXEC_AGENT_TEMPLATES` populated. Without these templates, approved `remote_exec` calls from the child agents cannot resolve to an executable and argument template.
10. Keep `PYTHON_CLAW_CHANNEL_ACCOUNTS=[{"channel_account_id":"webchat-demo","channel_kind":"webchat","mode":"fake"}]` so the example webchat UI can connect without live provider credentials.
11. Use the default fake webchat client token from [`example/webchat.html`](/example/webchat.html): `fake-webchat-token`. If you send requests with a different client, include header `X-Webchat-Client-Token: fake-webchat-token` or the gateway will reject the request.
12. Keep `PYTHON_CLAW_WEBCHAT_INTERACTIVE_APPROVALS_ENABLED=true` so approval prompts are rendered for the webchat surface.
13. Keep the auth and diagnostics tokens populated. The runtime and the admin inspection steps both depend on them.
14. If you change host ports such as `PYTHON_CLAW_POSTGRES_PORT` or `PYTHON_CLAW_REDIS_PORT`, also update your Docker usage accordingly. These two values affect host exposure, not the in-container service names used by `PYTHON_CLAW_DATABASE_URL`.
15. After editing `.env`, run the example with a fresh database volume if you previously booted the stack in `rule_based` mode. The agent/model bootstrap is seeded from current settings.

## `.env` Settings Needed For `example`

### Core application and infrastructure

```env
PYTHON_CLAW_APP_NAME=python-claw-gateway
PYTHON_CLAW_POSTGRES_DB=openassistant
PYTHON_CLAW_POSTGRES_USER=openassistant
PYTHON_CLAW_POSTGRES_PASSWORD=openassistant
PYTHON_CLAW_POSTGRES_PORT=5432
PYTHON_CLAW_REDIS_PORT=6379
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@postgres:5432/openassistant
PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent
PYTHON_CLAW_WORKER_POLL_SECONDS=2
PYTHON_CLAW_WORKER_IDLE_LOG_EVERY=30
```

### Provider-backed LLM runtime

```env
PYTHON_CLAW_RUNTIME_TRANSCRIPT_CONTEXT_LIMIT=50
PYTHON_CLAW_RUNTIME_MODE=provider
PYTHON_CLAW_LLM_PROVIDER=openai
PYTHON_CLAW_LLM_API_KEY=YOUR_OPENAI_API_KEY
PYTHON_CLAW_LLM_MODEL=gpt-4o-mini
PYTHON_CLAW_LLM_TIMEOUT_SECONDS=30
PYTHON_CLAW_LLM_MAX_RETRIES=1
PYTHON_CLAW_LLM_TEMPERATURE=0.2
PYTHON_CLAW_LLM_MAX_OUTPUT_TOKENS=700
PYTHON_CLAW_LLM_TOOL_CALL_MODE=auto
PYTHON_CLAW_LLM_MAX_TOOL_REQUESTS_PER_TURN=4
PYTHON_CLAW_LLM_DISABLE_TOOLS=false
```

### Remote execution and node-runner

```env
PYTHON_CLAW_REMOTE_EXECUTION_ENABLED=true
PYTHON_CLAW_NODE_RUNNER_MODE=http
PYTHON_CLAW_NODE_RUNNER_BASE_URL=http://node-runner:8010
PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID=local-demo-key
PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET=local-demo-signing-secret
PYTHON_CLAW_NODE_RUNNER_INTERNAL_BEARER_TOKEN=local-demo-node-token
PYTHON_CLAW_NODE_RUNNER_REQUEST_TTL_SECONDS=30
PYTHON_CLAW_NODE_RUNNER_TIMEOUT_CEILING_SECONDS=30
PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES=/usr/bin/curl,/bin/echo,/usr/bin/env,/usr/local/bin/python3
PYTHON_CLAW_NODE_RUNNER_ALLOW_OFF_MODE=false
```

### Auth, diagnostics, and webchat approval UX

```env
PYTHON_CLAW_ADMIN_READS_REQUIRE_AUTH=true
PYTHON_CLAW_DIAGNOSTICS_REQUIRE_AUTH=true
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true
PYTHON_CLAW_AUTH_FAIL_CLOSED_IN_PRODUCTION=true
PYTHON_CLAW_OPERATOR_AUTH_BEARER_TOKEN=demo-operator-token
PYTHON_CLAW_INTERNAL_SERVICE_AUTH_TOKEN=demo-internal-token
PYTHON_CLAW_OPERATOR_PRINCIPAL_HEADER_NAME=X-Operator-Id
PYTHON_CLAW_INTERNAL_SERVICE_PRINCIPAL_HEADER_NAME=X-Internal-Service-Principal
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=demo-operator-token
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=demo-internal-token
PYTHON_CLAW_WEBCHAT_INTERACTIVE_APPROVALS_ENABLED=true
```

### Rate limits and quotas

```env
PYTHON_CLAW_RATE_LIMITS_ENABLED=true
PYTHON_CLAW_INBOUND_REQUESTS_PER_MINUTE_PER_CHANNEL_ACCOUNT=20
PYTHON_CLAW_ADMIN_REQUESTS_PER_MINUTE_PER_OPERATOR=30
PYTHON_CLAW_APPROVAL_ACTION_REQUESTS_PER_MINUTE_PER_SESSION=20
PYTHON_CLAW_PROVIDER_TOKENS_PER_HOUR_PER_AGENT=200000
PYTHON_CLAW_PROVIDER_REQUESTS_PER_MINUTE_PER_MODEL=120
PYTHON_CLAW_QUOTA_COUNTER_RETENTION_DAYS=7
```

### Delegation packaging and agent control

```env
PYTHON_CLAW_DELEGATION_PACKAGE_TRANSCRIPT_TURNS=6
PYTHON_CLAW_DELEGATION_PACKAGE_RETRIEVAL_ITEMS=4
PYTHON_CLAW_DELEGATION_PACKAGE_ATTACHMENT_ITEMS=2
PYTHON_CLAW_DELEGATION_PACKAGE_MAX_CHARS=4000
PYTHON_CLAW_POLICY_PROFILES=[{"key":"default","remote_execution_enabled":false,"denied_capability_names":[],"delegation_enabled":true,"max_delegation_depth":2,"allowed_child_agent_ids":["deploy-agent","code-agent","notify-agent"],"max_active_delegations_per_run":1,"max_active_delegations_per_session":3},{"key":"deploy-policy","remote_execution_enabled":true,"denied_capability_names":[],"delegation_enabled":false,"max_delegation_depth":0,"allowed_child_agent_ids":[],"max_active_delegations_per_run":null,"max_active_delegations_per_session":null},{"key":"code-policy","remote_execution_enabled":true,"denied_capability_names":[],"delegation_enabled":false,"max_delegation_depth":0,"allowed_child_agent_ids":[],"max_active_delegations_per_run":null,"max_active_delegations_per_session":null},{"key":"notify-policy","remote_execution_enabled":true,"denied_capability_names":[],"delegation_enabled":false,"max_delegation_depth":0,"allowed_child_agent_ids":[],"max_active_delegations_per_run":null,"max_active_delegations_per_session":null}]
PYTHON_CLAW_TOOL_PROFILES=[{"key":"default","allowed_capability_names":["echo_text","delegate_to_agent"]},{"key":"deploy-tools","allowed_capability_names":["echo_text","remote_exec"]},{"key":"code-tools","allowed_capability_names":["echo_text","remote_exec"]},{"key":"notify-tools","allowed_capability_names":["echo_text","remote_exec"]}]
PYTHON_CLAW_HISTORICAL_AGENT_PROFILE_OVERRIDES=[{"agent_id":"deploy-agent","model_profile_key":"default","policy_profile_key":"deploy-policy","tool_profile_key":"deploy-tools"},{"agent_id":"code-agent","model_profile_key":"default","policy_profile_key":"code-policy","tool_profile_key":"code-tools"},{"agent_id":"notify-agent","model_profile_key":"default","policy_profile_key":"notify-policy","tool_profile_key":"notify-tools"}]
PYTHON_CLAW_CHANNEL_ACCOUNTS=[{"channel_account_id":"webchat-demo","channel_kind":"webchat","mode":"fake"}]
PYTHON_CLAW_REMOTE_EXEC_AGENT_TEMPLATES=[{"agent_id":"deploy-agent","executable":"/usr/bin/curl","argv_template":["-s","-X","POST","-H","Content-Type: application/json","-d","{json_payload}","{url}"],"timeout_seconds":15,"sandbox_profile_key":"shared-default","workspace_binding_kind":"none","workspace_mount_mode":"none"},{"agent_id":"code-agent","executable":"/usr/local/bin/python3","argv_template":["-c","{script}"],"timeout_seconds":30,"sandbox_profile_key":"shared-default","workspace_binding_kind":"agent","workspace_mount_mode":"rw"},{"agent_id":"notify-agent","executable":"/usr/local/bin/python3","argv_template":["-c","{script}"],"timeout_seconds":30,"sandbox_profile_key":"shared-default","workspace_binding_kind":"none","workspace_mount_mode":"none"}]
```

## Variable Reference

The table below focuses on the variables that materially affect `example`.

| Variable | What it does | Impact on `example` | Example |
| --- | --- | --- | --- |
| `PYTHON_CLAW_APP_NAME` | Names the FastAPI service. | Affects service identity in logs and health output. | `PYTHON_CLAW_APP_NAME=python-claw-gateway` |
| `PYTHON_CLAW_POSTGRES_DB` | Names the Docker Postgres database. | Must match the database expected by Compose and migration commands. | `PYTHON_CLAW_POSTGRES_DB=openassistant` |
| `PYTHON_CLAW_POSTGRES_USER` | Docker Postgres username. | Must align with `PYTHON_CLAW_DATABASE_URL`. | `PYTHON_CLAW_POSTGRES_USER=openassistant` |
| `PYTHON_CLAW_POSTGRES_PASSWORD` | Docker Postgres password. | Must align with `PYTHON_CLAW_DATABASE_URL`. | `PYTHON_CLAW_POSTGRES_PASSWORD=openassistant` |
| `PYTHON_CLAW_POSTGRES_PORT` | Host port for Postgres exposure. | Only matters for host access; the app still uses `postgres` inside Docker. | `PYTHON_CLAW_POSTGRES_PORT=5432` |
| `PYTHON_CLAW_REDIS_PORT` | Host port for Redis exposure. | Needed for local stack parity; not the main runtime persistence path. | `PYTHON_CLAW_REDIS_PORT=6379` |
| `PYTHON_CLAW_DATABASE_URL` | Main SQLAlchemy connection string. | The gateway and worker cannot run without it. In Compose the host must be `postgres`. | `PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@postgres:5432/openassistant` |
| `PYTHON_CLAW_DEFAULT_AGENT_ID` | Default owner agent for new primary sessions. | Creates primary webchat sessions under `default-agent`. | `PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent` |
| `PYTHON_CLAW_RUNTIME_TRANSCRIPT_CONTEXT_LIMIT` | Caps direct transcript context assembly. | Controls how much recent session history the model sees. | `PYTHON_CLAW_RUNTIME_TRANSCRIPT_CONTEXT_LIMIT=50` |
| `PYTHON_CLAW_RUNTIME_MODE` | Chooses `rule_based` or `provider`. | Must be `provider` for LLM delegation and child-agent planning to work as shown. | `PYTHON_CLAW_RUNTIME_MODE=provider` |
| `PYTHON_CLAW_LLM_PROVIDER` | Selects provider backend. | Must be `openai` for the example configuration. | `PYTHON_CLAW_LLM_PROVIDER=openai` |
| `PYTHON_CLAW_LLM_API_KEY` | Provider credential. | Required by settings validation when `runtime_mode=provider`; this is the main user-supplied secret. | `PYTHON_CLAW_LLM_API_KEY=sk-...` |
| `PYTHON_CLAW_LLM_MODEL` | Default provider model. | Controls how the parent and child agents reason and choose tools. | `PYTHON_CLAW_LLM_MODEL=gpt-4o-mini` |
| `PYTHON_CLAW_LLM_TIMEOUT_SECONDS` | Provider request timeout. | Prevents long-hanging model calls. | `PYTHON_CLAW_LLM_TIMEOUT_SECONDS=30` |
| `PYTHON_CLAW_LLM_MAX_RETRIES` | Provider retry count. | Limits automatic retries on model failures. | `PYTHON_CLAW_LLM_MAX_RETRIES=1` |
| `PYTHON_CLAW_LLM_TEMPERATURE` | Sampling temperature. | Keeps the example relatively deterministic while still allowing tool selection. | `PYTHON_CLAW_LLM_TEMPERATURE=0.2` |
| `PYTHON_CLAW_LLM_MAX_OUTPUT_TOKENS` | Caps model output length. | Helps keep responses and tool plans bounded. | `PYTHON_CLAW_LLM_MAX_OUTPUT_TOKENS=700` |
| `PYTHON_CLAW_LLM_TOOL_CALL_MODE` | Controls whether provider tool calling is enabled. | Must allow automatic tool calling so delegation and `remote_exec` can be proposed. | `PYTHON_CLAW_LLM_TOOL_CALL_MODE=auto` |
| `PYTHON_CLAW_LLM_MAX_TOOL_REQUESTS_PER_TURN` | Max tool requests per turn. | Keeps tool planning bounded. | `PYTHON_CLAW_LLM_MAX_TOOL_REQUESTS_PER_TURN=4` |
| `PYTHON_CLAW_LLM_DISABLE_TOOLS` | Hard switch for tool use. | Must remain `false` or the example cannot delegate or propose `remote_exec`. | `PYTHON_CLAW_LLM_DISABLE_TOOLS=false` |
| `PYTHON_CLAW_REMOTE_EXECUTION_ENABLED` | Global remote-exec capability switch. | Enables the governed `remote_exec` path. | `PYTHON_CLAW_REMOTE_EXECUTION_ENABLED=true` |
| `PYTHON_CLAW_NODE_RUNNER_MODE` | Chooses in-process or HTTP node-runner mode. | Must be `http` for the isolated containerized example. | `PYTHON_CLAW_NODE_RUNNER_MODE=http` |
| `PYTHON_CLAW_NODE_RUNNER_BASE_URL` | Gateway-to-node-runner URL. | Required when `node_runner_mode=http`; used by `apps/gateway/deps.py`. | `PYTHON_CLAW_NODE_RUNNER_BASE_URL=http://node-runner:8010` |
| `PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID` | Signing key id for internal node execution requests. | Lets node-runner verify gateway-signed payloads. | `PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID=local-demo-key` |
| `PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET` | Shared signing secret. | Must match between gateway and node-runner or remote execution is rejected. | `PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET=local-demo-signing-secret` |
| `PYTHON_CLAW_NODE_RUNNER_INTERNAL_BEARER_TOKEN` | Bearer token for gateway-to-node-runner HTTP calls. | Required by settings validation in HTTP mode. | `PYTHON_CLAW_NODE_RUNNER_INTERNAL_BEARER_TOKEN=local-demo-node-token` |
| `PYTHON_CLAW_NODE_RUNNER_REQUEST_TTL_SECONDS` | Signed-request lifetime. | Limits replay window for node-runner requests. | `PYTHON_CLAW_NODE_RUNNER_REQUEST_TTL_SECONDS=30` |
| `PYTHON_CLAW_NODE_RUNNER_TIMEOUT_CEILING_SECONDS` | Max remote execution timeout. | Caps gateway HTTP wait and sandbox execution duration. | `PYTHON_CLAW_NODE_RUNNER_TIMEOUT_CEILING_SECONDS=30` |
| `PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES` | Allowlist of executable paths. | Must include `/usr/bin/curl` for deploy-agent and `/usr/local/bin/python3` for code-agent and notify-agent. | `PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES=/usr/bin/curl,/bin/echo,/usr/bin/env,/usr/local/bin/python3` |
| `PYTHON_CLAW_NODE_RUNNER_ALLOW_OFF_MODE` | Allows sandbox `off` mode. | Kept `false` for a safer demo posture. | `PYTHON_CLAW_NODE_RUNNER_ALLOW_OFF_MODE=false` |
| `PYTHON_CLAW_ADMIN_READS_REQUIRE_AUTH` | Protects admin reads. | Required for the audit-inspection steps. | `PYTHON_CLAW_ADMIN_READS_REQUIRE_AUTH=true` |
| `PYTHON_CLAW_DIAGNOSTICS_REQUIRE_AUTH` | Protects diagnostics APIs. | Required for Step 9 diagnostics reads. | `PYTHON_CLAW_DIAGNOSTICS_REQUIRE_AUTH=true` |
| `PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH` | Protects readiness checks. | Keeps production-style auth behavior in the demo. | `PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true` |
| `PYTHON_CLAW_AUTH_FAIL_CLOSED_IN_PRODUCTION` | Makes auth fail closed. | Prevents silently-open auth behavior. | `PYTHON_CLAW_AUTH_FAIL_CLOSED_IN_PRODUCTION=true` |
| `PYTHON_CLAW_OPERATOR_AUTH_BEARER_TOKEN` | Admin bearer token. | Used by Step 9 `curl` examples. | `PYTHON_CLAW_OPERATOR_AUTH_BEARER_TOKEN=demo-operator-token` |
| `PYTHON_CLAW_INTERNAL_SERVICE_AUTH_TOKEN` | Internal service token. | Supports trusted internal access patterns. | `PYTHON_CLAW_INTERNAL_SERVICE_AUTH_TOKEN=demo-internal-token` |
| `PYTHON_CLAW_OPERATOR_PRINCIPAL_HEADER_NAME` | Operator identity header name. | Used for durable operator principal propagation. | `PYTHON_CLAW_OPERATOR_PRINCIPAL_HEADER_NAME=X-Operator-Id` |
| `PYTHON_CLAW_INTERNAL_SERVICE_PRINCIPAL_HEADER_NAME` | Internal principal header name. | Used on internal-service style calls. | `PYTHON_CLAW_INTERNAL_SERVICE_PRINCIPAL_HEADER_NAME=X-Internal-Service-Principal` |
| `PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN` | Diagnostics admin token. | Mirrors the operator token in the demo. | `PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=demo-operator-token` |
| `PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN` | Diagnostics internal token. | Mirrors the internal token in the demo. | `PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=demo-internal-token` |
| `PYTHON_CLAW_WEBCHAT_INTERACTIVE_APPROVALS_ENABLED` | Enables webchat approval UX. | Required so pending proposals appear as webchat approval prompts. | `PYTHON_CLAW_WEBCHAT_INTERACTIVE_APPROVALS_ENABLED=true` |
| `PYTHON_CLAW_RATE_LIMITS_ENABLED` | Enables quota checks. | Turns on the guarded path used by webchat ingress. | `PYTHON_CLAW_RATE_LIMITS_ENABLED=true` |
| `PYTHON_CLAW_INBOUND_REQUESTS_PER_MINUTE_PER_CHANNEL_ACCOUNT` | Inbound per-channel account limit. | Protects webchat ingress in the demo. | `PYTHON_CLAW_INBOUND_REQUESTS_PER_MINUTE_PER_CHANNEL_ACCOUNT=20` |
| `PYTHON_CLAW_ADMIN_REQUESTS_PER_MINUTE_PER_OPERATOR` | Admin API rate limit. | Bounds Step 9 admin reads. | `PYTHON_CLAW_ADMIN_REQUESTS_PER_MINUTE_PER_OPERATOR=30` |
| `PYTHON_CLAW_APPROVAL_ACTION_REQUESTS_PER_MINUTE_PER_SESSION` | Approval action rate limit. | Bounds interactive approval operations. | `PYTHON_CLAW_APPROVAL_ACTION_REQUESTS_PER_MINUTE_PER_SESSION=20` |
| `PYTHON_CLAW_PROVIDER_TOKENS_PER_HOUR_PER_AGENT` | Provider token quota. | Prevents one agent from consuming unlimited model tokens. | `PYTHON_CLAW_PROVIDER_TOKENS_PER_HOUR_PER_AGENT=200000` |
| `PYTHON_CLAW_PROVIDER_REQUESTS_PER_MINUTE_PER_MODEL` | Provider request quota. | Bounds model call throughput. | `PYTHON_CLAW_PROVIDER_REQUESTS_PER_MINUTE_PER_MODEL=120` |
| `PYTHON_CLAW_QUOTA_COUNTER_RETENTION_DAYS` | Retains quota counters. | Affects cleanup horizon for rate-limit state. | `PYTHON_CLAW_QUOTA_COUNTER_RETENTION_DAYS=7` |
| `PYTHON_CLAW_DELEGATION_PACKAGE_TRANSCRIPT_TURNS` | How much parent transcript is packed for child agents. | Gives child agents enough local context to act. | `PYTHON_CLAW_DELEGATION_PACKAGE_TRANSCRIPT_TURNS=6` |
| `PYTHON_CLAW_DELEGATION_PACKAGE_RETRIEVAL_ITEMS` | Retrieved records packed for delegation. | Helps child context assembly. | `PYTHON_CLAW_DELEGATION_PACKAGE_RETRIEVAL_ITEMS=4` |
| `PYTHON_CLAW_DELEGATION_PACKAGE_ATTACHMENT_ITEMS` | Attachment references packed for delegation. | Not central in this demo, but part of bounded child context. | `PYTHON_CLAW_DELEGATION_PACKAGE_ATTACHMENT_ITEMS=2` |
| `PYTHON_CLAW_DELEGATION_PACKAGE_MAX_CHARS` | Max serialized delegation package size. | Prevents oversized child context payloads. | `PYTHON_CLAW_DELEGATION_PACKAGE_MAX_CHARS=4000` |
| `PYTHON_CLAW_POLICY_PROFILES` | Defines policy registry. | Critical for allowing `default-agent` to delegate and child agents to use `remote_exec`. | See `.env.demo` |
| `PYTHON_CLAW_TOOL_PROFILES` | Defines tool allowlists. | Critical for exposing `delegate_to_agent` only to the parent and `remote_exec` only to the specialists. | See `.env.demo` |
| `PYTHON_CLAW_HISTORICAL_AGENT_PROFILE_OVERRIDES` | Maps historical/bootstrap agent ids to explicit profiles. | Ensures `deploy-agent`, `code-agent`, and `notify-agent` bootstrap with the right tool/policy combinations. | See `.env.demo` |
| `PYTHON_CLAW_CHANNEL_ACCOUNTS` | Registers channel accounts. | Must include fake `webchat-demo` or the browser UI cannot send/poll. | `PYTHON_CLAW_CHANNEL_ACCOUNTS=[{"channel_account_id":"webchat-demo","channel_kind":"webchat","mode":"fake"}]` |
| `PYTHON_CLAW_REMOTE_EXEC_AGENT_TEMPLATES` | Seeds approved node command templates for child agents. | Required so `remote_exec` can resolve from approved arguments into concrete commands. | See `.env.demo` |
| `PYTHON_CLAW_WORKER_POLL_SECONDS` | Worker poll cadence. | Controls how quickly queued runs are claimed. | `PYTHON_CLAW_WORKER_POLL_SECONDS=2` |
| `PYTHON_CLAW_WORKER_IDLE_LOG_EVERY` | Idle log interval. | Operational only; useful while tailing worker logs. | `PYTHON_CLAW_WORKER_IDLE_LOG_EVERY=30` |

## Why These Settings Matter Together

`example` works only when all of these slices line up:

- The gateway must accept webchat input through a configured fake `webchat-demo` account.
- The worker must run in `provider` mode with a valid OpenAI API key.
- The default agent must be able to see `delegate_to_agent` but not `remote_exec`.
- The child agents must be bootstrapped with profiles that allow `remote_exec` but not further delegation.
- The node-runner must accept signed HTTP execution requests from the gateway.
- The bootstrap service must seed `NodeCommandTemplate` capability records from `PYTHON_CLAW_REMOTE_EXEC_AGENT_TEMPLATES`.
- Webchat approvals must be enabled so pending proposals become visible to the user.

If any one of those is missing, the example degrades. The most common failure modes are:

- `PYTHON_CLAW_RUNTIME_MODE=rule_based`: the assistant replies with simple echo-style behavior instead of delegating.
- Missing `PYTHON_CLAW_LLM_API_KEY`: startup validation fails closed.
- Missing `PYTHON_CLAW_NODE_RUNNER_INTERNAL_BEARER_TOKEN` with HTTP mode: startup validation fails closed.
- Missing `PYTHON_CLAW_REMOTE_EXEC_AGENT_TEMPLATES`: approval may exist, but `remote_exec` cannot resolve the child agent’s command template.
- Missing `webchat-demo` channel account: the browser chat cannot connect correctly.

## Sequence Diagrams By Example Step

## Step 1: Install Host Tools

This step is entirely outside the application runtime. You install `maildev` and `serve` on the host so the demo has a local SMTP sink and a static file server for `webchat.html`.

No `python-claw` code paths run here, and the database is untouched. This is a pure host prerequisite step.

```mermaid
sequenceDiagram
    actor User
    participant HostShell as Host Shell
    participant NPM as npm Registry/CLI
    participant HostFS as Host Filesystem

    User->>HostShell: npm install -g maildev
    HostShell->>NPM: download package
    NPM-->>HostShell: package contents
    HostShell->>HostFS: install global binary

    User->>HostShell: npm install -g serve
    HostShell->>NPM: download package
    NPM-->>HostShell: package contents
    HostShell->>HostFS: install global binary

    Note over User,HostFS: `python-claw` code paths: none
    Note over User,HostFS: Database tables touched: none
```

## Step 2: Prepare `.env` From `.env.demo`

This step defines the runtime behavior that the gateway, worker, and node-runner will use later. The important thing is not only copying the file, but keeping the example-specific registry JSON intact so the bootstrap process can seed the right agents, templates, and policy relationships.

At this point, the application still has not started. The `.env` file only becomes active when `src/config/settings.py` loads it during service startup.

```mermaid
sequenceDiagram
    actor User
    participant HostShell as Host Shell
    participant EnvDemo as .env.demo
    participant EnvFile as .env
    participant Settings as src/config/settings.py

    User->>HostShell: cp .env.demo .env
    HostShell->>EnvDemo: read template
    HostShell->>EnvFile: write project .env
    User->>EnvFile: replace PYTHON_CLAW_LLM_API_KEY
    Note over Settings: File is consumed later by `load_dotenv(find_dotenv(...), override=False)`

    Note over User,Settings: `python-claw` code paths prepared: `src/config/settings.py`
    Note over User,Settings: Database tables touched: none
```

## Step 3: Start Everything

This step brings the durable platform online. Docker starts PostgreSQL, Redis, the gateway, the worker, and the node-runner; Alembic creates the schema; then `apps/gateway/main.py` calls `bootstrap_runtime_state`, which loads settings, creates the SQLAlchemy metadata, and seeds model profiles, agent profiles, and remote-exec command templates from the environment-backed registries.

This is the first step where the `.env` values materially change the database. In particular, `src/agents/bootstrap.py` seeds `model_profiles`, `agent_profiles`, and system bootstrap capability records for the child agents defined in `PYTHON_CLAW_REMOTE_EXEC_AGENT_TEMPLATES`.

Use the same runtime sequence shown in [`example/example.md`](/example/example.md):

1. Start MailDev: `maildev --smtp 1025 --web 1080`
2. Start the webhook receiver from the [`example`](/example) directory: `node webhook-receiver.js`
3. If you previously ran the stack with older settings, reset volumes: `docker compose -f docker-compose.yml -f docker-compose.app.yml down -v`
4. Start Postgres and Redis: `docker compose --env-file .env -f docker-compose.yml up -d postgres redis`
5. Run migrations: `docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml run --rm gateway uv run alembic upgrade head`
6. Start the full app stack: `docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml up -d --build`
7. Tail the worker logs: `docker logs -f python-claw-worker`
8. Tail the gateway logs in another terminal: `docker logs -f python-claw-gateway`
9. Serve the browser UI from [`example`](/example): `npx serve -l 3000 .`
10. Open `http://localhost:3000/webchat.html` and confirm the system message `Connected to http://localhost:8000 as demo-user`

```mermaid
sequenceDiagram
    actor User
    participant Docker as Docker Compose
    participant Postgres as PostgreSQL
    participant Gateway as apps/gateway/main.py
    participant Settings as src/config/settings.py
    participant Bootstrap as src/agents/bootstrap.py
    participant CapsRepo as src/capabilities/repository.py
    participant Worker as scripts/worker_loop.py
    participant NodeRunner as apps/node_runner/main.py

    User->>Docker: start postgres + redis
    Docker->>Postgres: create/open database
    User->>Docker: run alembic upgrade head
    Docker->>Postgres: create schema and tables

    User->>Docker: start gateway, worker, node-runner
    Gateway->>Settings: load and validate .env
    Gateway->>Postgres: Base.metadata/create_all
    Gateway->>Bootstrap: bootstrap_runtime_state(...)
    Bootstrap->>Postgres: seed/read model_profiles
    Bootstrap->>Postgres: seed/read agent_profiles
    Bootstrap->>Postgres: create bootstrap sessions/messages
    Bootstrap->>CapsRepo: create remote exec capabilities
    CapsRepo->>Postgres: write resource_proposals/resource_versions/resource_approvals/active_resources/governance_transcript_events
    Worker->>Settings: load same .env
    NodeRunner->>Settings: load same .env

    Note over Gateway,NodeRunner: Main code paths: `apps/gateway/main.py`, `apps/gateway/deps.py`, `src/config/settings.py`, `src/agents/bootstrap.py`
    Note over Postgres: Database tables touched: `model_profiles`, `agent_profiles`, `sessions`, `messages`, `resource_proposals`, `resource_versions`, `resource_approvals`, `active_resources`, `governance_transcript_events`
```

## Step 4: Chat Request The Deployment

The browser sends a webchat message to `apps/gateway/api/webchat.py`. The gateway verifies the fake webchat token, checks the channel-account quota, routes the message to the canonical primary session, stores the user message, and creates an `execution_run`. The worker claims that run and executes the parent `default-agent` graph. Because the default policy/tool profile allows delegation, the parent proposes work for `deploy-agent`.

Delegation creates a child session, a child system message, and a child run. The child run then reaches a `remote_exec` tool request, but because `remote_exec` is approval-gated, the runtime records a governance proposal instead of executing it. The parent session receives a system notification about the pending approval, the graph turns that into a user-friendly assistant message, and the dispatch layer writes outbound delivery records for webchat.

To run this step in practice, paste the following into the browser chat:

```text
Deploy the app northwind-api to staging.
Delegate this to deploy-agent.
The deploy-agent should use remote_exec to POST to the webhook.
Call remote_exec with these exact arguments:
- url: http://host.docker.internal:3001/deploy-events
- json_payload: {"correlation_id":"northwind-api-staging-001","event":"deployment_started","app":"northwind-api","environment":"staging"}
```

Expected user-visible results:

1. A system message with the session ID
2. A queued delegation message for `deploy-agent`
3. An approval message that includes `Action: remote_exec` and a `Proposal ID`

```mermaid
sequenceDiagram
    actor User
    participant UI as example/webchat.html
    participant WebchatAPI as apps/gateway/api/webchat.py
    participant SessionSvc as src/sessions/service.py
    participant Repo as src/sessions/repository.py
    participant JobsRepo as src/jobs/repository.py
    participant Worker as src/jobs/service.py
    participant Graph as src/graphs/assistant_graph.py
    participant Nodes as src/graphs/nodes.py
    participant Delegation as src/delegations/service.py
    participant Policy as src/policies/service.py
    participant Dispatch as src/channels/dispatch.py
    participant DB as PostgreSQL

    User->>UI: Send deployment request
    UI->>WebchatAPI: POST /providers/webchat/accounts/webchat-demo/messages
    WebchatAPI->>SessionSvc: process_inbound(...)
    SessionSvc->>DB: write `inbound_dedupe`
    SessionSvc->>DB: read/create `sessions`
    SessionSvc->>DB: insert `messages` (user)
    SessionSvc->>DB: insert `execution_runs` (parent inbound run)
    WebchatAPI-->>UI: accepted with session_id/run_id

    Worker->>JobsRepo: claim run
    Worker->>Graph: invoke parent graph
    Graph->>Nodes: assemble state + execute turn
    Nodes->>Delegation: create_delegation(...)
    Delegation->>DB: read parent `sessions`
    Delegation->>DB: create child `sessions`
    Delegation->>DB: insert child `messages`
    Delegation->>DB: insert child `execution_runs`
    Delegation->>DB: insert `delegations`
    Delegation->>DB: insert `delegation_events`
    Nodes->>DB: insert assistant/tool audit artifacts
    Worker->>Dispatch: deliver queued delegation message
    Dispatch->>DB: write `session_artifacts`, `outbound_deliveries`, `outbound_delivery_attempts`, `outbound_delivery_stream_events`

    Worker->>JobsRepo: claim child run
    Worker->>Graph: invoke child graph for `deploy-agent`
    Graph->>Nodes: execute child turn
    Nodes->>Policy: classify `remote_exec` request
    Policy->>DB: insert `resource_proposals` and `resource_versions`
    Policy->>DB: insert `governance_transcript_events`
    Nodes->>DB: insert `tool_audit_events`
    Worker->>Delegation: handle_child_run_paused_for_approval(...)
    Delegation->>DB: update `delegations`
    Delegation->>DB: insert `delegation_events`
    Delegation->>DB: insert parent `messages` (system notification)
    Delegation->>DB: insert parent `execution_runs` (delegation_approval_prompt)
    Worker->>Graph: invoke parent notification run
    Graph->>Nodes: build approval summary text
    Worker->>Dispatch: deliver approval message
    Dispatch->>DB: write `messages`, `session_artifacts`, `outbound_deliveries`, `outbound_delivery_attempts`, `outbound_delivery_stream_events`, `approval_action_prompts`

    Note over DB: Tables touched: `inbound_dedupe`, `sessions`, `messages`, `execution_runs`, `delegations`, `delegation_events`, `tool_audit_events`, `resource_proposals`, `resource_versions`, `governance_transcript_events`, `session_artifacts`, `outbound_deliveries`, `outbound_delivery_attempts`, `outbound_delivery_stream_events`, `approval_action_prompts`
```

## Step 5: Chat Approve The Deployment Action

When the user types `approve <proposal-id>` into chat, that approval still enters as a normal inbound webchat message. The gateway persists the user turn and queues another parent run. During graph execution, `src/graphs/nodes.py` recognizes the approval command, and `ApprovalDecisionService` converts the pending governance proposal into an approved and activated resource.

Because the proposal belongs to a child session, the approval service automatically appends a system continuation message into that child session and queues a new child run. That continuation run performs the approved `remote_exec`, which the gateway signs and forwards to the node-runner. After the `curl` succeeds, the child delegation completes, the parent receives a delegation result system message, and a final parent run produces the user-visible completion response.

To trigger that continuation, reply in chat with:

```text
approve <proposal-id>
```

Expected user-visible and external results:

1. A confirmation message that approval was recorded
2. A completion message showing `deploy-agent` finished the delegated work
3. A matching webhook POST visible in the webhook receiver terminal

```mermaid
sequenceDiagram
    actor User
    participant UI as example/webchat.html
    participant WebchatAPI as apps/gateway/api/webchat.py
    participant SessionSvc as src/sessions/service.py
    participant Worker as src/jobs/service.py
    participant Nodes as src/graphs/nodes.py
    participant ApprovalSvc as src/policies/approval_actions.py
    participant Delegation as src/delegations/service.py
    participant RemoteExec as src/execution/runtime.py
    participant NodeRunner as apps/node_runner/api/internal.py
    participant Dispatch as src/channels/dispatch.py
    participant DB as PostgreSQL

    User->>UI: Send `approve <proposal-id>`
    UI->>WebchatAPI: POST webchat inbound
    WebchatAPI->>SessionSvc: process_inbound(...)
    SessionSvc->>DB: write `inbound_dedupe`, `messages`, `execution_runs`

    Worker->>Nodes: execute parent approval turn
    Nodes->>ApprovalSvc: decide(..., decision=approve)
    ApprovalSvc->>DB: update `resource_proposals`
    ApprovalSvc->>DB: insert `resource_approvals`
    ApprovalSvc->>DB: upsert `active_resources`
    ApprovalSvc->>DB: insert `governance_transcript_events`
    ApprovalSvc->>DB: update `approval_action_prompts`
    ApprovalSvc->>DB: append child continuation `messages`
    ApprovalSvc->>DB: insert child continuation `execution_runs`
    ApprovalSvc->>DB: update `delegations`
    ApprovalSvc->>DB: insert `delegation_events`
    Worker->>Dispatch: deliver approval-confirmed parent message

    Worker->>Nodes: execute child continuation run
    Nodes->>RemoteExec: execute approved remote_exec
    RemoteExec->>DB: resolve active template/resource state
    RemoteExec->>NodeRunner: signed HTTP exec request
    NodeRunner->>DB: insert/update `node_execution_audits`
    NodeRunner-->>RemoteExec: completed result
    Nodes->>DB: insert `tool_audit_events`
    Worker->>Delegation: handle_child_run_completed(...)
    Delegation->>DB: insert parent result `messages`
    Delegation->>DB: insert parent result `execution_runs`
    Delegation->>DB: update `delegations`
    Delegation->>DB: insert `delegation_events`

    Worker->>Nodes: execute parent delegation_result run
    Worker->>Dispatch: deliver completion message
    Dispatch->>DB: write `messages`, `session_artifacts`, `outbound_deliveries`, `outbound_delivery_attempts`, `outbound_delivery_stream_events`

    Note over DB: Tables touched: `inbound_dedupe`, `messages`, `execution_runs`, `resource_proposals`, `resource_approvals`, `active_resources`, `governance_transcript_events`, `approval_action_prompts`, `delegations`, `delegation_events`, `node_execution_audits`, `tool_audit_events`, `session_artifacts`, `outbound_deliveries`, `outbound_delivery_attempts`, `outbound_delivery_stream_events`
```

## Step 6: Send The Deployment Callback

This step simulates an external deployment system posting a callback into the same conversation. Unlike the browser path, the callback goes through the generic gateway route at `POST /inbound/message`, but it still resolves into the same canonical webchat primary session because the `peer_id` and channel-account tuple match the original session routing rules from Spec `001`.

The gateway stores the callback as another user message, creates a new run, and the worker processes it like any other inbound turn. This gives the parent agent the callback data as durable transcript context for whatever it needs to do next.

Use this command to simulate the callback:

```bash
curl -X POST http://localhost:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "webchat-demo",
    "external_message_id": "deploy-callback-001",
    "sender_id": "deployment-system",
    "peer_id": "demo-user",
    "content": "deployment_callback status=completed app=northwind-api environment=staging correlation_id=northwind-api-staging-001"
  }'
```

The returned `session_id` should match the browser chat session, confirming the callback was routed into the same conversation.

```mermaid
sequenceDiagram
    actor ExternalSystem as Deployment System
    participant InboundAPI as apps/gateway/api/inbound.py
    participant SessionSvc as src/sessions/service.py
    participant Routing as src/routing/service.py
    participant JobsRepo as src/jobs/repository.py
    participant Worker as src/jobs/service.py
    participant Graph as src/graphs/assistant_graph.py
    participant DB as PostgreSQL

    ExternalSystem->>InboundAPI: POST /inbound/message
    InboundAPI->>SessionSvc: process_inbound(...)
    SessionSvc->>Routing: normalize peer_id/group_id
    SessionSvc->>DB: claim/finalize `inbound_dedupe`
    SessionSvc->>DB: resolve existing `sessions`
    SessionSvc->>DB: insert callback `messages`
    SessionSvc->>DB: insert `execution_runs`
    InboundAPI-->>ExternalSystem: accepted response

    Worker->>JobsRepo: claim callback run
    Worker->>Graph: invoke parent graph with callback message
    Graph->>DB: read transcript/context state
    Worker->>DB: complete run and after-turn artifacts

    Note over DB: Tables touched: `inbound_dedupe`, `sessions`, `messages`, `execution_runs`, plus derived context tables if after-turn jobs run such as `outbox_jobs` and `context_manifests`
```

## Step 7: Chat Request A Deploy Report

This step repeats the same parent-to-child delegation pattern, but the delegated specialist is `code-agent`. The parent agent delegates, the child agent plans a single approved `python3 -c` execution, and the governance layer records that request as a pending `remote_exec` proposal. After the user approves, the continuation run executes the Python script in the child agent’s writable sandbox workspace.

The main difference from Step 5 is the sandbox workspace side effect. The node-runner still audits the remote execution in the database, but the generated files themselves live on disk under `.claw-sandboxes/agents/code-agent`. The database records the proposal, approval, execution audit, and delegation lifecycle; the generated report files are filesystem artifacts, not SQL rows.

Paste this into the browser chat:

```text
The deployment completed.
Delegate to code-agent.

Use exactly one remote_exec call with one python3 -c script payload.
Do not split this into multiple remote_exec calls.

In that single script:
- write deploy_report.json with:
- app: northwind-api
- environment: staging
- status: completed
- correlation_id: northwind-api-staging-001
- generated_at: current timestamp
- write deploy_report.py that reads and prints the JSON
- execute deploy_report.py
- show the script output
```

Then approve the resulting proposal in chat:

```text
approve <proposal-id>
```

To verify the workspace side effects, run:

```bash
docker exec python-claw-node-runner sh -lc 'find /app/.claw-sandboxes/agents/code-agent -type f 2>/dev/null'
docker exec python-claw-node-runner sh -lc 'cat /app/.claw-sandboxes/agents/code-agent/deploy_report.json 2>/dev/null'
docker exec python-claw-node-runner sh -lc 'cat /app/.claw-sandboxes/agents/code-agent/deploy_report.py 2>/dev/null'
```

```mermaid
sequenceDiagram
    actor User
    participant UI as example/webchat.html
    participant WebchatAPI as apps/gateway/api/webchat.py
    participant Worker as src/jobs/service.py
    participant Nodes as src/graphs/nodes.py
    participant Delegation as src/delegations/service.py
    participant ApprovalSvc as src/policies/approval_actions.py
    participant RemoteExec as src/execution/runtime.py
    participant Sandbox as src/sandbox/service.py
    participant NodeRunner as apps/node_runner/executor.py
    participant Workspace as .claw-sandboxes/agents/code-agent
    participant DB as PostgreSQL

    User->>UI: Ask for deploy report
    UI->>WebchatAPI: send webchat message
    WebchatAPI->>DB: insert parent `messages` + `execution_runs`
    Worker->>Nodes: parent delegates to `code-agent`
    Nodes->>Delegation: create child session/run
    Delegation->>DB: write `delegations`, child `sessions`, child `messages`, child `execution_runs`, `delegation_events`

    Worker->>Nodes: child proposes `remote_exec`
    Nodes->>DB: write `resource_proposals`, `resource_versions`, `governance_transcript_events`, `approval_action_prompts`
    User->>UI: approve proposal
    UI->>WebchatAPI: send approval command
    Worker->>ApprovalSvc: approve + enqueue child continuation
    ApprovalSvc->>DB: write `resource_approvals`, `active_resources`, continuation `messages`, continuation `execution_runs`

    Worker->>RemoteExec: execute approved Python script
    RemoteExec->>Sandbox: resolve agent workspace
    RemoteExec->>NodeRunner: signed exec request
    NodeRunner->>Workspace: write `deploy_report.json` and `deploy_report.py`
    NodeRunner->>DB: write `node_execution_audits`
    Worker->>DB: write `tool_audit_events`
    Worker->>Delegation: complete child, queue parent result
    Worker->>DB: write parent result `messages`, `execution_runs`, `delegation_events`

    Note over DB: Tables touched: `messages`, `execution_runs`, `delegations`, `delegation_events`, `resource_proposals`, `resource_versions`, `resource_approvals`, `active_resources`, `governance_transcript_events`, `approval_action_prompts`, `node_execution_audits`, `tool_audit_events`, `session_artifacts`, `outbound_deliveries`, `outbound_delivery_attempts`, `outbound_delivery_stream_events`
    Note over Workspace: Filesystem artifacts touched: `deploy_report.json`, `deploy_report.py`
```

## Step 8: Chat Request Email Notification

This step uses the same approval and continuation mechanics as the deploy report step, but with `notify-agent` and a Python `smtplib` script instead of a report-writing script. The database flow remains the same: inbound message, parent delegation, child proposal, approval activation, child continuation run, node execution audit, and parent completion message.

The external side effect changes from filesystem writes to SMTP delivery. MailDev receives the email outside the database, while `python-claw` keeps the durable trace in governance, delegation, run, tool-audit, and node-execution tables.

Paste this into the browser chat:

```text
Delegate to notify-agent to send a deployment-complete email.

Use remote_exec with python3 -c and smtplib.

Send the email to host.docker.internal on port 1025.

Use these fields:
- From: python-claw@localhost
- To: ops-team@localhost
- Subject: Deployment complete northwind-api staging
- Body: The deployment for northwind-api completed successfully. Correlation id: northwind-api-staging-001.
```

Then approve the proposal in chat:

```text
approve <proposal-id>
```

Verify the email by opening `http://localhost:1080` in MailDev.

```mermaid
sequenceDiagram
    actor User
    participant UI as example/webchat.html
    participant WebchatAPI as apps/gateway/api/webchat.py
    participant Worker as src/jobs/service.py
    participant Delegation as src/delegations/service.py
    participant ApprovalSvc as src/policies/approval_actions.py
    participant RemoteExec as src/execution/runtime.py
    participant NodeRunner as apps/node_runner/executor.py
    participant MailDev as MailDev SMTP
    participant DB as PostgreSQL

    User->>UI: Ask for email notification
    UI->>WebchatAPI: send webchat message
    WebchatAPI->>DB: insert parent `messages` + `execution_runs`
    Worker->>Delegation: create `notify-agent` child session/run
    Delegation->>DB: write `delegations`, `delegation_events`, child `sessions`, child `messages`, child `execution_runs`
    Worker->>DB: child writes pending `resource_proposals`, `resource_versions`, `governance_transcript_events`, `approval_action_prompts`

    User->>UI: approve proposal
    UI->>WebchatAPI: send approval command
    Worker->>ApprovalSvc: approve proposal and queue child continuation
    ApprovalSvc->>DB: write `resource_approvals`, `active_resources`, continuation `messages`, continuation `execution_runs`

    Worker->>RemoteExec: execute approved smtplib script
    RemoteExec->>NodeRunner: signed exec request
    NodeRunner->>MailDev: SMTP send
    NodeRunner->>DB: write `node_execution_audits`
    Worker->>Delegation: complete child and queue parent result
    Delegation->>DB: write parent result `messages`, `execution_runs`, `delegation_events`

    Note over DB: Tables touched: `messages`, `execution_runs`, `delegations`, `delegation_events`, `resource_proposals`, `resource_versions`, `resource_approvals`, `active_resources`, `governance_transcript_events`, `approval_action_prompts`, `node_execution_audits`, `tool_audit_events`, `session_artifacts`, `outbound_deliveries`, `outbound_delivery_attempts`, `outbound_delivery_stream_events`
```

## Step 9: Inspect The Audit Trail

The final step is read-only. The admin and diagnostics APIs expose the durable state created by the earlier steps, including parent sessions, transcript rows, delegation records, execution runs, node execution audits, and outbound deliveries. This is where the benefit of the append-only, database-first design from the specs becomes visible.

Nothing new is executed here. The system simply reads back the operational history that earlier steps wrote. The exact tables queried depend on which endpoint you call, but the example’s inspection flow covers the main runtime surfaces.

Use the same minimal inspection sequence from [`example/example.md`](/example/example.md):

```bash
BASE=http://localhost:8000
AUTH='Authorization: Bearer demo-operator-token'
curl -s "$BASE/agents/default-agent/sessions" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/sessions/<SESSION_ID>/messages" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/sessions/<SESSION_ID>/delegations" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/diagnostics/runs" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/diagnostics/node-executions" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/diagnostics/deliveries" -H "$AUTH" | python3 -m json.tool
```

```mermaid
sequenceDiagram
    actor User
    participant AdminAPI as apps/gateway/api/admin.py
    participant Diag as src/observability/diagnostics.py
    participant Repo as src/sessions/repository.py
    participant DelegRepo as src/delegations/repository.py
    participant DB as PostgreSQL

    User->>AdminAPI: GET /agents/default-agent/sessions
    AdminAPI->>Repo: list sessions
    Repo->>DB: read `sessions`
    AdminAPI-->>User: session list

    User->>AdminAPI: GET /sessions/{id}/messages
    AdminAPI->>Repo: list transcript
    Repo->>DB: read `messages`
    AdminAPI-->>User: transcript

    User->>AdminAPI: GET /sessions/{id}/delegations
    AdminAPI->>DelegRepo: list delegations
    DelegRepo->>DB: read `delegations`, `delegation_events`
    AdminAPI-->>User: delegation list

    User->>AdminAPI: GET /diagnostics/runs
    AdminAPI->>Diag: list runs
    Diag->>DB: read `execution_runs`
    AdminAPI-->>User: run diagnostics

    User->>AdminAPI: GET /diagnostics/node-executions
    AdminAPI->>Diag: list node executions
    Diag->>DB: read `node_execution_audits`
    AdminAPI-->>User: node execution audit

    User->>AdminAPI: GET /diagnostics/deliveries
    AdminAPI->>Diag: list deliveries
    Diag->>DB: read `outbound_deliveries`, `outbound_delivery_attempts`, `outbound_delivery_stream_events`
    AdminAPI-->>User: delivery audit

    Note over DB: Tables touched: `sessions`, `messages`, `delegations`, `delegation_events`, `execution_runs`, `node_execution_audits`, `outbound_deliveries`, `outbound_delivery_attempts`, `outbound_delivery_stream_events`
```

## Practical Setup Summary

To get `example` running, use `.env.demo` as the base, replace the OpenAI API key, and keep the rest of the demo profile intact. The demo specifically relies on:

- provider mode
- fake `webchat-demo`
- delegation-enabled `default-agent`
- `remote_exec`-enabled child agents
- HTTP node-runner with shared signing and bearer credentials
- seeded remote-exec agent templates
- webchat approval prompts enabled

If those stay aligned, the example flow in [`example/example.md`](/example/example.md) matches the current code structure and durable database behavior.
