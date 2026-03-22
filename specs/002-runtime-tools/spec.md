# Spec 002: LangGraph Runtime and Typed Tool Registry

## Purpose
Introduce the agent runtime and a typed tool registry without collapsing transport concerns into orchestration.

## Non-Goals
- Capability activation approvals
- Remote node execution
- Context compaction and replay jobs
- Scheduler execution

## Upstream Dependencies
- Spec 001

## Scope
- `AssistantState`
- Graph assembly and single-turn invocation
- Injectable runtime dependencies
- Tool runtime context object
- Policy-aware tool registry
- Outbound message tool
- One safe local example tool
- Tool audit event capture

## Data Model Changes
- Transcript fields for tool calls/results if not already present
- Optional audit table or structured event sink for tool executions

## Contracts
- Graph factory builds the turn graph from injected repositories/services.
- Tool registry exposes factories keyed by capability name.
- Tool visibility is filtered by session/channel/agent policy.

## Runtime Invariants
- Transport logic stays outside the graph.
- Tools are built through registry contracts, not imported ad hoc by nodes.
- Tool outcomes are never fabricated.
- The graph remains functional without remote execution support.

## Security Constraints
- Safe local tools only in this spec
- No privileged tool exposure
- Tool calls and outcomes must be auditable

## Operational Considerations
- Tool binding must be reproducible in tests.
- Failures in tool execution need explicit surfaced outcomes.

## Acceptance Criteria
- Graph state is deterministic for the same inputs.
- Tool exposure differs by runtime policy.
- Tool execution records arguments and outcomes.
- Channel adapters still do not invoke the graph directly.

## Test Expectations
- Graph node tests
- Registry exposure tests
- Tool execution audit tests
- Integration test for a tool-using turn through the gateway-owned runtime path
