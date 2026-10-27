"""Profile every landed CFPB export before modelling it.

The warehouse models in phase 2 depend on facts about the data that nobody has checked
yet: does every file parse, do the row counts match the audit, which date formats
appear, are Complaint IDs whole numbers and unique across exports, how often key fields
are empty, and which categories exist. This script answers those questions.

It reads ingestion_audit to find each export's latest landed batch, extracts its CSV to a
temporary folder one export at a time (deleting it afterwards), loads the columns it needs
into data/profile/profile.duckdb, and writes the findings to docs/04-data-profile.md.

    python scripts/profile_exports.py
    python scripts/profile_exports.py --limit 2      # a quick try on the first two exports
"""

from __future__ import annotations

import argparse
import csv
import re
import tempfile
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent

# The 16 columns of the archive exports, and the short names this script stores them as.
# The narrative itself isn't stored, only its length.
COLUMNS = {
    "Date received": "date_received",
    "Product": "product",
    "Sub-product": "sub_product",
    "Issue": "issue",
    "Sub-issue": "sub_issue",
    "Consumer complaint narrative": "narrative_len",
    "Company public response": "company_public_response",
    "Company": "company",
    "State": "state",
    "ZIP code": "zip_code",
    "Tags": "tags",
    "Submitted via": "submitted_via",
    "Date sent to company": "date_sent",
    "Company response to consumer": "company_response",
    "Timely response?": "timely_response",
    "Complaint ID": "complaint_id",
}
ARCHIVE_START, ARCHIVE_END = date(2011, 12, 1), date(2026, 8, 14)
READ_OPTIONS = (
    "header = true, all_varchar = true, delim = ',', quote = '\"', escape = '\"', "
    "max_line_size = 10000000"
)

SETUP_SQL = """
set memory_limit = '3GB';
set preserve_insertion_order = false;

create or replace table profile_rows (
    export_no integer, date_received varchar, product varchar, sub_product varchar,
    issue varchar, sub_issue varchar, narrative_len integer, company_public_response varchar,
    company varchar, state varchar, zip_code varchar, tags varchar, submitted_via varchar,
    date_sent varchar, company_response varchar, timely_response varchar, complaint_id varchar
);

create or replace macro date_format(d) as
    case
        when d is null or trim(d) = '' then 'empty'
        when regexp_full_match(d, '\\d{4}-\\d{2}-\\d{2}') then 'YYYY-MM-DD'
        when regexp_full_match(d, '\\d{1,2}/\\d{1,2}/\\d{4}') then 'MM/DD/YYYY'
        when regexp_full_match(d, '\\d{1,2}/\\d{1,2}/\\d{2}') then 'MM/DD/YY'
        else 'other'
    end;

create or replace macro parse_date(d) as
    case date_format(d)
        when 'YYYY-MM-DD' then try_strptime(d, '%Y-%m-%d')
        when 'MM/DD/YYYY' then try_strptime(d, '%m/%d/%Y')
        when 'MM/DD/YY' then try_strptime(d, '%m/%d/%y')
    end::date;

create or replace macro is_empty(v) as v is null or trim(v) = '';
"""


def sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def export_number(name: str) -> int:
    match = re.search(r"Export_(\d+)_", name)
    return int(match.group(1)) if match else 0


def landed_exports(audit_db: Path) -> list[tuple[int, str, Path, int]]:
    """(export number, name, zip path, audited row count) for each export's latest batch."""
    with duckdb.connect(str(audit_db), read_only=True) as conn:
        rows = conn.execute(
            """
            select export_name, landed_uri, row_count
            from ingestion_audit
            where source = 'cfpb' and status = 'landed'
            qualify row_number() over (partition by export_name order by attempt_id desc) = 1
            """
        ).fetchall()
    return sorted((export_number(name), name, Path(uri), count) for name, uri, count in rows)


def extract_csv(zip_path: Path, tmp_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.infolist() if m.filename.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"expected one CSV in {zip_path.name}, found {len(members)}")
        return Path(zf.extract(members[0], tmp_dir))


def read_header(csv_path: Path) -> list[str]:
    with csv_path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        return next(csv.reader(f), [])


