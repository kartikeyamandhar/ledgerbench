"""Period traps from declared time columns, calendars, and timezones.

Windows are derived from the warehouse itself (one read-only min/max probe per
metric): the last two full calendar months inside the data range. Gold gets
explicit UTC bounds, so it stays mechanical whatever the data happens to span.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from ledgerbench.contracts.item import Item
from ledgerbench.ingestion.dbt_manifest import DbtSemantics
from ledgerbench.runner.safety import vet_sql

if TYPE_CHECKING:
    import duckdb

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _month_start(value: datetime.datetime) -> datetime.date:
    return datetime.date(value.year, value.month, 1)


def _next_month(day: datetime.date) -> datetime.date:
    return datetime.date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def _prev_month(day: datetime.date) -> datetime.date:
    return datetime.date(day.year - (day.month == 1), (day.month - 2) % 12 + 1, 1)


def generate(sem: DbtSemantics, con: duckdb.DuckDBPyConnection) -> tuple[list[Item], str | None]:
    """Two full-month windows per metric that declares a time column."""
    if sem.reporting_timezone is None:
        return [], "no reporting_timezone declared in ledgerbench_project meta"
    if not sem.time_columns:
        return [], "no metric declares a time_column"

    items: list[Item] = []
    for metric_id in sorted(sem.time_columns):
        metric = sem.registry.get(metric_id)
        column = sem.time_columns[metric_id]
        probe = vet_sql(f"SELECT min({column}), max({column}) FROM {metric.base_table}")
        row = con.execute(probe).fetchone()
        if row is None or row[0] is None:
            continue
        low, high = row
        last_full_start = _prev_month(_month_start(high))
        if last_full_start < _month_start(low):
            continue
        windows = [last_full_start]
        earlier = _prev_month(last_full_start)
        if earlier >= _month_start(low):
            windows.append(earlier)
        name = metric_id.replace("_", " ")
        for start in windows:
            end = _next_month(start)
            items.append(
                Item(
                    id=f"byo-per-{len(items) + 1:03d}",
                    world=sem.project_name,
                    question=f"What was {name} in {_MONTHS[start.month - 1]} {start.year}?",
                    trap_class="period",
                    expected_action="answer",
                    gold_recipe={
                        "metric_id": metric_id,
                        "params": {
                            "extra_where": [
                                f"{column} >= TIMESTAMP '{start.isoformat()}'",
                                f"{column} < TIMESTAMP '{end.isoformat()}'",
                            ]
                        },
                    },
                    rubric=(
                        f"Generated from metric {metric_id!r} time column {column!r} "
                        f"(window derived from a read-only min/max probe); gold uses "
                        f"explicit UTC bounds; declared reporting timezone is "
                        f"{sem.reporting_timezone!r}."
                    ),
                    version="generated_v1",
                )
            )
    if not items:
        return [], "no full calendar month inside the data range"
    return items, None
