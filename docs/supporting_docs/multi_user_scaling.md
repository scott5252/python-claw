# Multi-User Scaling

## Purpose

This document explains whether `python-claw` can support multiple users, how it scales toward multi-user operation, what is already implemented, and what is still missing for safe large-scale multi-user deployment.

## Short Answer

Yes, the system is designed in a way that can support multiple users, and several core parts of that support already exist today.

However, the answer depends on what “multiple users” means:

- if it means multiple end users sending messages to the system through channels, then **yes, the current architecture already supports that**
- if it means multiple human operators/admins managing the system safely, then **not fully yet until Spec 018**
- if it means multiple customers or organizations isolated from each other on shared infrastructure, then **not fully yet until Spec 019**
- if it means large-scale production deployment with strong observability, quotas, recovery, and safe operations, then **the full answer depends on Specs 017 through 029**

So the accurate answer is:

- **the architecture is multi-user capable**
- **the current implementation is already multi-session and multi-conversation capable**
- **full secure multi-operator and multi-tenant scale requires the planned future specs**

## What Already Supports Multiple Users Today

### 1. Durable sessions per conversation

The current system is built on durable session records, not a single in-memory chat loop.

Core tables and services:

- `sessions`
- `messages`
- `execution_runs`
- `src/sessions/service.py`
- `src/sessions/repository.py`
- `src/jobs/service.py`

This matters because each conversation is isolated into its own durable session, with:

- its own transcript
- its own execution lane
- its own owner agent
- its own context history
- its own queued runs

That means many different users can interact with the system at the same time, each through their own sessions.

### 2. Routing by channel/account/peer/group

Spec 001 established canonical routing and session creation rules.

The current routing model uses a normalized transport tuple based on values such as:

- channel kind
- channel account id
- peer id
- group id

That allows the gateway to separate one user conversation from another and route inbound messages into the correct durable session.

In practice, this means:

- one Slack user can have a different session from another Slack user
- one Telegram chat can be isolated from another Telegram chat
- webchat users can have separate sessions

This is the first layer of multi-user support.

### 3. Queue-based execution

Spec 005 added the execution queue and worker model.

Important components:

- `execution_runs`
- lease-based claiming
- concurrency lanes
- worker processing through `RunExecutionService`

This is a strong fit for multi-user scale because the system does not depend on one request thread finishing all work synchronously. Instead:

- inbound activity creates durable queued work
- workers claim eligible runs
- session lanes prevent conflicting work in the same session
- different sessions can progress independently

This allows many users to be active at once without collapsing into a single serialized runtime.

### 4. Idempotent inbound handling

The gateway already includes idempotency handling for inbound events.

This helps multi-user reliability because real messaging systems often:

- retry deliveries
- duplicate webhook events
- race under network instability

By claiming idempotency keys before work is created, the system reduces duplicate run creation and transcript corruption during concurrent multi-user traffic.

### 5. Per-session context and continuity

Specs 004 and 011 make context assembly session-scoped.

That means:

- summaries are scoped by session
- memory extraction and retrieval are scoped by session
- attachment handling is scoped by session
- context assembly for one user does not automatically mix with another user’s transcript

This is essential for multi-user correctness.

### 6. Human handoff and paused automation

Spec 016 adds collaboration state per session:

- `assistant_active`
- `human_takeover`
- `paused`

This matters for multi-user operations because it allows one session to be paused or taken over without blocking unrelated sessions.

### 7. Observability and recovery foundations

Specs 008 and 017 provide key scaling support:

- diagnostics
- health checks
- logging
- failure classification
- stale-work recovery and operational hardening

These do not create multi-user behavior by themselves, but they are necessary for reliable operation under load.

## What “Multiple Users” Means In Different Modes

### End users talking to the assistant

This is the strongest supported case today.

The current system can already support many end users because:

- sessions are durable
- routing is per conversation
- runs are queued
- workers process runs independently
- outbound delivery is decoupled from inbound ingestion

So if the question is:

- can multiple people message the assistant at the same time?

the answer is **yes**.

### Multiple human operators managing sessions

This is only partly supported today.

The current system has admin and operator-style surfaces, but until Spec 018 there is not a full real identity and RBAC model for multiple human staff members.

Without Spec 018, the limitations are:

- no full operator account system
- no full role hierarchy
- no real JWT/session auth model for operators
- weaker boundaries around who can do what

So the architecture can expose management surfaces, but true safe multi-operator scale requires Spec 018.

### Multiple tenants or organizations

This is not fully supported yet.

Today, the system behaves much more like a single logical deployment. It can serve many users, but it does not yet fully isolate:

- customers
- organizations
- workspaces
- tenant-scoped agent configuration
- tenant-scoped quota and policy boundaries

That isolation is explicitly planned in Spec 019.

So:

- multi-user: yes
- multi-tenant: not fully yet

## Why The Current Architecture Can Scale

### 1. Durable state instead of in-memory state

The most important scaling property is that the system’s source of truth is in the database, not in transient in-memory agent loops.

That means:

- workers can restart without losing the overall platform state
- concurrent users do not depend on a single process-local conversation object
- horizontal scaling is much more practical

This is a strong design for multi-user systems.

### 2. Session-lane concurrency control

