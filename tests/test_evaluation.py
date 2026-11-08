"""INTENT-002: AI evaluation of submissions (fake evaluators; no model is called)."""

import json
import sqlite3
import stat

import pytest
from fastapi.testclient import TestClient

from conftest import SAMPLE, good_items
from mastery_lab import db
from mastery_lab.evaluator import ClaudeCliEvaluator, EvaluatorError, Reply, parse_reply, run_evaluation
from mastery_lab.service import MasteryLab
from mastery_lab.web import create_app

INVENTED = "We run quarterly disaster-recovery drills"


def reply_json(items=None, **extra):
    items = items if items is not None else [
        {**it, "recommendation": f"Strengthen {it['criterion']} with one concrete mechanism."} for it in good_items()]
    return json.dumps({"evaluator_name": "ignored", "summary": "Solid boundary thinking; weak validation plan.",
                       "next_step": "Write a test plan for C6.", "unverified_claims": ["All injection is blocked"],
                       "items": items, **extra})


class FakeEvaluator:
    name = "fake CLI"

    def __init__(self, *replies):
        self.replies = list(replies) or [reply_json()]
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        r = self.replies[min(len(self.prompts), len(self.replies)) - 1]
        if isinstance(r, Exception):
            raise r
        return Reply(text=r, model="fake-model")


def app(lab, evaluator=None, **kw):
    return TestClient(create_app(lab, evaluator, **kw))


def submission_id(response):
    return int(response.headers["location"].rsplit("/", 1)[-1])


def count(lab, table):
    with lab._conn() as c:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_submit_starts_evaluation_and_persists_linked_feedback(lab, seed_ids):
    fake = FakeEvaluator()
    c = app(lab, fake)
    r = c.post(f"/challenges/{seed_ids[1]}/submissions", data={"content": SAMPLE}, follow_redirects=False)
    sid = submission_id(r)

    sub = lab.get_submission(sid)
    assert sub["evaluation"]["status"] == "evaluated"
    fb = sub["feedback"][0]
    assert sub["evaluation"]["feedback_id"] == fb["id"]
    assert fb["provider_kind"] == "ai_assistant" and fb["provider_name"] == "fake-model via fake CLI"
    assert fb["channel"] == "ai-evaluator"
    c1 = next(i for i in fb["items"] if i["criterion_code"] == "C1")
    assert c1["support"] == "evidenced" and c1["recommendation"].startswith("Strengthen C1")

    page = c.get(f"/submissions/{sid}").text
    assert "Evaluated." in page and "Submit an improved attempt" in page
    assert "Strengthen C1 with one concrete mechanism." in page and "<mark>" in page
    assert 'http-equiv="refresh"' not in page
    # the prompt carried the challenge's real criteria and the learner's text
    assert "Governance of actions" in fake.prompts[0] and "<<<\n" + SAMPLE in fake.prompts[0]


def test_existing_unevaluated_submission_can_be_evaluated(lab, seed_ids):
    sid = lab.submit(seed_ids[1], SAMPLE)["id"]  # e.g. Submission #1, saved before AI evaluation existed
    c = app(lab, FakeEvaluator())
    page = c.get(f"/submissions/{sid}").text
    assert "not been evaluated by AI yet" in page and "Evaluate Submission" in page

    r = c.post(f"/submissions/{sid}/evaluate", follow_redirects=False)
    assert r.status_code == 303
    assert lab.get_submission(sid)["evaluation"]["status"] == "evaluated"
    assert count(lab, "submissions") == 1  # nothing re-submitted


def test_refresh_and_repeat_requests_never_duplicate(lab, seed_ids):
    sid = lab.submit(seed_ids[1], SAMPLE)["id"]
    fake = FakeEvaluator()
    c = app(lab, fake)
    for _ in range(3):
        c.post(f"/submissions/{sid}/evaluate")
        c.get(f"/submissions/{sid}")
    assert len(fake.prompts) == 1
    assert count(lab, "evaluations") == 1 and count(lab, "feedback") == 1


def test_in_progress_evaluation_cannot_be_started_twice(lab, seed_ids):
    sid = lab.submit(seed_ids[1], SAMPLE)["id"]
    first = lab.start_evaluation(sid, "x")
    second = lab.start_evaluation(sid, "x")
    assert first["created"] and not second["created"] and second["id"] == first["id"]


