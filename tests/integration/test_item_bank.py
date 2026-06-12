"""The public bank linter in CI: structure, preconditions, and full gold recomputation.

This is the executable version of the bank's promises: 150 items, taxonomy
exact, every trap precondition present in its world, and every answer item's
gold recomputing mechanically from the rulebook against freshly built worlds
(the acceptance gate says under 5 minutes; the duration is printed).
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb

from ledgerbench.generator.suite import PUBLIC_TAXONOMY, load_bank, suite_hash, validate_items
from ledgerbench.ingestion.rulebook import load_rulebook
from ledgerbench.worlds import WORLDS_DIR

REPO = Path(__file__).resolve().parents[2]
BANK = REPO / "benchmark" / "items" / "public_v1.jsonl"


def test_public_bank_lints_clean_with_full_gold_recomputation(built_worlds, capsys) -> None:
    items = load_bank(BANK)
    assert len(items) == 150

    rulebooks = {
        world: load_rulebook(WORLDS_DIR / world / "rulebook.yaml") for world in built_worlds
    }
    connections = {
        world: duckdb.connect(str(path), read_only=True) for world, path in built_worlds.items()
    }
    started = time.perf_counter()
    try:
        report = validate_items(
            items, rulebooks, connections=connections, expected_taxonomy=PUBLIC_TAXONOMY
        )
    finally:
        for con in connections.values():
            con.close()
    elapsed = time.perf_counter() - started

    with capsys.disabled():
        print(
            f"\n[item linter] items={report.checked_items} "
            f"gold_recomputed={report.recomputed_gold} in {elapsed:.1f}s "
            f"suite_hash={suite_hash(BANK)}"
        )

    assert report.ok, "\n".join(report.errors)
    answer_items = sum(1 for i in items if i.expected_action == "answer")
    assert report.recomputed_gold == answer_items  # every recipe executed
    assert elapsed < 300, "full-bank gold recomputation must stay under 5 minutes"


def test_bank_is_append_only_versioned() -> None:
    items = load_bank(BANK)
    assert all(item.version == "public_v1" for item in items)


def test_linter_catches_planted_defects(built_worlds) -> None:
    """Negative control: a corrupted item must produce errors, not silence."""
    items = load_bank(BANK)
    rulebooks = {
        world: load_rulebook(WORLDS_DIR / world / "rulebook.yaml") for world in built_worlds
    }

    bad = items[0].model_copy(update={"id": items[1].id})  # duplicate id
    report = validate_items([*items, bad], rulebooks)
    assert not report.ok and any("duplicate" in e for e in report.errors)

    wrong_term = next(i for i in items if i.trap_class == "ambiguity").model_copy(
        update={"ambiguous_term": "synergy"}
    )
    report = validate_items([wrong_term], rulebooks)
    assert not report.ok and any("not a declared ambiguity" in e for e in report.errors)
