# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Rules
Read intent/current-feature.md first, including any deltas appended to it.
Run hooks/pre-implement.sh before implementing.
Build the smallest useful delta, then let the human observe it and decide: continue or stop.
Always write tests.
Respect architecture.

## What this repo is

Two things share this repo:

1. **Mastery Lab** (`mastery_lab/`): a local-first Python POC for a learning loop: goal → challenge → learner submission → evidence-linked, criterion-by-criterion feedback → resume later. It has no API keys, auth, cloud, or model calls. The "intelligence" comes from a human or a connected MCP assistant.
2. **The intent-drive-starter scaffold** it was built from (`intent/`, `hooks/`, `skills/`, `agents/`, `templates/`, `context/`, `.claude-plugin/`). This is the Progressive Intent workflow: Intent → Build → Observe → Refine → Continue or Stop. Deltas (Observation, Keep, Change, New Boundary, Evidence) are **appended** to `intent/current-feature.md`. The original intent is never rewritten. The full spec is in `intent/INTENT-001-mastery-lab.md`, and success criteria SC-01..SC-08 are mapped to evidence in `docs/EVIDENCE.md`.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python -m mastery_lab web [--port 8765] [--db PATH]   # browser UI on 127.0.0.1
python -m mastery_lab mcp [--db PATH]                 # MCP server over stdio
python -m mastery_lab seed [--db PATH]                # create DB + seed only

pytest -q                                             # full suite
pytest tests/test_service.py::test_name -q            # single test
bash tests/pre-implement.test.sh                      # intent-gate script tests
bash hooks/pre-implement.sh [intent-file]             # check intent is sufficient (Outcome + Success/Evidence)

python scripts/mcp_roundtrip.py                       # real stdio MCP round trip (evidence transcript)
python scripts/ui_walkthrough.py                      # Playwright screenshots; needs playwright + Chromium
```

The DB defaults to `data/mastery_lab.db`. Override it with `--db` or `MASTERY_LAB_DB`. CI (`.github/workflows/ci.yml`, Python 3.12) runs `pytest -q` and `tests/pre-implement.test.sh`. There is no linter configured.

## Architecture

One domain layer, two thin adapters, one SQLite file (WAL mode, so web and MCP can share a DB at the same time):

```
Browser ──HTTP──> web.py ───────────┐
                                    ├──> service.py (MasteryLab) ──> SQLite
MCP client ──stdio──> mcp_server.py ┘
```

- **`service.py` owns every rule**: validation, evidence verification, atomic feedback writes, provenance, the activity log, and the next-step recommendation. `web.py` (FastAPI + Jinja, server-rendered forms with no JS framework) and `mcp_server.py` (MCP SDK v2 `MCPServer`, built with `build_server(lab)`) only translate I/O. New rules go in the service so that the browser form, pasted-JSON, and MCP channels stay consistent.
- Errors are raised as `LabError(code='not_found'|'invalid')`. Adapters map them to an HTTP 404/400 error page or to an MCP tool error.
- Schema lives in `db.py`. `seed.py` is idempotent and runs automatically on first open.
- Context docs: `context/architecture.md`, `business-rules.md`, `security.md`, `glossary.md`.

### Invariants that must not regress
- Evidence must be a verbatim excerpt (≥ 8 chars, whitespace-tolerant) of *that* submission, or an evidence id belonging to it. One bad reference rejects the whole feedback record, so nothing is half-saved.
- Feedback items keep `observation`, `judgment`, and `gaps` separate. A positive rating with no evidence displays as **Unverified judgment**, and criteria nobody addressed display as **Not assessed**.
- Every feedback record stores the provider (kind + name) and the channel (`web-form`, `web-json`, `mcp`).
- There is no numeric mastery score. A submission's goal is derived from its challenge, and feedback criteria must belong to the submission's challenge.
- The web server binds to loopback by default and warns on any other host. The app has no auth and is not production-ready.

## Tests

`tests/conftest.py` provides `lab` (a fresh `MasteryLab` on a tmp DB), `seed_ids`, `good_items()`, and `SAMPLE` (from `docs/demo/sample-submission.md`). Evidence quotes in fixtures must stay verbatim substrings of that sample file. `test_web.py` uses the FastAPI TestClient. `test_mcp.py` runs the MCP server as a real stdio subprocess.

## Hook note

`hooks/hooks.json` registers a PreToolUse hook (`pre-implement-hook.sh`) that blocks non-Markdown edits when `intent/current-feature.md` is insufficient. It **skips itself in this repo** because `.claude-plugin/plugin.json` is named `intent-drive-starter`, so run `hooks/pre-implement.sh` manually as the rules above require.
