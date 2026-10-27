import csv
import io
import zipfile
from pathlib import Path

import pytest

from complaint_radar import audit
from complaint_radar.config import SourceConfig
from complaint_radar.storage import LocalStore

HEADER = ("Date received", "Product", "Consumer complaint narrative", "Company", "Complaint ID")

# Narratives with commas, quotes and line breaks inside quoted fields: three rows, not five.
ROWS = [
    ("2016-08-01", "Bank account", 'An account I never "asked" for,\nopened twice.', "Bank A", "1"),
    ("2016-08-02", "Credit card", "", "Card Co B", "2"),
    ("2016-08-03", "Mortgage", "Line one\r\nLine two", "Lender C", "3"),
]


def write_export(path: Path, rows, header=HEADER) -> Path:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(path.with_suffix(".csv").name, buffer.getvalue())
    return path


@pytest.fixture
def inbox(tmp_path) -> Path:
    folder = tmp_path / "inbox"
    folder.mkdir()
    write_export(folder / "export_1.zip", ROWS)
    write_export(folder / "export_2.zip", ROWS[:1])
    return folder


@pytest.fixture
def source(inbox) -> SourceConfig:
    return SourceConfig(
        name="test",
        description="test source",
        enabled=True,
        format="csv_zip",
        base_uri=str(inbox),
        exports=("export_1.zip", "export_2.zip"),
        expected_columns=HEADER,
    )


@pytest.fixture
def raw_dir(tmp_path) -> Path:
    return tmp_path / "raw"


@pytest.fixture
def store(raw_dir) -> LocalStore:
    return LocalStore(raw_dir)


@pytest.fixture
def conn(tmp_path):
    connection = audit.connect(tmp_path / "warehouse" / "test.duckdb")
    yield connection
    connection.close()
