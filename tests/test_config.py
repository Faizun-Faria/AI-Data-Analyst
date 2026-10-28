import pytest
import yaml

from query_cf.config import ConfigError, load_source, load_sources


def write_config(folder, stem, **fields):
    path = folder / f"{stem}.yaml"
    path.write_text(yaml.safe_dump(fields), encoding="utf-8")
    return path


def test_cfpb_config_lists_all_21_exports_oldest_first():
    cfpb = load_sources()["cfpb"]

    assert cfpb.enabled
    assert len(cfpb.exports) == 21
    numbers = [int(e.split("_")[2]) for e in cfpb.exports]
    assert numbers == list(range(1, 22))
    assert len(cfpb.expected_columns) == 16
    assert cfpb.location(cfpb.exports[-1]) == (
        "https://files.consumerfinance.gov/f/documents/CCDB_Export_21_August_2026.zip"
    )


def test_fspo_layer_stays_off_until_its_terms_are_checked():
    assert load_sources()["fspo"].enabled is False


def test_name_must_match_file_name(tmp_path):
    path = write_config(tmp_path, "cfpb", name="other", enabled=False, format="csv_zip")
    with pytest.raises(ConfigError, match="must match the file name"):
        load_source(path)


def test_missing_required_field(tmp_path):
    path = write_config(tmp_path, "src", name="src", format="csv_zip")
    with pytest.raises(ConfigError, match="missing required field 'enabled'"):
        load_source(path)


def test_enabled_source_needs_exports(tmp_path):
    path = write_config(tmp_path, "src", name="src", enabled=True, format="csv_zip", exports=[])
    with pytest.raises(ConfigError, match="at least one export"):
        load_source(path)


def test_enabled_source_needs_an_ingestible_format(tmp_path):
    path = write_config(
        tmp_path, "src", name="src", enabled=True, format="documents", exports=["a.zip"]
    )
    with pytest.raises(ConfigError, match="can't be ingested yet"):
        load_source(path)


def test_duplicate_exports_are_rejected(tmp_path):
    path = write_config(
        tmp_path, "src", name="src", enabled=True, format="csv_zip", exports=["a.zip", "a.zip"]
    )
    with pytest.raises(ConfigError, match="same value twice"):
        load_source(path)


def test_location_joins_base_uri_and_export(tmp_path):
    path = write_config(
        tmp_path,
        "src",
        name="src",
        enabled=True,
        format="csv_zip",
        base_uri="https://example.org/files/",
        exports=["a.zip"],
    )
    assert load_source(path).location("a.zip") == "https://example.org/files/a.zip"


def test_empty_config_dir_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="no source configs"):
        load_sources(tmp_path)
