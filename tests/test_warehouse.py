"""Phase 2 end to end on made-up exports with planted problems: ingest, load, dbt build.

Each planted row should land exactly where the design says: quarantined under the rule it
breaks, or kept in the marts with the right flags.
"""

import csv
import io
import zipfile

import duckdb
import pytest

from query_cf import audit, load, transform
from query_cf.config import SourceConfig, load_sources
from query_cf.ingest import ingest_source
from query_cf.storage import LocalStore

COLUMNS = load_sources()["cfpb"].expected_columns
DEFAULTS = {
    "Date received": "2016-08-01",
    "Product": "Credit card",
    "Sub-product": "General-purpose credit card or charge card",
    "Issue": "Billing disputes",
    "Sub-issue": "",
    "Consumer complaint narrative": "",
    "Company public response": "",
    "Company": "Bank A",
    "State": "CA",
    "ZIP code": "90210",
    "Tags": "",
    "Submitted via": "Web",
    "Date sent to company": "2016-08-02",
    "Company response to consumer": "Closed with explanation",
    "Timely response?": "Yes",
}

OLD_EXPORT = [
    {"Complaint ID": "1"},
    {
        "Complaint ID": "2",
        "Product": "Bank account or service",
        "Company": "Wells Fargo",
        "Tags": "Older American, Servicemember",
        "Consumer complaint narrative": 'They opened an account "for me",\nwithout asking.',
    },
    {"Complaint ID": "abc"},
    {"Complaint ID": "4", "Date received": "2016-02-30"},
    {"Complaint ID": "5", "Product": ""},
    {"Complaint ID": "6", "Company": ""},
    {"Complaint ID": "7", "Date received": "2030-01-01"},
    {"Complaint ID": "8", "State": "Ontario"},
    {"Complaint ID": "9", "State": ""},
    {"Complaint ID": "10", "Date sent to company": "2016-07-01"},
    {"Complaint ID": "11", "Issue": ""},
    {"Complaint ID": "12", "Company response to consumer": ""},
    {"Complaint ID": "13", "Company response to consumer": "In progress", "Timely response?": "No"},
    {"Complaint ID": "20", "Company": "Old copy"},
]
NEW_EXPORT = [
    {
        "Complaint ID": "20",
        "Date received": "2021-05-01",
        "Date sent to company": "2021-05-01",
        "Product": "Checking or savings account",
        "Company": "New copy",
    },
    {
        "Complaint ID": "21",
        "Date received": "2026-08-20",
        "Date sent to company": "2026-08-21",
        "Product": "Credit card or prepaid card",
    },
]


def quiet(_message: str) -> None:
    pass


def write_export(path, rows) -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    writer.writerows([[{**DEFAULTS, **row}[c] for c in COLUMNS] for row in rows])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(path.with_suffix(".csv").name, buffer.getvalue())


def build_warehouse(folder, old_rows=OLD_EXPORT, new_rows=NEW_EXPORT, tamper=None):
    """Ingest and load two exports into a fresh warehouse, then run dbt build on it."""
    inbox = folder / "inbox"
    inbox.mkdir()
    write_export(inbox / "CCDB_Export_1_Old.zip", old_rows)
    write_export(inbox / "CCDB_Export_2_New.zip", new_rows)
    source = SourceConfig(
        name="cfpb",
        description="made-up exports",
        enabled=True,
        format="csv_zip",
        base_uri=str(inbox),
        exports=("CCDB_Export_1_Old.zip", "CCDB_Export_2_New.zip"),
        expected_columns=COLUMNS,
    )
    db = folder / "warehouse.duckdb"
    conn = audit.connect(db)
    ingest_source(source, LocalStore(folder / "raw"), conn, log=quiet)
    load.load_source(source, conn, work_dir=folder / "work", log=quiet)
    if tamper:
        conn.execute(tamper)
    conn.close()
    ok = transform.run_dbt(db, target_path=folder / "target", log_path=folder / "logs")
    return db, ok


def query(db, sql):
    conn = duckdb.connect(str(db))
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    db, ok = build_warehouse(tmp_path_factory.mktemp("warehouse"))
    assert ok, "dbt build failed; see the dbt output above"
    return db


