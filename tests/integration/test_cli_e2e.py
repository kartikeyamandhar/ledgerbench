"""CLI end to end: demo, exit-code matrix, report re-render. The product tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ledgerbench.cli import app

runner = CliRunner()
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", autouse=True)
def in_repo_root(tmp_path_factory):
    """Run the CLI from a sandbox dir that carries the repo's data files."""
    sandbox = tmp_path_factory.mktemp("cli_sandbox")
    (sandbox / "benchmark" / "items").mkdir(parents=True)
    shutil.copy(REPO / "benchmark/items/public_v1.jsonl", sandbox / "benchmark/items/")
    import os

    old = Path.cwd()
    os.chdir(sandbox)
    yield sandbox
    os.chdir(old)


def test_demo_limit_runs_end_to_end() -> None:
    result = runner.invoke(app, ["demo", "--limit", "12", "--no-open"])
    assert result.exit_code == 0, result.output
    assert "demo complete" in result.output
    assert Path(".ledgerbench/demo/report.html").is_file()
    assert Path(".ledgerbench/demo/traces.jsonl").is_file()
    assert Path(".ledgerbench/demo/manifest.json").is_file()
    # The report stays a single small file.
    assert Path(".ledgerbench/demo/report.html").stat().st_size < 2_000_000


def test_run_exit_code_1_on_threshold_breach() -> None:
    Path("ledgerbench.yaml").write_text(
        "agent: {adapter: naive}\nconditions: [closed]\nrepetitions: {seeds: [42]}\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["run", "--limit", "12", "--no-judge"])
    assert result.exit_code == 1, result.output  # naive breaches by design
    assert "threshold breaches" in result.output


def test_run_exit_code_0_when_thresholds_met() -> None:
    Path("ledgerbench.yaml").write_text(
        "agent: {adapter: naive}\n"
        "conditions: [closed]\n"
        "repetitions: {seeds: [42]}\n"
        "thresholds: {definitional: 0.0, grain: 0.0, ambiguity: 0.0, refusal: 0.0,"
        " faithfulness: 0.0}\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["run", "--limit", "12", "--no-judge"])
    assert result.exit_code == 0, result.output
    assert "all axis thresholds met" in result.output


def test_run_exit_code_2_on_bad_config() -> None:
    Path("ledgerbench.yaml").write_text("agent: {adapter: naive}\nsurprise: true\n")
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 2
    assert "ledgerbench.example.yaml" in result.output  # the next step is named


def test_report_rerenders_from_traces() -> None:
    result = runner.invoke(
        app,
        [
            "report",
            "--traces",
            ".ledgerbench/demo/traces.jsonl",
            "--manifest",
            ".ledgerbench/demo/manifest.json",
            "--out",
            ".ledgerbench/rerender.html",
        ],
    )
    assert result.exit_code == 0, result.output
    assert Path(".ledgerbench/rerender.html").is_file()


def test_report_missing_file_is_exit_2() -> None:
    result = runner.invoke(app, ["report", "--traces", "nope.jsonl", "--manifest", "nope.json"])
    assert result.exit_code == 2
    assert "not found" in result.output


def test_validate_passes_on_the_public_bank() -> None:
    result = runner.invoke(app, ["validate", "--no-gold"])
    assert result.exit_code == 0, result.output
    assert "suite valid" in result.output
