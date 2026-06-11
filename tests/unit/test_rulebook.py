"""Unit tests for rulebook loading, validation, and projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from ledgerbench import worlds
from ledgerbench.errors import RulebookError, RulebookValidationError
from ledgerbench.ingestion.rulebook import load_rulebook


def _minimal() -> dict[str, Any]:
    """A smallest valid rulebook, as a mutable dict for error-case tests."""
    return {
        "world": "t",
        "reference_date": "2026-01-01",
        "tables": [{"name": "a", "grain": ["id"], "primary_key": ["id"]}],
        "metrics": [
            {
                "id": "m",
                "description": "d",
                "base_table": "a",
                "measure": "count(*)",
                "value_type": "count",
                "grain": ["id"],
            }
        ],
    }


def _write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "rulebook.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.mark.parametrize("world", ["saas", "finance"])
def test_bundled_rulebooks_load_and_project(world: str) -> None:
    rb = load_rulebook(worlds.WORLDS_DIR / world / "rulebook.yaml")
    assert rb.world == world
    registry = rb.to_registry()
    grain = rb.to_grain_model()
    assert len(registry) >= 1
    assert grain.tables  # at least one table


def test_minimal_rulebook_is_valid(tmp_path: Path) -> None:
    rb = load_rulebook(_write(tmp_path, _minimal()))
    assert rb.to_registry().get("m").value_type == "count"


def test_missing_file_raises_rulebook_error(tmp_path: Path) -> None:
    with pytest.raises(RulebookError):
        load_rulebook(tmp_path / "does-not-exist.yaml")


def test_malformed_yaml_raises_rulebook_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("world: [unterminated\n", encoding="utf-8")
    with pytest.raises(RulebookError):
        load_rulebook(path)


def test_non_mapping_raises_validation_error(tmp_path: Path) -> None:
    with pytest.raises(RulebookValidationError):
        load_rulebook(_write(tmp_path, ["not", "a", "mapping"]))


def test_unknown_base_table_rejected(tmp_path: Path) -> None:
    data = _minimal()
    data["metrics"][0]["base_table"] = "ghost"
    with pytest.raises(RulebookValidationError):
        load_rulebook(_write(tmp_path, data))


def test_duplicate_metric_ids_rejected(tmp_path: Path) -> None:
    data = _minimal()
    data["metrics"].append(dict(data["metrics"][0]))
    with pytest.raises(RulebookValidationError):
        load_rulebook(_write(tmp_path, data))


def test_relationship_unknown_table_rejected(tmp_path: Path) -> None:
    data = _minimal()
    data["relationships"] = [
        {
            "name": "r",
            "from_table": "a",
            "to_table": "ghost",
            "from_columns": ["id"],
            "to_columns": ["id"],
            "cardinality": "many_to_one",
        }
    ]
    with pytest.raises(RulebookValidationError):
        load_rulebook(_write(tmp_path, data))


def test_ambiguity_referencing_unknown_metric_rejected(tmp_path: Path) -> None:
    data = _minimal()
    data["ambiguities"] = [{"term": "x", "readings": ["m", "ghost"]}]
    with pytest.raises(RulebookValidationError):
        load_rulebook(_write(tmp_path, data))


def test_irregularity_unknown_table_rejected(tmp_path: Path) -> None:
    data = _minimal()
    data["irregularities"] = [{"table": "ghost", "kind": "nulls"}]
    with pytest.raises(RulebookValidationError):
        load_rulebook(_write(tmp_path, data))


def test_missing_required_field_rejected(tmp_path: Path) -> None:
    data = _minimal()
    del data["metrics"]
    with pytest.raises(RulebookValidationError):
        load_rulebook(_write(tmp_path, data))
