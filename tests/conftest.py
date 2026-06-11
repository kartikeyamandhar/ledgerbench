"""Shared Phase 1 fixtures.

Building a world takes a few seconds, so each bundled world is built once per test
session (seed 42) and reused. Tests that need a *second* independent build (the
determinism golden tests) build their own copies explicitly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ledgerbench import worlds

SEED = 42


@pytest.fixture(scope="session")
def built_worlds(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Build every bundled world once (seed 42); return {world: db_path}."""
    out_dir = tmp_path_factory.mktemp("worlds_seed42")
    return {
        name: worlds.build_world(name, seed=SEED, out_dir=out_dir)
        for name in worlds.available_worlds()
    }