def test_each_broken_row_is_quarantined_under_its_rule(warehouse):
    quarantined = query(
        warehouse, "select complaint_id_raw, failed_rule from quality.quarantine_complaints"
    )
    assert sorted(quarantined) == [
        ("20", "complaint_id_duplicate"),
        ("4", "date_received_invalid"),
        ("5", "product_missing"),
        ("6", "company_missing"),
        ("7", "date_received_out_of_range"),
        ("abc", "complaint_id_invalid"),
    ]


def test_a_repeated_complaint_keeps_the_copy_from_the_latest_export(warehouse):
    rows = query(
        warehouse,
        "select c.company_name from marts.fct_complaints f "
        "join marts.dim_company c using (company_key) where f.complaint_id = 20",
    )
    assert rows == [("New copy",)]


def test_soft_issues_stay_in_the_marts_with_flags(warehouse):
    flags = query(
        warehouse,
        "select rule, sum(row_count) from quality.dq_summary where kind = 'flag' group by rule",
    )
    assert dict(flags) == {
        "state_unrecognized": 1,
        "state_missing": 1,
        "sent_before_received": 1,
        "issue_missing": 1,
        "company_response_missing": 1,
    }
    ontario = query(
        warehouse,
        "select state, state_raw, is_state_unrecognized from marts.fct_complaints "
        "where complaint_id = 8",
    )
    assert ontario == [(None, "Ontario", True)]


def test_renamed_products_share_a_group(warehouse):
    groups = query(
        warehouse,
        "select f.complaint_id, p.product_group from marts.fct_complaints f "
        "join marts.dim_product p using (product_key) where f.complaint_id in (2, 20, 21)",
    )
    assert sorted(groups) == [(2, "Bank account"), (20, "Bank account"), (21, "Credit card")]


def test_columns_are_typed_from_the_published_text(warehouse):
    rows = query(
        warehouse,
        "select complaint_id, is_timely_response, response_status, relief_type, "
        "is_older_american, is_servicemember, has_narrative "
        "from marts.fct_complaints where complaint_id in (2, 12, 13) order by complaint_id",
    )
    assert rows == [
        (2, True, "closed", "none", True, True, True),
        (12, True, "unknown", "unknown", False, False, False),
        (13, False, "in progress", "pending", False, False, False),
    ]


def test_narratives_live_in_their_own_table(warehouse):
    assert query(warehouse, "select * from marts.complaint_narratives") == [
        (2, OLD_EXPORT[1]["Consumer complaint narrative"])
    ]


def test_every_batch_adds_up(warehouse):
    rows = query(
        warehouse,
        "select export_name, audited_rows, loaded_rows, fact_rows, quarantined_rows, is_complete "
        "from quality.completeness_by_batch order by export_name",
    )
    assert rows == [
        ("CCDB_Export_1_Old.zip", 14, 14, 8, 6, True),
        ("CCDB_Export_2_New.zip", 2, 2, 2, 0, True),
    ]
    assert transform.incomplete_batches(warehouse) == []


def test_a_product_missing_from_the_groups_file_fails_the_build(tmp_path):
    _, ok = build_warehouse(tmp_path, new_rows=[{"Complaint ID": "30", "Product": "Brand-new"}])
    assert not ok


def test_a_lost_row_fails_the_build_and_names_its_batch(tmp_path):
    db, ok = build_warehouse(
        tmp_path,
        tamper="""delete from bronze.cfpb_complaints where "Complaint ID" = '1'""",
    )
    assert not ok
    assert [row[1] for row in transform.incomplete_batches(db)] == ["CCDB_Export_1_Old.zip"]


def test_an_export_that_never_landed_fails_the_build_and_is_named(tmp_path):
    db, ok = build_warehouse(
        tmp_path,
        tamper="""
            delete from ingestion_audit where export_name = 'CCDB_Export_2_New.zip';
            delete from bronze.cfpb_complaints where export_name = 'CCDB_Export_2_New.zip';
        """,
    )
    assert not ok
    assert transform.incomplete_batches(db) == [(None, "CCDB_Export_2_New.zip", 0, 0, 0, 0)]
