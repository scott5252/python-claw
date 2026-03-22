# Spec 003 Sequence Diagrams

These diagrams show the runtime after Specs 001, 002, and 003 are combined.

Spec 001 still owns the canonical inbound session flow.
Spec 002 still owns the single-turn runtime path.
Spec 003 adds approval-aware proposal, approval, activation, execution, and revocation behavior on top of that path.

## 1. Governed Request Creates A Persisted Approval Wait

```mermaid
sequenceDiagram
    actor Client
    participant API as Inbound API
    participant Svc as SessionService
    participant Idem as Idempotency
    participant Repo as Repository
    participant Graph as AssistantGraph
    participant Nodes as Graph nodes
    participant Policy as PolicyService
    participant DB as DB

    Client->>API: POST /inbound/message ("send hello")
    API->>Svc: process_inbound(...)
    Svc->>Idem: claim(...)
    Idem->>DB: insert or refresh claimed row
    Svc->>DB: commit claim session
    Svc->>Repo: get_or_create_session(...)
    Repo->>DB: select or insert session
    Svc->>Repo: append user message
    Repo->>DB: insert inbound transcript row
    Svc->>Idem: finalize(...)
    Idem->>DB: mark dedupe completed
    Svc->>Graph: invoke(...)
    Graph->>Nodes: execute_turn(...)
    Nodes->>Policy: build_policy_context(...)
    Policy-->>Nodes: classification=execute_action, no exact approval
    Nodes->>Repo: create_governance_proposal(...)
    Repo->>DB: insert resource_proposals row
    Repo->>DB: insert resource_versions row
    Repo->>DB: insert governance event proposal_created
    Repo->>DB: insert governance event approval_requested
    Nodes->>Repo: append assistant message
    Repo->>DB: insert assistant transcript row
    Svc->>DB: commit work session
    API-->>Client: 201 response with approval-needed assistant message
```

## 2. Approval Turn Persists Approval And Activates Capability

```mermaid
sequenceDiagram
    actor Client
    participant API as Inbound API
    participant Svc as SessionService
    participant Repo as Repository
    participant Graph as AssistantGraph
    participant Nodes as Graph nodes
    participant Policy as PolicyService
    participant Activate as ActivationController
    participant DB as DB

    Client->>API: POST /inbound/message ("approve <proposal_id>")
    API->>Svc: process_inbound(...)
    Svc->>Graph: invoke(...)
    Graph->>Nodes: execute_turn(...)
    Nodes->>Policy: build_policy_context(...)
    Policy-->>Nodes: classification=approval_decision
    Nodes->>Repo: approve_proposal(...)
    Repo->>DB: insert or reuse resource_approvals row
    Repo->>DB: update resource_proposals to approved
    Repo->>DB: insert governance event approval_decision
    Nodes->>Activate: activate(...)
    Activate->>Repo: activate_approved_resource(...)
    Repo->>DB: insert or reuse active_resources row
    Repo->>DB: insert governance event activation_result
    Nodes->>Repo: append assistant message
    Repo->>DB: insert assistant transcript row
    Svc->>DB: commit work session
    API-->>Client: 201 response confirming approval
```

## 3. Later Retry Executes Governed Tool After Rebinding

```mermaid
sequenceDiagram
    actor Client
    participant API as Inbound API
    participant Svc as SessionService
    participant Graph as AssistantGraph
    participant Nodes as Graph nodes
    participant Policy as PolicyService
    participant Registry as ToolRegistry
    participant Tool as send_message tool
    participant Repo as Repository
    participant Audit as ToolAuditSink
    participant DB as DB

    Client->>API: POST /inbound/message ("send hello")
    API->>Svc: process_inbound(...)
    Svc->>Graph: invoke(...)
    Graph->>Nodes: execute_turn(...)
    Nodes->>Policy: build_policy_context(...)
    Policy->>Repo: list_active_approvals(...)
    Repo->>DB: select approved + active exact-match rows
    Policy-->>Nodes: classification=execute_action, exact approval available
    Nodes->>Registry: bind_tools(context, policy)
    Registry->>Policy: is_tool_allowed(...)
    Policy-->>Registry: send_message visible for this turn
    Nodes->>Nodes: model returns tool request
    Nodes->>Repo: append_tool_proposal(...)
    Repo->>DB: insert tool_proposal artifact
    Nodes->>Audit: record attempt
    Audit->>DB: insert audit event
    Nodes->>Policy: assert_execution_allowed(...)
    Policy-->>Nodes: approval match
    Nodes->>Tool: invoke(arguments)
    Tool-->>Nodes: ToolResultPayload + outbound intent
    Nodes->>Repo: append_outbound_intent(...)
    Repo->>DB: insert outbound_intent artifact
    Nodes->>Repo: append_tool_event(...)
    Repo->>DB: insert tool_result artifact
    Nodes->>Audit: record result
    Audit->>DB: insert audit event
    Nodes->>Repo: append assistant message
    Repo->>DB: insert assistant transcript row
    Svc->>DB: commit work session
    API-->>Client: 201 response
```

