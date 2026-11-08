# Mastery Lab — POC 0.1

**AI for Humans — Learn. Teach. Master.**

Mastery Lab is the smallest working loop that turns an AI-assisted conversation into
*demonstrated* learning:

**set a goal → get a practical challenge → submit your own answer → get criterion-by-criterion,
evidence-linked feedback → save progress → resume later.**

It is not a chatbot. Your AI assistant (Claude or any MCP-capable client) supplies the
conversation and evaluation; Mastery Lab supplies the persistent records, challenge structure,
evidence checks, and tools that assistants lack. Everything runs locally, needs no API key, and
works fully from the browser even with no assistant connected.

Built from the [intent-drive-starter](docs/intent-drive-starter-README.md) scaffold. The intent is in
[`intent/INTENT-001-mastery-lab.md`](intent/INTENT-001-mastery-lab.md); validation evidence is in
[`docs/EVIDENCE.md`](docs/EVIDENCE.md).

## Prerequisites

- Python 3.11+ (tested on 3.13)
- That's it. No cloud account, model API key, or paid service.

## Start (3 commands)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m mastery_lab web          # → http://127.0.0.1:8765
```

Data lives in `data/mastery_lab.db` (SQLite). Override with `--db PATH` or `MASTERY_LAB_DB`.
The seed goal and challenge are created automatically on first run.

Run the tests:

```bash
pytest -q                     # 32 tests: loop, restart persistence, invalid inputs, evidence linkage, MCP stdio
bash tests/pre-implement.test.sh   # starter's intent-gate tests
```

## Five-minute demo

1. **Start** — `python -m mastery_lab web`, open http://127.0.0.1:8765. The home page shows the
   *Enterprise AI Architecture* goal and the recommended next step. *(SC-01)*
2. **Practice** — click **Open challenge**. Read the Calder Medical Distribution scenario, the
   deliverable, and the six visible criteria C1–C6. *(SC-02)*
3. **Trust check** — click **Save submission** with an empty box: it is rejected and nothing is saved. *(SC-07)*
4. **Submit** — paste your own answer (or `docs/demo/sample-submission.md`) and save. You land on
   submission #1, linked to that goal and challenge. *(SC-03)*
5. **Evaluate** — open **Criterion-by-criterion feedback form**. For C5 choose *Demonstrated* and enter
   a quote that is *not* in your text — e.g. `We run quarterly disaster-recovery drills`. Saving is
   refused. Now enter real quotes for a few criteria, rate one positively with no quote, rate
   one *Not evident*, and list a claim you can't back up. Save. The page shows each criterion with
   highlighted evidence, *Unverified judgment* where no quote was given, *Not assessed* rows, and the
   evaluator's next step. *(SC-04, SC-07)*
6. **Persist** — stop the server (Ctrl-C), start it again, reload. Home says *Continue where you
   left off* and links to the submission; the goal page shows session history. *(SC-05)*
7. **Reuse via MCP** — with the server still running, in a second terminal:
   `python scripts/mcp_roundtrip.py`. It launches the MCP server over stdio, records a second
   submission and evidence-linked feedback, and shows the three rejections. Reload
   `/submissions/2` in the browser to see the record it created, tagged *via mcp*. *(SC-06)*

Evaluation JSON: the bottom of every submission page shows each feedback record as JSON
(criteria, ratings, observations, gaps, recommendations, verified evidence quotes, provenance), with a
**Download JSON** button (`/feedback/<id>.json`). Use it as the input to your next intent.

## Connect an MCP client

The MCP server uses the official Python MCP SDK v2 (`mcp>=2.3`, `MCPServer`) over **stdio**.

**Claude Desktop / Claude Code** (example config; use absolute paths):

```json
{
  "mcpServers": {
    "mastery-lab": {
      "command": "/ABSOLUTE/PATH/mastery-lab/.venv/bin/python",
      "args": ["-m", "mastery_lab", "mcp", "--db", "/ABSOLUTE/PATH/mastery-lab/data/mastery_lab.db"]
    }
  }
}
```

Claude Code alternative: `claude mcp add mastery-lab -- /ABS/PATH/.venv/bin/python -m mastery_lab mcp --db /ABS/PATH/data/mastery_lab.db`

Point the web app and MCP server at the **same `--db` file** to share records (SQLite WAL mode
allows both at once).

| Tool | Purpose |
| --- | --- |
| `get_learner_context(goal_id?)` | Goals, or one goal's challenges, submissions, feedback, history, next step |
| `create_goal` | New learning goal |
| `get_challenge(challenge_id)` | Scenario, deliverable, criteria (logs that it was opened) |
| `create_challenge` | Assistant-authored follow-up challenge with explicit criteria |
| `record_submission(challenge_id, content)` | Save the learner's own answer; goal derived from challenge |
| `get_submission(submission_id)` | Submission + criteria + evidence + feedback, for evaluation |
| `record_feedback(...)` | Criterion items with `observation` / `judgment` / `gaps` / verbatim `evidence_quotes` |
| `recommend_next_practice(goal_id)` | Next step plus the records it is based on |

**Integration status, stated honestly:** the MCP server has been tested end to end with the MCP SDK's
own client over a real stdio subprocess (`scripts/mcp_roundtrip.py`, `tests/test_mcp.py`). It has
**not** been tested inside Claude Desktop, Claude Code, ChatGPT, or any other end-user client.

## How honesty is enforced

All rules live in `mastery_lab/service.py`, so the browser, pasted JSON, and MCP share them:

- **Evidence must be real.** Each evidence reference must be a verbatim excerpt (≥ 8 characters,
  whitespace-tolerant) of *that* submission, or an evidence id belonging to it. One bad reference
  and the whole feedback record is rejected. Nothing is half-saved.
- **Observation vs. judgment.** Each criterion item separates what the text says from what the
  evaluator infers, plus gaps.
- **Unsupported positives are labelled.** *Demonstrated* or *Partial* with no evidence is shown as
  **Unverified judgment**. Unaddressed criteria are shown as **Not assessed**.
- **Provenance.** Every feedback record stores who provided it (human or AI assistant, by name) and
  the channel (`web-form`, `web-json`, `mcp`).
- **Unverified claims.** Evaluators can list claims the learner makes that the text doesn't back up.
- **No score.** There is no numeric mastery score. Every feedback view states that it assesses
  design reasoning, not operational effectiveness.
- **No misattribution.** Submissions take their goal from the challenge, and feedback criteria must
  belong to the submission's challenge.

## Layout

```
mastery_lab/
  service.py      the single learning engine: records, validation, recommendation
  db.py           SQLite schema (goals, challenges, criteria, submissions, evidence,
                  feedback, feedback_items, feedback_item_evidence, activity)
  seed.py         Enterprise AI Architecture goal + governed-assistant challenge
  web.py          FastAPI + Jinja browser UI (loopback only)
  mcp_server.py   MCP tools, thin adapter over service.py
scripts/          mcp_roundtrip.py (stdio transcript), ui_walkthrough.py (Playwright screenshots)
tests/            pytest suite + starter intent-gate test
docs/EVIDENCE.md  commands, results, screenshots, transcript, known issues
```

## Limitations

- **Not production-ready.** Single local user, no authentication, no authorization, no encryption at
  rest, no compliance controls. The web server binds `127.0.0.1` by default and warns if you change it.
- The "next step" is a transparent rule over your records (gaps, unverified items, unassessed
  criteria, plus the evaluator's own suggestion). It does not teach. Teaching comes from you or your assistant.
- Evidence checking proves a quote *is in your text*. It does not prove the quote *supports* the
  rating. That is still the evaluator's judgment, and it is labelled as such.
- Feedback evaluates written reasoning. It cannot show that an architecture works in operation.
- No editing or deleting of records through the UI. Each revision is a new submission.
- Session history is an activity log per goal, not timed study sessions.
- One seed challenge. More come from `create_challenge` (assistant or the goal page form).
