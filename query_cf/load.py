"""Phase 2, step 1: copy each landed export into the warehouse's bronze table.

bronze.<source>_complaints holds every row exactly as published, as text, plus the batch
it came from; dbt builds everything else from it. Each export's latest landed batch is
its current one, so when a newer batch lands, the export's old rows are replaced.
load_audit records every batch loaded and how many rows it gave.

Every run also records the exports the source config lists in expected_exports, and
reports any of them that has no landed batch, so a whole export can't go missing quietly:
dbt's completeness check reads the same table and fails the build.
"""

from __future__ import annotations

import csv
import os
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import duckdb

from query_cf import audit
from query_cf.config import SourceConfig
from query_cf.storage import local_copy

LOADED = "loaded"
MISSING = "missing"  # listed in the source config, but no batch of it has landed

# The strict CSV settings that scripts/profile_exports.py proved on all 21 exports. The
# header is read in Python and passed in as `columns`, so DuckDB never has to guess.
READ_OPTIONS = (
    "header = true, all_varchar = true, delim = ',', quote = '\"', escape = '\"', "
    "max_line_size = 10000000, auto_detect = false"
)

LOAD_AUDIT_DDL = """
create table if not exists load_audit (
    batch_id       varchar primary key,
    source         varchar not null,
    export_name    varchar not null,
    status         varchar not null,
    rows_loaded    bigint,
    loaded_at_utc  timestamp not null,
    error          varchar
);

create table if not exists expected_exports (
    source       varchar not null,
    export_name  varchar not null,
    position     integer not null
);
"""


@dataclass(frozen=True)
class LoadResult:
    export_name: str
    batch_id: str
    status: str
    rows_loaded: int | None = None
    message: str = ""


def bronze_table(source: SourceConfig) -> str:
    return f"bronze.{source.name}_complaints"


def sql_text(value: str) -> str:
    return value.replace("'", "''")


def ensure_tables(conn: duckdb.DuckDBPyConnection, source: SourceConfig) -> None:
    columns = "".join(f'    "{c}" varchar,\n' for c in source.expected_columns)
    conn.execute("create schema if not exists bronze")
    conn.execute(
        f"create table if not exists {bronze_table(source)} (\n{columns}"
        "    batch_id varchar not null,\n    export_name varchar not null\n)"
    )
    conn.execute(LOAD_AUDIT_DDL)


def record_expected_exports(conn: duckdb.DuckDBPyConnection, source: SourceConfig) -> None:
    """Replace the source's rows in expected_exports with the exports its config lists."""
    conn.execute("delete from expected_exports where source = ?", [source.name])
    conn.executemany(
        "insert into expected_exports values (?, ?, ?)",
        [[source.name, export, n] for n, export in enumerate(source.exports, start=1)],
    )


def current_batches(
    conn: duckdb.DuckDBPyConnection, source: SourceConfig
) -> list[tuple[str, str, str, int]]:
    """(export, batch_id, landed_uri, audited rows) for each export's latest batch."""
    rows = conn.execute(
        """
        select export_name, batch_id, landed_uri, row_count
        from ingestion_audit
        where source = ? and status = ?
        qualify row_number() over (partition by export_name order by attempt_id desc) = 1
        """,
        [source.name, audit.LANDED],
    ).fetchall()
    order = {export: n for n, export in enumerate(source.exports)}
    return sorted(rows, key=lambda row: order.get(row[0], len(order)))


def is_loaded(conn: duckdb.DuckDBPyConnection, batch_id: str) -> bool:
    row = conn.execute(
        "select 1 from load_audit where batch_id = ? and status = ?", [batch_id, LOADED]
    ).fetchone()
    return row is not None


def extract_csv(zip_path: Path, dest_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.infolist() if m.filename.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"expected one CSV in {zip_path.name}, found {len(members)}")
        return Path(zf.extract(members[0], dest_dir))


def read_header(csv_path: Path) -> list[str]:
    with csv_path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        return next(csv.reader(f), [])


