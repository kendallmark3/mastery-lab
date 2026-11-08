"""Minimal local browser UI. Server-rendered forms over the same MasteryLab service.

Run:  python -m mastery_lab web     (binds 127.0.0.1:8765 — local only, not production-ready)
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .evaluator import Evaluator, run_evaluation
from .service import ASSURANCE_NOTE, RATINGS, LabError, MasteryLab

HERE = Path(__file__).parent

RATING_LABELS = {"demonstrated": "Demonstrated", "partial": "Partially demonstrated", "not_evident": "Not evident"}
SUPPORT_LABELS = {"evidenced": "Evidenced observation", "unverified": "Unverified judgment — no evidence cited",
                  "gap": "Gap — not found in submission"}
KIND_LABELS = {"goal_created": "Goal created", "challenge_created": "Challenge created",
               "challenge_opened": "Challenge opened", "submitted": "Submission saved",
               "feedback_recorded": "Feedback recorded"}
EVAL_POLL_SECONDS = 4


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


def create_app(lab: MasteryLab | None = None, evaluator: Evaluator | None = None,
               evaluator_off_reason: str = "AI evaluation is turned off.") -> FastAPI:
    """`evaluator=None` means no AI evaluation: the page says so and the manual paths still work."""
    lab = lab or MasteryLab()
    lab.fail_interrupted_evaluations()
    app = FastAPI(title="Mastery Lab", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(RATING_LABELS=RATING_LABELS, SUPPORT_LABELS=SUPPORT_LABELS,
                                 KIND_LABELS=KIND_LABELS, RATINGS=RATINGS, ASSURANCE_NOTE=ASSURANCE_NOTE,
                                 EVAL_POLL_SECONDS=EVAL_POLL_SECONDS,
                                 AI_EVALUATOR=evaluator.name if evaluator else None,
                                 AI_OFF_REASON=evaluator_off_reason)

    def start_ai_evaluation(submission_id: int, tasks: BackgroundTasks) -> None:
        """Claim the submission and run the evaluator after the response is sent. Never duplicates."""
        if evaluator is None:
            return
        ev = lab.start_evaluation(submission_id, evaluator.name)
        if ev["created"]:
            tasks.add_task(run_evaluation, lab, ev, evaluator)

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
    async def submit(request: Request, challenge_id: str, tasks: BackgroundTasks):
        f = await request.form()
        try:
            sub = lab.submit(challenge_id, f.get("content", ""), channel="web")
        except LabError as e:
            if e.code == "not_found":
                return error_page(request, e)
            ch = lab.get_challenge(challenge_id)
            return render(request, "challenge.html", status=400, ch=ch, goal=lab.get_goal(ch["goal_id"]),
                          submissions=lab.list_submissions(ch["id"]), error=e.message, draft=f.get("content", ""))
        start_ai_evaluation(sub["id"], tasks)
        return RedirectResponse(f"/submissions/{sub['id']}", status_code=303)

    # ------------------------------------------------------ submissions & fb
    def submission_view(request: Request, submission_id: str, status: int = 200, **extra):
        sub = lab.get_submission(submission_id)
        return render(request, "submission.html", status=status, sub=sub,
                      goal=lab.get_goal(sub["goal_id"]),
                      segments=highlight(sub["content"], sub["evidence"]),
                      rec=lab.recommend_next(sub["goal_id"]),
                      exports=[(fb, json.dumps(lab.export_feedback(fb["id"]), indent=2, ensure_ascii=False))
                               for fb in sub["feedback"]], **extra)

    @app.get("/submissions/{submission_id}", response_class=HTMLResponse)
    def submission_page(request: Request, submission_id: str):
        try:
            return submission_view(request, submission_id)
        except LabError as e:
            return error_page(request, e)

    @app.post("/submissions/{submission_id}/evaluate")
    def evaluate(request: Request, submission_id: str, tasks: BackgroundTasks):
        try:
            sub = lab.get_submission(submission_id)
        except LabError as e:
            return error_page(request, e)
        if evaluator is None:
            return submission_view(request, submission_id, status=400,
                                   error=f"AI evaluation is unavailable. {evaluator_off_reason}")
        start_ai_evaluation(sub["id"], tasks)
        return RedirectResponse(f"/submissions/{sub['id']}#evaluation", status_code=303)

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

    @app.get("/feedback/{feedback_id}.json")
    def feedback_export(request: Request, feedback_id: str):
        try:
            data = lab.export_feedback(feedback_id)
        except LabError as e:
            return error_page(request, e)
        name = f"submission-{data['submission']['id']}-feedback-{data['feedback']['id']}.json"
        return Response(json.dumps(data, indent=2, ensure_ascii=False), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    return app
