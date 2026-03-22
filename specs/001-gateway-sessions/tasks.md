# Tasks 001: Gateway, Routing, Sessions, and Transcript Foundation

1. Write routing unit tests for trim-only normalization, preserved-case identifier handling, exact-one-of `peer_id` or `group_id` validation, direct `main` session keys, and group session keys.
2. Write idempotency unit tests for first-claim acceptance, `claimed` to `completed` finalization, duplicate replay lookup, stale `claimed` recovery behavior, and duplicate return of original `session_id` and `message_id`.
3. Write repository tests for get-or-create session behavior, append-only message inserts, ordered transcript paging with `before_message_id`, and dedupe lookup keyed by `(channel_kind, channel_account_id, external_message_id)`.
4. Create migrations for `sessions`, `messages`, and `inbound_dedupe`, including `inbound_dedupe.status`, nullable final-reference fields, and the required unique and lookup indexes from the spec.
5. Add SQLAlchemy models and DB session wiring for `sessions`, `messages`, and `inbound_dedupe`, including the two-phase dedupe lifecycle fields.
6. Implement the routing service contract in `src/routing/service.py`, including gateway-owned trim-only normalization, `scope_kind`, `scope_name`, and canonical `session_key` composition.
7. Implement the session repository and service contracts for canonical session lookup or creation, append-only message persistence, session metadata retrieval, and bounded transcript paging.
8. Implement the PostgreSQL-backed idempotency guard in `src/gateway/idempotency.py` so dedupe is claimed before transcript mutation, finalized after transcript insert, keyed by `channel_kind`, and safe across restart and stale-claim recovery.
9. Add the `POST /inbound/message` API contract with payload validation, invalid routing rejection, first-delivery claim and finalize behavior, duplicate replay behavior, and structured logging fields required by the spec.
10. Add read-only `GET /sessions/{session_id}` and `GET /sessions/{session_id}/messages` endpoints with bounded `limit` and `before_message_id` support.
11. Add API tests for inbound acceptance, invalid routing tuple rejection, duplicate delivery suppression, deterministic session reuse, cross-channel dedupe isolation, read-only session metadata retrieval, and paged transcript retrieval.
12. Add integration tests covering restart-safe session reuse, duplicate replay after process restart using persisted dedupe state, stale `claimed` recovery, cross-channel dedupe isolation, and ordered transcript history across page boundaries.
13. Document scaffold-only request-path behavior and any deferred dedupe-retention cleanup so later specs do not treat them as complete production features.
