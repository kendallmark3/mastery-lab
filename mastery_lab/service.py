"""Mastery Lab domain logic — the single learning engine.

The web UI and the MCP server are thin adapters over this module. All
validation and trust rules live here so neither surface can bypass them:

* a submission must be non-empty and belong to an existing challenge;
  its goal is derived from the challenge, never supplied by the caller
* feedback must target an existing submission, and every criterion it
  addresses must belong to that submission's challenge
* every evidence reference must be an excerpt that actually occurs in the
  submission it is attached to (or an existing evidence id of that same
  submission); otherwise the whole feedback record is rejected
* a positive rating with no evidence is stored but surfaced as
  "unverified judgment", never as an evidenced observation
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db

RATINGS = ("demonstrated", "partial", "not_evident")
PROVIDER_KINDS = ("human", "ai_assistant")
MIN_EXCERPT_CHARS = 8
MAX_SUBMISSION_CHARS = 100_000

ASSURANCE_NOTE = (
    "This feedback assesses the written design reasoning against the stated criteria. "
    "It is not evidence that the design works in operation, and it is not a mastery score."
)


class LabError(ValueError):
    """A request was rejected. `code` is 'not_found' or 'invalid'."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _not_found(what: str, ident: Any) -> LabError:
    return LabError("not_found", f"{what} {ident!r} does not exist.")


