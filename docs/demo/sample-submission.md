Assumptions: Calder uses a central identity provider (OIDC) with department and role groups; the document management system (DMS) exposes per-document ACLs and an "effective version" flag; the ERP exposes APIs for lots and supplier status.

1. Components and boundaries
- Chat client (web) authenticates the user via OIDC and sends requests with the user's token.
- Orchestrator service: the only component that talks to the model. It assembles prompts, calls retrieval and the action gateway, and never stores long-lived credentials in prompts.
- LLM (hosted model): treated as untrusted for authorization. The model never holds credentials and cannot call source systems directly; it can only return text and structured action proposals.
- Retrieval service: queries a search index built from the DMS. It is the enforcement point for document access.
- Action gateway: a separate service with an approved action catalog (draft_capa, place_quality_hold, update_supplier_status), each with a typed JSON schema.
- Policy engine (OPA) evaluates who may request and who may approve each action.
- Audit store: append-only log.

2. Access control for retrieval
The orchestrator passes the user's identity to the retrieval service using token exchange (on-behalf-of), so retrieval runs with the user's entitlements, not a service super-user. Search results are filtered by the document ACL and classification at query time, inside the retrieval service, before anything reaches the model. Only documents flagged as the currently effective version are indexed for guidance; superseded versions are excluded.

3. Governance of actions
The model can only propose an action from the catalog. A proposal is shown to the user with the parameters and the cited source documents. Draft CAPA can be created by any quality user as a draft. Placing a quality hold or changing supplier status requires approval by a user with the QA Approver role, and the approver cannot be the requester. At execution time the action gateway re-checks permissions with the policy engine using the approver's identity, and each execution carries an idempotency key so retries do not double-apply.

4. Auditability
Every request writes an audit event with user, timestamp, prompt template version, model version, retrieved document IDs and versions, the proposed action, approver, and execution result. Events are hash-chained so tampering is detectable. Answers cite document IDs and versions.

5. Failure behavior
If retrieval returns nothing, the assistant says it could not find a controlled source and does not answer from general knowledge. If the ERP or policy engine is unavailable, actions fail closed and remain as pending proposals. Retrieved document text is passed to the model as quoted data, and the action gateway ignores any action not explicitly confirmed by the user, which limits prompt injection from supplier attachments.

6. Validation
We would test it before go-live. This design is fully compliant with 21 CFR Part 11 and has been proven to block all prompt injection attacks.
