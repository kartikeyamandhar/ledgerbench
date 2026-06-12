"""Grain-checker corpus: exact labels plus published precision numbers.

Every query is asserted against its hand-assigned label, and the suite computes
and PRINTS the checker's measured precision -- TPR on fan-out traps, FPR on
clean queries, and the unknown rate -- then asserts the acceptance gates
(TPR >= 0.90, FPR <= 0.05). The printed numbers are recorded in
docs/architecture.md; if this corpus changes, update them there.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml

from ledgerbench.ingestion.rulebook import load_rulebook
from ledgerbench.scorer.grain_check import check_grain

_DIR = Path(__file__).parent
_REPO = _DIR.parents[2]

CORPUS = yaml.safe_load((_DIR / "corpus.yaml").read_text(encoding="utf-8"))

_GRAIN_MODELS = {
    world: load_rulebook(_REPO / "benchmark" / "worlds" / world / "rulebook.yaml").to_grain_model()
    for world in ("saas", "finance")
}

_CAUGHT = ("unsafe", "needs_distinct")


def test_corpus_is_large_enough() -> None:
    assert len(CORPUS) >= 40, f"corpus shrank to {len(CORPUS)}; it must stay >= 40"


@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c["name"])
def test_corpus_label(case: dict) -> None:
    result = check_grain(case["sql"], _GRAIN_MODELS[case["world"]])
    assert result.status == case["expect"], (
        f"{case['name']}: got {result.status} (unsupported={result.unsupported!r}, "
        f"paths={[(e.from_table, e.to_table) for e in result.fan_out_paths]})"
    )
    for expected_path in case.get("paths", []):
        rendered = [f"{e.from_table} -> {e.to_table}" for e in result.fan_out_paths]
        assert expected_path in rendered, f"{case['name']}: missing path {expected_path}"


def test_precision_gates_and_publish_numbers(capsys) -> None:
    """Compute TPR / FPR / unknown rate; print them; enforce the gates."""
    verdicts = {
        case["name"]: (case, check_grain(case["sql"], _GRAIN_MODELS[case["world"]]).status)
        for case in CORPUS
    }
    traps = [(c, v) for c, v in verdicts.values() if c["expect"] in _CAUGHT]
    clean = [(c, v) for c, v in verdicts.values() if c["expect"] == "safe"]
    fence = [(c, v) for c, v in verdicts.values() if c["expect"] == "unknown"]

    tpr = sum(v in _CAUGHT for _, v in traps) / len(traps)
    fpr = sum(v in _CAUGHT for _, v in clean) / len(clean)
    unknown_rate = sum(v == "unknown" for _, v in verdicts.values()) / len(verdicts)

    with capsys.disabled():
        print(
            f"\n[grain-checker precision] corpus={len(verdicts)} "
            f"traps={len(traps)} clean={len(clean)} fence={len(fence)} | "
            f"TPR={tpr:.3f} FPR={fpr:.3f} unknown_rate={unknown_rate:.3f}"
        )

    assert tpr >= 0.90, f"TPR {tpr:.3f} below the 0.90 acceptance gate"
    assert fpr <= 0.05, f"FPR {fpr:.3f} above the 0.05 acceptance gate"


def test_analysis_speed_under_50ms_per_query() -> None:
    start = time.perf_counter()
    for case in CORPUS:
        check_grain(case["sql"], _GRAIN_MODELS[case["world"]])
    mean_ms = (time.perf_counter() - start) * 1000 / len(CORPUS)
    assert mean_ms < 50, f"mean analysis time {mean_ms:.1f} ms exceeds the 50 ms budget"