def _invalid(message: str) -> LabError:
    return LabError("invalid", message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(r) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


def _as_int(value: Any, what: str) -> int:
    try:
        if isinstance(value, bool):
            raise TypeError
        return int(value)
    except (TypeError, ValueError):
        raise _invalid(f"{what} must be an integer id, got {value!r}.") from None


@dataclass
class MasteryLab:
    db_path: Path | str = db.DEFAULT_DB_PATH
    seed: bool = True

    def __post_init__(self) -> None:
        db.init_db(self.db_path)
        if self.seed:
            from .seed import ensure_seed

            ensure_seed(self)

    @contextmanager
    def _conn(self):
        """One transaction per block: commit on success, roll back on any error, always close."""
        conn = db.connect(self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ goals
    def list_goals(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT g.*,
                          (SELECT MAX(created_at) FROM activity a WHERE a.goal_id = g.id) AS last_activity
                   FROM goals g ORDER BY COALESCE(last_activity, g.created_at) DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def get_goal(self, goal_id: Any) -> dict:
        gid = _as_int(goal_id, "goal_id")
        with self._conn() as c:
            goal = _row(c.execute("SELECT * FROM goals WHERE id = ?", (gid,)).fetchone())
        if not goal:
            raise _not_found("Goal", goal_id)
        return goal

    def create_goal(self, title: str, domain: str, description: str = "", *, channel: str = "web",
                    slug: str | None = None) -> dict:
        title, domain = (title or "").strip(), (domain or "").strip()
        if not title:
            raise _invalid("A learning goal needs a title.")
        if not domain:
            raise _invalid("A learning goal needs a domain.")
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO goals (slug, title, domain, description, created_at) VALUES (?,?,?,?,?)",
                (slug, title, domain, (description or "").strip(), _now()),
            )
            gid = cur.lastrowid
            self._log(c, gid, "goal_created", "goals", gid, title, channel)
        return self.get_goal(gid)

    # ------------------------------------------------------------- challenges
    def get_challenge(self, challenge_id: Any) -> dict:
        cid = _as_int(challenge_id, "challenge_id")
        with self._conn() as c:
            ch = _row(c.execute("SELECT * FROM challenges WHERE id = ?", (cid,)).fetchone())
            if not ch:
                raise _not_found("Challenge", challenge_id)
            ch["criteria"] = [dict(r) for r in c.execute(
                "SELECT * FROM criteria WHERE challenge_id = ? ORDER BY position", (cid,))]
        return ch

    def list_challenges(self, goal_id: Any) -> list[dict]:
        gid = self.get_goal(goal_id)["id"]
        with self._conn() as c:
            rows = c.execute("SELECT * FROM challenges WHERE goal_id = ? ORDER BY id", (gid,)).fetchall()
        return [self.get_challenge(r["id"]) for r in rows]

    def create_challenge(self, goal_id: Any, title: str, scenario: str, deliverable: str,
                         criteria: list[dict], *, created_by: str = "human", channel: str = "web",
                         slug: str | None = None) -> dict:
        gid = self.get_goal(goal_id)["id"]
        title, scenario, deliverable = (title or "").strip(), (scenario or "").strip(), (deliverable or "").strip()
        if not title or not scenario or not deliverable:
            raise _invalid("A challenge needs a title, a scenario, and a deliverable.")
        if not isinstance(criteria, list) or not criteria:
            raise _invalid("A challenge needs at least one explicit evaluation criterion.")
        cleaned = []
        for i, cr in enumerate(criteria, start=1):
            if not isinstance(cr, dict):
                raise _invalid(f"Criterion #{i} must be an object with title and description.")
            t, d = str(cr.get("title", "")).strip(), str(cr.get("description", "")).strip()
            if not t or not d:
                raise _invalid(f"Criterion #{i} needs a title and a description.")
            code = str(cr.get("code") or f"C{i}").strip()
            cleaned.append((code, t, d, str(cr.get("strong_evidence", "")).strip(), i))
        codes = [x[0] for x in cleaned]
        if len(set(codes)) != len(codes):
            raise _invalid(f"Criterion codes must be unique, got {codes}.")
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO challenges (goal_id, slug, title, scenario, deliverable, created_by, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (gid, slug, title, scenario, deliverable, created_by, _now()),
            )
            cid = cur.lastrowid
            c.executemany(
                """INSERT INTO criteria (challenge_id, code, title, description, strong_evidence, position)
                   VALUES (?,?,?,?,?,?)""",
                [(cid, *x) for x in cleaned],
            )
            self._log(c, gid, "challenge_created", "challenges", cid, title, channel)
        return self.get_challenge(cid)

    def record_challenge_opened(self, challenge_id: Any, channel: str) -> None:
        ch = self.get_challenge(challenge_id)
        with self._conn() as c:
            last = c.execute(
                "SELECT kind, ref_id FROM activity WHERE goal_id = ? ORDER BY id DESC LIMIT 1",
                (ch["goal_id"],),
            ).fetchone()
            if not last or (last["kind"], last["ref_id"]) != ("challenge_opened", ch["id"]):
                self._log(c, ch["goal_id"], "challenge_opened", "challenges", ch["id"], ch["title"], channel)

    # ------------------------------------------------------------ submissions
    def submit(self, challenge_id: Any, content: str, *, channel: str = "web") -> dict:
        if challenge_id is None or str(challenge_id).strip() == "":
            raise _invalid("A submission must name the challenge it answers.")
        ch = self.get_challenge(challenge_id)  # raises not_found
        if not isinstance(content, str) or not content.strip():
            raise _invalid("Submission is empty. Write your solution before submitting.")
        if len(content) > MAX_SUBMISSION_CHARS:
            raise _invalid(f"Submission exceeds {MAX_SUBMISSION_CHARS} characters.")
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO submissions (challenge_id, goal_id, content, source, created_at) VALUES (?,?,?,?,?)",
                (ch["id"], ch["goal_id"], content, channel, _now()),
            )
            sid = cur.lastrowid
            self._log(c, ch["goal_id"], "submitted", "submissions", sid, ch["title"], channel)
        return self.get_submission(sid)

    def get_submission(self, submission_id: Any) -> dict:
        sid = _as_int(submission_id, "submission_id")
        with self._conn() as c:
            sub = _row(c.execute("SELECT * FROM submissions WHERE id = ?", (sid,)).fetchone())
            if not sub:
                raise _not_found("Submission", submission_id)
            sub["evidence"] = [dict(r) for r in c.execute(
                "SELECT * FROM evidence WHERE submission_id = ? ORDER BY start_offset", (sid,))]
            fb_ids = [r["id"] for r in c.execute(
                "SELECT id FROM feedback WHERE submission_id = ? ORDER BY id", (sid,))]
        sub["challenge"] = self.get_challenge(sub["challenge_id"])
        sub["feedback"] = [self.get_feedback(f) for f in fb_ids]
        sub["evaluation"] = self.latest_evaluation(sid)
        return sub

    def list_submissions(self, challenge_id: Any) -> list[dict]:
        cid = self.get_challenge(challenge_id)["id"]
        with self._conn() as c:
            rows = c.execute("SELECT id FROM submissions WHERE challenge_id = ? ORDER BY id", (cid,)).fetchall()
        return [self.get_submission(r["id"]) for r in rows]

    # --------------------------------------------------------------- evidence
    @staticmethod
    def _locate(content: str, excerpt: str) -> tuple[int, int] | None:
        """Find `excerpt` in `content`, tolerating whitespace differences only."""
        words = excerpt.split()
        if not words:
            return None
        m = re.search(r"\s+".join(re.escape(w) for w in words), content)
        return (m.start(), m.end()) if m else None

    def _add_evidence(self, c, submission: dict, excerpt: Any) -> int:
        if not isinstance(excerpt, str) or len("".join(excerpt.split())) < MIN_EXCERPT_CHARS:
            raise _invalid(
                f"Evidence excerpt {excerpt!r} is too short; quote at least {MIN_EXCERPT_CHARS} "
                "characters of the submission.")
        span = self._locate(submission["content"], excerpt)
        if span is None:
            raise _invalid(
                f"Evidence excerpt {excerpt[:80]!r} does not appear in submission {submission['id']}. "
                "Evidence must quote the learner's actual text.")
        start, end = span
        existing = c.execute(
            "SELECT id FROM evidence WHERE submission_id = ? AND start_offset = ? AND end_offset = ?",
            (submission["id"], start, end)).fetchone()
        if existing:
            return existing["id"]
        cur = c.execute(
            "INSERT INTO evidence (submission_id, excerpt, start_offset, end_offset, created_at) VALUES (?,?,?,?,?)",
            (submission["id"], submission["content"][start:end], start, end, _now()))
        return cur.lastrowid

    def add_evidence(self, submission_id: Any, excerpt: str) -> dict:
        sub = self.get_submission(submission_id)
        with self._conn() as c:
            eid = self._add_evidence(c, sub, excerpt)
            return dict(c.execute("SELECT * FROM evidence WHERE id = ?", (eid,)).fetchone())

    # --------------------------------------------------------------- feedback
    def record_feedback(self, submission_id: Any, *, provider_kind: str, provider_name: str,
                        items: list[dict], summary: str = "", next_step: str = "",
                        unverified_claims: list[str] | None = None, channel: str = "web-form") -> dict:
        """Validate everything first, then write atomically. Nothing is saved on any error."""
        sub = self.get_submission(submission_id)
        if provider_kind not in PROVIDER_KINDS:
            raise _invalid(f"provider_kind must be one of {PROVIDER_KINDS}, got {provider_kind!r}.")
        provider_name = (provider_name or "").strip()
        if not provider_name:
            raise _invalid("Feedback must name who or what provided it (provider_name).")
        if not isinstance(items, list) or not items:
            raise _invalid("Feedback needs at least one criterion-level item.")
        claims = unverified_claims or []
        if not isinstance(claims, list) or not all(isinstance(x, str) for x in claims):
            raise _invalid("unverified_claims must be a list of strings.")
        for name, val in (("summary", summary), ("next_step", next_step)):
            if val is not None and not isinstance(val, str):
                raise _invalid(f"{name} must be text.")
        claims = [x.strip() for x in claims if x.strip()]

        criteria = sub["challenge"]["criteria"]
        by_code = {cr["code"].upper(): cr for cr in criteria}
        by_id = {cr["id"]: cr for cr in criteria}
        valid_evidence_ids = {e["id"] for e in sub["evidence"]}

        prepared, seen = [], set()
        for n, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise _invalid(f"Feedback item #{n} must be an object.")
            ref = item.get("criterion", item.get("criterion_code", item.get("criterion_id")))
            cr = None
            if isinstance(ref, int) and not isinstance(ref, bool):
                cr = by_id.get(ref)
            elif isinstance(ref, str):
                cr = by_code.get(ref.strip().upper())
                if cr is None and ref.strip().isdigit():
                    cr = by_id.get(int(ref.strip()))
            if cr is None:
                raise _invalid(
                    f"Feedback item #{n} references criterion {ref!r}, which is not a criterion of "
                    f"challenge {sub['challenge_id']} (valid: {sorted(by_code)}).")
            if cr["id"] in seen:
                raise _invalid(f"Criterion {cr['code']} is addressed more than once.")
            seen.add(cr["id"])
            rating = str(item.get("rating", "")).strip().lower()
            if rating not in RATINGS:
                raise _invalid(f"Feedback item for {cr['code']}: rating must be one of {RATINGS}, got {rating!r}.")
            quotes = item.get("evidence_quotes") or []
            ids = item.get("evidence_ids") or []
            if isinstance(quotes, str):
                quotes = [quotes]
            if not isinstance(quotes, list) or not isinstance(ids, list):
                raise _invalid(f"Feedback item for {cr['code']}: evidence_quotes/evidence_ids must be lists.")
            for raw in ids:
                eid = _as_int(raw, "evidence id")
                if eid not in valid_evidence_ids:
                    raise _invalid(
                        f"Feedback item for {cr['code']} cites evidence id {raw!r}, which does not belong "
                        f"to submission {sub['id']}.")
            for q in quotes:  # validate before any write
                if not isinstance(q, str) or len("".join(q.split())) < MIN_EXCERPT_CHARS or \
                        self._locate(sub["content"], q) is None:
                    raise _invalid(
                        f"Feedback item for {cr['code']} cites evidence {str(q)[:80]!r}, which is not an "
                        f"excerpt (≥{MIN_EXCERPT_CHARS} chars) of submission {sub['id']}.")
            prepared.append((cr, rating, item, quotes, [int(i) for i in ids]))

        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO feedback (submission_id, provider_kind, provider_name, channel, summary,
                                         unverified_claims, next_step, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (sub["id"], provider_kind, provider_name, channel, (summary or "").strip(),
                 json.dumps(claims), (next_step or "").strip(), _now()))
            fid = cur.lastrowid
            for cr, rating, item, quotes, ids in prepared:
                icur = c.execute(
                    """INSERT INTO feedback_items (feedback_id, criterion_id, rating, observation, judgment, gaps,
                                                  recommendation)
                       VALUES (?,?,?,?,?,?,?)""",
                    (fid, cr["id"], rating, str(item.get("observation", "")).strip(),
                     str(item.get("judgment", "")).strip(), str(item.get("gaps", "")).strip(),
                     str(item.get("recommendation") or "").strip()))
                ev_ids = list(ids) + [self._add_evidence(c, sub, q) for q in quotes]
                c.executemany(
                    "INSERT OR IGNORE INTO feedback_item_evidence (feedback_item_id, evidence_id) VALUES (?,?)",
                    [(icur.lastrowid, e) for e in ev_ids])
            self._log(c, sub["goal_id"], "feedback_recorded", "feedback", fid,
                      f"{provider_name} on submission {sub['id']}", channel)
        return self.get_feedback(fid)

    def get_feedback(self, feedback_id: Any) -> dict:
        fid = _as_int(feedback_id, "feedback_id")
        with self._conn() as c:
            fb = _row(c.execute("SELECT * FROM feedback WHERE id = ?", (fid,)).fetchone())
            if not fb:
                raise _not_found("Feedback", feedback_id)
            fb["unverified_claims"] = json.loads(fb["unverified_claims"])
            items = []
            for r in c.execute(
                    """SELECT fi.*, cr.code AS criterion_code, cr.title AS criterion_title
                       FROM feedback_items fi JOIN criteria cr ON cr.id = fi.criterion_id
                       WHERE fi.feedback_id = ? ORDER BY cr.position""", (fid,)):
                it = dict(r)
                it["evidence"] = [dict(e) for e in c.execute(
                    """SELECT e.* FROM evidence e JOIN feedback_item_evidence x ON x.evidence_id = e.id
                       WHERE x.feedback_item_id = ? ORDER BY e.start_offset""", (it["id"],))]
                if it["rating"] == "not_evident":
                    it["support"] = "gap"
                elif it["evidence"]:
                    it["support"] = "evidenced"
                else:
                    it["support"] = "unverified"
                items.append(it)
            fb["items"] = items
            sub = c.execute("SELECT challenge_id FROM submissions WHERE id = ?", (fb["submission_id"],)).fetchone()
            addressed = {i["criterion_id"] for i in items}
            fb["not_assessed"] = [
                {"code": r["code"], "title": r["title"]} for r in c.execute(
                    "SELECT id, code, title FROM criteria WHERE challenge_id = ? ORDER BY position",
                    (sub["challenge_id"],)) if r["id"] not in addressed]
        fb["assurance_note"] = ASSURANCE_NOTE
        return fb

    # ---------------------------------------------------------- AI evaluation
    def start_evaluation(self, submission_id: Any, evaluator: str) -> dict:
        """Claim the submission for one AI evaluation run.

        Returns the new run with ``created=True``, or the run already in progress or
        already successful with ``created=False``. Never creates a duplicate.
        """
        sub = self.get_submission(submission_id)
        try:
            with self._conn() as c:
                cur = c.execute(
                    "INSERT INTO evaluations (submission_id, status, evaluator, started_at) VALUES (?,?,?,?)",
                    (sub["id"], "evaluating", evaluator, _now()))
                eid = cur.lastrowid
        except sqlite3.IntegrityError:
            return {**self.latest_evaluation(sub["id"]), "created": False}
        return {**self.get_evaluation(eid), "created": True}

    def finish_evaluation(self, evaluation_id: int, feedback_id: int) -> dict:
        with self._conn() as c:
            c.execute("UPDATE evaluations SET status='evaluated', feedback_id=?, finished_at=? "
                      "WHERE id=? AND status='evaluating'", (feedback_id, _now(), evaluation_id))
        return self.get_evaluation(evaluation_id)

    def fail_evaluation(self, evaluation_id: int, error: str) -> dict:
        with self._conn() as c:
            c.execute("UPDATE evaluations SET status='failed', error=?, finished_at=? "
                      "WHERE id=? AND status='evaluating'", ((error or "Unknown error").strip(), _now(),
                                                              evaluation_id))
        return self.get_evaluation(evaluation_id)

    def fail_interrupted_evaluations(self) -> int:
        """Mark runs left 'evaluating' by a stopped server as failed, so none hang forever."""
        with self._conn() as c:
            cur = c.execute("UPDATE evaluations SET status='failed', finished_at=?, "
                            "error='Interrupted: the server stopped before the evaluation finished.' "
                            "WHERE status='evaluating'", (_now(),))
            return cur.rowcount

    def get_evaluation(self, evaluation_id: int) -> dict:
        with self._conn() as c:
            ev = _row(c.execute("SELECT * FROM evaluations WHERE id = ?", (evaluation_id,)).fetchone())
        if not ev:
            raise _not_found("Evaluation", evaluation_id)
        return ev

    def latest_evaluation(self, submission_id: int) -> dict | None:
        with self._conn() as c:
            return _row(c.execute("SELECT * FROM evaluations WHERE submission_id = ? ORDER BY id DESC LIMIT 1",
                                  (submission_id,)).fetchone())

    def export_feedback(self, feedback_id: Any) -> dict:
        """A self-contained record of one feedback, for carrying into the next intent."""
        fb = self.get_feedback(feedback_id)
        sub = self.get_submission(fb["submission_id"])
        ch, goal = sub["challenge"], self.get_goal(sub["goal_id"])
        crit = {c["code"]: c for c in ch["criteria"]}
        return {
            "goal": {"id": goal["id"], "title": goal["title"], "domain": goal["domain"]},
            "challenge": {"id": ch["id"], "title": ch["title"]},
            "submission": {"id": sub["id"], "created_at": sub["created_at"]},
            "feedback": {"id": fb["id"], "provider_kind": fb["provider_kind"], "provider_name": fb["provider_name"],
                         "channel": fb["channel"], "created_at": fb["created_at"]},
            "summary": fb["summary"],
            "next_step": fb["next_step"],
            "unverified_claims": fb["unverified_claims"],
            "items": [{
                "criterion": it["criterion_code"], "title": it["criterion_title"],
                "description": crit[it["criterion_code"]]["description"],
                "rating": it["rating"], "support": it["support"],
                "observation": it["observation"], "judgment": it["judgment"], "gaps": it["gaps"],
                "recommendation": it["recommendation"],
                "evidence_quotes": [e["excerpt"] for e in it["evidence"]],
            } for it in fb["items"]],
            "not_assessed": [na["code"] for na in fb["not_assessed"]],
            "assurance_note": fb["assurance_note"],
        }

    # -------------------------------------------------- context & next step
    def recommend_next(self, goal_id: Any) -> dict:
        """Transparent, rule-based next step. It summarises the records; it does not teach.

        The evaluator's own `next_step` text is passed through with attribution; the
        learning intelligence (new challenges, explanations) comes from the human or
        a connected assistant.
        """
        goal = self.get_goal(goal_id)
        challenges = self.list_challenges(goal["id"])
        if not challenges:
            return {"action": "create_challenge", "goal_id": goal["id"],
                    "message": "No challenge yet. Create one (or ask your assistant to via create_challenge).",
                    "basis": "No challenges recorded for this goal."}
        for ch in reversed(challenges):
            subs = self.list_submissions(ch["id"])
            if not subs:
                continue
            latest = subs[-1]
            if not latest["feedback"]:
                return {"action": "get_feedback", "challenge_id": ch["id"], "submission_id": latest["id"],
                        "message": f"Submission #{latest['id']} for “{ch['title']}” has no feedback yet. "
                                   "Get criterion-by-criterion feedback (browser form, or an assistant via MCP).",
                        "basis": "Latest submission has no feedback record."}
            fb = latest["feedback"][-1]
            focus = [{"code": i["criterion_code"], "title": i["criterion_title"],
                      "reason": {"gap": "not evident in submission", "unverified": "rated positively without cited evidence"}
                      .get(i["support"]) or "partially demonstrated"}
                     for i in fb["items"] if i["support"] in ("gap", "unverified") or i["rating"] == "partial"]
            focus += [{"code": x["code"], "title": x["title"], "reason": "not assessed"} for x in fb["not_assessed"]]
            if focus:
                codes = ", ".join(f["code"] for f in focus)
                return {"action": "revise_and_resubmit", "challenge_id": ch["id"], "submission_id": latest["id"],
                        "focus_criteria": focus,
                        "evaluator_next_step": fb["next_step"], "evaluator": fb["provider_name"],
                        "message": f"Revise “{ch['title']}” and resubmit, focusing on {codes}.",
                        "basis": f"Feedback #{fb['id']} by {fb['provider_name']} on submission #{latest['id']}."}
            return {"action": "next_challenge", "challenge_id": ch["id"], "submission_id": latest["id"],
                    "evaluator_next_step": fb["next_step"], "evaluator": fb["provider_name"],
                    "message": "Every criterion is demonstrated with cited evidence. Take on a harder follow-up "
                               "challenge (an assistant can create one with create_challenge).",
                    "basis": f"Feedback #{fb['id']} by {fb['provider_name']} on submission #{latest['id']}."}
        ch = challenges[0]
        return {"action": "start_challenge", "challenge_id": ch["id"],
                "message": f"Start “{ch['title']}”.", "basis": "No submissions yet."}

    def goal_context(self, goal_id: Any, history_limit: int = 25) -> dict:
        goal = self.get_goal(goal_id)
        challenges = []
        for ch in self.list_challenges(goal["id"]):
            subs = self.list_submissions(ch["id"])
            challenges.append({**ch, "submissions": subs})
        with self._conn() as c:
            history = [dict(r) for r in c.execute(
                "SELECT * FROM activity WHERE goal_id = ? ORDER BY id DESC LIMIT ?", (goal["id"], history_limit))]
        return {"goal": goal, "challenges": challenges, "history": history,
                "recommendation": self.recommend_next(goal["id"])}

    # ---------------------------------------------------------------- history
    @staticmethod
    def _log(c, goal_id: int, kind: str, ref_table: str, ref_id: int, note: str, channel: str) -> None:
        c.execute(
            "INSERT INTO activity (goal_id, kind, ref_table, ref_id, note, channel, created_at) VALUES (?,?,?,?,?,?,?)",
            (goal_id, kind, ref_table, ref_id, note, channel, _now()))
