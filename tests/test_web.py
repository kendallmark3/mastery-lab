"""Browser loop through the real FastAPI app, including restart and the no-connector JSON path."""

import re

from fastapi.testclient import TestClient

from conftest import SAMPLE
from mastery_lab.service import MasteryLab
from mastery_lab.web import create_app


def client(db_path):
    return TestClient(create_app(MasteryLab(db_path)))


def test_browser_loop_and_resume_after_restart(db_path):
    c = client(db_path)
    home = c.get("/")
    assert home.status_code == 200 and "Enterprise AI Architecture" in home.text
    goal_url = re.search(r'href="(/goals/\d+)"', home.text).group(1)
    goal = c.get(goal_url)
    ch_url = re.search(r'href="(/challenges/\d+)"', goal.text).group(1)
    ch = c.get(ch_url)
    assert "Evaluation criteria" in ch.text and "Governance of actions" in ch.text  # SC-02 visible

    r = c.post(f"{ch_url}/submissions", data={"content": SAMPLE}, follow_redirects=False)
    assert r.status_code == 303
    sub_url = r.headers["location"]

    form = {"provider_name": "Mark (self-review)", "provider_kind": "human",
            "rating_C1": "demonstrated", "quotes_C1": "The model never holds credentials",
            "observation_C1": "States model holds no credentials.", "judgment_C1": "Sound boundary.",
            "rating_C6": "not_evident", "gaps_C6": "No concrete tests.",
            "rating_C4": "partial",
            "unverified_claims": "Claims full Part 11 compliance\nClaims all injection blocked",
            "next_step": "Write a validation plan."}
    r = c.post(f"{sub_url}/feedback", data=form, follow_redirects=False)
    assert r.status_code == 303

    # --- restart: brand-new app + service on the same DB file
    c2 = client(db_path)
    home2 = c2.get("/")
    assert "Continue where you left off" in home2.text and "Revise" in home2.text
    page = c2.get(sub_url).text
    assert "<mark>The model never holds credentials</mark>" in page
    assert "Unverified judgment" in page            # C4 partial without evidence
    assert "Gap — not found in submission" in page   # C6
    assert "Not assessed in this feedback record" in page
    assert "Claims full Part 11 compliance" in page
    assert "Write a validation plan." in page
    assert "Human: Mark (self-review)" in page
    hist = c2.get(goal_url).text
    assert "Feedback recorded" in hist and "Submission saved" in hist


def test_empty_submission_shows_error_and_saves_nothing(db_path):
    c = client(db_path)
    r = c.post("/challenges/1/submissions", data={"content": "   "})
    assert r.status_code == 400 and "Submission is empty" in r.text
    assert "Submission #" not in c.get("/challenges/1").text


def test_nonexistent_records_404(db_path):
    c = client(db_path)
    assert c.get("/challenges/999").status_code == 404
    assert c.post("/challenges/999/submissions", data={"content": "hi"}).status_code == 404
    assert c.get("/submissions/5").status_code == 404
    assert c.get("/goals/abc").status_code == 400


def test_feedback_with_invented_quote_rejected_in_browser(db_path):
    c = client(db_path)
    sub_url = c.post("/challenges/1/submissions", data={"content": SAMPLE}, follow_redirects=False).headers["location"]
    r = c.post(f"{sub_url}/feedback", data={"provider_name": "Me", "provider_kind": "human",
                                            "rating_C5": "demonstrated",
                                            "quotes_C5": "We run quarterly disaster recovery drills"})
    assert r.status_code == 400
    assert "Not saved." in r.text and "not an excerpt" in r.text
    assert "Feedback #" not in c.get(sub_url).text


def test_paste_json_path_is_removed(db_path):
    c = client(db_path)
    sub_url = c.post("/challenges/1/submissions", data={"content": SAMPLE}, follow_redirects=False).headers["location"]
    page = c.get(sub_url).text
    assert "Reply with ONLY this JSON" not in page and "feedback-json" not in page
    assert c.post(f"{sub_url}/feedback-json", data={"payload": "{}"}).status_code in (404, 405)
