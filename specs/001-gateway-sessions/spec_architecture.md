# Spec 001 Architecture Overview

This version is formatted to print more cleanly on 8.5 x 11 paper with shorter labels and a top-to-bottom layout.

## Runtime Architecture

```mermaid
flowchart TB
    Client[Client]

    subgraph Gateway[Gateway]
        Main[create_app]
        InboundAPI[POST /inbound/message]
        AdminAPI[GET /sessions]
        Deps[deps]
    end

    subgraph Services[Services]
        SessionSvc[SessionService]
        Routing[Routing]
        Idem[Idempotency]
        Repo[Repository]
        Schemas[Schemas]
        Settings[Settings]
    end

    subgraph Persistence[Persistence]
        DBMgr[DB Session Manager]
        Models[ORM Models]
        Tables[(sessions / messages / inbound_dedupe)]
        Migration[Migration 20260322_001]
    end

    subgraph Tests[Tests]
        RoutingT[Routing tests]
        IdemT[Idempotency tests]
        RepoT[Repository tests]
        APIT[API tests]
        IntT[Integration tests]
    end

    Client --> InboundAPI
    Client --> AdminAPI

    Main --> InboundAPI
    Main --> AdminAPI
    Main --> Deps
    Main --> Settings
    Main --> DBMgr

    InboundAPI --> Deps
    AdminAPI --> Deps
    InboundAPI --> SessionSvc
    AdminAPI --> SessionSvc

    Deps --> SessionSvc
    Deps --> DBMgr
    Deps --> Settings

    SessionSvc --> Routing
    SessionSvc --> Idem
    SessionSvc --> Repo
    SessionSvc --> Schemas

    Repo --> Models
    Idem --> Models
    Models --> Tables
    Migration --> Tables
    DBMgr --> Tables

    RoutingT --> Routing
    IdemT --> Idem
    RepoT --> Repo
    APIT --> InboundAPI
    APIT --> AdminAPI
    IntT --> Main
```

## Layer Map

```mermaid
flowchart TB
    A[HTTP layer\napps/gateway/api] --> B[Service layer\nsrc/sessions/service.py]
    B --> C[Routing rules\nsrc/routing/service.py]
    B --> D[Dedupe rules\nsrc/gateway/idempotency.py]
    B --> E[Persistence access\nsrc/sessions/repository.py]
    E --> F[ORM models\nsrc/db/models.py]
    F --> G[(Database tables)]
```

## Legend

- `Gateway`: FastAPI app, routes, and dependency wiring.
- `SessionService`: orchestration point for inbound processing and read-only queries.
- `Routing`: canonical routing normalization and `session_key` creation.
- `Idempotency`: dedupe claim/finalize lifecycle.
- `Repository`: session lookup/create and append-only message history.
