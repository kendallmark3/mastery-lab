"""SC-06: the MCP surface uses the same records as the browser.

The stdio test launches `python -m mastery_lab mcp` as a real subprocess and talks
to it with the MCP SDK client — the same transport a desktop AI client uses.
"""

import sys

import anyio
from fastapi.testclient import TestClient
from mcp import Client, StdioServerParameters

from conftest import SAMPLE, ROOT
from mastery_lab.mcp_server import build_server
from mastery_lab.service import MasteryLab
from mastery_lab.web import create_app

EXPECTED_TOOLS = {"get_learner_context", "create_goal", "get_challenge", "create_challenge",
                  "record_submission", "get_submission", "record_feedback", "recommend_next_practice"}


def stdio_params(db_path):
    return StdioServerParameters(command=sys.executable, args=["-m", "mastery_lab", "mcp", "--db", str(db_path)],
                                 cwd=str(ROOT))


def test_stdio_round_trip_shares_records_with_browser(db_path):
    async def run():
        async with Client(stdio_params(db_path)) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert EXPECTED_TOOLS <= names
            ctx = (await c.call_tool("get_learner_context", {})).structured_content
            goal_id = ctx["goals"][0]["id"]
            full = (await c.call_tool("get_learner_context", {"goal_id": goal_id})).structured_content
            ch_id = full["challenges"][0]["id"]
            ch = (await c.call_tool("get_challenge", {"challenge_id": ch_id})).structured_content
            assert len(ch["criteria"]) == 6
            sub = (await c.call_tool("record_submission", {"challenge_id": ch_id, "content": SAMPLE})).structured_content
            fb = await c.call_tool("record_feedback", {
                "submission_id": sub["submission_id"], "evaluator_name": "test-harness",
                "summary": "Boundaries strong; validation weak.", "next_step": "Write validation plan.",
                "unverified_claims": ["Fully compliant with 21 CFR Part 11"],
                "items": [{"criterion": "C1", "rating": "demonstrated",
                           "evidence_quotes": ["The model never holds credentials"]},
                          {"criterion": "C6", "rating": "not_evident", "gaps": "no tests named"}]})
            assert not fb.is_error
            rec = (await c.call_tool("recommend_next_practice", {"goal_id": goal_id})).structured_content
            assert rec["action"] == "revise_and_resubmit"
            return sub["submission_id"]

    sid = anyio.run(run)
    # Same record visible in the browser UI (separate process view of the same DB).
    page = TestClient(create_app(MasteryLab(db_path))).get(f"/submissions/{sid}").text
    assert "AI assistant: test-harness" in page and "via mcp" in page
    assert "<mark>The model never holds credentials</mark>" in page


def test_mcp_rejections_are_tool_errors(db_path):
    lab = MasteryLab(db_path)
    sub = lab.submit(1, SAMPLE, channel="web")  # created via the browser path

    async def run():
        async with Client(build_server(lab)) as c:
            r = await c.call_tool("record_submission", {"challenge_id": 1, "content": "  "})
            assert r.is_error and "empty" in r.content[0].text
            r = await c.call_tool("record_submission", {"challenge_id": 404, "content": "answer"})
            assert r.is_error and "not_found" in r.content[0].text
            r = await c.call_tool("record_feedback", {
                "submission_id": sub["id"], "evaluator_name": "x",
                "items": [{"criterion": "C5", "rating": "demonstrated",
                           "evidence_quotes": ["we tested this in production for a year"]}]})
            assert r.is_error and "excerpt" in r.content[0].text
            r = await c.call_tool("get_submission", {"submission_id": sub["id"]})
            assert r.structured_content["feedback"] == []  # nothing partially saved

    anyio.run(run)


def test_assistant_can_create_follow_up_challenge(db_path):
    lab = MasteryLab(db_path)

    async def run():
        async with Client(build_server(lab)) as c:
            r = await c.call_tool("create_challenge", {
                "goal_id": 1, "title": "Rollback for quality holds", "scenario": "A hold was placed in error.",
                "deliverable": "Describe reversal and audit.", "author": "claude",
                "criteria": [{"title": "Reversal", "description": "Explains safe reversal."}]})
            assert not r.is_error
            return r.structured_content["id"]

    cid = anyio.run(run)
    assert lab.get_challenge(cid)["created_by"] == "assistant:claude"
