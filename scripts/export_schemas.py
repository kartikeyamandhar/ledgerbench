"""Export the frozen contract JSON Schemas to docs/contracts/.

Run from the repo root inside the venv:

    python scripts/export_schemas.py
"""

from __future__ import annotations

from pathlib import Path

from ledgerbench.contracts.export import write_schemas

if __name__ == "__main__":
    for path in write_schemas(Path(__file__).resolve().parents[1] / "docs" / "contracts"):
        print(path)
