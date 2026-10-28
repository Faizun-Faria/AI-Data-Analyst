"""Phase 2, step 2: build and test the warehouse with dbt.

Runs `dbt build` on the project in warehouse/: the seeds, then every model, each followed
by its tests. A failing test stops everything downstream of it. Afterwards, any batch
whose counts don't add up is listed by name.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import duckdb
from dbt.cli.main import dbtRunner

WAREHOUSE_DIR = Path(__file__).resolve().parent.parent / "warehouse"


def run_dbt(
    db_path: str | Path,
    args: Sequence[str] = ("build",),
    *,
    target_path: Path | None = None,
    log_path: Path | None = None,
) -> bool:
    """Run a dbt command against the DuckDB file at db_path; True if it succeeded."""
    os.environ["QUERY_CF_DB"] = str(Path(db_path).resolve())
    cli = [*args, "--project-dir", str(WAREHOUSE_DIR), "--profiles-dir", str(WAREHOUSE_DIR)]
    if target_path:
        cli += ["--target-path", str(target_path)]
    if log_path:
        cli += ["--log-path", str(log_path)]
    return dbtRunner().invoke(cli).success


def incomplete_batches(db_path: str | Path) -> list[tuple]:
    """Batches whose audited, loaded, mart and quarantine counts don't add up."""
    conn = duckdb.connect(str(db_path))
    try:
        return conn.execute(
            """
            select batch_id, export_name, audited_rows, loaded_rows, fact_rows, quarantined_rows
            from quality.completeness_by_batch
            where not is_complete
            order by export_name
            """
        ).fetchall()
    except duckdb.CatalogException:
        return []  # the completeness model wasn't built
    finally:
        conn.close()
