"""Run the QueryCF pipeline from one command.

    python run_pipeline.py ingest      # phase 1: land every enabled source's exports, in order
    python run_pipeline.py load        # phase 2: copy each landed batch into bronze
    python run_pipeline.py transform   # phase 2: dbt builds and tests the warehouse
    python run_pipeline.py all         # ingest, load and transform in one go
    python run_pipeline.py status      # show every ingestion attempt and batch load

    python run_pipeline.py ingest --export CCDB_Export_21_August_2026.zip

Raw files land in data/raw; the audit tables and the warehouse live in
data/warehouse/query_cf.duckdb. Set QUERY_CF_RAW=s3://bucket/prefix to land
raw files in S3 instead.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from query_cf import audit, load
from query_cf.config import DEFAULT_CONFIG_DIR, ConfigError, load_sources
from query_cf.ingest import ingest_source
from query_cf.storage import open_store

DEFAULT_RAW = os.environ.get("QUERY_CF_RAW", "data/raw")
DEFAULT_DB = os.environ.get("QUERY_CF_DB", "data/warehouse/query_cf.duckdb")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QueryCF pipeline")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"DuckDB file (default {DEFAULT_DB})")
    parser.add_argument(
        "--config-dir", type=Path, default=DEFAULT_CONFIG_DIR, help="folder of source configs"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    raw = argparse.ArgumentParser(add_help=False)
    raw.add_argument(
        "--raw",
        default=DEFAULT_RAW,
        help=f"raw zone: a folder or s3://bucket/prefix ({DEFAULT_RAW})",
    )

    ingest = commands.add_parser(
        "ingest", parents=[raw], help="land exports in the raw zone and audit them"
    )
    ingest.add_argument("--source", action="append", help="only this source (repeatable)")
    ingest.add_argument("--export", action="append", help="only this export file (repeatable)")
    ingest.add_argument(
        "--force",
        action="store_true",
        help="fetch landed exports again; they land again only if their bytes changed",
    )

    commands.add_parser("load", help="copy each landed batch into the bronze table")
    transform = commands.add_parser("transform", help="build and test the warehouse with dbt")
    transform.add_argument("--select", help="only these dbt models (dbt selection syntax)")
    commands.add_parser("all", parents=[raw], help="ingest, load and transform")
    commands.add_parser("status", help="show every ingestion attempt and batch load")
    return parser


def enabled_sources(args: argparse.Namespace) -> list:
    return [s for s in load_sources(args.config_dir).values() if s.enabled]


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


def cmd_load(args: argparse.Namespace) -> int:
    failed = 0
    conn = audit.connect(args.db)
    try:
        for source in enabled_sources(args):
            print(f"{source.name}: loading into {load.bronze_table(source)}")
            results = load.load_source(source, conn, work_dir=Path(args.db).parent)
            failed += sum(r.status == audit.FAILED for r in results)
    finally:
        conn.close()

    if failed:
        print(f"{failed} batch(es) failed to load; see `python run_pipeline.py status`.")
        return 1
    return 0


def cmd_transform(args: argparse.Namespace) -> int:
    from query_cf import transform  # imports dbt, which takes a few seconds

    dbt_args = ["build"] + (["--select", args.select] if args.select else [])
    ok = transform.run_dbt(args.db, dbt_args)
    incomplete = transform.incomplete_batches(args.db)
    for batch_id, export, audited, loaded, in_marts, quarantined in incomplete:
        print(
            f"INCOMPLETE {export} (batch {batch_id}): audited {audited:,}, loaded {loaded:,}, "
            f"in marts {in_marts:,} + quarantined {quarantined:,}"
        )
    return 0 if ok and not incomplete else 1


def cmd_all(args: argparse.Namespace) -> int:
    args.source, args.export, args.force, args.select = None, None, False, None
    for step in (cmd_ingest, cmd_load, cmd_transform):
        if code := step(args):
            return code
    return 0


def print_table(columns: list[str], rows: list[tuple]) -> None:
    cells = [columns] + [["" if v is None else str(v) for v in row] for row in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(columns))]
    for n, row in enumerate(cells):
        print("  ".join(value.ljust(width) for value, width in zip(row, widths, strict=True)))
        if n == 0:
            print("  ".join("-" * width for width in widths))


def cmd_status(args: argparse.Namespace) -> int:
    conn = audit.connect(args.db)
    try:
        attempts = audit.summary(conn)
        loads = load.summary(conn)
    finally:
        conn.close()
    if not attempts[1]:
        print("No ingestion attempts yet. Run: python run_pipeline.py ingest")
        return 0

    print("Ingestion attempts")
    print_table(*attempts)
    print("\nBatch loads")
    if loads[1]:
        print_table(*loads)
    else:
        print("None yet. Run: python run_pipeline.py load")
    return 0


COMMANDS = {
    "ingest": cmd_ingest,
    "load": cmd_load,
    "transform": cmd_transform,
    "all": cmd_all,
    "status": cmd_status,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except ConfigError as exc:
        print(f"Config error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