def load_export(conn: duckdb.DuckDBPyConnection, export_no: int, csv_path: Path) -> dict:
    """Load one export's columns into profile_rows; report what didn't fit."""
    # The header is read here and handed to DuckDB, so a malformed row further down
    # can't stop DuckDB from working out the file's layout.
    header = read_header(csv_path)
    columns = ", ".join(f"'{c.replace(chr(39), chr(39) * 2)}': 'VARCHAR'" for c in header)
    options = f"{READ_OPTIONS}, auto_detect = false, columns = {{{columns}}}"
    source = f"read_csv('{sql_path(csv_path)}', {options})"
    lenient = (
        f"read_csv('{sql_path(csv_path)}', {options}, ignore_errors = true, store_rejects = true)"
    )
    present = set(header)
    select = ", ".join(
        (f'length("{col}")' if short == "narrative_len" else f'"{col}"') + f" as {short}"
        if col in present
        else f"null as {short}"
        for col, short in COLUMNS.items()
    )
    result = {
        "missing_columns": [c for c in COLUMNS if c not in present],
        "extra_columns": [c for c in header if c not in COLUMNS],
        "parse_error": "",
        "rejected_rows": 0,
        "reject_examples": [],
    }
    insert = f"insert into profile_rows by name select {export_no} as export_no, {select} from "
    try:
        conn.execute(insert + source)
    except duckdb.Error as exc:
        # Strict parsing failed: note why, then load what parses and count what doesn't.
        result["parse_error"] = str(exc).splitlines()[0][:300]
        conn.execute(f"delete from profile_rows where export_no = {export_no}")
        conn.execute("drop table if exists reject_errors; drop table if exists reject_scans;")
        conn.execute(insert + lenient)
        result["rejected_rows"] = conn.execute("select count(*) from reject_errors").fetchone()[0]
        result["reject_examples"] = conn.execute(
            "select line, error_type, left(error_message, 160) from reject_errors limit 3"
        ).fetchall()
    return result


