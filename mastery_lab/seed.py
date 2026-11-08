"""Idempotent seed: the Enterprise AI Architecture goal and its first challenge."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import MasteryLab

GOAL_SLUG = "enterprise-ai-architecture"
CHALLENGE_SLUG = "governed-retrieval-and-actions"

GOAL = {
    "title": "Design governed AI systems that retrieve enterprise data and execute approved actions",
    "domain": "Enterprise AI Architecture",
    "description": (
        "Be able to design, explain, and defend an AI assistant architecture for a regulated "
        "enterprise: where its boundaries are, how access is enforced, how actions are governed, "
        "how every decision can be audited, and how it fails safely."
    ),
}

SCENARIO = """\
Calder Medical Distribution (fictional) is a regulated distributor of medical supplies. It has
roughly 4,000 employees across quality, procurement, warehouse operations, and customer service.

Leadership wants an internal AI assistant that can:

1. Answer questions from controlled documents — SOPs, work instructions, supplier quality
   agreements, and batch/lot quality records. Documents are classified (Public-Internal,
   Restricted, Quality-Controlled) and access today is governed by department and role in the
   document management system. Only the currently effective version of a controlled document
   may be used as a basis for guidance.

2. Propose or execute a small set of business actions:
   • draft a CAPA (corrective and preventive action) record for human review
   • place a temporary quality hold on an inventory lot
   • update a supplier's status (e.g. Approved → Under Review)
   A quality hold or supplier status change has business and regulatory consequences.
   Some users may only request actions; others may approve them.

Known constraints and concerns:
   • Regulators and internal auditors expect a reconstructable record of who did what, when,
     on what basis, and with whose approval.
   • Documents may contain text that looks like instructions (for example in supplier-provided
     attachments).
   • The model provider, the document system, and the ERP can each be slow or unavailable.
   • The assistant must never become a way to see documents or perform actions the user
     could not see or perform directly.
"""

DELIVERABLE = """\
A structured written architecture (roughly 800–1,500 words; diagrams optional) covering:
  1. Components and system boundaries — what each part is trusted to do
  2. Access control for retrieval
  3. Governance of actions (propose vs. execute, approvals)
  4. Auditability and provenance
  5. Failure behavior and safety under abnormal conditions
  6. How you would validate the design before and after go-live
State your assumptions. Where you claim something would work, say what would demonstrate it.
"""

CRITERIA = [
    {
        "code": "C1",
        "title": "System boundaries and components",
        "description": "Identifies the main components (client, orchestration, model, retrieval, "
                       "action/tool layer, policy, audit store, source systems) and states which are "
                       "trusted to make which decisions — in particular, that the model does not "
                       "directly hold credentials or decide authorization.",
        "strong_evidence": "Named components with responsibilities; explicit trust boundary statements.",
    },
    {
        "code": "C2",
        "title": "Access control for retrieval",
        "description": "Retrieval is filtered by the requesting user's identity and entitlements, "
                       "enforced outside the model (not by prompt instructions), respects document "
                       "classification and effective-version rules, and follows least privilege.",
        "strong_evidence": "Identity propagation mechanism, where filtering happens, handling of versions.",
    },
    {
        "code": "C3",
        "title": "Governance of actions",
        "description": "Actions come from an approved catalog with typed parameters; proposing is "
                       "separated from executing; consequential actions require an authorized human "
                       "approval; execution is checked against the user's own permissions and is "
                       "idempotent or reversible where possible.",
        "strong_evidence": "Propose/approve/execute flow, who may approve, how permissions are re-checked.",
    },
    {
        "code": "C4",
        "title": "Auditability and provenance",
        "description": "Defines what is recorded (user, request, retrieved document IDs and versions, "
                       "model/prompt version, proposed action, approver, execution result, timestamps), "
                       "how records are protected from tampering, and how answers cite sources.",
        "strong_evidence": "A concrete audit event list and a statement of how integrity is protected.",
    },
    {
        "code": "C5",
        "title": "Failure behavior and safety",
        "description": "Describes behavior when retrieval returns nothing or conflicting results, the "
                       "model is uncertain, a dependency is down, or a document contains injected "
                       "instructions — and fails closed for actions.",
        "strong_evidence": "Specific failure cases with the intended system response for each.",
    },
    {
        "code": "C6",
        "title": "Validation plan and honesty about evidence",
        "description": "Explains how the design would be tested before and monitored after go-live "
                       "(e.g. access-control tests, injection red-teaming, approval-path tests, audit "
                       "replay), and distinguishes what is designed from what has been proven.",
        "strong_evidence": "Named tests or checks tied to the claims made in C1–C5.",
    },
]


def ensure_seed(lab: "MasteryLab") -> None:
    with lab._conn() as c:
        goal = c.execute("SELECT id FROM goals WHERE slug = ?", (GOAL_SLUG,)).fetchone()
        has_challenge = c.execute("SELECT 1 FROM challenges WHERE slug = ?", (CHALLENGE_SLUG,)).fetchone()
    if goal is None:
        goal_id = lab.create_goal(**GOAL, channel="seed", slug=GOAL_SLUG)["id"]
    else:
        goal_id = goal["id"]
    if has_challenge is None:
        lab.create_challenge(
            goal_id,
            title="Governed assistant: controlled-document retrieval and approved actions",
            scenario=SCENARIO,
            deliverable=DELIVERABLE,
            criteria=CRITERIA,
            created_by="seed",
            channel="seed",
            slug=CHALLENGE_SLUG,
        )
