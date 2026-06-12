"""The committed JSON Schemas must match a fresh export (no silent contract drift)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ledgerbench.contracts.export import EXPORTED_CONTRACTS, render_schema

DOCS_CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


@pytest.mark.parametrize("model", EXPORTED_CONTRACTS, ids=lambda m: m.__name__)
def test_committed_schema_matches_fresh_export(model) -> None:
    committed = (DOCS_CONTRACTS / f"{model.__name__}.json").read_text(encoding="utf-8")
    assert committed == render_schema(model), (
        f"{model.__name__} schema drifted; run scripts/export_schemas.py and commit"
    )


def test_export_is_deterministic() -> None:
    for model in EXPORTED_CONTRACTS:
        assert render_schema(model) == render_schema(model)
