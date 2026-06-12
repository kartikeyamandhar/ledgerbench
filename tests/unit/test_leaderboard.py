"""Leaderboard builder: a pure function of committed results."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location(
    "build_leaderboard", REPO / "scripts" / "build_leaderboard.py"
)
mod = importlib.util.module_from_spec(spec)
sys.modules["build_leaderboard"] = mod
spec.loader.exec_module(mod)


def test_leaderboard_renders_committed_results(tmp_path) -> None:
    out = mod.build(REPO / "benchmark" / "results", tmp_path / "index.html")
    html = out.read_text(encoding="utf-8")
    assert "naive" in html
    assert "9.3%" in html and "100.0%" in html  # the floor row, from real manifests
    assert "definitional" in html and "grain" in html  # per-axis beside aggregate
    assert "pending keyed runs" in html  # honesty marker
    assert "<script" not in html  # no JS, like the report


def test_committed_page_matches_fresh_build(tmp_path) -> None:
    fresh = mod.build(REPO / "benchmark" / "results", tmp_path / "fresh.html")
    committed = REPO / "benchmark" / "leaderboard" / "index.html"
    assert committed.read_text(encoding="utf-8") == fresh.read_text(encoding="utf-8"), (
        "leaderboard drifted from results; run scripts/build_leaderboard.py and commit"
    )
