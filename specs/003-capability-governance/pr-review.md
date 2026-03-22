# PR Review Guide: Spec 003 Capability Governance

## Why this file exists
This guide helps a developer understand the implementation of Spec 003 without having to reconstruct the approval model from the codebase by hand. The goal is to make it easy to answer four questions:

- what changed in this spec
- where those changes live in the codebase
- how the approval and activation flow works now
- what invariants matter most during review and maintenance

## What Spec 003 adds
Spec 003 adds a capability-governance layer on top of the existing gateway-owned runtime from Spec 002.

At a high level, the system now does this:

1. Classify the current turn before exposing tools.
2. Treat some capabilities as typed actions that require exact approval.
3. Persist a proposal and transcript-linked governance events when a gated capability is requested without approval.
4. Allow a later gateway-owned turn to approve and activate that exact proposal.
5. Rebuild tool visibility from current approval state on each turn.
6. Re-check approval at execution time even if a tool is visible.
7. Allow later revocation to invalidate future visibility and future execution.

In the current implementation slice, `send_message` is the approval-gated capability and `echo_text` remains an always-available safe action.

## Current status in this workspace
The Spec 003 implementation is present in the workspace and includes:

- additive governance tables and migration support
- typed action metadata for approval-aware capabilities
- a policy service that classifies turns and enforces exact approval matching
- repository support for proposal, approval, activation, revocation, and transcript-linked governance events
- runtime changes so unapproved gated work exits in a persisted awaiting-approval state
- tests for proposal, approval, activation, revocation, canonicalization, and fail-closed execution

This implementation uses a deliberately bounded interaction model:

- a user requests a governed action with a normal message like `send hello`
- the system creates a proposal and responds with an approval instruction
- a later message like `approve <proposal_id>` activates the capability
- a later message like `revoke <proposal_id>` revokes it

That is the concrete gateway-owned resume path for this slice.

## Best review order
Read in this order:

1. [`spec.md`](./spec.md)
2. [`plan.md`](./plan.md)
3. [`tasks.md`](./tasks.md)
4. [`src/tools/typed_actions.py`](../../src/tools/typed_actions.py)
5. [`src/policies/service.py`](../../src/policies/service.py)
6. [`src/sessions/repository.py`](../../src/sessions/repository.py)
7. [`src/capabilities/activation.py`](../../src/capabilities/activation.py)
8. [`src/graphs/state.py`](../../src/graphs/state.py)
9. [`src/graphs/nodes.py`](../../src/graphs/nodes.py)
10. [`src/graphs/assistant_graph.py`](../../src/graphs/assistant_graph.py)
11. [`apps/gateway/deps.py`](../../apps/gateway/deps.py)
12. [`src/db/models.py`](../../src/db/models.py)
13. [`migrations/versions/20260322_003_capability_governance.py`](../../migrations/versions/20260322_003_capability_governance.py)
14. governance-focused tests in `tests/`

Why this order works:

- start with the new action and policy contracts
- then read persistence and activation ownership
- then inspect how the graph uses those services
- finish with schema and tests

## Spec-to-code map

| Spec area | Main files |
| --- | --- |
| Typed action catalog and approval breadth | `src/tools/typed_actions.py` |
| Turn classification and exact approval enforcement | `src/policies/service.py` |
| Proposal, approval, activation, revocation persistence | `src/sessions/repository.py` |
| Sole gateway-owned activation path | `src/capabilities/activation.py` |
| Approval-aware runtime state | `src/graphs/state.py` |
| Persisted await-approval exit and later resume | `src/graphs/nodes.py`, `src/graphs/assistant_graph.py` |
| Dependency wiring for gateway-owned governance flow | `apps/gateway/deps.py`, `src/sessions/service.py` |
| Governance schema and migration | `src/db/models.py`, `migrations/versions/20260322_003_capability_governance.py` |
| Proof that behavior works | `tests/test_runtime.py`, `tests/test_integration.py`, `tests/test_repository.py` |

