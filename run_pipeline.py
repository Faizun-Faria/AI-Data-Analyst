"""Run the Complaint Radar pipeline from one command.

    python run_pipeline.py ingest                 # land every enabled source's exports, in order
    python run_pipeline.py ingest --export CCDB_Export_21_August_2026.zip
    python run_pipeline.py status                 # show the ingestion_audit table

Raw files land in data/raw and the audit table lives in data/warehouse/complaint_radar.duckdb.
Set COMPLAINT_RADAR_RAW=s3://bucket/prefix to land raw files in S3 instead.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from complaint_radar import audit
from complaint_radar.config import DEFAULT_CONFIG_DIR, ConfigError, load_sources
from complaint_radar.ingest import ingest_source
from complaint_radar.storage import open_store

DEFAULT_RAW = os.environ.get("COMPLAINT_RADAR_RAW", "data/raw")
DEFAULT_DB = os.environ.get("COMPLAINT_RADAR_DB", "data/warehouse/complaint_radar.duckdb")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Complaint Radar pipeline")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"DuckDB file (default {DEFAULT_DB})")
    parser.add_argument(
        "--config-dir", type=Path, default=DEFAULT_CONFIG_DIR, help="folder of source configs"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="land exports in the raw zone and audit them")
    ingest.add_argument(
        "--raw",
        default=DEFAULT_RAW,
        help=f"raw zone: a folder or s3://bucket/prefix ({DEFAULT_RAW})",
    )
    ingest.add_argument("--source", action="append", help="only this source (repeatable)")
    ingest.add_argument("--export", action="append", help="only this export file (repeatable)")
    ingest.add_argument(
        "--force",
        action="store_true",
        help="fetch landed exports again; they land again only if their bytes changed",
    )

    commands.add_parser("status", help="show every ingestion attempt")
    return parser


def cmd_ingest(args: argparse.Namespace) -> int:
    sources = load_sources(args.config_dir)
    wanted = args.source or list(sources)
    unknown = sorted(set(wanted) - set(sources))
    if unknown:
        print(f"Unknown source: {', '.join(unknown)}. Known: {', '.join(sources)}")
        return 2
    selected = [sources[name] for name in wanted]

    if args.export:
        known = {e for source in selected for e in source.exports}
        missing = sorted(set(args.export) - known)
        if missing:
            print(f"Not in any selected source's config: {', '.join(missing)}")
            return 2

    store = open_store(args.raw)
    failed = 0
    conn = audit.connect(args.db)
    try:
        for source in selected:
            if not source.enabled:
                print(f"{source.name}: disabled in config, skipped")
                continue
            print(f"{source.name}: {source.description}")
            results = ingest_source(source, store, conn, only=args.export, force=args.force)
            failed += sum(r.status == audit.FAILED for r in results)
    finally:
        conn.close()

    if failed:
        print(f"{failed} export(s) failed; see `python run_pipeline.py status`.")
        return 1
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    conn = audit.connect(args.db)
    try:
        columns, rows = audit.summary(conn)
    finally:
        conn.close()
    if not rows:
        print("No ingestion attempts yet. Run: python run_pipeline.py ingest")
        return 0

    cells = [columns] + [["" if v is None else str(v) for v in row] for row in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(columns))]
    for n, row in enumerate(cells):
        print("  ".join(value.ljust(width) for value, width in zip(row, widths, strict=True)))
        if n == 0:
            print("  ".join("-" * width for width in widths))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ingest":
            return cmd_ingest(args)
        return cmd_status(args)
    except ConfigError as exc:
        print(f"Config error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
