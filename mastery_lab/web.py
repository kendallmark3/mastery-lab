"""Minimal local browser UI. Server-rendered forms over the same MasteryLab service.

Run:  python -m mastery_lab web     (binds 127.0.0.1:8765 — local only, not production-ready)
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .service import ASSURANCE_NOTE, RATINGS, LabError, MasteryLab

HERE = Path(__file__).parent

RATING_LABELS = {"demonstrated": "Demonstrated", "partial": "Partially demonstrated", "not_evident": "Not evident"}
SUPPORT_LABELS = {"evidenced": "Evidenced observation", "unverified": "Unverified judgment — no evidence cited",
                  "gap": "Gap — not found in submission"}
KIND_LABELS = {"goal_created": "Goal created", "challenge_created": "Challenge created",
               "challenge_opened": "Challenge opened", "submitted": "Submission saved",
               "feedback_recorded": "Feedback recorded"}


def highlight(content: str, evidence: list[dict]) -> list[tuple[str, bool]]:
    """Split content into (text, is_evidence) segments, merging overlapping evidence spans."""
    spans = sorted((e["start_offset"], e["end_offset"]) for e in evidence)
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    out, pos = [], 0
    for s, e in merged:
        if s > pos:
            out.append((content[pos:s], False))
        out.append((content[s:e], True))
        pos = e
    if pos < len(content):
        out.append((content[pos:], False))
    return out


def assistant_prompt(sub: dict) -> str:
    ch = sub["challenge"]
    crit = "\n".join(f"- {c['code']} {c['title']}: {c['description']}" for c in ch["criteria"])
    return f"""You are evaluating a learner's written answer. Be specific and honest.

CHALLENGE: {ch['title']}
SCENARIO:
{ch['scenario']}
DELIVERABLE:
{ch['deliverable']}
CRITERIA:
{crit}

LEARNER SUBMISSION #{sub['id']}:
<<<
{sub['content']}
>>>

Rules:
- For each criterion give a rating: demonstrated | partial | not_evident.
- "observation" = only what the submission literally says. "judgment" = your inference.
- "evidence_quotes" must be copied VERBATIM from the submission (at least 8 characters).
  Quotes that are not in the submission will be rejected by the system.
- Do not rate demonstrated/partial without a quote; it will be shown as unverified.
- List claims the learner makes that the text does not substantiate in "unverified_claims".
- A well-argued design is not proof it works in operation; do not imply otherwise.

