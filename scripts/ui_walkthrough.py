"""Drive the running browser UI with Playwright and capture screenshots.

    python scripts/ui_walkthrough.py phase1 --base http://127.0.0.1:8765 --out docs/evidence
    (restart the server)
    python scripts/ui_walkthrough.py phase2 --base http://127.0.0.1:8765 --out docs/evidence

Optional evidence tooling; requires `pip install playwright` and a Chrome/Chromium.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (ROOT / "docs/demo/sample-submission.md").read_text()


def launch(p):
    for kw in ({"channel": "chrome"}, {"executable_path": "/usr/bin/google-chrome"}, {}):
        try:
            return p.chromium.launch(**kw)
        except Exception:
            continue
    raise SystemExit("No Chromium/Chrome available for Playwright.")


def phase1(page, base, out):
    page.goto(base)
    page.screenshot(path=out / "01-home.png", full_page=True)
    page.click("ul.cards a >> nth=0")          # the goal
    page.click("ul.cards a >> nth=0")          # its first challenge
    page.screenshot(path=out / "02-challenge.png", full_page=True)
    # SC-07: empty submission
    page.click("text=Save submission")
    page.screenshot(path=out / "03-empty-submission-rejected.png")
    page.fill("textarea[name=content]", SAMPLE)
    page.click("text=Save submission")
    page.wait_for_url("**/submissions/*")
    sub_url = page.url
    # Manual criterion-level feedback, with one invented quote first (must be rejected)
    page.click("text=Criterion-by-criterion feedback form")
    page.fill("input[name=provider_name]", "Mark (self-review)")
    page.select_option("select[name=rating_C5]", "demonstrated")
    page.fill("textarea[name=quotes_C5]", "We run quarterly disaster-recovery drills")
    page.click("text=Save feedback")
    page.screenshot(path=out / "04-invented-evidence-rejected.png")
    page.select_option("select[name=rating_C5]", "partial")
    page.fill("textarea[name=quotes_C5]", "actions fail closed and remain as pending proposals")
    page.fill("textarea[name=observation_C5]", "Covers empty retrieval, dependency outage, injection.")
    page.fill("textarea[name=gaps_C5]", "No handling of conflicting document versions or low model confidence.")
    page.select_option("select[name=rating_C1]", "demonstrated")
    page.fill("textarea[name=quotes_C1]", "The model never holds credentials and cannot call source systems directly")
    page.fill("textarea[name=judgment_C1]", "Clear trust boundary.")
    page.select_option("select[name=rating_C4]", "partial")
    page.fill("textarea[name=judgment_C4]", "Probably adequate, but I did not quote anything.")
    page.select_option("select[name=rating_C6]", "not_evident")
    page.fill("textarea[name=gaps_C6]", "Only 'we would test it'.")
    page.fill("textarea[name=unverified_claims]", "Claims full 21 CFR Part 11 compliance\nClaims all prompt injection is blocked")
    page.fill("textarea[name=summary]", "Good boundaries; validation section is a gap.")
    page.fill("input[name=next_step]", "Rewrite section 6 with named tests for each claim.")
    page.click("text=Save feedback")
    page.wait_for_load_state()
    page.locator("#feedback").scroll_into_view_if_needed()
    page.screenshot(path=out / "05-feedback-recorded.png", full_page=True)
    print("submission:", sub_url)


def phase2(page, base, out):
    page.goto(base)
    page.screenshot(path=out / "06-after-restart-home.png", full_page=True)
    page.click("text=Goal overview")
    page.screenshot(path=out / "07-after-restart-goal-history.png", full_page=True)


def phase3(page, base, out, sub_id):
    page.goto(f"{base}/submissions/{sub_id}#feedback")
    page.screenshot(path=out / "08-mcp-feedback-in-browser.png", full_page=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["phase1", "phase2", "phase3"])
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--out", type=Path, default=ROOT / "docs/evidence")
    ap.add_argument("--submission", type=int, default=2)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = launch(p)
        page = b.new_page(viewport={"width": 1280, "height": 900})
        if a.phase == "phase1":
            phase1(page, a.base, a.out)
        elif a.phase == "phase2":
            phase2(page, a.base, a.out)
        else:
            phase3(page, a.base, a.out, a.submission)
        b.close()
