import hashlib
import zipfile
from pathlib import Path

from conftest import HEADER, ROWS, write_export
from query_cf import audit
from query_cf.ingest import ingest_source, profile_zip


def quiet(_message: str) -> None:
    pass


def attempts(conn, columns="export_name, status"):
    return conn.execute(f"select {columns} from ingestion_audit order by attempt_id").fetchall()


def test_profile_counts_records_not_lines(inbox):
    profile = profile_zip(inbox / "export_1.zip")
    assert profile.row_count == 3
    assert profile.columns == HEADER


def test_lands_each_export_in_config_order_with_audit_details(source, store, conn, inbox):
    results = ingest_source(source, store, conn, log=quiet)

    assert [(r.export_name, r.status) for r in results] == [
        ("export_1.zip", "landed"),
        ("export_2.zip", "landed"),
    ]
    first = attempts(
        conn,
        "row_count, sha256, byte_size, landed_uri, batch_id, columns_match, column_count, "
        "extract_ts, finished_at_utc",
    )[0]
    data = (inbox / "export_1.zip").read_bytes()
    row_count, sha256, byte_size, landed_uri, batch_id, columns_match, column_count, *times = first
    assert row_count == 3
    assert sha256 == hashlib.sha256(data).hexdigest()
    assert byte_size == len(data)
    assert Path(landed_uri).read_bytes() == data
    assert batch_id == f"test-{sha256[:16]}"
    assert columns_match is True
    assert column_count == len(HEADER)
    assert all(times)


def test_rerun_skips_landed_exports_without_new_rows(source, store, conn):
    ingest_source(source, store, conn, log=quiet)
    results = ingest_source(source, store, conn, log=quiet)

    assert [r.status for r in results] == ["skipped", "skipped"]
    assert len(attempts(conn)) == 2


def test_force_refetches_but_unchanged_bytes_do_not_land_again(source, store, conn, raw_dir):
    first = ingest_source(source, store, conn, log=quiet)
    again = ingest_source(source, store, conn, force=True, log=quiet)

    assert [r.status for r in again] == ["unchanged", "unchanged"]
    assert [r.batch_id for r in again] == [r.batch_id for r in first]
    assert [s for _, s in attempts(conn)].count("landed") == 2
    assert len(list(raw_dir.rglob("*.zip"))) == 2


def test_force_lands_a_new_batch_when_bytes_change(source, store, conn, inbox):
    first = ingest_source(source, store, conn, log=quiet)
    write_export(inbox / "export_2.zip", ROWS)  # upstream file replaced

    again = ingest_source(source, store, conn, only={"export_2.zip"}, force=True, log=quiet)

    assert [r.status for r in again] == ["landed"]
    assert again[0].batch_id != first[1].batch_id
    assert again[0].row_count == 3


def test_corrupt_export_fails_without_landing_then_retries(source, store, conn, inbox, raw_dir):
    good = (inbox / "export_2.zip").read_bytes()
    (inbox / "export_2.zip").write_bytes(b"not a zip file")

    results = ingest_source(source, store, conn, log=quiet)

    assert [r.status for r in results] == ["landed", "failed"]
    assert "BadZipFile" in results[1].message
    error = attempts(conn, "error")[1][0]
    assert error.startswith("BadZipFile")
    assert not list(raw_dir.rglob("export_2.zip"))

    (inbox / "export_2.zip").write_bytes(good)
    retry = ingest_source(source, store, conn, log=quiet)
    assert [r.status for r in retry] == ["skipped", "landed"]


def test_missing_export_is_recorded_as_failed(source, store, conn, inbox):
    (inbox / "export_1.zip").unlink()

    results = ingest_source(source, store, conn, log=quiet)

    assert [r.status for r in results] == ["failed", "landed"]
    assert attempts(conn, "status, error")[0][1].startswith("FileNotFoundError")


def test_column_drift_still_lands_but_is_flagged(source, store, conn, inbox):
    write_export(inbox / "export_2.zip", [r[:4] for r in ROWS], header=HEADER[:4])

    results = ingest_source(source, store, conn, log=quiet)

    assert [r.status for r in results] == ["landed", "landed"]
    assert [m for (m,) in attempts(conn, "columns_match")] == [True, False]


def test_zip_without_exactly_one_csv_fails(source, store, conn, inbox):
    with zipfile.ZipFile(inbox / "export_2.zip", "w") as zf:
        zf.writestr("a.csv", ",".join(HEADER))
        zf.writestr("b.csv", ",".join(HEADER))

    results = ingest_source(source, store, conn, log=quiet)

    assert results[1].status == "failed"
    assert "expected one CSV" in results[1].message


def test_only_limits_the_run_to_named_exports(source, store, conn):
    results = ingest_source(source, store, conn, only={"export_2.zip"}, log=quiet)

    assert [r.export_name for r in results] == ["export_2.zip"]
    assert audit.has_landed(conn, "test", "export_2.zip")
    assert not audit.has_landed(conn, "test", "export_1.zip")
