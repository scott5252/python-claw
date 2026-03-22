# Spec 006: Remote Node Runner and Per-Agent Sandboxing

## Purpose
Separate orchestration from privileged execution and make remote execution authenticated, policy-bound, and isolated per agent.

## Non-Goals
- Channel delivery logic
- Presence UI
- Auth profile rotation

## Upstream Dependencies
- Specs 002, 003, and 005

## Scope
- Node-runner service
- Signed gateway-to-node requests
- Per-agent sandbox modes
- Command allowlists and deny behavior
- Execution audit logging
- Approval requirements for privileged actions

## Data Model Changes
- Node execution audit records
- Per-agent sandbox configuration if persisted in DB

## Contracts
- Gateway orchestrates; node runner executes.
- Node runner validates signatures and policy before execution.
- Sandbox mode is resolved per agent and action.

## Runtime Invariants
- Unauthorized commands fail closed.
- Blocked commands never execute partially.
- Execution audit records are queryable.

## Security Constraints
- Signed requests required
- Approval before privileged execution
- Allowlist enforcement on execution host

## Operational Considerations
- Need container lifecycle strategy for shared vs per-agent sandboxes.
- Need timeout, rate-limit, and stdout/stderr capture rules.

## Acceptance Criteria
- Node requests without valid signatures are rejected.
- Disallowed commands fail closed.
- Sandbox mode is enforced by policy for each execution.

## Test Expectations
- Policy tests, signature validation tests, and integration tests against a stub or isolated node runner