def _replace_export_rows(
    conn: duckdb.DuckDBPyConnection,
    source: SourceConfig,
    export_name: str,
    batch_id: str,
    csv_path: Path,
) -> int:
    header = read_header(csv_path)
    unexpected = [c for c in header if c not in source.expected_columns]
    if unexpected:
        raise ValueError(f"columns not in the source config: {', '.join(unexpected)}")
    columns = ", ".join(f"'{sql_text(c)}': 'VARCHAR'" for c in header)
    path = sql_text(csv_path.resolve().as_posix())
    table = bronze_table(source)

    conn.execute("begin transaction")
    try:
        conn.execute(f"delete from {table} where export_name = ?", [export_name])
        conn.execute(
            f"insert into {table} by name "
            f"select *, ? as batch_id, ? as export_name "
            f"from read_csv('{path}', {READ_OPTIONS}, columns = {{{columns}}})",
            [batch_id, export_name],
        )
        rows = conn.execute(
            f"select count(*) from {table} where batch_id = ?", [batch_id]
        ).fetchone()[0]
        conn.execute("commit")
    except Exception:
        conn.execute("rollback")
        raise
    return rows


def _record(
    conn: duckdb.DuckDBPyConnection,
    source: SourceConfig,
    export_name: str,
    batch_id: str,
    status: str,
    rows: int | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        "insert or replace into load_audit values (?, ?, ?, ?, ?, ?, ?)",
        [batch_id, source.name, export_name, status, rows, audit.utcnow(), error],
    )


def load_source(
    source: SourceConfig,
    conn: duckdb.DuckDBPyConnection,
    *,
    work_dir: Path,
    log: Callable[[str], None] = print,
) -> list[LoadResult]:
    """Load every export whose current batch isn't in bronze yet, in config order.

    Each CSV is unzipped into a temporary folder inside work_dir and deleted once loaded.
    """
    ensure_tables(conn, source)
    record_expected_exports(conn, source)
    conn.execute(f"set memory_limit = '{os.environ.get('QUERY_CF_MEMORY', '4GB')}'")
    conn.execute("set preserve_insertion_order = false")
    work_dir.mkdir(parents=True, exist_ok=True)

    batches = current_batches(conn, source)
    results = []
    with tempfile.TemporaryDirectory(prefix="load-", dir=work_dir) as tmp:
        for export_name, batch_id, landed_uri, audited_rows in batches:
            if is_loaded(conn, batch_id):
                log(f"  skipped    {export_name} (batch {batch_id} already loaded)")
                results.append(LoadResult(export_name, batch_id, audit.SKIPPED))
                continue
            csv_path = None
            try:
                zip_path = local_copy(landed_uri, Path(tmp))
                csv_path = extract_csv(zip_path, Path(tmp))
                rows = _replace_export_rows(conn, source, export_name, batch_id, csv_path)
            except Exception as exc:
                error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}"
                _record(conn, source, export_name, batch_id, audit.FAILED, error=error)
                log(f"  FAILED     {export_name}: {error}")
                results.append(LoadResult(export_name, batch_id, audit.FAILED, message=error))
                continue
            finally:
                if csv_path:
                    csv_path.unlink(missing_ok=True)

            _record(conn, source, export_name, batch_id, LOADED, rows)
            note = "" if rows == audited_rows else f"; ingestion counted {audited_rows:,}"
            log(f"  loaded     {export_name} ({rows:,} rows{note})")
            results.append(LoadResult(export_name, batch_id, LOADED, rows, note.lstrip("; ")))

    landed = {batch[0] for batch in batches}
    for export_name in source.exports:
        if export_name not in landed:
            log(f"  MISSING    {export_name} (no landed batch; run: python run_pipeline.py ingest)")
            results.append(LoadResult(export_name, "", MISSING, message="no landed batch"))
    return results


def summary(conn: duckdb.DuckDBPyConnection) -> tuple[list[str], list[tuple]]:
    """Every batch load, in the order loaded, as (column names, rows) for printing."""
    exists = conn.execute(
        "select 1 from information_schema.tables where table_name = 'load_audit'"
    ).fetchone()
    if not exists:
        return [], []
    result = conn.execute(
        """
        select source, export_name, status, rows_loaded, batch_id, loaded_at_utc
        from load_audit order by loaded_at_utc
        """
    )
    return [d[0] for d in result.description], result.fetchall()