def test_invented_quote_is_retried_then_fails_visibly(lab, seed_ids):
    bad = reply_json(items=[{"criterion": "C5", "rating": "demonstrated", "evidence_quotes": [INVENTED]}])
    fake = FakeEvaluator(bad)
    sid = lab.submit(seed_ids[1], SAMPLE)["id"]
    c = app(lab, fake)
    c.post(f"/submissions/{sid}/evaluate")

    assert len(fake.prompts) == 2
    assert "previous reply was rejected" in fake.prompts[1] and "does not appear" not in fake.prompts[0]
    ev = lab.get_submission(sid)["evaluation"]
    assert ev["status"] == "failed" and "rejected twice" in ev["error"] and "C5" in ev["error"]
    assert count(lab, "feedback") == 0 and count(lab, "evidence") == 0  # nothing half-saved
    page = c.get(f"/submissions/{sid}").text
    assert "Evaluation failed." in page and "Retry evaluation" in page

    # retrying after a failure is allowed and keeps the failed run as history
    fake.replies = [reply_json()]
    fake.prompts.clear()
    c.post(f"/submissions/{sid}/evaluate")
    assert lab.get_submission(sid)["evaluation"]["status"] == "evaluated"
    assert count(lab, "evaluations") == 2


def test_rejected_reply_is_fixed_on_retry(lab, seed_ids):
    fake = FakeEvaluator("Sorry, here is my analysis in prose.", reply_json())
    sid = lab.submit(seed_ids[1], SAMPLE)["id"]
    ev = run_evaluation(lab, lab.start_evaluation(sid, "fake"), fake)
    assert ev["status"] == "evaluated" and len(fake.prompts) == 2
    assert "not valid JSON" in fake.prompts[1]


def test_evaluator_failure_is_not_retried_and_is_recorded(lab, seed_ids):
    fake = FakeEvaluator(EvaluatorError("The 'claude' command was not found."))
    sid = lab.submit(seed_ids[1], SAMPLE)["id"]
    ev = run_evaluation(lab, lab.start_evaluation(sid, "fake"), fake)
    assert ev["status"] == "failed" and "not found" in ev["error"] and len(fake.prompts) == 1


def test_unexpected_error_never_leaves_run_stuck(lab, seed_ids):
    fake = FakeEvaluator(RuntimeError("boom"))
    sid = lab.submit(seed_ids[1], SAMPLE)["id"]
    ev = run_evaluation(lab, lab.start_evaluation(sid, "fake"), fake)
    assert ev["status"] == "failed" and "boom" in ev["error"]


def test_without_an_evaluator_the_page_says_unavailable(lab, seed_ids):
    sid = lab.submit(seed_ids[1], SAMPLE)["id"]
    c = app(lab, None, evaluator_off_reason="The `claude` command was not found on PATH.")
    page = c.get(f"/submissions/{sid}").text
    assert "AI evaluation is unavailable" in page and "Evaluate Submission</button>" not in page
    r = c.post(f"/submissions/{sid}/evaluate")
    assert r.status_code == 400 and "not found on PATH" in r.text
    assert count(lab, "evaluations") == 0
    # submitting still works, with no evaluation attempted
    r = c.post(f"/challenges/{seed_ids[1]}/submissions", data={"content": SAMPLE}, follow_redirects=False)
    assert r.status_code == 303 and count(lab, "evaluations") == 0


def test_restart_marks_interrupted_evaluation_failed(db_path, seed_ids):
    lab = MasteryLab(db_path)
    sid = lab.submit(seed_ids[1], SAMPLE)["id"]
    lab.start_evaluation(sid, "fake CLI")  # the server dies mid-evaluation
    assert lab.get_submission(sid)["evaluation"]["status"] == "evaluating"

    # a restarted web app marks the abandoned run failed, so nothing hangs forever
    c = app(MasteryLab(db_path), FakeEvaluator())
    ev = lab.get_submission(sid)["evaluation"]
    assert ev["status"] == "failed" and "Interrupted" in ev["error"]
    assert "Retry evaluation" in c.get(f"/submissions/{sid}").text


def test_evaluating_status_page_auto_refreshes(lab, seed_ids):
    sid = lab.submit(seed_ids[1], SAMPLE)["id"]
    c = app(lab, FakeEvaluator())
    lab.start_evaluation(sid, "fake CLI")  # claimed after startup, still running
    page = c.get(f"/submissions/{sid}").text
    assert "AI evaluation in progress" in page and 'http-equiv="refresh"' in page


