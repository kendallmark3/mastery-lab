"""AI evaluation of a submission against its challenge's criteria.

The evaluator only *proposes* feedback. Everything it returns goes through
``MasteryLab.record_feedback``, so the same trust rules apply as for a human or
an MCP client: quotes must be verbatim, criteria must belong to the challenge,
and nothing is half-saved.

The default backend is the locally installed Claude Code CLI (``claude -p``).
It runs with no tools, outside the repository, and uses the learner's existing
Claude login. The app itself never stores an API key.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Protocol

from .service import LabError, MasteryLab

CHANNEL = "ai-evaluator"
MAX_ATTEMPTS = 2  # first reply, plus one retry that is told why the first was rejected


class EvaluatorError(RuntimeError):
    """The evaluator could not produce a reply at all (not retried)."""


@dataclass
class Reply:
    text: str
    model: str


class Evaluator(Protocol):
    name: str

    def __call__(self, prompt: str) -> Reply: ...


def evaluation_prompt(sub: dict) -> str:
    """The rubric prompt. Also shown on the page for the copy-paste (no connector) path."""
    ch = sub["challenge"]
    crit = "\n".join(
        f"- {c['code']} {c['title']}: {c['description']}"
        + (f"\n    Strong evidence looks like: {c['strong_evidence']}" if c.get("strong_evidence") else "")
        for c in ch["criteria"])
    return f"""You are evaluating a learner's written answer. Be specific and honest.

CHALLENGE: {ch['title']}
SCENARIO:
{ch['scenario']}
DELIVERABLE:
{ch['deliverable']}
CRITERIA:
{crit}

LEARNER SUBMISSION #{sub['id']}:
<<<
{sub['content']}
>>>

Rules:
- Assess every criterion above. For each give a rating: demonstrated | partial | not_evident.
- "observation" = only what the submission literally says. "judgment" = your inference.
- Distinguish a capability the learner merely names or describes from one they demonstrate with
  concrete mechanisms, tradeoffs, and reasoning. Naming terms (orchestration, MCP, RAG, governance,
  audit, ...) is not demonstration.
- Judge architectural reasoning, correctness, tradeoffs, and completeness. A sound design that differs
  from the "strong evidence" hints can still be rated demonstrated.
- "evidence_quotes" must be copied VERBATIM from the submission (at least 8 characters).
  Quotes that are not in the submission will be rejected by the system.
- Do not rate demonstrated/partial without a quote; it will be shown as unverified.
- "gaps" = what is missing, weak, or unproven. "recommendation" = ONE concrete thing to add or change
  in the next attempt.
- List claims the learner makes that the text does not substantiate in "unverified_claims".
- A well-argued design is not proof it works in operation; do not imply otherwise.

Reply with ONLY this JSON:
{{"evaluator_name": "<your model name>", "summary": "...", "next_step": "...",
 "unverified_claims": ["..."],
 "items": [{{"criterion": "C1", "rating": "partial", "observation": "...", "judgment": "...",
            "gaps": "...", "recommendation": "...", "evidence_quotes": ["..."]}}]}}"""


def parse_reply(text: str) -> dict:
    """Extract the JSON object from a model reply (tolerates code fences or stray prose)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("the reply contained no JSON object")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("top-level value must be an object")
    return data


@dataclass
class ClaudeCliEvaluator:
    """Runs ``claude -p`` as a subprocess: no tools, no project settings, no saved session."""

    command: str = "claude"
    model: str | None = None
    timeout: float = 600
    name: str = "claude CLI"

    @staticmethod
    def available(command: str = "claude") -> bool:
        return shutil.which(command) is not None

    def __call__(self, prompt: str) -> Reply:
        args = [self.command, "-p", "--output-format", "json", "--tools", "",
                "--no-session-persistence", "--setting-sources", ""]
        if self.model:
            args += ["--model", self.model]
        # Allow launching from inside a Claude Code session (e.g. a dev server started by one).
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        with tempfile.TemporaryDirectory() as cwd:  # keep any project CLAUDE.md out of the prompt
            try:
                proc = subprocess.run(args, input=prompt, capture_output=True, text=True,
                                      timeout=self.timeout, cwd=cwd, env=env)
            except FileNotFoundError:
                raise EvaluatorError(f"The '{self.command}' command was not found.") from None
            except subprocess.TimeoutExpired:
                raise EvaluatorError(f"The evaluator did not answer within {int(self.timeout)} seconds.") from None
        try:
            out = json.loads(proc.stdout)
        except ValueError:
            detail = (proc.stderr or proc.stdout).strip()[:300]
            raise EvaluatorError(f"claude exited with code {proc.returncode}: {detail or 'no output'}") from None
        if out.get("is_error") or proc.returncode != 0:
            raise EvaluatorError(f"claude reported an error: {str(out.get('result') or out)[:300]}")
        usage: dict[str, Any] = out.get("modelUsage") or {}
        model = max(usage, key=lambda m: usage[m].get("outputTokens", 0)) if usage else (self.model or "Claude")
        return Reply(text=str(out.get("result", "")), model=model)


def run_evaluation(lab: MasteryLab, evaluation: dict, evaluator: Evaluator) -> dict:
    """Run one claimed evaluation to completion. Always ends 'evaluated' or 'failed'."""
    eid, sid = evaluation["id"], evaluation["submission_id"]
    try:
        prompt = evaluation_prompt(lab.get_submission(sid))
        error = ""
        for _ in range(MAX_ATTEMPTS):
            ask = prompt if not error else (
                f"{prompt}\n\nYour previous reply was rejected by the system: {error}\n"
                "Fix that problem and reply again with ONLY the JSON.")
            try:
                reply = evaluator(ask)
            except EvaluatorError as e:
                return lab.fail_evaluation(eid, str(e))
            try:
                data = parse_reply(reply.text)
                fb = lab.record_feedback(
                    sid, provider_kind="ai_assistant", provider_name=f"{reply.model} via {evaluator.name}",
                    items=data.get("items"), summary=data.get("summary") or "",
                    next_step=data.get("next_step") or "",
                    unverified_claims=data.get("unverified_claims") or [], channel=CHANNEL)
            except ValueError as e:  # LabError is a ValueError; so are JSON errors
                error = e.message if isinstance(e, LabError) else f"Reply was not valid JSON: {e}"
                continue
            return lab.finish_evaluation(eid, fb["id"])
        return lab.fail_evaluation(eid, f"The evaluator's feedback was rejected twice. Last reason: {error}")
    except Exception as e:  # never leave a run stuck in 'evaluating'
        return lab.fail_evaluation(eid, f"Unexpected error: {e}")
