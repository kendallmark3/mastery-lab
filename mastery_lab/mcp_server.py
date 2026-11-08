"""MCP surface for Mastery Lab (Python MCP SDK v2, `MCPServer`).

Thin adapter over `MasteryLab`: no learning logic lives here. A connected AI
assistant supplies the conversational intelligence (explaining, evaluating,
inventing follow-up challenges); these tools give it persistent learner
records and enforce the same trust rules as the browser UI.

Run:  python -m mastery_lab mcp          (stdio transport)
"""

from __future__ import annotations

import functools
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from .service import ASSURANCE_NOTE, LabError, MasteryLab

INSTRUCTIONS = f"""\
Mastery Lab stores a learner's goals, practice challenges, submissions, and evidence-linked feedback.
Typical loop: get_learner_context → get_challenge → (learner writes answer) → record_submission →
get_submission → record_feedback → recommend_next_practice.

When you evaluate a submission with record_feedback:
- address criteria by code (C1, C2, ...) from the challenge;
- put only what is literally in the submission in `observation`, and your inference in `judgment`;
- quote supporting text verbatim in `evidence_quotes` — quotes that are not in the submission are rejected;
- rate 'demonstrated' or 'partial' only with evidence; otherwise it is shown as an unverified judgment;
- list claims the learner made that the text does not substantiate in `unverified_claims`.
{ASSURANCE_NOTE}
Never submit work on the learner's behalf unless they explicitly ask you to record their own text.
"""


class CriterionInput(BaseModel):
    title: str
    description: str
    strong_evidence: str = ""
    code: str | None = Field(None, description="Optional code; defaults to C1, C2, ... by position.")


class FeedbackItemInput(BaseModel):
    criterion: str = Field(description="Criterion code from the challenge, e.g. 'C3'.")
    rating: Literal["demonstrated", "partial", "not_evident"]
    observation: str = Field("", description="What the submission literally says about this criterion.")
    judgment: str = Field("", description="The evaluator's inference or opinion.")
    gaps: str = Field("", description="What is missing or uncertain.")
    evidence_quotes: list[str] = Field(default_factory=list,
                                       description="Verbatim excerpts (≥8 chars) of the submission.")
    evidence_ids: list[int] = Field(default_factory=list,
                                    description="Existing evidence ids of the same submission.")


def build_server(lab: MasteryLab | None = None) -> MCPServer:
    lab = lab or MasteryLab()
    server = MCPServer("mastery-lab", instructions=INSTRUCTIONS, version="0.1.0")

    def lab_errors(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except LabError as e:
                raise ToolError(f"[{e.code}] {e.message}") from None
        return wrapper

    @server.tool()
    @lab_errors
    def get_learner_context(goal_id: int | None = None) -> dict[str, Any]:
        """List the learner's goals, or (with goal_id) return the goal's challenges, submissions,
        feedback, recent session history, and the recommended next step."""
        if goal_id is None:
            goals = lab.list_goals()
            return {"goals": goals,
                    "hint": "Call again with goal_id for full context." if goals else "Create a goal first."}
        return lab.goal_context(goal_id)

    @server.tool()
    @lab_errors
    def create_goal(title: str, domain: str, description: str = "") -> dict[str, Any]:
        """Create a new learning goal for the learner."""
        return lab.create_goal(title, domain, description, channel="mcp")

    @server.tool()
    @lab_errors
    def get_challenge(challenge_id: int) -> dict[str, Any]:
        """Return a challenge's scenario, deliverable, and explicit evaluation criteria
        so you can present it to the learner. Records that the challenge was opened."""
        lab.record_challenge_opened(challenge_id, channel="mcp")
        return lab.get_challenge(challenge_id)

    @server.tool()
    @lab_errors
    def create_challenge(goal_id: int, title: str, scenario: str, deliverable: str,
                         criteria: list[CriterionInput], author: str = "assistant") -> dict[str, Any]:
        """Create a practice challenge with a concrete scenario, a deliverable, and explicit criteria."""
        return lab.create_challenge(goal_id, title, scenario, deliverable,
                                    [c.model_dump() for c in criteria],
                                    created_by=f"assistant:{author}", channel="mcp")

    @server.tool()
    @lab_errors
    def record_submission(challenge_id: int, content: str) -> dict[str, Any]:
        """Save the learner's own written answer to a challenge. The goal is derived from the challenge."""
        sub = lab.submit(challenge_id, content, channel="mcp")
        return {"submission_id": sub["id"], "challenge_id": sub["challenge_id"], "goal_id": sub["goal_id"],
                "created_at": sub["created_at"], "characters": len(sub["content"])}

    @server.tool()
    @lab_errors
    def get_submission(submission_id: int) -> dict[str, Any]:
        """Return a submission with its challenge, criteria, evidence, and any feedback."""
        return lab.get_submission(submission_id)

    @server.tool()
    @lab_errors
    def record_feedback(submission_id: int, evaluator_name: str, items: list[FeedbackItemInput],
                        summary: str = "", next_step: str = "",
                        unverified_claims: list[str] | None = None,
                        evaluator_kind: Literal["ai_assistant", "human"] = "ai_assistant") -> dict[str, Any]:
        """Record criterion-by-criterion feedback linked to verbatim submission evidence.
        The whole record is rejected if any criterion or evidence reference is invalid."""
        return lab.record_feedback(
            submission_id, provider_kind=evaluator_kind, provider_name=evaluator_name,
            items=[i.model_dump() for i in items], summary=summary, next_step=next_step,
            unverified_claims=unverified_claims or [], channel="mcp")

    @server.tool()
    @lab_errors
    def recommend_next_practice(goal_id: int) -> dict[str, Any]:
        """Report the recommended next practice step for a goal, with the records it is based on."""
        return lab.recommend_next(goal_id)

    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
