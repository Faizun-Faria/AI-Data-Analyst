"""Load the per-source YAML configs that drive ingestion.

Each file in config/sources/ describes one source: where its exports live, the order to
replay them in, and the columns every export should carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config" / "sources"

# Formats the ingestion step knows how to land. Other formats may sit in a config
# (the FSPO document layer, say) but only while the source is disabled.
INGESTIBLE_FORMATS = {"csv_zip"}


class ConfigError(ValueError):
    """A source config is missing a field or holds a value of the wrong kind."""


@dataclass(frozen=True)
class SourceConfig:
    name: str
    description: str
    enabled: bool
    format: str
    base_uri: str
    exports: tuple[str, ...]
    expected_columns: tuple[str, ...] = ()

    def location(self, export: str) -> str:
        """Where to fetch an export from: a URL, or a path on disk."""
        if not self.base_uri:
            return export
        return f"{self.base_uri.rstrip('/')}/{export}"


def load_source(path: Path) -> SourceConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name}: expected a mapping at the top level")

    def require(key: str, kind: type) -> Any:
        if key not in raw:
            raise ConfigError(f"{path.name}: missing required field '{key}'")
        if not isinstance(raw[key], kind):
            raise ConfigError(
                f"{path.name}: '{key}' should be {kind.__name__}, got {type(raw[key]).__name__}"
            )
        return raw[key]

    def string_list(key: str) -> tuple[str, ...]:
        values = raw.get(key) or []
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ConfigError(f"{path.name}: '{key}' should be a list of strings")
        if len(set(values)) != len(values):
            raise ConfigError(f"{path.name}: '{key}' lists the same value twice")
        return tuple(values)

    name = require("name", str)
    if name != path.stem:
        raise ConfigError(f"{path.name}: name '{name}' must match the file name '{path.stem}'")
    enabled = require("enabled", bool)
    fmt = require("format", str)
    exports = string_list("exports")

    if enabled and fmt not in INGESTIBLE_FORMATS:
        raise ConfigError(
            f"{path.name}: format '{fmt}' can't be ingested yet; "
            f"use one of {sorted(INGESTIBLE_FORMATS)} or set enabled: false"
        )
    if enabled and not exports:
        raise ConfigError(f"{path.name}: an enabled source needs at least one export")

    return SourceConfig(
        name=name,
        description=raw.get("description") or "",
        enabled=enabled,
        format=fmt,
        base_uri=raw.get("base_uri") or "",
        exports=exports,
        expected_columns=string_list("expected_columns"),
    )


def load_sources(config_dir: Path = DEFAULT_CONFIG_DIR) -> dict[str, SourceConfig]:
    paths = sorted(Path(config_dir).glob("*.yaml"))
    if not paths:
        raise ConfigError(f"no source configs found in {config_dir}")
    return {path.stem: load_source(path) for path in paths}
