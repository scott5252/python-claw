# Spec 001 Scaffold Notes

- `POST /inbound/message` stops at transcript persistence and dedupe finalization in this slice.
- No LangGraph execution, memory extraction, scheduler-triggered execution, media handling, or remote execution is active yet.
- Dedupe retention cleanup is deferred; records carry `expires_at`, but automated pruning is intentionally left for a later operational slice.
