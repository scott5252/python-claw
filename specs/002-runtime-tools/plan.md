# Plan 002: LangGraph Runtime and Typed Tool Registry

## Target Modules
- `src/graphs/state.py`
- `src/graphs/prompts.py`
- `src/graphs/nodes.py`
- `src/graphs/assistant_graph.py`
- `src/tools/registry.py`
- `src/tools/messaging.py`
- `src/tools/local_safe.py`
- `src/policies/service.py`
- `src/providers/models.py`
- `tests/`

## Migration Order
1. Extend transcript storage for tool-call/result capture if needed
2. Add any audit persistence required for tool execution history

## Implementation Shape
- Define the minimal `AssistantState` needed for one user turn.
- Keep repositories/services injectable for tests and future worker execution.
- Build the registry first, then bind tools into the graph via runtime context.
- Use `ToolNode` only if it satisfies audit and policy requirements; otherwise use a custom tool node.

## Risk Areas
- Leaking transport details into graph nodes
- Coupling tool exposure to static imports
- Incomplete audit coverage around failures

## Rollback Strategy
- Registry and graph modules remain additive.
- Tool execution audit can degrade to structured logs if storage changes need rollback.

## Test Strategy
- Unit: node branching, registry visibility, tool-context injection
- Integration: one tool-assisted run, one tool-denied run
