from pathlib import Path

import pytest

from mastery_lab.service import MasteryLab

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (ROOT / "docs/demo/sample-submission.md").read_text()


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "lab.db"


@pytest.fixture
def lab(db_path):
    return MasteryLab(db_path)


@pytest.fixture
def seed_ids(lab):
    goal = lab.list_goals()[0]
    ch = lab.list_challenges(goal["id"])[0]
    return goal["id"], ch["id"]


def good_items():
    return [
        {"criterion": "C1", "rating": "demonstrated",
         "observation": "Names orchestrator, model, retrieval, action gateway, policy engine, audit store.",
         "judgment": "Clear trust boundary around the model.",
         "evidence_quotes": ["The model never holds credentials and cannot call source systems directly"]},
        {"criterion": "C2", "rating": "demonstrated",
         "evidence_quotes": ["filtered by the document ACL and classification at query time"]},
        {"criterion": "C3", "rating": "partial", "gaps": "No rollback for a mistaken hold.",
         "evidence_quotes": ["the approver cannot be the requester"]},
        {"criterion": "C4", "rating": "partial"},  # no evidence -> unverified
        {"criterion": "C6", "rating": "not_evident", "gaps": "Only 'we would test it'."},
    ]
