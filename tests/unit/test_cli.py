"""Unit tests for the `ledgerbench world build` CLI (build is stubbed out)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ledgerbench import worlds
from ledgerbench.cli import app

runner = CliRunner()


@pytest.fixture
def stub_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real (slow) build with fast stubs so the CLI logic is unit-tested."""
    monkeypatch.setattr(worlds, "available_worlds", lambda: ["finance", "saas"])
    monkeypatch.setattr(worlds, "build_world", lambda name, seed: Path(f"/tmp/{name}.duckdb"))
    monkeypatch.setattr(worlds, "digest_database", lambda path: "0" * 64)


def test_build_single_world(stub_build: None) -> None:
    result = runner.invoke(app, ["world", "build", "--world", "saas"])
    assert result.exit_code == 0


def test_build_all_worlds(stub_build: None) -> None:
    result = runner.invoke(app, ["world", "build"])
    assert result.exit_code == 0


def test_build_unknown_world_exits_nonzero(stub_build: None) -> None:
    result = runner.invoke(app, ["world", "build", "--world", "bogus"])
    assert result.exit_code == 2


def test_build_when_no_worlds_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worlds, "available_worlds", lambda: [])
    result = runner.invoke(app, ["world", "build"])
    assert result.exit_code == 2
