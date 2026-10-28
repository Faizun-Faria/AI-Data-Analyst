from conftest import HEADER, ROWS, write_export
from query_cf import load
from query_cf.ingest import ingest_source


def quiet(_message: str) -> None:
    pass


def bronze(conn, source):
    return conn.execute(
        f"select export_name, batch_id, count(*) from {load.bronze_table(source)} "
        "group by all order by export_name"
    ).fetchall()


def test_loads_each_current_batch_with_its_batch_id(source, store, conn, tmp_path):
    landed = ingest_source(source, store, conn, log=quiet)

    results = load.load_source(source, conn, work_dir=tmp_path / "work", log=quiet)

    assert [(r.export_name, r.status, r.rows_loaded) for r in results] == [
        ("export_1.zip", "loaded", 3),
        ("export_2.zip", "loaded", 1),
    ]
    assert bronze(conn, source) == [
        ("export_1.zip", landed[0].batch_id, 3),
        ("export_2.zip", landed[1].batch_id, 1),
    ]


def test_text_with_quotes_commas_and_line_breaks_survives(source, store, conn, tmp_path):
    ingest_source(source, store, conn, log=quiet)
    load.load_source(source, conn, work_dir=tmp_path / "work", log=quiet)

    narrative = conn.execute(
        f'select "Consumer complaint narrative" from {load.bronze_table(source)} '
        """where "Complaint ID" = '1' and export_name = 'export_1.zip'"""
    ).fetchone()[0]
    assert narrative == ROWS[0][2]


def test_second_load_skips_batches_already_loaded(source, store, conn, tmp_path):
    ingest_source(source, store, conn, log=quiet)
    load.load_source(source, conn, work_dir=tmp_path / "work", log=quiet)
    before = bronze(conn, source)

    results = load.load_source(source, conn, work_dir=tmp_path / "work", log=quiet)

    assert [r.status for r in results] == ["skipped", "skipped"]
    assert bronze(conn, source) == before


def test_a_newer_batch_replaces_the_exports_old_rows(source, store, conn, inbox, tmp_path):
    ingest_source(source, store, conn, log=quiet)
    load.load_source(source, conn, work_dir=tmp_path / "work", log=quiet)
    write_export(inbox / "export_2.zip", ROWS)  # upstream file replaced: 3 rows, not 1
    newer = ingest_source(source, store, conn, only={"export_2.zip"}, force=True, log=quiet)

    results = load.load_source(source, conn, work_dir=tmp_path / "work", log=quiet)

    assert [(r.export_name, r.status) for r in results] == [
        ("export_1.zip", "skipped"),
        ("export_2.zip", "loaded"),
    ]
    assert bronze(conn, source)[1] == ("export_2.zip", newer[0].batch_id, 3)


def test_unexpected_column_fails_the_load_and_leaves_bronze_untouched(
    source, store, conn, inbox, tmp_path
):
    write_export(inbox / "export_2.zip", [r + ("x",) for r in ROWS], header=HEADER + ("Surprise",))
    ingest_source(source, store, conn, log=quiet)

    results = load.load_source(source, conn, work_dir=tmp_path / "work", log=quiet)

    assert [r.status for r in results] == ["loaded", "failed"]
    assert "Surprise" in results[1].message
    assert [row[0] for row in bronze(conn, source)] == ["export_1.zip"]
    status = conn.execute(
        "select status from load_audit where export_name = 'export_2.zip'"
    ).fetchone()[0]
    assert status == "failed"


def test_unzipped_files_are_deleted_after_loading(source, store, conn, tmp_path):
    ingest_source(source, store, conn, log=quiet)

    load.load_source(source, conn, work_dir=tmp_path / "work", log=quiet)

    assert list((tmp_path / "work").iterdir()) == []
