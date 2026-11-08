"""SQLite persistence. One file, stdlib only.

Every connection enables foreign keys and WAL so the web app and the MCP
server can share the same database file at the same time.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(os.environ.get("MASTERY_LAB_DB", "data/mastery_lab.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id          INTEGER PRIMARY KEY,
    slug        TEXT UNIQUE,
    title       TEXT NOT NULL,
    domain      TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS challenges (
    id          INTEGER PRIMARY KEY,
    goal_id     INTEGER NOT NULL REFERENCES goals(id),
    slug        TEXT UNIQUE,
    title       TEXT NOT NULL,
    scenario    TEXT NOT NULL,
    deliverable TEXT NOT NULL,
    created_by  TEXT NOT NULL,           -- 'seed', 'human', or 'assistant:<name>'
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS criteria (
    id              INTEGER PRIMARY KEY,
    challenge_id    INTEGER NOT NULL REFERENCES challenges(id),
    code            TEXT NOT NULL,       -- 'C1', 'C2', ... unique per challenge
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    strong_evidence TEXT NOT NULL DEFAULT '',
    position        INTEGER NOT NULL,
    UNIQUE (challenge_id, code)
);

CREATE TABLE IF NOT EXISTS submissions (
    id           INTEGER PRIMARY KEY,
    challenge_id INTEGER NOT NULL REFERENCES challenges(id),
    goal_id      INTEGER NOT NULL REFERENCES goals(id),
    content      TEXT NOT NULL,
    source       TEXT NOT NULL,          -- 'web' or 'mcp'
    created_at   TEXT NOT NULL
);

-- An evidence reference is an exact excerpt of one submission.
CREATE TABLE IF NOT EXISTS evidence (
    id            INTEGER PRIMARY KEY,
    submission_id INTEGER NOT NULL REFERENCES submissions(id),
    excerpt       TEXT NOT NULL,
    start_offset  INTEGER NOT NULL,
    end_offset    INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id                 INTEGER PRIMARY KEY,
    submission_id      INTEGER NOT NULL REFERENCES submissions(id),
    provider_kind      TEXT NOT NULL,    -- 'human' or 'ai_assistant'
    provider_name      TEXT NOT NULL,
    channel            TEXT NOT NULL,    -- 'web-form', 'web-json', 'mcp'
    summary            TEXT NOT NULL DEFAULT '',
    unverified_claims  TEXT NOT NULL DEFAULT '[]',  -- JSON list of strings
    next_step          TEXT NOT NULL DEFAULT '',
    created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback_items (
    id           INTEGER PRIMARY KEY,
    feedback_id  INTEGER NOT NULL REFERENCES feedback(id),
    criterion_id INTEGER NOT NULL REFERENCES criteria(id),
    rating       TEXT NOT NULL CHECK (rating IN ('demonstrated','partial','not_evident')),
    observation  TEXT NOT NULL DEFAULT '',  -- what is literally in the submission
    judgment     TEXT NOT NULL DEFAULT '',  -- the evaluator's inference
    gaps         TEXT NOT NULL DEFAULT '',
    UNIQUE (feedback_id, criterion_id)
);

CREATE TABLE IF NOT EXISTS feedback_item_evidence (
    feedback_item_id INTEGER NOT NULL REFERENCES feedback_items(id),
    evidence_id      INTEGER NOT NULL REFERENCES evidence(id),
    PRIMARY KEY (feedback_item_id, evidence_id)
);

-- Session history: every meaningful learner action, used to resume.
CREATE TABLE IF NOT EXISTS activity (
    id         INTEGER PRIMARY KEY,
    goal_id    INTEGER NOT NULL REFERENCES goals(id),
    kind       TEXT NOT NULL,
    ref_table  TEXT NOT NULL,
    ref_id     INTEGER NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    channel    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(path: Path | str) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
