"""Calibration set plumbing: every case extracts cleanly and flows end to end.

The live judge-agreement measurement (gate >= 0.8) requires an API key and runs
via scripts/judge_calibration.py as a pre-launch step; CI pins everything that
can be pinned without a model: the set's size and label vocabulary, that every
SQL extracts to facts, and that a judge answering the hand label reproduces the
expected axis outcome.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ledgerbench.contracts.agent_io import AgentResponse
from ledgerbench.scorer.faithfulness import extract_sql_facts, score_faithfulness

CASES = yaml.safe_load((Path(__file__).parent / "calibration.yaml").read_text(encoding="utf-8"))


def test_calibration_set_shape() -> None:
    assert len(CASES) == 20
    assert {c["label"] for c in CASES} == {"supported", "contradicted", "unrelated"}
    assert len({c["name"] for c in CASES}) == 20


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_every_case_extracts_facts(case: dict) -> None:
    facts = extract_sql_facts(case["sql"])
    assert facts is not None, "calibration SQL must be extractable"
    assert facts.tables


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_label_drives_expected_axis_outcome(case: dict) -> None:
    """A judge that answers exactly the human label yields the expected axis status."""
    response = AgentResponse(
        action="answer", value=1.0, sql=case["sql"], assumptions=(case["assumption"],)
    )
    result = score_faithfulness(response, lambda _: case["label"].upper())
    expected = {"supported": "pass", "unrelated": "pass", "contradicted": "fail"}[case["label"]]
    assert result.status == expected
