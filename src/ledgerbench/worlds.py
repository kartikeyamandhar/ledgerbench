"""Build benchmark world databases deterministically from schema + generator.

Each world under ``benchmark/worlds/<name>/`` ships a ``schema.sql`` (DuckDB DDL
with PK/FK) and a ``generate.py`` exposing ``build(con, seed)``. This module is the
thin orchestrator the CLI calls: it runs the schema, invokes the generator, and
writes a ``.duckdb`` file. Worlds are data-adjacent scripts, so the generator is
loaded by path rather than imported as a package.

(Not listed in CLAUDE.md section 9; added in Phase 1 as the importable builder so
the CLI stays a thin shell -- see ADR-0002.)
"""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import duckdb

from ledgerbench.errors import WorldBuildError

BuildFn = Callable[[Any, int], None]
"""Signature of a world generator's ``build(con, seed)`` entry point."""

_REPO_ROOT = Path(__file__).resolve().parents[2]
WORLDS_DIR = _REPO_ROOT / "benchmark" / "worlds"
"""Directory holding the bundled worlds (resolved relative to the source tree)."""

DEFAULT_OUTPUT_DIR = _REPO_ROOT / ".ledgerbench" / "worlds"
"""Default location for built ``.duckdb`` files (gitignored)."""


def available_worlds() -> list[str]:
    """Return the names of bundled worlds, sorted.

    A directory is a world only if it contains a ``schema.sql``.
    """
    if not WORLDS_DIR.is_dir():
        return []
    return sorted(p.name for p in WORLDS_DIR.iterdir() if (p / "schema.sql").is_file())


def _load_generator(world: str) -> BuildFn:
    """Load ``build`` from a world's ``generate.py`` by file path.

    Raises:
        WorldBuildError: the generator file is missing, unloadable, or has no
            callable ``build``.
    """
    gen_path = WORLDS_DIR / world / "generate.py"
    if not gen_path.is_file():
        raise WorldBuildError(f"world {world!r} has no generator at {gen_path}")

    spec = importlib.util.spec_from_file_location(f"ledgerbench._worlds.{world}", gen_path)
    if spec is None or spec.loader is None:
        raise WorldBuildError(f"cannot load generator for world {world!r}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    build = getattr(module, "build", None)
    if not callable(build):
        raise WorldBuildError(f"world {world!r} generator has no callable build(con, seed)")
    return cast(BuildFn, build)


def build_world(world: str, seed: int, out_dir: str | Path = DEFAULT_OUTPUT_DIR) -> Path:
    """Build one world into ``out_dir/<world>.duckdb`` and return its path.

    Any existing database at that path is removed first, so a rebuild with the
    same seed is reproducible from scratch.

    Raises:
        WorldBuildError: the world is unknown or its schema/generator fails.
    """
    schema_path = WORLDS_DIR / world / "schema.sql"
    if not schema_path.is_file():
        known = ", ".join(available_worlds()) or "(none)"
        raise WorldBuildError(f"unknown world {world!r}; available worlds: {known}")

    build = _load_generator(world)
    schema_sql = schema_path.read_text(encoding="utf-8")

    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / f"{world}.duckdb"
    db_path.unlink(missing_ok=True)

    con = duckdb.connect(str(db_path))
    try:
        con.execute(schema_sql)
        build(con, seed)
    except Exception as exc:
        raise WorldBuildError(f"failed to build world {world!r}: {exc}") from exc
    finally:
        con.close()
    return db_path


def world_digest(con: Any) -> str:
    """Return a content hash of every table in an open connection.

    Rows are read in a fully-ordered way (``ORDER BY`` all columns) so the digest
    depends only on the *data*, not on insertion order or storage layout. This is
    the meaningful determinism check -- raw ``.duckdb`` file bytes are not stable
    across DuckDB versions, so we hash content, not the file (see ADR-0002).
    """
    digest = hashlib.sha256()
    tables = [
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
    ]
    for table in tables:
        columns = [
            row[0]
            for row in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
                [table],
            ).fetchall()
        ]
        order_by = ", ".join(f'"{col}"' for col in columns)
        rows = con.execute(f'SELECT * FROM "{table}" ORDER BY {order_by}').fetchall()
        digest.update(table.encode())
        digest.update(b"\x00")
        for row in rows:
            digest.update(repr(row).encode())
            digest.update(b"\x01")
    return digest.hexdigest()


def digest_database(path: str | Path) -> str:
    """Open a built database read-only and return its :func:`world_digest`."""
    con = duckdb.connect(str(path), read_only=True)
    try:
        return world_digest(con)
    finally:
        con.close()
