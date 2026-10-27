"""Phase 1: land each export in the raw zone and record it in ingestion_audit.

Exports are replayed in the order the source config lists them, one batch per export,
as if each were a new delivery. A run is safe to repeat: an export that already landed
is skipped, and with force=True it is fetched again but lands only if its bytes changed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import tempfile
import zipfile
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import requests

from complaint_radar import audit
from complaint_radar.config import SourceConfig
from complaint_radar.storage import RawStore

CHUNK_BYTES = 1 << 20
# Narratives can run long; the csv module's default 128 KB field limit is too small.
csv.field_size_limit(16 * 1024 * 1024)


@dataclass(frozen=True)
class ZipProfile:
    row_count: int
    columns: tuple[str, ...]
    extract_ts: datetime


@dataclass(frozen=True)
class BatchResult:
    export_name: str
    status: str
    batch_id: str | None = None
    row_count: int | None = None
    message: str = ""


def _chunks(location: str) -> Iterator[bytes]:
    if location.startswith(("http://", "https://")):
        with requests.get(location, stream=True, timeout=(10, 300)) as response:
            response.raise_for_status()
            yield from response.iter_content(CHUNK_BYTES)
    else:
        with open(location, "rb") as f:
            while chunk := f.read(CHUNK_BYTES):
                yield chunk


def fetch(location: str, dest: Path) -> tuple[str, int]:
    """Download or copy location to dest; return its SHA-256 and size in bytes."""
    digest = hashlib.sha256()
    size = 0
    with dest.open("wb") as out:
        for chunk in _chunks(location):
            digest.update(chunk)
            out.write(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def profile_zip(path: Path) -> ZipProfile:
    """Read the export's header, count its data rows and take its extract time.

    Rows are counted with the csv module rather than by lines, because narratives hold
    line breaks inside quoted fields.
    """
    with zipfile.ZipFile(path) as zf:
        members = [m for m in zf.infolist() if m.filename.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"expected one CSV in the zip, found {len(members)}")
        member = members[0]
        with zf.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
            reader = csv.reader(text)
            header = next(reader, None)
            if not header:
                raise ValueError(f"{member.filename} has no header row")
            row_count = sum(1 for _ in reader)
    return ZipProfile(row_count, tuple(header), datetime(*member.date_time))


def ingest_source(
    source: SourceConfig,
    store: RawStore,
    conn: duckdb.DuckDBPyConnection,
    *,
    only: Collection[str] | None = None,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> list[BatchResult]:
    """Land the source's exports in config order; only= limits it to those file names."""
    return [
        _ingest_export(source, export, store, conn, force=force, log=log)
        for export in source.exports
        if not only or export in only
    ]


def _ingest_export(
    source: SourceConfig,
    export: str,
    store: RawStore,
    conn: duckdb.DuckDBPyConnection,
    *,
    force: bool,
    log: Callable[[str], None],
) -> BatchResult:
    if not force and audit.has_landed(conn, source.name, export):
        log(f"  skipped    {export} (already landed)")
        return BatchResult(export, audit.SKIPPED)

    location = source.location(export)
    attempt_id = audit.start_attempt(conn, source.name, export, location)
    try:
        with tempfile.TemporaryDirectory(prefix="complaint-radar-") as tmp:
            local = Path(tmp) / export
            sha256, size = fetch(location, local)

            existing = audit.landed_batch(conn, source.name, sha256)
            if existing:
                audit.finish_attempt(
                    conn,
                    attempt_id,
                    status=audit.UNCHANGED,
                    batch_id=existing,
                    sha256=sha256,
                    byte_size=size,
                )
                log(f"  unchanged  {export} (same bytes as {existing})")
                return BatchResult(export, audit.UNCHANGED, existing)

            profile = profile_zip(local)
            batch_id = audit.make_batch_id(source.name, sha256)
            landed_uri = store.put(local, f"{source.name}/{batch_id}/{export}")
    except Exception as exc:
        # Record every failure and move on to the next export; the run exits non-zero.
        error = f"{type(exc).__name__}: {exc}"
        audit.finish_attempt(conn, attempt_id, status=audit.FAILED, error=error)
        log(f"  FAILED     {export}: {error}")
        return BatchResult(export, audit.FAILED, message=error)

    columns_match = not source.expected_columns or profile.columns == source.expected_columns
    audit.finish_attempt(
        conn,
        attempt_id,
        status=audit.LANDED,
        batch_id=batch_id,
        landed_uri=landed_uri,
        sha256=sha256,
        byte_size=size,
        row_count=profile.row_count,
        column_count=len(profile.columns),
        columns_match=columns_match,
        extract_ts=profile.extract_ts,
    )
    note = "" if columns_match else "; columns differ from config"
    log(f"  landed     {export} ({profile.row_count:,} rows, batch {batch_id}{note})")
    return BatchResult(export, audit.LANDED, batch_id, profile.row_count, note.lstrip("; "))