def test_old_database_gains_recommendation_column(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE feedback_items (id INTEGER PRIMARY KEY, feedback_id INTEGER NOT NULL,
                    criterion_id INTEGER NOT NULL, rating TEXT NOT NULL, observation TEXT NOT NULL DEFAULT '',
                    judgment TEXT NOT NULL DEFAULT '', gaps TEXT NOT NULL DEFAULT '')""")
    conn.commit()
    conn.close()
    MasteryLab(path)
    conn = db.connect(path)
    assert "recommendation" in {r["name"] for r in conn.execute("PRAGMA table_info(feedback_items)")}
    conn.close()


def test_evaluation_json_is_shown_and_downloadable(lab, seed_ids):
    c = app(lab, FakeEvaluator())
    sid = submission_id(c.post(f"/challenges/{seed_ids[1]}/submissions", data={"content": SAMPLE},
                               follow_redirects=False))
    fid = lab.get_submission(sid)["feedback"][0]["id"]

    r = c.get(f"/feedback/{fid}.json")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert f'filename="submission-{sid}-feedback-{fid}.json"' in r.headers["content-disposition"]
    data = r.json()
    assert data["submission"]["id"] == sid and data["challenge"]["id"] == seed_ids[1]
    assert data["feedback"]["provider_name"] == "fake-model via fake CLI"
    c1 = next(i for i in data["items"] if i["criterion"] == "C1")
    assert c1["rating"] == "demonstrated" and c1["support"] == "evidenced"
    assert c1["recommendation"] and c1["title"] and c1["description"]
    assert all(q in SAMPLE for i in data["items"] for q in i["evidence_quotes"])  # only verified quotes
    assert data["not_assessed"] == ["C5"]  # good_items() leaves C5 out

    page = c.get(f"/submissions/{sid}").text
    assert "Evaluation JSON" in page and f'href="/feedback/{fid}.json"' in page
    assert page.index("Evaluation JSON") > page.index("Add feedback")  # at the bottom
    assert c.get("/feedback/999.json").status_code == 404


def test_no_evaluation_json_before_feedback(lab, seed_ids):
    sid = lab.submit(seed_ids[1], SAMPLE)["id"]
    page = app(lab).get(f"/submissions/{sid}").text
    assert "Appears here after this submission is evaluated" in page and ".json" not in page


def test_parse_reply_tolerates_code_fences():
    assert parse_reply('```json\n{"items": []}\n```')["items"] == []
    with pytest.raises(ValueError):
        parse_reply("no json here")


# --------------------------------------------------- the real claude CLI wrapper
def fake_cli(tmp_path, stdout, code=0):
    script = tmp_path / "claude"
    script.write_text(f"#!/bin/sh\ncat > \"$0.stdin\"\necho \"$*\" > \"$0.args\"\ncat <<'OUT'\n{stdout}\nOUT\nexit {code}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_claude_cli_wrapper_sends_prompt_and_picks_main_model(tmp_path):
    out = json.dumps({"is_error": False, "result": reply_json(),
                      "modelUsage": {"claude-haiku-4-5": {"outputTokens": 13},
                                     "claude-sonnet-5": {"outputTokens": 900}}})
    script = fake_cli(tmp_path, out)
    reply = ClaudeCliEvaluator(command=str(script), model="sonnet")("PROMPT TEXT")
    assert reply.model == "claude-sonnet-5" and json.loads(reply.text)["items"]
    assert (tmp_path / "claude.stdin").read_text() == "PROMPT TEXT"
    args = (tmp_path / "claude.args").read_text()
    assert "-p" in args and "--tools" in args and "--model sonnet" in args


def test_claude_cli_wrapper_reports_errors(tmp_path):
    with pytest.raises(EvaluatorError, match="not found"):
        ClaudeCliEvaluator(command=str(tmp_path / "missing"))("x")
    script = fake_cli(tmp_path, json.dumps({"is_error": True, "result": "Not logged in"}), code=1)
    with pytest.raises(EvaluatorError, match="Not logged in"):
        ClaudeCliEvaluator(command=str(script))("x")
    script = fake_cli(tmp_path, "garbage", code=2)
    with pytest.raises(EvaluatorError, match="code 2"):
        ClaudeCliEvaluator(command=str(script))("x")
