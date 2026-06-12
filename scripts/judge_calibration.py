"""Measure live judge agreement on the calibration set (pre-launch step).

Requires ANTHROPIC_API_KEY. Runs the real judge (double-run, cached) over the
20 hand-labeled cases and prints per-case verdicts and overall agreement.
The acceptance gate is agreement >= 0.8; record the measured number in
docs/architecture.md when run.

    python scripts/judge_calibration.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ledgerbench.scorer.faithfulness import (
    AnthropicJudge,
    CachingJudge,
    extract_sql_facts,
    judge_assumption,
)

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    """Run the live calibration; return a nonzero exit code below the gate."""
    cases = yaml.safe_load(
        (REPO / "tests/golden/faithfulness/calibration.yaml").read_text(encoding="utf-8")
    )
    judge = CachingJudge(AnthropicJudge(), cache_dir=REPO / ".ledgerbench" / "judge_cache")

    agree = 0
    for case in cases:
        facts = extract_sql_facts(case["sql"])
        assert facts is not None
        verdict = judge_assumption(case["assumption"], facts, judge)
        match = verdict == case["label"]
        agree += match
        print(
            f"{'OK ' if match else 'MISS'} {case['name']:40s} judge={verdict:12s} "
            f"label={case['label']}"
        )

    agreement = agree / len(cases)
    print(f"\njudge agreement: {agreement:.2f} (gate: >= 0.80)")
    return 0 if agreement >= 0.8 else 1


if __name__ == "__main__":
    raise SystemExit(main())
