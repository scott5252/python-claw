# Spec 002 Architecture Overview

## Runtime Architecture

```mermaid
flowchart TB
    Client[Client]

    subgraph Gateway[Gateway]
        Main[create_app]
        InboundAPI[POST /inbound/message]
        AdminAPI[GET /sessions and messages]
        Deps[deps]
    end

    subgraph Services[Services]
        SessionSvc[SessionService]
        Idem[IdempotencyService]
        Repo[SessionRepository]
        Graph[AssistantGraph]
        GraphFactory[GraphFactory]
    end

    subgraph Runtime[Runtime]
        Nodes[Graph nodes]
        State[AssistantState]
        Model[ModelAdapter]
        Registry[ToolRegistry]
        Policy[PolicyService]
        Echo[echo_text tool]
        Send[send_message tool]
        Audit[ToolAuditSink]
    end

    subgraph Persistence[Persistence]
        DBMgr[DB Session Manager]
        Models[ORM Models]
        Sessions[(sessions)]
        Messages[(messages)]
        Artifacts[(session_artifacts)]
        AuditRows[(tool_audit_events)]
        Dedupe[(inbound_dedupe)]
        Migration[Migration 20260322_002]
    end

    subgraph Tests[Tests]
        RuntimeT[Runtime tests]
        RepoT[Repository tests]
        APIT[API tests]
        IntT[Integration tests]
    end

    Client --> InboundAPI
    Client --> AdminAPI

    Main --> InboundAPI
    Main --> AdminAPI
    Main --> Deps
    Main --> DBMgr

    InboundAPI --> Deps
    InboundAPI --> SessionSvc
    AdminAPI --> SessionSvc

    Deps --> SessionSvc
    Deps --> GraphFactory
    GraphFactory --> Graph

    SessionSvc --> Idem
    SessionSvc --> Repo
    SessionSvc --> Graph

    Graph --> Nodes
    Nodes --> State
    Nodes --> Model
    Nodes --> Registry
    Nodes --> Repo
    Nodes --> Audit
    Registry --> Policy
    Registry --> Echo
    Registry --> Send

    Repo --> Models
    Idem --> Models
    Audit --> Models
    Models --> Sessions
    Models --> Messages
    Models --> Artifacts
    Models --> AuditRows
    Models --> Dedupe
    Migration --> Artifacts
    Migration --> AuditRows
    DBMgr --> Sessions
    DBMgr --> Messages
    DBMgr --> Artifacts
    DBMgr --> AuditRows
    DBMgr --> Dedupe

    RuntimeT --> Graph
    RepoT --> Repo
    APIT --> InboundAPI
    IntT --> SessionSvc
```

## Layer Map

```mermaid
flowchart TB
    A[HTTP layer\napps/gateway/api] --> B[Service layer\nsrc/sessions/service.py]
    B --> C[Idempotency + routing\nexisting gateway/session flow]
    B --> D[Graph runtime\nsrc/graphs]
    D --> E[Model contract\nsrc/providers/models.py]
    D --> F[Tool registry + policies\nsrc/tools and src/policies]
    D --> G[Audit sink\nsrc/observability/audit.py]
    B --> H[Persistence\nsrc/sessions/repository.py]
    H --> I[Messages + artifacts + audit rows\nsrc/db/models.py]
```

## Notes

- The gateway still owns runtime invocation through `SessionService`.
- The graph is a single-turn runtime, not a background workflow engine.
- Tool execution stays local and policy-filtered in this spec.
- Outbound messaging creates runtime-owned intent records; it does not dispatch transports.
