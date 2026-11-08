"""Real MCP round-trip over stdio, printing a transcript.

Launches `python -m mastery_lab mcp --db <db>` as a subprocess (exactly how a desktop
MCP client would) and drives the learning loop through it with the MCP SDK client.

    python scripts/mcp_roundtrip.py [--db data/mastery_lab.db] [--submission-file FILE]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


def show(direction: str, name: str, payload) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    if len(text) > 1800:
        text = text[:1800] + "\n  … (truncated for transcript)"
    print(f"\n{direction} {name}\n{text}")


async def call(c: Client, name: str, args: dict):
    show("→ call_tool", name, args)
    r = await c.call_tool(name, args)
    if r.is_error:
        show("← ERROR", name, r.content[0].text)
    else:
        show("← result", name, r.structured_content)
    return r


async def main(db: str, submission_file: Path) -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "mastery_lab", "mcp", "--db", db],
                                   cwd=str(ROOT))
    async with Client(params) as c:
        print(f"Connected over stdio to: {c.server_info.name} {c.server_info.version} "
              f"(protocol {c.protocol_version})")
        tools = await c.list_tools()
        print("Tools:", ", ".join(t.name for t in tools.tools))

        ctx = (await call(c, "get_learner_context", {})).structured_content
        goal_id = ctx["goals"][0]["id"]
        full = (await call(c, "get_learner_context", {"goal_id": goal_id})).structured_content
        ch_id = full["challenges"][0]["id"]
        await call(c, "get_challenge", {"challenge_id": ch_id})

        content = submission_file.read_text()
        sub = (await call(c, "record_submission", {"challenge_id": ch_id, "content": content})).structured_content
        sid = sub["submission_id"]

        print("\n--- Trust checks (each must be rejected) ---")
        await call(c, "record_submission", {"challenge_id": ch_id, "content": "   "})
        await call(c, "record_submission", {"challenge_id": 9999, "content": "an answer"})
        await call(c, "record_feedback", {
            "submission_id": sid, "evaluator_name": "mcp_roundtrip.py",
            "items": [{"criterion": "C5", "rating": "demonstrated",
                       "evidence_quotes": ["We run quarterly disaster-recovery drills"]}]})

        print("\n--- Evidence-linked feedback (as a connected assistant would record it) ---")
        await call(c, "record_feedback", {
            "submission_id": sid,
            "evaluator_name": "mcp_roundtrip.py (scripted harness, not an LLM)",
            "evaluator_kind": "ai_assistant",
            "summary": "Strong boundaries and retrieval enforcement; validation section does not support its claims.",
            "next_step": "Replace section 6 with named tests tied to each claim in sections 1–5.",
            "unverified_claims": ["'fully compliant with 21 CFR Part 11' — no controls mapped",
                                  "'proven to block all prompt injection attacks' — no test evidence"],
            "items": [
                {"criterion": "C1", "rating": "demonstrated",
                 "observation": "Names seven components; states the model holds no credentials.",
                 "judgment": "Trust boundary around the model is explicit.",
                 "evidence_quotes": ["The model never holds credentials and cannot call source systems directly"]},
                {"criterion": "C2", "rating": "demonstrated",
                 "observation": "On-behalf-of token exchange; ACL + classification filter at query time.",
                 "evidence_quotes": ["token exchange (on-behalf-of)",
                                     "filtered by the document ACL and classification at query time"]},
                {"criterion": "C3", "rating": "partial",
                 "observation": "Catalog, approver role, separation of duties, idempotency keys.",
                 "gaps": "No reversal path for an erroneous quality hold.",
                 "evidence_quotes": ["the approver cannot be the requester", "idempotency key"]},
                {"criterion": "C6", "rating": "not_evident",
                 "observation": "Section 6 says only that it would be tested.",
                 "gaps": "No named tests; makes compliance and injection-proof claims."}]})

        await call(c, "recommend_next_practice", {"goal_id": goal_id})
        print(f"\nDone. Submission #{sid} is now visible in the browser at /submissions/{sid}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data/mastery_lab.db"))
    ap.add_argument("--submission-file", type=Path, default=ROOT / "docs/demo/sample-submission.md")
    a = ap.parse_args()
    anyio.run(main, a.db, a.submission_file)
