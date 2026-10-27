import pytest
import yaml

import run_pipeline


@pytest.fixture
def config_dir(tmp_path, inbox):
    folder = tmp_path / "sources"
    folder.mkdir()
    config = {
        "name": "test",
        "description": "test source",
        "enabled": True,
        "format": "csv_zip",
        "base_uri": str(inbox),
        "exports": ["export_1.zip", "export_2.zip"],
    }
    (folder / "test.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return folder


@pytest.fixture
def cli(tmp_path, config_dir):
    db = str(tmp_path / "warehouse" / "cli.duckdb")

    def run(*args):
        return run_pipeline.main(["--db", db, "--config-dir", str(config_dir), *args])

    return run


def test_ingest_then_status(cli, raw_dir, capsys):
    assert cli("ingest", "--raw", str(raw_dir)) == 0
    assert cli("status") == 0

    out = capsys.readouterr().out
    assert "landed     export_1.zip (3 rows" in out
    assert out.count("landed") >= 4  # two log lines + two status rows


def test_status_before_any_run(cli, capsys):
    assert cli("status") == 0
    assert "No ingestion attempts yet" in capsys.readouterr().out


def test_unknown_export_is_rejected_before_any_work(cli, raw_dir, capsys):
    assert cli("ingest", "--raw", str(raw_dir), "--export", "nope.zip") == 2
    assert "nope.zip" in capsys.readouterr().out
    assert not raw_dir.exists()


def test_unknown_source_is_rejected(cli, raw_dir):
    assert cli("ingest", "--raw", str(raw_dir), "--source", "nope") == 2


def test_failed_export_gives_a_nonzero_exit(cli, raw_dir, inbox):
    (inbox / "export_2.zip").write_bytes(b"broken")
    assert cli("ingest", "--raw", str(raw_dir)) == 1
