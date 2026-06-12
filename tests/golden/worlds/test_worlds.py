"""Golden tests for the bundled worlds: determinism, integrity, and trap coverage."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from ledgerbench import worlds
from ledgerbench.ingestion.rulebook import Rulebook, load_rulebook

WORLD_NAMES = ["finance", "saas"]

# (child_table, fk_column, parent_table, pk_column) for every foreign key per world.
FOREIGN_KEYS: dict[str, list[tuple[str, str, str, str]]] = {
    "saas": [
        ("subscriptions", "customer_id", "customers", "customer_id"),
        ("users", "customer_id", "customers", "customer_id"),
        ("orders", "customer_id", "customers", "customer_id"),
        ("shipments", "order_id", "orders", "order_id"),
        ("events", "user_id", "users", "user_id"),
    ],
    "finance": [
        ("transactions", "account_id", "accounts", "account_id"),
        ("ledger_entries", "transaction_id", "transactions", "transaction_id"),
        ("ledger_entries", "account_id", "accounts", "account_id"),
    ],
}


def _rulebook(world: str) -> Rulebook:
    return load_rulebook(worlds.WORLDS_DIR / world / "rulebook.yaml")


def _total_rows(con: duckdb.DuckDBPyConnection) -> int:
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return sum(con.execute(f'SELECT count(*) FROM "{t[0]}"').fetchone()[0] for t in tables)


def test_two_worlds_are_bundled() -> None:
    assert worlds.available_worlds() == WORLD_NAMES


@pytest.mark.parametrize("world", WORLD_NAMES)
def test_row_count_in_ci_friendly_band(world: str, built_worlds: dict[str, Path]) -> None:
    con = duckdb.connect(str(built_worlds[world]), read_only=True)
    try:
        total = _total_rows(con)
    finally:
        con.close()
    assert 50_000 <= total <= 100_000, f"{world} has {total} rows, outside 50k-100k"


@pytest.mark.parametrize("world", WORLD_NAMES)
def test_referential_integrity_no_orphans(world: str, built_worlds: dict[str, Path]) -> None:
    con = duckdb.connect(str(built_worlds[world]), read_only=True)
    try:
        for child, fk, parent, pk in FOREIGN_KEYS[world]:
            orphans = con.execute(
                f'SELECT count(*) FROM "{child}" c '
                f'LEFT JOIN "{parent}" p ON c."{fk}" = p."{pk}" '
                f'WHERE c."{fk}" IS NOT NULL AND p."{pk}" IS NULL'
            ).fetchone()[0]
            assert orphans == 0, f"{world}: {child}.{fk} has {orphans} orphan rows"
    finally:
        con.close()


@pytest.mark.parametrize("world", WORLD_NAMES)
def test_same_seed_is_byte_identical(
    world: str, built_worlds: dict[str, Path], tmp_path: Path
) -> None:
    rebuilt = worlds.build_world(world, seed=42, out_dir=tmp_path)
    assert worlds.digest_database(rebuilt) == worlds.digest_database(built_worlds[world])


def test_different_seed_changes_data_not_schema(
    built_worlds: dict[str, Path], tmp_path: Path
) -> None:
    other = worlds.build_world("saas", seed=7, out_dir=tmp_path)
    assert worlds.digest_database(other) != worlds.digest_database(built_worlds["saas"])

    def schema(path: Path) -> list[tuple[str, str]]:
        con = duckdb.connect(str(path), read_only=True)
        try:
            return con.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position"
            ).fetchall()
        finally:
            con.close()

    assert schema(other) == schema(built_worlds["saas"])


@pytest.mark.parametrize("world", WORLD_NAMES)
def test_every_trap_class_has_a_precondition(world: str) -> None:
    rb = _rulebook(world)
    registry = rb.to_registry()
    grain = rb.to_grain_model()
    metrics = list(registry.metrics.values())

    definitional = any(m.exclusions for m in metrics)
    grain_fanout = any(
        grain.fans_out(m.base_table, table)
        for m in metrics
        for table in grain.tables
        if table != m.base_table
    )
    ambiguity = len(rb.ambiguities) >= 1
    refusal = len(rb.absent_dimensions) >= 1
    period = rb.reporting_timezone is not None or rb.fiscal_year_start_month != 1
    control = any(not m.filters and not m.exclusions for m in metrics)
    irregular = len(rb.irregularities) >= 1

    missing = [
        name
        for name, present in {
            "definitional": definitional,
            "grain": grain_fanout,
            "ambiguity": ambiguity,
            "refusal": refusal,
            "period": period,
            "control": control,
            "irregularities": irregular,
        }.items()
        if not present
    ]
    assert not missing, f"{world} is missing preconditions: {missing}"