## 4. Revocation Blocks Future Use

```mermaid
sequenceDiagram
    actor Client
    participant API as Inbound API
    participant Svc as SessionService
    participant Graph as AssistantGraph
    participant Nodes as Graph nodes
    participant Policy as PolicyService
    participant Repo as Repository
    participant DB as DB

    Client->>API: POST /inbound/message ("revoke <proposal_id>")
    API->>Svc: process_inbound(...)
    Svc->>Graph: invoke(...)
    Graph->>Nodes: execute_turn(...)
    Nodes->>Policy: build_policy_context(...)
    Policy-->>Nodes: classification=revocation
    Nodes->>Repo: revoke_proposal(...)
    Repo->>DB: update resource_approvals revoked_at/revoked_by
    Repo->>DB: update active_resources activation_state=revoked
    Repo->>DB: insert governance event revocation_result
    Nodes->>Repo: append assistant message
    Repo->>DB: insert assistant transcript row
    Svc->>DB: commit work session

    Note over Client,DB: Later retry of the same governed request

    Client->>API: POST /inbound/message ("send hello")
    API->>Svc: process_inbound(...)
    Svc->>Graph: invoke(...)
    Graph->>Nodes: execute_turn(...)
    Nodes->>Policy: build_policy_context(...)
    Policy->>Repo: list_active_approvals(...)
    Repo->>DB: no active exact-match approval found
    Policy-->>Nodes: governed tool not visible
    Nodes->>Repo: create_governance_proposal(...)
    Repo->>DB: insert or refresh proposal wait state
    Repo->>DB: insert governance wait events
    Nodes->>Repo: append assistant message
    Repo->>DB: insert assistant transcript row
    API-->>Client: approval required again
```

## 5. Full Combined Lifecycle

```mermaid
sequenceDiagram
    actor User
    participant Gateway as Gateway runtime
    participant Policy as PolicyService
    participant Repo as Repository
    participant Activate as ActivationController
    participant Tool as Governed tool
    participant DB as DB

    User->>Gateway: governed request
    Gateway->>Policy: classify + load approvals
    Policy-->>Gateway: no approval
    Gateway->>Repo: create proposal and approval-request artifacts
    Repo->>DB: proposal/version/governance events
    Gateway-->>User: approval required

    User->>Gateway: approve proposal
    Gateway->>Repo: persist approval
    Repo->>DB: approval row + governance event
    Gateway->>Activate: activate approved resource
    Activate->>DB: active resource + governance event
    Gateway-->>User: approved

    User->>Gateway: retry governed request
    Gateway->>Policy: classify + load approvals
    Policy-->>Gateway: exact approval available
    Gateway->>Tool: execute governed action
    Tool-->>Gateway: result
    Gateway->>Repo: runtime artifacts + transcript
    Repo->>DB: tool artifacts + assistant message

    User->>Gateway: revoke proposal
    Gateway->>Repo: revoke approval and active resource
    Repo->>DB: revoked rows + governance event
    Gateway-->>User: revoked
```

## Notes

- Spec 001’s claim-and-finalize dedupe flow still wraps every inbound message before runtime work begins.
- Spec 002’s runtime artifact and audit behavior still applies after approval exists and governed work is allowed to execute.
- Spec 003 changes the path for governed actions only: missing approval now exits through proposal persistence instead of immediate tool execution.
- Approval and activation are separate persisted steps.
- Revocation affects future turns by removing active approval visibility and execution eligibility.
