"""The ingestion_audit table: one row per attempt to land an export.

An attempt gets its row the moment it starts (status 'running'), so a crash still leaves
a trace. A landed export carries a batch_id derived from its SHA-256, and the pipeline
checks it before landing, so the same bytes never land twice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb

RUNNING = "running"
LANDED = "landed"
UNCHANGED = "unchanged"  # fetched again with --force, but the bytes match a landed batch
FAILED = "failed"
SKIPPED = "skipped"  # already landed; no row is written for a skip

DDL = """
create sequence if not exists ingestion_attempt_seq start 1;

create table if not exists ingestion_audit (
    attempt_id      bigint primary key default nextval('ingestion_attempt_seq'),
    source          varchar not null,
    export_name     varchar not null,
    source_uri      varchar not null,
    status          varchar not null,
    batch_id        varchar,
    landed_uri      varchar,
    sha256          varchar,
    byte_size       bigint,
    row_count       bigint,
    column_count    integer,
    columns_match   boolean,
    extract_ts      timestamp,
    started_at_utc  timestamp not null,
    finished_at_utc timestamp,
    error           varchar
);
"""


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def connect(db_path: str | Path) -> duckdb.DuckDBPyConnection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    conn.execute(DDL)
    return conn


def make_batch_id(source: str, sha256: str) -> str:
    return f"{source}-{sha256[:16]}"


def start_attempt(
    conn: duckdb.DuckDBPyConnection, source: str, export_name: str, source_uri: str
) -> int:
    row = conn.execute(
        """
        insert into ingestion_audit (source, export_name, source_uri, status, started_at_utc)
        values (?, ?, ?, ?, ?)
        returning attempt_id
        """,
        [source, export_name, source_uri, RUNNING, utcnow()],
    ).fetchone()
    return row[0]


def finish_attempt(
    conn: duckdb.DuckDBPyConnection,
    attempt_id: int,
    *,
    status: str,
    batch_id: str | None = None,
    landed_uri: str | None = None,
    sha256: str | None = None,
    byte_size: int | None = None,
    row_count: int | None = None,
    column_count: int | None = None,
    columns_match: bool | None = None,
    extract_ts: datetime | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        update ingestion_audit
        set status = ?, batch_id = ?, landed_uri = ?, sha256 = ?, byte_size = ?,
            row_count = ?, column_count = ?, columns_match = ?, extract_ts = ?,
            error = ?, finished_at_utc = ?
        where attempt_id = ?
        """,
        [
            status,
            batch_id,
            landed_uri,
            sha256,
            byte_size,
            row_count,
            column_count,
            columns_match,
            extract_ts,
            error,
            utcnow(),
            attempt_id,
        ],
    )


def has_landed(conn: duckdb.DuckDBPyConnection, source: str, export_name: str) -> bool:
    row = conn.execute(
        "select 1 from ingestion_audit where source = ? and export_name = ? and status = ? limit 1",
        [source, export_name, LANDED],
    ).fetchone()
    return row is not None


def landed_batch(conn: duckdb.DuckDBPyConnection, source: str, sha256: str) -> str | None:
    """The batch_id that already holds these exact bytes, if any."""
    row = conn.execute(
        "select batch_id from ingestion_audit where source = ? and sha256 = ? and status = ? "
        "limit 1",
        [source, sha256, LANDED],
    ).fetchone()
    return row[0] if row else None


def summary(conn: duckdb.DuckDBPyConnection) -> tuple[list[str], list[tuple]]:
    """Every attempt, oldest first, as (column names, rows) for printing."""
    result = conn.execute(
        """
        select attempt_id, source, export_name, status, row_count,
               round(byte_size / 1e6, 1) as mb, columns_match, batch_id, finished_at_utc
        from ingestion_audit
        order by attempt_id
        """
    )
    return [d[0] for d in result.description], result.fetchall()
