"""Learning loop, persistence, invalid inputs, and evidence/feedback linkage at the domain layer."""

import sqlite3

import pytest

from conftest import SAMPLE, good_items
from mastery_lab.service import LabError, MasteryLab


def count(db_path, table):
    with sqlite3.connect(db_path) as c:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ---------------------------------------------------------------- SC-01/02
def test_seed_goal_and_substantial_challenge(lab, seed_ids):
    goal_id, ch_id = seed_ids
    assert lab.get_goal(goal_id)["domain"] == "Enterprise AI Architecture"
    ch = lab.get_challenge(ch_id)
    assert len(ch["scenario"]) > 1000 and "quality hold" in ch["scenario"]
    assert "800–1,500 words" in ch["deliverable"]
    assert [c["code"] for c in ch["criteria"]] == ["C1", "C2", "C3", "C4", "C5", "C6"]
    assert all(c["description"] and c["strong_evidence"] for c in ch["criteria"])


def test_seed_is_idempotent(db_path):
    MasteryLab(db_path)
    MasteryLab(db_path)
    assert count(db_path, "goals") == 1 and count(db_path, "challenges") == 1


# ------------------------------------------------------------ full loop
def test_full_loop_and_persistence_across_restart(db_path):
    lab = MasteryLab(db_path)
    goal_id = lab.list_goals()[0]["id"]
    ch_id = lab.list_challenges(goal_id)[0]["id"]
    sub = lab.submit(ch_id, SAMPLE)
    assert (sub["challenge_id"], sub["goal_id"]) == (ch_id, goal_id)  # SC-03
    fb = lab.record_feedback(sub["id"], provider_kind="human", provider_name="Mark (self-review)",
                             items=good_items(), next_step="Write a validation plan for C1–C5.",
                             unverified_claims=["Claims full 21 CFR Part 11 compliance"])
    assert lab.recommend_next(goal_id)["action"] == "revise_and_resubmit"
    del lab  # "close the program"

    lab2 = MasteryLab(db_path)  # SC-05: a fresh process view of the same file
    ctx = lab2.goal_context(goal_id)
    [ch] = ctx["challenges"]
    [s] = ch["submissions"]
    assert s["content"] == SAMPLE
    [fb2] = s["feedback"]
    assert fb2["id"] == fb["id"] and fb2["provider_name"] == "Mark (self-review)"
    assert fb2["unverified_claims"] == ["Claims full 21 CFR Part 11 compliance"]
    rec = ctx["recommendation"]
    assert rec["evaluator_next_step"] == "Write a validation plan for C1–C5."
    assert {f["code"] for f in rec["focus_criteria"]} == {"C3", "C4", "C5", "C6"}
    assert [h["kind"] for h in ctx["history"]][:2] == ["feedback_recorded", "submitted"]


# ------------------------------------------------------ SC-04 linkage
def test_feedback_items_link_to_exact_submission_spans(lab, seed_ids):
    _, ch_id = seed_ids
    sub = lab.submit(ch_id, SAMPLE)
    fb = lab.record_feedback(sub["id"], provider_kind="ai_assistant", provider_name="Claude", items=good_items())
    by = {i["criterion_code"]: i for i in fb["items"]}
    assert by["C1"]["support"] == "evidenced"
    ev = by["C1"]["evidence"][0]
    assert SAMPLE[ev["start_offset"]:ev["end_offset"]] == ev["excerpt"]
    assert by["C4"]["support"] == "unverified"   # positive rating, no evidence
    assert by["C6"]["support"] == "gap"
    assert [x["code"] for x in fb["not_assessed"]] == ["C5"]
    assert "not evidence that the design works in operation" in fb["assurance_note"]
    assert "score" not in str(fb.keys())


def test_evidence_quote_tolerates_whitespace_only(lab, seed_ids):
    _, ch_id = seed_ids
    sub = lab.submit(ch_id, SAMPLE)
    e = lab.add_evidence(sub["id"], "The model never   holds\ncredentials")
    assert e["excerpt"] == "The model never holds credentials"
    with pytest.raises(LabError):
        lab.add_evidence(sub["id"], "The model never holds secrets")  # different words


def test_reusing_existing_evidence_id(lab, seed_ids):
    _, ch_id = seed_ids
    sub = lab.submit(ch_id, SAMPLE)
    e = lab.add_evidence(sub["id"], "Events are hash-chained")
    fb = lab.record_feedback(sub["id"], provider_kind="human", provider_name="Mentor",
                             items=[{"criterion": "C4", "rating": "demonstrated", "evidence_ids": [e["id"]]}])
    assert fb["items"][0]["evidence"][0]["id"] == e["id"]


# --------------------------------------------------------------- SC-07
@pytest.mark.parametrize("content", ["", "   \n\t "])
def test_empty_submission_rejected(lab, seed_ids, db_path, content):
    with pytest.raises(LabError) as e:
        lab.submit(seed_ids[1], content)
    assert e.value.code == "invalid" and count(db_path, "submissions") == 0


