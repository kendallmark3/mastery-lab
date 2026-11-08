# Current Feature — INTENT-001: Mastery Lab first complete learning loop
<!-- Full specification: intent/INTENT-001-mastery-lab.md. This file is the working summary. -->

## Outcome
One local learner can complete a full learning cycle on Enterprise AI Architecture:
set goal → receive a practical challenge → submit a written answer → receive
evidence-grounded, criterion-by-criterion feedback → save progress → resume later.
The same records and operations are reachable from a local browser UI and an MCP server.

## Inputs
- INTENT-001 specification (intent/INTENT-001-mastery-lab.md)
- Seed scenario: governed enterprise AI assistant (retrieval + approved actions)

## Outputs
- Local web app (loopback only), SQLite store, MCP server (stdio), seed challenge,
  honest feedback mechanism (human form, pasted assistant JSON, or MCP), tests, README.

## Success / Evidence
SC-01..SC-08 from the full spec. Evidence: commands run, pytest output, UI screenshots,
a real stdio MCP round-trip transcript, and known failures — recorded in docs/EVIDENCE.md.

## Constraints / Boundaries
Local-first; no API keys, paid services, cloud, auth, or multi-user. Not production-ready.
No numeric mastery score. Feedback provenance and evidence linkage are mandatory.

## Plan (mapped to success criteria)
| Step | Delivers | SC |
| --- | --- | --- |
| `mastery_lab/service.py` — one domain layer over SQLite; all validation lives here | records, trust rules | 02, 03, 04, 05, 07 |
| `mastery_lab/seed.py` — idempotent seed goal + challenge with 6 explicit criteria | concrete scenario | 01, 02 |
| `mastery_lab/web.py` — FastAPI + Jinja forms, binds 127.0.0.1 | browser loop | 01–05 |
| `mastery_lab/mcp_server.py` — MCP tools calling the same service | assistant reuse | 06 |
| `tests/` — loop, persistence across restart, invalid inputs, evidence linkage, MCP stdio round-trip | proof | 05–08 |

---

# Delta 1 — INTENT-002: Close the mastery loop
<!-- Source: intent/intentr1.md (sections A–C; the file ends mid-sentence in C). Appended 2026-11-07. -->

## Observation
Submission #1 exists with no feedback. Getting feedback means filling in the form by hand, pasting JSON from an assistant, or connecting an MCP client. The learner gets no AI evaluation without leaving the app.

## Outcome
After submitting, or on any saved submission that has no feedback, the learner gets an AI evaluation against the challenge's own criteria. Each criterion shows a rating, what was demonstrated, verbatim evidence, what is missing or weak, and one concrete recommendation. The learner can then submit an improved attempt.

## Keep
Every INTENT-001 trust rule: verbatim evidence checks, all-or-nothing feedback writes, provenance, Unverified judgment / Not assessed labels, no numeric score. The manual form, pasted-JSON path, MCP tools, styling, and navigation are unchanged.

## Change
- Submitting starts an AI evaluation automatically. The submission page shows its status: Submitted, Evaluating, Evaluated, or Evaluation failed (with the reason and a Retry action).
- Unevaluated submissions show an **Evaluate Submission** action. No re-submission is needed.
- Each feedback item gains a `recommendation` field.
- The evaluator's output goes through the same `record_feedback` validation. A rejected reply is retried once with the rejection reason, then marked failed. It is never silently dropped.

## New Boundary
- The evaluator is the locally installed `claude` CLI (`claude -p`, no tools), using the learner's existing Claude login. The app stores no API key. If `claude` is missing or `--no-ai` is passed, the UI says evaluation is unavailable.
- This replaces INTENT-001's "no model calls" and "nothing leaves your machine" boundaries: when AI evaluation runs, the submission and criteria are sent to Anthropic through the CLI.
- At most one in-progress or successful evaluation per submission, enforced by the database. Refreshing or re-posting never duplicates. Failed attempts are kept as history.

## Success / Evidence
- Opening Submission #1 and clicking Evaluate Submission produces persisted criterion-by-criterion AI feedback with highlighted evidence and recommendations (screenshot + DB row).
- Tests use a fake evaluator for: auto-evaluate on submit, evaluating an existing submission, no duplicate evaluations, invented quotes being retried then failing visibly, CLI unavailable, and an interrupted evaluation being shown as failed after restart.
- The full existing suite still passes.

# Delta 2 — Evaluation JSON as the hand-off
<!-- Appended 2026-11-07 after observing Delta 1 in the browser. -->

## Observation
The "use any AI assistant without a connector" section (copy prompt, paste JSON) is no longer needed now that Evaluate Submission exists. The criterion / rating / observation structure is useful, but as an output to take forward, not as an input.

## Change
- Remove the paste-JSON section and its route.
- At the bottom of each submission page, show every feedback record as JSON (criteria, ratings, observations, judgments, gaps, recommendations, verified evidence quotes, provenance) with a download per record. That file is the input for the next intent.

## Keep
The manual feedback form, MCP tools, and all trust rules.

## Success / Evidence
After an evaluation, the submission page shows its JSON and `/feedback/<id>.json` downloads the same content. Tests cover the export shape and the removed route.
