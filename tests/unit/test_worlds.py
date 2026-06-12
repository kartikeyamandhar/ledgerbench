"""Unit tests for world discovery and build error handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from ledgerbench import worlds
from ledgerbench.errors import WorldBuildError


def test_available_worlds_lists_bundled() -> None:
    assert worlds.available_worlds() == ["finance", "saas"]


def test_available_worlds_empty_when_dir_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(worlds, "WORLDS_DIR", tmp_path / "missing")
    assert worlds.available_worlds() == []


def test_build_unknown_world_raises(tmp_path: Path) -> None:
    with pytest.raises(WorldBuildError, match="unknown world"):
        worlds.build_world("nonexistent", seed=1, out_dir=tmp_path)


def test_missing_generator_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # A directory with a schema.sql but no generate.py should fail clearly.
    fake_worlds = tmp_path / "worlds"
    (fake_worlds / "broken").mkdir(parents=True)
    (fake_worlds / "broken" / "schema.sql").write_text("CREATE TABLE t (id INTEGER);", "utf-8")
    monkeypatch.setattr(worlds, "WORLDS_DIR", fake_worlds)
    with pytest.raises(WorldBuildError, match="no generator"):
        worlds.build_world("broken", seed=1, out_dir=tmp_path / "out")
