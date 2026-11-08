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
