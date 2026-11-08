# INTENT-001 — Validation Evidence

Run on 2026-11-07, Linux, Python 3.13, `mcp` 2.3.0, FastAPI 0.162. Every item below comes from
an actual run. Raw logs are in `docs/evidence/`.

## Success criteria

| SC | Result | Evidence |
| --- | --- | --- |
| SC-01 Start | ✅ | `01-home.png` — seed goal listed, "Open challenge". `test_seed_goal_and_substantial_challenge` |
| SC-02 Practice | ✅ | `02-challenge.png` — scenario (≈1.8k chars), deliverable, criteria C1–C6 visible. Not multiple choice |
| SC-03 Submit | ✅ | Submission #1 saved via browser, linked to goal 1 / challenge 1. `test_full_loop_and_persistence_across_restart` asserts linkage |
| SC-04 Evaluate | ✅ | `05-feedback-recorded.png` — per-criterion rating, highlighted verbatim evidence with char offsets, observation vs judgment, *Unverified judgment* (C4), *Gap* (C6), *Not assessed* (C2, C3), unverified-claims box, provenance "Human: Mark (self-review) · via web-form" |
| SC-05 Persist | ✅ | `demo-run.log`: server killed (`GET / → 000`), restarted. `06-after-restart-home.png` "Continue where you left off → Open submission #1". `07-after-restart-goal-history.png` session history |
| SC-06 Reuse | ✅ | `mcp-roundtrip-transcript.txt` — real stdio subprocess, protocol 2026-07-28, 8 tools. Its submission #2 appears in the browser tagged *via mcp* (`08-mcp-feedback-in-browser.png`). `test_stdio_round_trip_shares_records_with_browser` |
| SC-07 Trust | ✅ | Empty submission (`03-…png`, MCP transcript), nonexistent challenge 9999 (MCP transcript, 404 in web), invented evidence quote (`04-…png`, MCP transcript), evidence id from another submission, criterion from another challenge. All rejected with nothing saved (row counts asserted) |
| SC-08 Reproduce | ✅ | `fresh-checkout.log` — clone → venv → `pip install -e ".[dev]"` → 32 passed → starter tests pass → web 200 → MCP round-trip |

## Commands run

```bash
python -m pytest -q                         # 32 passed
bash tests/pre-implement.test.sh            # all tests passed
python -m mastery_lab web --db /tmp/demo/lab.db &
python scripts/ui_walkthrough.py phase1     # browser loop + screenshots 01–05
kill <pid>; python -m mastery_lab web --db /tmp/demo/lab.db &   # restart
python scripts/ui_walkthrough.py phase2     # screenshots 06–07
python scripts/mcp_roundtrip.py --db /tmp/demo/lab.db  # while web server runs on same DB
python scripts/ui_walkthrough.py phase3     # screenshot 08
```

## MCP round-trip (excerpt; full transcript in `docs/evidence/mcp-roundtrip-transcript.txt`)

```
Connected over stdio to: mastery-lab 0.1.0 (protocol 2026-07-28)
Tools: get_learner_context, create_goal, get_challenge, create_challenge, record_submission,
       get_submission, record_feedback, recommend_next_practice
→ record_submission {challenge_id: 1, content: "   "}
← ERROR [invalid] Submission is empty. Write your solution before submitting.
→ record_submission {challenge_id: 9999, ...}
← ERROR [not_found] Challenge 9999 does not exist.
→ record_feedback {... evidence_quotes: ["We run quarterly disaster-recovery drills"]}
← ERROR [invalid] Feedback item for C5 cites evidence '...', which is not an excerpt (≥8 chars) of submission 2.
→ record_feedback {C1 demonstrated + quote, C2 demonstrated + 2 quotes, C3 partial + 2 quotes, C6 not_evident}
← result {items with evidence ids and offsets, not_assessed: [C4, C5], unverified_claims: [...]}
→ recommend_next_practice {goal_id: 1}
← result {action: revise_and_resubmit, focus_criteria: [C3, C6, C4, C5], evaluator_next_step: ...}
```

The harness that recorded feedback is a script, not an LLM. It is labelled that way in the stored provenance.

## Known failures and issues found during the build

- The starter's `tests/pre-implement.test.sh` asserted that `intent/current-feature.md` stays blank.
  Writing a real intent broke that assertion. Fixed by testing the gate against a blank fixture
  and adding a check that this project's intent passes.
- First Playwright run clicked heading text instead of the goal link. Fixed the selectors and
  re-ran from a clean DB.
- **Not tested:** any end-user MCP client (Claude Desktop/Code, ChatGPT). Only the MCP SDK's own client over stdio.
- **Not tested:** Windows/macOS. Linux only.

## Smallest evidence-driven recommendation for INTENT-002

**Connect a real assistant and close the revise-and-resubmit loop.** Register the MCP server in
Claude Desktop or Claude Code, then have Claude evaluate a real submission with `record_feedback`.
Add one feature: a **comparison view between two submissions** of the same challenge, showing
criterion ratings and evidence side by side.

Why this is next: this POC proves the records and trust rules. It does not yet show *improvement*,
which is the north-star claim. The recommender already sends the learner to "revise and resubmit".
Showing v1 against v2 per criterion is the smallest addition that makes demonstrable improvement
visible. A real-client test is the one SC-06 gap that remains untested.
