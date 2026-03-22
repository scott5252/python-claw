# Plan 007: Channels, Streaming, Chunking, and Media Pipeline

## Target Modules
- `apps/gateway/channels/base.py`
- `apps/gateway/channels/telegram.py`
- `apps/gateway/channels/slack.py`
- `apps/gateway/channels/webchat.py`
- `src/channels/dispatch.py`
- `src/domain/reply_directives.py`
- `src/domain/block_chunker.py`
- `src/media/processor.py`
- `tests/`

## Migration Order
1. Add attachment metadata persistence only if required for this slice
2. Add outbound delivery tracking if auditing chunked sends is required

## Implementation Shape
- Keep adapters thin and transport-specific.
- Normalize inbound attachments before they reach the context path.
- Process reply directives and chunking in the outbound dispatcher, not in the graph.

## Risk Areas
- Channel logic creeping into orchestration
- Oversized messages or unsupported attachments causing silent delivery failures
- Unbounded attachment download behavior

## Rollback Strategy
- Text-only outbound delivery remains available if media processing is disabled.

## Test Strategy
- Unit: directive parsing, chunk sizing, MIME classification
- Integration: end-to-end attachment normalization and chunked outbound send
