# Architecture

One domain layer, two thin adapters, one SQLite file.

```
Browser ──HTTP(127.0.0.1)──> web.py ─┐
                                     ├──> service.py (MasteryLab) ──> SQLite (WAL)
MCP client ──stdio──> mcp_server.py ─┘
```

- `service.py` owns every rule: validation, evidence verification, atomic feedback writes,
  provenance, activity log, next-step recommendation. Adapters only translate I/O.
- Errors: `LabError(code='not_found'|'invalid')` → HTTP 404/400 page with message, or MCP tool error.
- Evidence = exact excerpt of one submission (offsets stored). Feedback items link to evidence
  through `feedback_item_evidence`.
- No background jobs, agents, queues, or model calls. The intelligence comes from the human or the connected assistant.

Decisions and tradeoffs:
- Server-rendered forms (no JS framework) to keep the vertical slice small.
- stdio MCP transport only. Streamable HTTP was deferred because it would need its own auth story.
- Recommendation is rule-based and shows its basis, rather than a hidden heuristic or score.