## The most important invariants to review

### 1. Classification happens before gated tool exposure
Look at [`src/policies/service.py`](../../src/policies/service.py) and [`src/graphs/nodes.py`](../../src/graphs/nodes.py).

Things to confirm:

- the policy service classifies the turn from the inbound text
- approval-gated tools are not exposed by default
- `send_message` only becomes visible when there is a current exact approval match
- the runtime exits into proposal creation before model-driven execution when approval is missing

Why this matters:

- the spec requires denied or unapproved capabilities to be omitted before execution planning

### 2. Approval matching is exact and deterministic
Look at [`src/policies/service.py`](../../src/policies/service.py) and [`src/sessions/repository.py`](../../src/sessions/repository.py).

Things to confirm:

- canonical parameters are serialized with stable key ordering
- the canonicalizer used for approval packets is the same one used for enforcement
- approval matching depends on typed action plus canonical parameter hash
- execution still fails closed if approval data is missing or mismatched

Why this matters:

- the spec is intentionally narrow: one exact version, one exact action, one exact parameter payload

### 3. Proposal and activation remain separate persisted concepts
Look at [`src/db/models.py`](../../src/db/models.py), [`src/sessions/repository.py`](../../src/sessions/repository.py), and [`src/capabilities/activation.py`](../../src/capabilities/activation.py).

Things to confirm:

- proposals use proposal-state fields such as `pending_approval` and `approved`
- active resources use activation-state fields such as `active` and `revoked`
- approval does not bypass activation persistence
- activation is idempotent on proposal, version, action, and canonical params

Why this matters:

- collapsing proposal and activation back into one state machine would violate the spec’s core contract

### 4. Governance uses dual durability
Look at [`src/sessions/repository.py`](../../src/sessions/repository.py) and [`src/db/models.py`](../../src/db/models.py).

Things to confirm:

- normalized tables exist for enforcement and lookup
- append-only `governance_transcript_events` are also written
- proposal creation writes both proposal/version rows and transcript-linked governance events
- approval, activation, and revocation also append governance events

Why this matters:

- the spec requires transcript-linked history plus normalized enforcement records, not one or the other

### 5. Revocation blocks future use
Look at [`src/sessions/repository.py`](../../src/sessions/repository.py), [`src/policies/service.py`](../../src/policies/service.py), and [`src/graphs/nodes.py`](../../src/graphs/nodes.py).

Things to confirm:

- revocation marks approval rows revoked
- revocation moves active resources to `revoked`
- later turns no longer expose the revoked capability
- later execution cannot reuse stale approval state

Why this matters:

- approval is only safe if later revocation actually takes effect on future turns

## End-to-end walkthrough

### Step 1: inbound request still enters through the gateway-owned service path
[`src/sessions/service.py`](../../src/sessions/service.py)

The inbound message is still deduplicated and appended to the session transcript before the assistant graph runs. Spec 003 does not bypass the existing gateway boundary.

### Step 2: the runtime builds policy context for the current turn
[`src/graphs/nodes.py`](../../src/graphs/nodes.py) and [`src/policies/service.py`](../../src/policies/service.py)

The graph asks the policy service to:

- classify the request
- load active approvals for the current `session_id` and `agent_id`
- build the policy context used for tool visibility and execution checks

### Step 3: an unapproved governed request creates a proposal instead of executing
[`src/graphs/nodes.py`](../../src/graphs/nodes.py) and [`src/sessions/repository.py`](../../src/sessions/repository.py)

For a request like `send hello channel` with no active approval:

1. the runtime classifies it as `execute_action`
2. `send_message` is recognized as a governed typed action
3. the policy service does not expose the tool
4. the graph creates a `resource_proposals` row and a `resource_versions` row
5. the graph appends `proposal_created` and `approval_requested` governance transcript events
6. the assistant responds with a proposal id and approval instruction

At this point the turn exits in a persisted awaiting-approval state.

