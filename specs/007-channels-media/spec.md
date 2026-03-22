# Spec 007: Channels, Streaming, Chunking, and Media Pipeline

## Purpose
Add realistic delivery behavior and attachment handling while keeping channel adapters transport-specific.

## Non-Goals
- Capability governance redesign
- Remote execution
- Operational presence

## Upstream Dependencies
- Specs 001, 002, and 005

## Scope
- Outbound dispatcher abstraction
- Reply-directive parsing
- Block chunking
- Inbound attachment normalization
- Media-safe storage path
- Transport-specific channel adapter boundaries

## Data Model Changes
- Attachment metadata storage if needed
- Optional outbound delivery records for chunked sends

## Contracts
- Channel adapters translate transport payloads to the gateway contract and back.
- Outbound dispatch performs directive parsing and chunking before delivery.
- Attachments are normalized before context assembly consumes them.

## Runtime Invariants
- Large responses are chunked before send.
- Directives are stripped from display text and routed to outbound actions.
- Orchestration does not move into channel adapters.

## Security Constraints
- Attachment fetching and storage must respect size/type allowlists.
- Media URLs and stored artifacts require sanitization and bounded retention.

## Operational Considerations
- Channel-specific size limits vary and need per-adapter config.
- Attachment processing failures should degrade gracefully to text-only handling when possible.

## Acceptance Criteria
- Long responses are split before outbound send.
- Reply directives produce the correct outbound metadata.
- Attachments pass through a normalized processing stage before graph use.

## Test Expectations
- Unit tests for parser and chunker
- Integration tests for normalized attachment ingestion and chunked outbound delivery