The run queue uses lane-based coordination so that:

- one session does not get conflicting turns processed at the same time
- many other sessions can still run concurrently

This is a classic pattern for scaling conversation systems:

- serialize per conversation
- parallelize across conversations

That is exactly what you want for many simultaneous users.

### 3. Separation of gateway, worker, and delivery responsibilities

The codebase already separates:

- inbound gateway work
- execution worker work
- outbox and delivery work
- node-runner execution work

That separation is good for scaling because bottlenecks can be addressed by scaling the right subsystem instead of one giant monolith loop.

### 4. Bounded execution and retries

The execution model includes:

- run statuses
- retries
- backoff
- dead-letter behavior
- stale work handling

These are important for scale because larger systems always experience:

- transient provider failures
- channel callback duplication
- worker interruptions
- partial delivery failures

The platform is already moving in the direction of handling those conditions durably.

## What Limits Multi-User Scale Today

### 1. No full operator auth/RBAC yet

Before Spec 018, multiple human operators can become a risk because there is not yet a complete identity and permission layer for staff use.

Effect:

- safe internal scaling of admin/operator access is incomplete

### 2. No tenant isolation yet

Before Spec 019, the system can serve many users but does not yet strongly isolate many organizations on shared infrastructure.

Effect:

- good for multi-user within one deployment context
- not yet complete for SaaS-style multi-tenant scale

### 3. No complete management console yet

Before Spec 025, managing a large number of users, sessions, agents, approvals, and failures is still too operationally manual.

Effect:

- backend can scale earlier than the operational workflow

### 4. Quotas and usage controls are still maturing

Spec 017 adds hardening, and Spec 024 later adds stronger usage/cost accounting and quota enforcement.

Without those, large multi-user deployment can be exposed to:

- runaway cost
- uneven noisy-neighbor behavior
- weaker per-agent or per-tenant budget control

### 5. Some scaling depends on infrastructure choices

The architecture supports scale, but actual scale still depends on deployment choices such as:

- database performance
- worker count
- queue throughput
- provider rate limits
- channel webhook handling capacity
- node-runner scaling

So the software shape is supportive, but infrastructure still matters.

## What Specs Improve Multi-User Scale

### Already implemented foundation

| Spec | Multi-user scaling contribution |
| --- | --- |
| 001 | Durable sessions, transcripts, and routing foundation |
| 004 | Per-session continuity and recovery |
| 005 | Async queueing, worker execution, and concurrency lanes |
| 007 | Channel pipeline and outbound delivery flow |
| 008 | Observability and diagnostics |
| 012 | Production channel integration |
| 013 | Streaming delivery |
| 016 | Session-level collaboration and takeover controls |
| 017 | Production hardening and operational readiness |

### Future specs that matter most

| Spec | Why it matters for multi-user scale |
| --- | --- |
| 018 | Safe support for multiple human operators with RBAC |
| 019 | True multi-tenant isolation across customers or organizations |
| 020 | Durable contact model for user identity across sessions |
| 021 | Better channel-native interaction at larger operational scale |
| 022 | Proactive messaging and campaigns |
| 023 | Webhook/event integrations for external systems |
| 024 | Usage metering, cost attribution, and quota enforcement |
| 025 | Management console for operating many users and sessions |
| 027 | Retention, privacy, and compliance controls |
| 028 | Safety validation at scale |
| 029 | Repair and recovery tooling for production incidents |

## Practical Answer By Phase

### Current state through Spec 017

The system can already support multiple end users at once.

Why:

- separate durable sessions
- queue-driven execution
- session-lane concurrency
- per-session context isolation
- production-oriented runtime hardening

What is still weak:

- operator identity
- tenant isolation
- admin UX
- quota governance at larger scale

### After Specs 018 through 029

The system should support multi-user operation much more completely.

At that point it should be able to support:

- many end users
- many operators
- many tenants
- cost governance
- operational monitoring
- recovery and repair at production scale

This is the point where the system becomes much more credible as a real multi-user platform rather than just a multi-session backend.

### After Specs 030 through 040

The later specs are more focused on custom agents, workspaces, user-facing sub-agents, and OpenClaw-style product parity.

Those specs are not the primary reason the system becomes multi-user capable. That capability comes earlier.

What 030 through 040 add is more:

- richer user-specific agent experiences
- more configurable per-user or per-tenant agent ecosystems
- more advanced per-agent isolation and control

So they improve the quality of multi-user product behavior, but the core multi-user scaling story is mostly established earlier.

## Final Conclusion

Yes, the system supports and can scale toward multiple users.

It already has the most important architectural traits needed for that:

- durable session isolation
- queue-based execution
- per-session concurrency control
- decoupled worker processing
- context isolation
- operational observability and hardening

But the full answer depends on which kind of “multiple users” you mean:

- multiple end users sending messages: **yes, already supported in the current architecture**
- multiple human operators managing the platform safely: **requires Spec 018**
- multiple tenants/customers sharing the system safely: **requires Spec 019**
- large-scale production operations with governance and repair: **requires Specs 017 through 029**

So the best single-sentence answer is:

`python-claw` is already architected for multi-user conversation scale, but full secure multi-operator and multi-tenant production scale depends on the planned auth, tenancy, quota, console, and operational specs.
