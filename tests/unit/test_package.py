"""Phase 0 placeholder test: the package installs, imports, and is versioned."""

from __future__ import annotations

import importlib
import pkgutil
from importlib.metadata import version

import ledgerbench


def test_version_matches_installed_metadata() -> None:
    """__version__ in source must equal the installed distribution version."""
    assert ledgerbench.__version__ == version("ledgerbench")


def test_every_submodule_imports() -> None:
    """Every module under the package imports cleanly (no hidden import errors)."""
    failures: list[str] = []
    for mod in pkgutil.walk_packages(ledgerbench.__path__, ledgerbench.__name__ + "."):
        try:
            importlib.import_module(mod.name)
        except Exception as exc:
            failures.append(f"{mod.name}: {exc!r}")
    assert not failures, "modules failed to import:\n" + "\n".join(failures)
