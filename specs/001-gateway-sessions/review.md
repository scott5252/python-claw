# Review 001: Gateway, Routing, Sessions, and Transcript Foundation

## Purpose
Review Spec 001 against the project constitution and [docs/architecture.md](/Users/scottcornell/src/projects/python-claw/docs/architecture.md) to confirm the slice is bounded correctly, surface unresolved contract gaps, and decide whether implementation should begin.

## Review Status
- Spec clarified: `yes`
- Plan analyzed: `yes`
- Constitution check passed: `yes`
- Ready for implementation: `yes`

## Resolved Findings
### 1. Resolved: Dedupe flow now uses an explicit two-phase lifecycle
- `inbound_dedupe` now carries a `status` field with `claimed` and `completed` states.
- `session_id` and `message_id` are nullable during `claimed` and become required only when finalized to `completed`.
- The spec now defines recovery expectations for persisted `claimed` rows so retries do not create duplicate transcript rows after crash or restart.
- This resolves the first-delivery claim gap while preserving PostgreSQL as the replay-safe source of truth.

### 2. Resolved: Dedupe identity is now scoped by channel kind
- The dedupe unique key is updated to `(channel_kind, channel_account_id, external_message_id)`.
- The planned routing lookup indexes are also updated to include `channel_kind`.
- This keeps dedupe identity aligned with the session identity boundary already defined in the spec and avoids cross-channel collisions.

### 3. Resolved: Routing normalization is now explicit and deterministic
- `channel_kind` is a validated lowercase enum value.
- `channel_account_id`, `sender_id`, `peer_id`, and `group_id` use trim-only normalization and are otherwise preserved exactly, including case and Unicode code points.
- The spec explicitly rejects empty-after-trim identifiers and forbids case folding, Unicode normalization, punctuation rewriting, or adapter-specific canonicalization in this slice.
- This gives implementers one stable canonicalization rule for session-key composition and restart-safe reuse.

## Architecture Alignment
- The spec remains aligned with the architecture document's gateway-first boundary: all inbound traffic enters through FastAPI and adapters do not bypass routing or session control.
- The slice also matches the architecture's emphasis on durable sessions and append-only transcripts as canonical state.
- The direct-message `main` mapping is consistent with the architecture's OpenClaw-inspired continuity model.
- The spec stays properly scoped by excluding LangGraph orchestration, memory extraction, scheduler execution, and remote execution from this first vertical slice.

## Constitution Check
- Gateway-first execution is preserved. Spec 001 keeps routing, idempotency, and session lifecycle in the gateway path.
- Transcript-first durability is preserved. PostgreSQL remains the source of truth for sessions, messages, and dedupe state.
- Observable, bounded delivery is satisfied. The spec includes explicit invariants, acceptance criteria, structured logging requirements, and recovery-aware idempotency rules for the highest-risk correctness path.

## Plan Analysis
- The module list and migration order are sensible and match the architecture document's separation between gateway, routing, persistence, and session services.
- The tasks are dependency-aware and correctly put high-risk tests ahead of implementation.
- The remaining implementation risk is normal execution complexity rather than unresolved contract ambiguity. The updated plan now captures two-phase dedupe semantics, stale-claim recovery expectations, cross-channel identity isolation, and explicit normalization behavior.

## Applied Decisions
- Decision: `inbound_dedupe` lifecycle
  - Selection: explicit two-phase lifecycle with `claimed` then `completed`
  - Impact: first-delivery claim correctness, duplicate replay correctness, and restart safety are now specified in one contract
- Decision: Cross-channel dedupe identity
  - Selection: include `channel_kind` in dedupe identity and routing lookup indexes
  - Impact: prevents false duplicate suppression across channel kinds that reuse account or message identifiers
- Decision: Gateway normalization rules
  - Selection: validated lowercase `channel_kind`; trim-only and otherwise preserve-as-sent behavior for all external identifiers
  - Impact: session-key composition is deterministic without making unsafe assumptions about provider-specific case semantics

## Implementation Gate
- Implementation may begin. The remaining work is to translate the resolved contracts into schema, service, endpoint, and test coverage.

## Sign-Off
- Reviewer: Codex
- Date: `2026-03-22`
- Decision: `approved with resolved clarifications`
- Summary: Spec 001 remains well-bounded and now explicitly defines the dedupe lifecycle, cross-channel identity boundary, and normalization rules required for safe implementation.