@pytest.mark.parametrize("cid", [999, "999", "abc", None])
def test_nonexistent_challenge_rejected(lab, db_path, cid):
    with pytest.raises(LabError):
        lab.submit(cid, "a real answer")
    assert count(db_path, "submissions") == 0


def test_feedback_with_quote_not_in_submission_rejected_atomically(lab, seed_ids, db_path):
    sub = lab.submit(seed_ids[1], SAMPLE)
    items = good_items() + [{"criterion": "C5", "rating": "demonstrated",
                             "evidence_quotes": ["We run chaos engineering every week"]}]
    with pytest.raises(LabError, match="does not appear|not an excerpt"):
        lab.record_feedback(sub["id"], provider_kind="human", provider_name="x", items=items)
    for t in ("feedback", "feedback_items", "evidence", "feedback_item_evidence"):
        assert count(db_path, t) == 0, t


def test_feedback_citing_other_submissions_evidence_rejected(lab, seed_ids, db_path):
    s1 = lab.submit(seed_ids[1], SAMPLE)
    s2 = lab.submit(seed_ids[1], "A different answer entirely about audit logging and approvals.")
    foreign = lab.add_evidence(s1["id"], "Events are hash-chained")
    with pytest.raises(LabError, match="does not belong"):
        lab.record_feedback(s2["id"], provider_kind="human", provider_name="x",
                            items=[{"criterion": "C4", "rating": "partial", "evidence_ids": [foreign["id"]]}])
    with pytest.raises(LabError, match="does not belong"):
        lab.record_feedback(s2["id"], provider_kind="human", provider_name="x",
                            items=[{"criterion": "C4", "rating": "partial", "evidence_ids": [424242]}])
    assert count(db_path, "feedback") == 0


def test_feedback_criterion_from_other_challenge_rejected(lab, seed_ids):
    goal_id, ch_id = seed_ids
    other = lab.create_challenge(goal_id, "Other", "Scenario text", "Deliverable",
                                 [{"title": "Only", "description": "Only criterion"}])
    sub = lab.submit(ch_id, SAMPLE)
    other_crit_id = other["criteria"][0]["id"]
    with pytest.raises(LabError, match="not a criterion"):
        lab.record_feedback(sub["id"], provider_kind="human", provider_name="x",
                            items=[{"criterion": other_crit_id, "rating": "partial"}])
    with pytest.raises(LabError, match="not a criterion"):
        lab.record_feedback(sub["id"], provider_kind="human", provider_name="x",
                            items=[{"criterion": "C9", "rating": "partial"}])


@pytest.mark.parametrize("kwargs, msg", [
    ({"provider_name": ""}, "provider_name"),
    ({"provider_kind": "robot"}, "provider_kind"),
    ({"items": []}, "at least one"),
    ({"items": [{"criterion": "C1", "rating": "excellent"}]}, "rating"),
    ({"items": [{"criterion": "C1", "rating": "partial"}, {"criterion": "c1", "rating": "partial"}]}, "more than once"),
    ({"items": [{"criterion": "C1", "rating": "partial", "evidence_quotes": ["short"]}]}, "excerpt"),
])
def test_invalid_feedback_shapes_rejected(lab, seed_ids, db_path, kwargs, msg):
    sub = lab.submit(seed_ids[1], SAMPLE)
    args = {"provider_kind": "human", "provider_name": "x", "items": [{"criterion": "C1", "rating": "partial"}]}
    args.update(kwargs)
    with pytest.raises(LabError, match=msg):
        lab.record_feedback(sub["id"], **args)
    assert count(db_path, "feedback") == 0


def test_feedback_for_missing_submission_rejected(lab):
    with pytest.raises(LabError) as e:
        lab.record_feedback(77, provider_kind="human", provider_name="x", items=[{"criterion": "C1", "rating": "partial"}])
    assert e.value.code == "not_found"


def test_challenge_requires_explicit_criteria(lab, seed_ids):
    with pytest.raises(LabError, match="criterion"):
        lab.create_challenge(seed_ids[0], "T", "S", "D", [])


def test_recommendation_progression(lab, seed_ids):
    goal_id, ch_id = seed_ids
    assert lab.recommend_next(goal_id)["action"] == "start_challenge"
    sub = lab.submit(ch_id, SAMPLE)
    assert lab.recommend_next(goal_id)["action"] == "get_feedback"
    quotes = {"C1": "The model never holds credentials", "C2": "filtered by the document ACL",
              "C3": "the approver cannot be the requester", "C4": "Events are hash-chained",
              "C5": "actions fail closed", "C6": "We would test it before go-live"}
    lab.record_feedback(sub["id"], provider_kind="human", provider_name="x",
                        items=[{"criterion": k, "rating": "demonstrated", "evidence_quotes": [v]} for k, v in quotes.items()])
    assert lab.recommend_next(goal_id)["action"] == "next_challenge"