Reply with ONLY this JSON:
{{"evaluator_name": "<your model name>", "summary": "...", "next_step": "...",
 "unverified_claims": ["..."],
 "items": [{{"criterion": "C1", "rating": "partial", "observation": "...", "judgment": "...",
            "gaps": "...", "evidence_quotes": ["..."]}}]}}"""


def create_app(lab: MasteryLab | None = None) -> FastAPI:
    lab = lab or MasteryLab()
    app = FastAPI(title="Mastery Lab", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(RATING_LABELS=RATING_LABELS, SUPPORT_LABELS=SUPPORT_LABELS,
                                 KIND_LABELS=KIND_LABELS, RATINGS=RATINGS, ASSURANCE_NOTE=ASSURANCE_NOTE)

    def render(request: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
        return templates.TemplateResponse(request, name, ctx, status_code=status)

    def error_page(request: Request, e: LabError) -> HTMLResponse:
        return render(request, "error.html", status=404 if e.code == "not_found" else 400, message=e.message)

    # ------------------------------------------------------------------ goals
    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        goals = lab.list_goals()
        resume = lab.goal_context(goals[0]["id"]) if goals else None
        return render(request, "home.html", goals=goals, resume=resume)

    @app.post("/goals")
    async def create_goal(request: Request):
        f = await request.form()
        try:
            g = lab.create_goal(f.get("title", ""), f.get("domain", ""), f.get("description", ""), channel="web")
        except LabError as e:
            return render(request, "home.html", status=400, goals=lab.list_goals(), resume=None,
                          error=e.message, form=dict(f))
        return RedirectResponse(f"/goals/{g['id']}", status_code=303)

    @app.get("/goals/{goal_id}", response_class=HTMLResponse)
    def goal_page(request: Request, goal_id: str):
        try:
            return render(request, "goal.html", ctx=lab.goal_context(goal_id))
        except LabError as e:
            return error_page(request, e)

    @app.post("/goals/{goal_id}/challenges")
    async def create_challenge(request: Request, goal_id: str):
        f = await request.form()
        criteria = []
        for line in str(f.get("criteria", "")).splitlines():
            if line.strip():
                title, _, desc = line.partition("::")
                criteria.append({"title": title.strip(), "description": desc.strip()})
        try:
            ch = lab.create_challenge(goal_id, f.get("title", ""), f.get("scenario", ""),
                                      f.get("deliverable", ""), criteria, created_by="human", channel="web")
        except LabError as e:
            if e.code == "not_found":
                return error_page(request, e)
            return render(request, "goal.html", status=400, ctx=lab.goal_context(goal_id),
                          error=e.message, form=dict(f))
        return RedirectResponse(f"/challenges/{ch['id']}", status_code=303)

    # ------------------------------------------------------------- challenges
    @app.get("/challenges/{challenge_id}", response_class=HTMLResponse)
    def challenge_page(request: Request, challenge_id: str):
        try:
            lab.record_challenge_opened(challenge_id, channel="web")
            ch = lab.get_challenge(challenge_id)
            return render(request, "challenge.html", ch=ch, goal=lab.get_goal(ch["goal_id"]),
                          submissions=lab.list_submissions(ch["id"]))
        except LabError as e:
            return error_page(request, e)

    @app.post("/challenges/{challenge_id}/submissions")
    async def submit(request: Request, challenge_id: str):
        f = await request.form()
        try:
            sub = lab.submit(challenge_id, f.get("content", ""), channel="web")
        except LabError as e:
            if e.code == "not_found":
                return error_page(request, e)
            ch = lab.get_challenge(challenge_id)
            return render(request, "challenge.html", status=400, ch=ch, goal=lab.get_goal(ch["goal_id"]),
                          submissions=lab.list_submissions(ch["id"]), error=e.message, draft=f.get("content", ""))
        return RedirectResponse(f"/submissions/{sub['id']}", status_code=303)

    # ------------------------------------------------------ submissions & fb
    def submission_view(request: Request, submission_id: str, status: int = 200, **extra):
        sub = lab.get_submission(submission_id)
        return render(request, "submission.html", status=status, sub=sub,
                      goal=lab.get_goal(sub["goal_id"]),
                      segments=highlight(sub["content"], sub["evidence"]),
                      prompt=assistant_prompt(sub), rec=lab.recommend_next(sub["goal_id"]), **extra)

    @app.get("/submissions/{submission_id}", response_class=HTMLResponse)
    def submission_page(request: Request, submission_id: str):
        try:
            return submission_view(request, submission_id)
        except LabError as e:
            return error_page(request, e)

    @app.post("/submissions/{submission_id}/feedback")
    async def feedback_form(request: Request, submission_id: str):
        f = await request.form()
        try:
            sub = lab.get_submission(submission_id)
        except LabError as e:
            return error_page(request, e)
        items = []
        for cr in sub["challenge"]["criteria"]:
            code = cr["code"]
            rating = f.get(f"rating_{code}", "")
            if not rating:
                continue  # criterion left unassessed
            items.append({
                "criterion": code, "rating": rating,
                "observation": f.get(f"observation_{code}", ""), "judgment": f.get(f"judgment_{code}", ""),
                "gaps": f.get(f"gaps_{code}", ""),
                "evidence_quotes": [q for q in str(f.get(f"quotes_{code}", "")).splitlines() if q.strip()],
            })
        try:
            lab.record_feedback(
                submission_id, provider_kind=f.get("provider_kind", "human"),
                provider_name=f.get("provider_name", ""), items=items,
                summary=f.get("summary", ""), next_step=f.get("next_step", ""),
                unverified_claims=[x for x in str(f.get("unverified_claims", "")).splitlines() if x.strip()],
                channel="web-form")
        except LabError as e:
            return submission_view(request, submission_id, status=400, error=e.message, form=dict(f))
        return RedirectResponse(f"/submissions/{submission_id}#feedback", status_code=303)

    @app.post("/submissions/{submission_id}/feedback-json")
    async def feedback_json(request: Request, submission_id: str):
        f = await request.form()
        raw = str(f.get("payload", ""))
        try:
            lab.get_submission(submission_id)
        except LabError as e:
            return error_page(request, e)
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("top-level value must be an object")
        except ValueError as e:
            return submission_view(request, submission_id, status=400,
                                   error=f"Pasted feedback is not valid JSON: {e}", json_payload=raw)
        try:
            lab.record_feedback(
                submission_id, provider_kind="ai_assistant",
                provider_name=f"{data.get('evaluator_name') or 'AI assistant'} (pasted by learner)",
                items=data.get("items"), summary=data.get("summary", ""), next_step=data.get("next_step", ""),
                unverified_claims=data.get("unverified_claims") or [], channel="web-json")
        except LabError as e:
            return submission_view(request, submission_id, status=400, error=e.message, json_payload=raw)
        return RedirectResponse(f"/submissions/{submission_id}#feedback", status_code=303)

    return app