def table(headers: list[str], rows) -> str:
    def cell(value) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, int):
            return f"{value:,}"
        if isinstance(value, float):
            return f"{value:,.1f}"
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(headers) + " |", "|" + " --- |" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def build_report(conn: duckdb.DuckDBPyConnection, loads: list[dict]) -> str:
    def q(sql: str) -> list[tuple]:
        return conn.execute(sql).fetchall()

    total = q("select count(*) from profile_rows")[0][0]
    out = [
        "# Data profile: CFPB archive exports",
        "",
        f"Generated by `scripts/profile_exports.py` on {datetime.now():%Y-%m-%d %H:%M} "
        f"from {len(loads)} landed exports, {total:,} rows. Don't edit by hand: re-run the "
        "script instead.",
        "",
        "## 1. Did every export parse, with the audited row count?",
        "",
    ]
    per_export = {
        r[0]: r
        for r in q(
            """
            select export_no, count(*),
                   min(parse_date(date_received)), max(parse_date(date_received)),
                   string_agg(distinct date_format(date_received), ', '),
                   100.0 * count(*) filter (where narrative_len > 0) / count(*)
            from profile_rows group by export_no
            """
        )
    }
    rows = []
    for load in loads:
        stats = per_export.get(load["export_no"], (None, 0, None, None, "", None))
        rows.append(
            (
                load["export_no"],
                load["audit_rows"],
                stats[1],
                stats[1] == load["audit_rows"] and not load["rejected_rows"],
                load["rejected_rows"],
                ", ".join(load["missing_columns"]) or "none",
                ", ".join(load["extra_columns"]) or "none",
                stats[2],
                stats[3],
                stats[4],
                stats[5],
            )
        )
    out.append(
        table(
            [
                "Export",
                "Audited rows",
                "Parsed rows",
                "Match",
                "Rejected rows",
                "Missing columns",
                "Extra columns",
                "First received",
                "Last received",
                "Date formats",
                "% with narrative",
            ],
            rows,
        )
    )
    errors = [ld for ld in loads if ld["parse_error"] or ld["error"]]
    out += ["", "Parse errors:" if errors else "No export failed strict parsing.", ""]
    for ld in errors:
        out.append(f"- Export {ld['export_no']}: {ld['error'] or ld['parse_error']}")
        out += [f"  - line {line}, {kind}: {msg}" for line, kind, msg in ld["reject_examples"]]

    out += ["", "## 2. Date formats", ""]
    out.append(
        table(
            ["Column", "Format", "Rows"],
            q(
                """
                select 'Date received', date_format(date_received) f, count(*) from profile_rows
                group by f
                union all
                select 'Date sent to company', date_format(date_sent) f, count(*) from profile_rows
                group by f
                order by 1, 3 desc
                """
            ),
        )
    )
    odd = q(
        """
        select distinct date_received from profile_rows where date_format(date_received) = 'other'
        union
        select distinct date_sent from profile_rows where date_format(date_sent) = 'other'
        limit 8
        """
    )
    out += ["", f"Examples of 'other' formats: {', '.join(repr(r[0]) for r in odd) or 'none'}."]
    checks = q(
        f"""
        select
            count(*) filter (where date_format(date_received) not in ('empty', 'other')
                             and parse_date(date_received) is null),
            count(*) filter (where parse_date(date_received) < date '{ARCHIVE_START}'),
            count(*) filter (where parse_date(date_received) > date '{ARCHIVE_END}'),
            count(*) filter (where parse_date(date_sent) < parse_date(date_received))
        from profile_rows
        """
    )[0]
    out += [
        "",
        table(
            ["Check", "Rows"],
            [
                ("Date received looks like a date but isn't valid (e.g. 2020-02-30)", checks[0]),
                (f"Date received before {ARCHIVE_START} (the archive's stated start)", checks[1]),
                (f"Date received after {ARCHIVE_END} (the archive's stated end)", checks[2]),
                ("Date sent to company earlier than date received", checks[3]),
            ],
        ),
        "",
        "Rows by year received:",
        "",
        table(
            ["Year", "Rows", "Exports"],
            q(
                """
                select coalesce(year(parse_date(date_received))::varchar, '(no valid date)') y,
                       count(*),
                       string_agg(distinct export_no::varchar, ', ')
                from profile_rows group by y order by y
                """
            ),
        ),
    ]

    out += ["", "## 3. Complaint IDs", ""]
    ids = q(
        """
        with counted as (
            select complaint_id, count(*) n, count(distinct export_no) exports,
                   count(distinct hash(parse_date(date_received), product, sub_product, issue,
                                       sub_issue, company, state, company_response,
                                       timely_response)) variants
            from profile_rows where not is_empty(complaint_id) group by complaint_id
        )
        select
            (select count(*) from profile_rows where is_empty(complaint_id)),
            (select count(*) from profile_rows
             where not is_empty(complaint_id) and not regexp_full_match(complaint_id, '\\d+')),
            count(*) filter (where n > 1),
            count(*) filter (where n > 1 and exports = 1),
            count(*) filter (where exports > 1),
            count(*) filter (where n > 1 and variants = 1),
            count(*) filter (where n > 1 and variants > 1)
        from counted
        """
    )[0]
    out.append(
        table(
            ["Check", "Count"],
            [
                ("Rows with an empty Complaint ID", ids[0]),
                ("Rows whose Complaint ID isn't a whole number", ids[1]),
                ("Complaint IDs that appear more than once", ids[2]),
                ("... repeated within a single export", ids[3]),
                ("... appearing in more than one export", ids[4]),
                ("... whose repeats are identical in every compared column", ids[5]),
                ("... whose repeats differ (e.g. an updated company response)", ids[6]),
            ],
        )
    )
    pairs = q(
        """
        with dup as (
            select complaint_id, export_no from profile_rows
            where complaint_id in (
                select complaint_id from profile_rows where not is_empty(complaint_id)
                group by complaint_id having count(distinct export_no) > 1)
        )
        select a.export_no, b.export_no, count(distinct a.complaint_id)
        from dup a join dup b on a.complaint_id = b.complaint_id and a.export_no < b.export_no
        group by all order by 3 desc limit 10
        """
    )
    if pairs:
        out += ["", "Exports that share Complaint IDs (top 10 pairs):", ""]
        out.append(table(["Export", "Shares IDs with export", "Shared IDs"], pairs))
    examples = q(
        """
        select complaint_id, export_no, date_received, product, company_response, timely_response
        from profile_rows
        where complaint_id in (
            select complaint_id from profile_rows where not is_empty(complaint_id)
            group by complaint_id
            having count(distinct hash(parse_date(date_received), product, sub_product, issue,
                                       sub_issue, company, state, company_response,
                                       timely_response)) > 1
            order by complaint_id limit 3)
        order by complaint_id, export_no
        """
    )
    if examples:
        out += ["", "Examples of repeats that differ:", ""]
        out.append(
            table(
                ["Complaint ID", "Export", "Received", "Product", "Response", "Timely"],
                examples,
            )
        )

    out += ["", "## 4. Empty values", ""]
    shorts = [s for s in COLUMNS.values() if s != "narrative_len"]
    empties = q(
        "select "
        + ", ".join(f"count(*) filter (where is_empty({s}))" for s in shorts)
        + " from profile_rows"
    )[0]
    names = [c for c, s in COLUMNS.items() if s != "narrative_len"]
    out.append(
        table(
            ["Column", "Empty rows", "% empty"],
            [
                (c, n, 100.0 * n / total if total else 0.0)
                for c, n in zip(names, empties, strict=True)
            ],
        )
    )

    out += ["", "## 5. Products over time", ""]
    out.append(
        table(
            ["Product", "Rows", "First received", "Last received"],
            q(
                """
                select coalesce(nullif(trim(product), ''), '(empty)'), count(*),
                       min(parse_date(date_received)),
                       max(parse_date(date_received))
                from profile_rows group by 1 order by 2 desc
                """
            ),
        )
    )

    out += ["", "## 6. Other categories", ""]
    for column, short in [
        ("Timely response?", "timely_response"),
        ("Submitted via", "submitted_via"),
        ("Company response to consumer", "company_response"),
        ("Tags", "tags"),
        ("Company public response", "company_public_response"),
    ]:
        values = q(
            f"select coalesce(nullif(trim({short}), ''), '(empty)'), count(*) from profile_rows "
            "group by 1 order by 2 desc limit 15"
        )
        out += [f"**{column}** (top 15)", "", table(["Value", "Rows"], values), ""]
    counts = q(
        """
        select count(distinct product), count(distinct sub_product), count(distinct issue),
               count(distinct sub_issue), count(distinct company), count(distinct state),
               count(*) filter (where not is_empty(state)
                                and not regexp_full_match(state, '[A-Z]{2}'))
        from profile_rows
        """
    )[0]
    out.append(
        table(
            ["Distinct values", "Count"],
            [
                ("Products", counts[0]),
                ("Sub-products", counts[1]),
                ("Issues", counts[2]),
                ("Sub-issues", counts[3]),
                ("Companies", counts[4]),
                ("States", counts[5]),
                ("Rows whose State isn't two capital letters", counts[6]),
            ],
        )
    )

    out += ["", "## 7. Narratives", ""]
    narr = q(
        """
        select count(*) filter (where narrative_len > 0),
               100.0 * count(*) filter (where narrative_len > 0) / count(*),
               median(narrative_len) filter (where narrative_len > 0),
               quantile_cont(narrative_len, 0.99) filter (where narrative_len > 0),
               max(narrative_len)
        from profile_rows
        """
    )[0]
    out.append(
        table(
            ["Measure", "Value"],
            [
                ("Rows with a narrative", narr[0]),
                ("% of rows with a narrative", narr[1]),
                ("Median length (characters)", narr[2]),
                ("99th percentile length", narr[3]),
                ("Longest narrative", narr[4]),
            ],
        )
    )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile the landed CFPB exports")
    parser.add_argument("--db", type=Path, default=ROOT / "data/warehouse/complaint_radar.duckdb")
    parser.add_argument("--profile-db", type=Path, default=ROOT / "data/profile/profile.duckdb")
    parser.add_argument("--out", type=Path, default=ROOT / "docs/04-data-profile.md")
    parser.add_argument("--limit", type=int, help="only the first N exports")
    args = parser.parse_args(argv)

    exports = landed_exports(args.db)[: args.limit]
    if not exports:
        print("No landed exports in ingestion_audit. Run: python run_pipeline.py ingest")
        return 1
    args.profile_db.parent.mkdir(parents=True, exist_ok=True)

    loads = []
    flagged = 0
    # Each CSV is extracted next to the profile database (same drive) and deleted after use.
    with (
        tempfile.TemporaryDirectory(prefix="extract-", dir=args.profile_db.parent) as tmp,
        duckdb.connect(str(args.profile_db)) as conn,
    ):
        conn.execute(SETUP_SQL)
        for export_no, name, zip_path, audit_rows in exports:
            started = time.perf_counter()
            load = {
                "export_no": export_no,
                "audit_rows": audit_rows,
                "error": "",
                "missing_columns": [],
                "extra_columns": [],
                "parse_error": "",
                "rejected_rows": 0,
                "reject_examples": [],
            }
            csv_path = None
            try:
                csv_path = extract_csv(zip_path, Path(tmp))
                load |= load_export(conn, export_no, csv_path)
            except Exception as exc:
                load["error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}"
                conn.execute(f"delete from profile_rows where export_no = {export_no}")
            finally:
                if csv_path:
                    csv_path.unlink(missing_ok=True)
            loads.append(load)
            parsed = conn.execute(
                f"select count(*) from profile_rows where export_no = {export_no}"
            ).fetchone()[0]
            ok = parsed == audit_rows and not load["error"] and not load["rejected_rows"]
            flagged += not ok
            print(
                f"  export {export_no:>2}  {parsed:>10,} rows  (audit {audit_rows:,})  "
                f"{time.perf_counter() - started:5.1f}s  {'ok' if ok else 'CHECK'}  {name}"
            )
        report = build_report(conn, loads)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"\n{len(loads)} exports profiled, {flagged} flagged CHECK.")
    print(f"Report written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
