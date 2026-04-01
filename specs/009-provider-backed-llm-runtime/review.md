# Review 009: Provider-Backed LLM Runtime

## Purpose
Review Spec 009 against the current repository seams so the provider-backed runtime lands as a bounded slice on top of the existing gateway-first, worker-owned, append-only execution path instead of creating drift across prompts, governance, retry handling, and manifest persistence.

## Review Status
- Spec clarified: `yes`
- Plan analyzed: `yes`
- Constitution check passed: `yes`
- Ready for implementation: `yes`

## Gap Review
### 1. Resolved: LLM-originated governed tool requests now have one canonical persistence path
- Gap observed in the current codebase:
  - ordinary model tool requests currently flow through `append_tool_proposal(...)` in [nodes.py](/src/graphs/nodes.py#L264)
  - deterministic approval-gated requests currently flow through `create_governance_proposal(...)` in [nodes.py](/src/graphs/nodes.py#L177)
- Options considered:
  - persist both a `tool_proposal` artifact and a governance proposal
  - persist a `tool_proposal` first, then translate it into governance state
  - bypass `tool_proposal` and make the governance proposal the only canonical requested-action record
  - treat governed LLM requests as denied and require the user to retry manually
- Recommendation:
  - bypass `tool_proposal` and make the governance proposal the only canonical requested-action record
- Applied decision:
  - Spec 009 now explicitly requires the governance proposal path only, with `proposal_id` as the canonical correlation identifier and no competing `tool_proposal` artifact for that path.

### 2. Resolved: Malformed semantic provider output now has one canonical safe-completion pattern
- Gap observed in the current codebase:
  - normal tool execution today persists proposal and result artifacts together in [nodes.py](/src/graphs/nodes.py#L264)
  - the provider-backed path needed a precise rule for malformed tool-like payloads so append-only artifact history and operator diagnostics stay consistent
- Options considered:
  - always persist assistant fallback only
  - always persist both `tool_proposal` and failed `tool_result`
  - persist failed `tool_result` only when the attempted tool identity is stable enough to trust, otherwise assistant fallback plus observability only
  - convert malformed semantic output into an infrastructure failure and retry the whole run
- Recommendation:
  - persist failed `tool_result` only when the attempted tool identity is stable enough to trust, otherwise assistant fallback plus observability only
- Applied decision:
  - Spec 009, Plan 009, and Tasks 009 now all use that single durable pattern and explicitly forbid unsafe execution or invented governance proposals on malformed semantic output.

### 3. Resolved: The backend-owned prompt contract is now explicit enough to hold graph and adapter boundaries
- Gap observed in the current codebase:
  - prompt construction is currently a plain string helper in [prompts.py](/src/graphs/prompts.py#L1)
  - the provider adapter currently receives only `AssistantState` plus `available_tools` names in [models.py](/src/providers/models.py#L7)
- Options considered:
  - let the provider adapter keep owning prompt meaning and build provider-native prompts from raw state only
  - keep only `available_tools: list[str]` and derive tool descriptions implicitly inside the adapter
  - add a backend-owned typed prompt payload to `AssistantState` while keeping `available_tools` as the name-only execution list
  - let prompt construction query repositories directly at call time
- Recommendation:
  - add a backend-owned typed prompt payload to `AssistantState` while keeping `available_tools` as the name-only execution list
- Applied decision:
  - Spec 009 now states that the canonical prompt payload is assembled before `complete_turn(...)`, carried through `AssistantState`, and remains backend-authored even though provider serialization happens inside the adapter.

### 4. Resolved: Provider execution metadata now has one explicit round-trip path
- Gap observed in the current codebase:
  - the spec wanted provider name, model name, prompt strategy, and related metadata visible in manifests or observability
  - the existing `ModelTurnResult` contract in [state.py](/src/graphs/state.py#L43) had no explicit way to return that metadata from the adapter to graph-owned persistence
- Options considered:
  - persist provider metadata through adapter-local logging only
  - mutate `state.context_manifest` inside the adapter as a side effect
  - return bounded execution metadata additively on `ModelTurnResult`
  - add a provider-specific repository write path outside the graph
- Recommendation:
  - return bounded execution metadata additively on `ModelTurnResult`
- Applied decision:
  - Spec 009 and Plan 009 now call for additive `execution_metadata` on `ModelTurnResult`, with graph code remaining the owner of manifest and observability persistence.

### 5. Resolved: Provider failure and retry classification now has one bounded cross-module seam
- Gap observed in the current codebase:
  - worker retry behavior is currently driven by generic exception handling in [jobs/service.py](/src/jobs/service.py#L33)
  - without a provider-specific internal error contract, the first implementation could drift into provider-SDK string matching or inconsistent retry decisions
- Options considered:
  - let worker code inspect raw provider SDK exceptions directly
  - classify retryability by substring matching in worker code
  - return provider-call failures as normal `ModelTurnResult` values
  - define one bounded provider-error contract with category, retryable flag, and safe detail
- Recommendation:
  - define one bounded provider-error contract with category, retryable flag, and safe detail
- Applied decision:
  - Spec 009, Plan 009, and Tasks 009 now require that bounded provider-error contract so worker retry and observability logic do not become provider-SDK-specific.

## Constitution Check
- Gateway-first execution is preserved. The spec keeps model execution behind existing graph and worker boundaries and does not let provider modules accept inbound traffic or dispatch outbound traffic directly.
- Transcript-first durability is preserved. The slice stays additive to existing message, artifact, manifest, and observability records rather than introducing a second transcript or inference log.
- Approval and policy boundaries are preserved. Deterministic classification and exact-match approval enforcement remain backend-owned, and prompt instructions are not treated as authorization.
- Bounded and inspectable execution is preserved. The updated package now also names the prompt-payload handoff, provider-metadata return path, and provider-error boundary needed to keep execution explainable in the current codebase.

## Plan Analysis Notes
- The updated package now aligns better with the actual repository seams:
  - [prompts.py](/src/graphs/prompts.py#L1) can evolve from plain-string rendering to a typed payload without forcing adapter signature churn
  - [state.py](/src/graphs/state.py#L43) can absorb additive prompt and execution metadata fields without changing the append-only execution model
  - [jobs/service.py](/src/jobs/service.py#L33) now has a clearer target contract for provider failure and retry handling
- The remaining implementation risk is normal slice complexity rather than unresolved contract ambiguity.

## Implementation Gate
- Implementation may begin. The spec package now names one recommended resolution for each identified gap and carries those decisions consistently through the spec, plan, and task list.

## Sign-Off
- Reviewer: `Codex`
- Date: `2026-03-25`
- Decision: `approved with resolved clarifications`
- Summary: Spec 009 is now aligned with the current codebase and earlier specs. The updated package resolves the key design gaps around governed LLM request persistence, malformed semantic-output durability, prompt-payload ownership, provider execution metadata return flow, and provider failure signaling, while preserving the gateway-first, worker-owned, append-only runtime model.
