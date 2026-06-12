"""dbt manifest parser: extraction, version fence, declared-semantics validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ledgerbench.errors import LedgerBenchError
from ledgerbench.gold.compiler import connect_warehouse
from ledgerbench.ingestion.dbt_manifest import UNDECLARED_KEY, load_dbt_manifest

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tiny_dbt_project"


def test_full_extraction_from_fixture() -> None:
    sem = load_dbt_manifest(FIXTURE / "manifest.json")
    assert sorted(sem.grain_model.tables) == ["customers", "order_items", "orders"]
    assert sem.grain_model.tables["orders"].primary_key == ("order_id",)
    edges = {(r.from_table, r.to_table, r.cardinality) for r in sem.relationships}
    assert ("order_items", "orders", "many_to_one") in edges
    assert ("orders", "customers", "many_to_one") in edges
    assert sem.registry.ids() == ["order_count", "revenue_gross", "revenue_net"]
    net = sem.registry.get("revenue_net")
    assert net.filters == ("status = 'completed'",)
    assert net.exclusions == ("refunded = true",)
    assert sem.time_columns == {"revenue_net": "order_ts", "revenue_gross": "order_ts"}
    assert sem.reporting_timezone == "America/New_York"
    assert [a.term for a in sem.ambiguities] == ["revenue"]
    assert [d.name for d in sem.absent_dimensions] == ["acquisition_channel"]


def test_stripped_manifest_degrades_not_crashes() -> None:
    sem = load_dbt_manifest(FIXTURE / "manifest_stripped.json")
    assert len(sem.registry.metrics) == 0
    assert sem.relationships == ()
    # Models without unique tests get the fail-closed sentinel key.
    assert sem.grain_model.tables["orders"].primary_key == (UNDECLARED_KEY,)


def test_unsupported_schema_version_names_the_fix(tmp_path) -> None:
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    manifest["metadata"]["dbt_schema_version"] = "https://schemas.getdbt.com/dbt/manifest/v9.json"
    bad = tmp_path / "old.json"
    bad.write_text(json.dumps(manifest))
    with pytest.raises(LedgerBenchError, match=r"v9.*supported.*v11, v12"):
        load_dbt_manifest(bad)


def test_invalid_json_is_actionable(tmp_path) -> None:
    bad = tmp_path / "broken.json"
    bad.write_text("{not json")
    with pytest.raises(LedgerBenchError, match="not valid JSON"):
        load_dbt_manifest(bad)


def test_absent_dimension_that_exists_is_rejected(tmp_path) -> None:
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    meta = manifest["nodes"]["model.tiny_shop.orders"]["meta"]
    meta["ledgerbench_project"]["absent_dimensions"] = ["status"]  # it exists!
    bad = tmp_path / "lie.json"
    bad.write_text(json.dumps(manifest))
    with pytest.raises(LedgerBenchError, match="actually exist"):
        load_dbt_manifest(bad)


def test_ambiguous_term_with_unknown_reading_is_rejected(tmp_path) -> None:
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    meta = manifest["nodes"]["model.tiny_shop.orders"]["meta"]
    meta["ledgerbench_project"]["ambiguous_terms"] = [
        {"term": "revenue", "readings": ["revenue_gross", "no_such_metric"]}
    ]
    bad = tmp_path / "dangling.json"
    bad.write_text(json.dumps(manifest))
    with pytest.raises(LedgerBenchError, match="undeclared metrics"):
        load_dbt_manifest(bad)


def test_bad_metric_block_names_the_model(tmp_path) -> None:
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    meta = manifest["nodes"]["model.tiny_shop.orders"]["meta"]
    meta["ledgerbench"]["metrics"][0].pop("measure")
    bad = tmp_path / "bad_metric.json"
    bad.write_text(json.dumps(manifest))
    with pytest.raises(LedgerBenchError, match="model 'orders'"):
        load_dbt_manifest(bad)


# --- warehouse seam ----------------------------------------------------------


def test_connect_warehouse_rejects_other_schemes() -> None:
    with pytest.raises(LedgerBenchError, match=r"snowflake.*post-launch"):
        connect_warehouse("snowflake://account/db")


def test_connect_warehouse_opens_read_only(tmp_path) -> None:
    import duckdb

    db = tmp_path / "w.duckdb"
    duckdb.connect(str(db)).execute("CREATE TABLE t (a INTEGER)").close()
    con = connect_warehouse(f"duckdb://{db}")
    with pytest.raises(Exception, match=r"read-only|Cannot execute"):
        con.execute("INSERT INTO t VALUES (1)")
    con.close()
