# Spec 003 Architecture Overview

This diagram set shows the implementation after Specs 001, 002, and 003 are all in place.

Spec 001 established the gateway, canonical sessions, append-only messages, and inbound dedupe.
Spec 002 added the gateway-owned single-turn runtime, tool registry, runtime artifacts, and tool audit rows.
Spec 003 adds approval-aware capability governance, transcript-linked governance events, and gateway-owned activation and revocation handling.

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
        Typed[Typed actions]
        Activate[ActivationController]
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
        GovEvents[(governance_transcript_events)]
        Proposals[(resource_proposals)]
        Versions[(resource_versions)]
        Approvals[(resource_approvals)]
        Active[(active_resources)]
        Migration[Migration 20260322_003]
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
    Nodes --> Policy
    Nodes --> Repo
    Nodes --> Activate
    Nodes --> Audit
    Registry --> Policy
    Registry --> Echo
    Registry --> Send
    Policy --> Typed
    Activate --> Repo

    Repo --> Models
    Idem --> Models
    Audit --> Models
    Models --> Sessions
    Models --> Messages
    Models --> Artifacts
    Models --> AuditRows
    Models --> Dedupe
    Models --> GovEvents
    Models --> Proposals
    Models --> Versions
    Models --> Approvals
    Models --> Active
    Migration --> GovEvents
    Migration --> Proposals
    Migration --> Versions
    Migration --> Approvals
    Migration --> Active
    DBMgr --> Sessions
    DBMgr --> Messages
    DBMgr --> Artifacts
    DBMgr --> AuditRows
    DBMgr --> Dedupe
    DBMgr --> GovEvents
    DBMgr --> Proposals
    DBMgr --> Versions
    DBMgr --> Approvals
    DBMgr --> Active

    RuntimeT --> Graph
    RepoT --> Repo
    APIT --> InboundAPI
    IntT --> SessionSvc
```

## Layer Map

```mermaid
flowchart TB
    A[HTTP layer\napps/gateway/api] --> B[Service layer\nsrc/sessions/service.py]
    B --> C[Idempotency + routing\nSpecs 001 and 002 gateway/session flow]
    B --> D[Graph runtime\nsrc/graphs]
    D --> E[Model contract\nsrc/providers/models.py]
    D --> F[Tool registry + policies\nsrc/tools and src/policies]
    F --> G[Typed action catalog\nsrc/tools/typed_actions.py]
    D --> H[Activation path\nsrc/capabilities/activation.py]
    D --> I[Audit sink\nsrc/observability/audit.py]
    B --> J[Persistence\nsrc/sessions/repository.py]
    J --> K[Sessions + messages + runtime artifacts\nSpecs 001 and 002]
    J --> L[Governance events + proposals + approvals + active resources\nSpec 003]
```

## Governance View

```mermaid
flowchart LR
    User[User message] --> Policy[PolicyService]
    Policy --> Classify[Turn classification]
    Policy --> Visible[Visible tools for this turn]

    Classify -->|governed action without approval| Proposal[Create proposal]
    Proposal --> Repo[SessionRepository]
    Repo --> GovEvent[(governance_transcript_events)]
    Repo --> ProposalRow[(resource_proposals)]
    Repo --> VersionRow[(resource_versions)]

    Classify -->|approve proposal| Approve[Persist approval]
    Approve --> Repo
    Repo --> ApprovalRow[(resource_approvals)]
    Approve --> Activate[ActivationController]
    Activate --> ActiveRow[(active_resources)]

    Visible -->|exact active approval present| Registry[ToolRegistry binds governed tool]
    Registry --> Execute[Tool execution]
    Execute --> Audit[(tool_audit_events)]
    Execute --> Artifacts[(session_artifacts)]

    Classify -->|revoke proposal| Revoke[Revocation flow]
    Revoke --> Repo
    Repo --> ApprovalRow
    Repo --> ActiveRow
    Repo --> GovEvent
```

## Notes

- Spec 001 behavior is still the foundation: all work begins with canonical routing, dedupe, session reuse, and append-only transcript writes.
- Spec 002 behavior still owns runtime orchestration: the gateway invokes a single-turn graph after the inbound message is persisted.
- Spec 003 adds a policy and activation layer on top of that runtime rather than bypassing it.
- `send_message` is the current governed capability used to prove the approval flow.
- Approval and activation remain on the gateway-owned path through `SessionService`, `AssistantGraph`, `PolicyService`, `SessionRepository`, and `ActivationController`.
