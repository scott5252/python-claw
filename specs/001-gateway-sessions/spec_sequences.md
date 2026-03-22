# Spec 001 Sequence Diagrams

This version is split into smaller diagrams so it prints more cleanly on 8.5 x 11 paper.

## 1. Accepted Inbound Message

```mermaid
sequenceDiagram
    actor Client
    participant API as Inbound API
    participant Svc as SessionService
    participant Route as Routing
    participant Idem as Idempotency
    participant Repo as Repository
    participant DB as DB

    Client->>API: POST /inbound/message
    API->>Svc: process_inbound(...)
    Svc->>Route: normalize_routing_input(...)
    Route-->>Svc: RoutingResult
    Svc->>Idem: claim(...)
    Idem->>DB: insert or refresh claimed row
    Idem-->>Svc: ClaimAccepted
    Svc->>DB: commit claim session
    Svc->>Repo: get_or_create_session(...)
    Repo->>DB: select or insert session
    Repo-->>Svc: SessionRecord
    Svc->>Repo: append_message(...)
    Repo->>DB: insert message + update session
    Repo-->>Svc: MessageRecord
    Svc->>Idem: finalize(...)
    Idem->>DB: mark dedupe completed
    Svc->>DB: commit work session
    Svc-->>API: session_id, message_id, accepted
    API-->>Client: 201 response
```

## 2. Duplicate And Conflict Paths

```mermaid
sequenceDiagram
    actor Client
    participant API as Inbound API
    participant Svc as SessionService
    participant Idem as Idempotency
    participant DB as DB

    Client->>API: POST /inbound/message
    API->>Svc: process_inbound(...)
    Svc->>Idem: claim(...)
    Idem->>DB: lookup dedupe row

    alt completed duplicate
        DB-->>Idem: completed row with ids
        Idem-->>Svc: DuplicateReplay
        Svc-->>API: session_id, message_id, duplicate
        API-->>Client: 201 response
    else active claimed duplicate
        DB-->>Idem: claimed row still fresh
        Idem-->>Svc: IdempotencyConflictError
        API-->>Client: 409 conflict
    end
```

## 3. Read-Only Session Queries

```mermaid
sequenceDiagram
    actor Client
    participant API as Admin API
    participant Svc as SessionService
    participant Repo as Repository
    participant DB as DB

    alt GET /sessions/{id}
        Client->>API: get session
        API->>Svc: get_session(db, id)
        Svc->>Repo: get_session(...)
        Repo->>DB: select session
        Repo-->>Svc: row or none
        Svc-->>API: SessionResponse or none
        API-->>Client: 200 or 404
    else GET /sessions/{id}/messages
        Client->>API: get messages
        API->>Svc: get_messages(db, id, limit, before)
        Svc->>Repo: get_session(...)
        Repo->>DB: select session
        Repo-->>Svc: row or none
        Svc->>Repo: list_messages(...)
        Repo->>DB: select messages ordered by id
        Repo-->>Svc: ascending page
        Svc-->>API: MessagePageResponse
        API-->>Client: 200 or 404
    end
```

## Notes

- The inbound path uses two DB sessions in code: one for the dedupe claim and one for the write/finalize work.
- Duplicate replay returns the original `session_id` and `message_id`.
- Message history is fetched in descending DB order and reversed before returning so the API stays append-ordered.