### Step 4: a later approval turn activates the proposal
[`src/graphs/nodes.py`](../../src/graphs/nodes.py), [`src/sessions/repository.py`](../../src/sessions/repository.py), and [`src/capabilities/activation.py`](../../src/capabilities/activation.py)

For a message like `approve <proposal_id>`:

1. the policy service classifies the turn as an approval decision
2. the repository writes or reuses the exact approval record
3. the proposal state moves to `approved`
4. the activation controller creates or reuses the active-resource record
5. the system appends governance events for approval and activation
6. the assistant confirms approval and tells the user to retry the original request

### Step 5: a later normal turn rebinds tools from refreshed approval state
[`src/policies/service.py`](../../src/policies/service.py), [`src/tools/registry.py`](../../src/tools/registry.py), and [`src/graphs/nodes.py`](../../src/graphs/nodes.py)

When the user sends the original request again:

- the policy context now includes the matching active approval
- `send_message` becomes visible in the bound tool set
- execution-time enforcement re-checks the exact approval identity before the tool runs
- normal runtime artifacts are still recorded, including `tool_proposal`, `outbound_intent`, and `tool_result`

### Step 6: revocation removes future visibility and future execution
[`src/sessions/repository.py`](../../src/sessions/repository.py) and [`src/graphs/nodes.py`](../../src/graphs/nodes.py)

For a message like `revoke <proposal_id>`:

- matching approval rows are marked revoked
- active resources move to `revoked`
- a `revocation_result` governance event is appended
- future turns no longer treat that approval as active

## Database review checklist
Check [`src/db/models.py`](../../src/db/models.py) against [`migrations/versions/20260322_003_capability_governance.py`](../../migrations/versions/20260322_003_capability_governance.py).

You want the ORM models and migration to agree on:

- `governance_transcript_events` exists and links back to the canonical transcript
- `resource_proposals` exists with session, message, agent, and lifecycle fields
- `resource_versions` exists with immutable version numbering and content hash
- `resource_approvals` exists with exact-match uniqueness on proposal, version, action, and canonical params
- `active_resources` exists with idempotent activation identity
- lookup indexes exist for proposal state, approval matching, active-resource state, and transcript-linked event paging

## Test review checklist

### Runtime tests
[`tests/test_runtime.py`](../../tests/test_runtime.py)

Confirms:

- deterministic parameter canonicalization
- exact approval matching
- fail-closed execution when approval is missing or mismatched
- registry filtering still respects policy context

### Integration tests
[`tests/test_integration.py`](../../tests/test_integration.py)

Confirms:

- governed capabilities enter a persisted approval wait
- approval on a later turn activates the resource
- a later retry succeeds only after approval
- duplicate approval submissions stay idempotent
- revocation blocks later use

### Repository tests
[`tests/test_repository.py`](../../tests/test_repository.py)

Still confirms the append-only artifact behavior from earlier specs. That matters because Spec 003 builds on top of the same transcript and artifact persistence boundary rather than replacing it.

## Practical notes for developers

### What is intentionally simplified in this implementation
This slice is narrower than the full architecture language in `docs/architecture.md`.

Current simplifications:

- approval and revocation are driven by text commands rather than a dedicated admin API
- `send_message` is the primary governed capability used to prove the flow
- the rule-based model is still the default model adapter
- approval scope is session-and-agent scoped only

These are implementation choices for the bounded slice, not signals that broader approval reuse or privileged execution is already supported.

### What to be careful about when extending this spec

- Do not add ambient approvals without changing the contract first.
- Do not bypass the shared canonicalizer.
- Do not allow workers, schedulers, or adapters to call activation directly.
- Do not expose gated tools by default and rely only on execution-time checks.
- Do not treat `governance_transcript_events` as optional audit-only data; they are part of the durable record.

## Suggested local verification
Run:

```bash
uv run pytest tests
```

If you want to focus on the governance slice first, run:

```bash
uv run pytest tests/test_runtime.py tests/test_integration.py
```
