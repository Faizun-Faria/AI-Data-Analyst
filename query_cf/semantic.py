"""Phase 3: the semantic layer.

Loads the definitions in semantic/*.yml (metrics, dimensions, named filters, company
names, warnings and a glossary) and turns a metric request into SQL over the marts. The
same request always produces the same SQL, so every answer traces back to the exact
definitions it used.

    layer = load_layer()
    request = MetricQuery(
        metrics=("complaints",), by=("received:year",), filters={"company": ("Wells Fargo",)}
    )
    compiled = compile_query(layer, request)   # .sql, .caveats, .notes
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb
import yaml

SEMANTIC_DIR = Path(__file__).resolve().parent.parent / "semantic"
NAME = re.compile(r"[a-z][a-z0-9_]*")
TIME_GRAINS = ("day", "week", "month", "quarter", "year")
DIMENSION_TYPES = {"time", "category", "boolean"}
METRIC_TYPES = {"count", "count_distinct", "rate"}
TRUE_WORDS, FALSE_WORDS = {"true", "yes", "1"}, {"false", "no", "0"}


class SemanticError(ValueError):
    """A definition is invalid, or a request asks for something that isn't defined."""


@dataclass(frozen=True)
class Join:
    name: str
    table: str
    alias: str
    on: str


@dataclass(frozen=True)
class Dimension:
    name: str
    label: str
    type: str
    sql: str
    description: str
    join: str | None = None
    caveats: tuple[str, ...] = ()


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    type: str
    description: str
    where: str | None = None  # count: only rows matching this
    of: str | None = None  # count_distinct: what to count
    numerator: str | None = None  # rate: rows counted as a percentage of...
    denominator: str | None = None  # ...rows matching this (all rows when empty)
    caveats: tuple[str, ...] = ()

    def expression(self) -> str:
        if self.type == "count":
            return f"count(*) filter (where {self.where})" if self.where else "count(*)"
        if self.type == "count_distinct":
            return f"count(distinct {self.of})"
        if not self.denominator:
            return f"100.0 * count(*) filter (where {self.numerator}) / nullif(count(*), 0)"
        within = f"({self.denominator})"
        return (
            f"100.0 * count(*) filter (where ({self.numerator}) and {within})"
            f" / nullif(count(*) filter (where {within}), 0)"
        )


@dataclass(frozen=True)
class Segment:
    name: str
    label: str
    where: str
    description: str
    joins: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()


@dataclass(frozen=True)
class SemanticLayer:
    base_table: str
    base_alias: str
    joins: dict[str, Join]
    dimensions: dict[str, Dimension]
    metrics: dict[str, Metric]
    segments: dict[str, Segment]
    companies: dict[str, tuple[str, ...]]  # published name -> short names
    caveats: dict[str, str]
    glossary: dict[str, str]

    @property
    def time_dimension(self) -> Dimension:
        return next(d for d in self.dimensions.values() if d.type == "time")

    def company_name(self, value: str) -> str | None:
        """The published name a short or exact name refers to, ignoring case."""
        wanted = value.strip().lower()
        for name, aliases in self.companies.items():
            if wanted == name.lower() or wanted in (a.lower() for a in aliases):
                return name
        return None


# --- Loading ------------------------------------------------------------------------------


def _read(directory: Path, file: str, key: str) -> dict:
    path = directory / file
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get(key), dict):
        raise SemanticError(f"{file}: expected a mapping under '{key}'")
    return data[key]


def _field(entry: dict, key: str, where: str, required: bool = True):
    value = entry.get(key)
    if required and (value is None or value == ""):
        raise SemanticError(f"{where}: missing '{key}'")
    return " ".join(value.split()) if isinstance(value, str) else value


def _names(items, where: str, known: dict | set, kind: str) -> tuple[str, ...]:
    names = tuple(items or ())
    for name in names:
        if name not in known:
            raise SemanticError(f"{where}: unknown {kind} '{name}'")
    return names


def load_layer(directory: Path = SEMANTIC_DIR) -> SemanticLayer:
    """Read and check every definition; raise SemanticError on the first problem."""
    models = yaml.safe_load((directory / "models.yml").read_text(encoding="utf-8")) or {}
    base = models.get("base") or {}
    joins = {
        name: Join(
            name,
            _field(j, "table", f"join {name}"),
            _field(j, "alias", f"join {name}"),
            _field(j, "condition", f"join {name}"),
        )
        for name, j in (models.get("joins") or {}).items()
    }
    caveats = {
        k: " ".join(v.split()) for k, v in _read(directory, "caveats.yml", "caveats").items()
    }

    dimensions = {}
    for name, d in _read(directory, "dimensions.yml", "dimensions").items():
        where = f"dimension {name}"
        kind = _field(d, "type", where)
        if kind not in DIMENSION_TYPES:
            raise SemanticError(f"{where}: type must be one of {sorted(DIMENSION_TYPES)}")
        join = _field(d, "join", where, required=False)
        if join and join not in joins:
            raise SemanticError(f"{where}: unknown join '{join}'")
        dimensions[name] = Dimension(
            name,
            _field(d, "label", where),
            kind,
            _field(d, "sql", where),
            _field(d, "description", where),
            join,
            _names(d.get("caveats"), where, caveats, "caveat"),
        )
    if sum(d.type == "time" for d in dimensions.values()) != 1:
        raise SemanticError("dimensions.yml: define exactly one time dimension")

    metrics = {}
    for name, m in _read(directory, "metrics.yml", "metrics").items():
        where = f"metric {name}"
        kind = _field(m, "type", where)
        if kind not in METRIC_TYPES:
            raise SemanticError(f"{where}: type must be one of {sorted(METRIC_TYPES)}")
        metrics[name] = Metric(
            name,
            _field(m, "label", where),
            kind,
            _field(m, "description", where),
            where=_field(m, "where", where, required=False),
            of=_field(m, "of", where, required=kind == "count_distinct"),
            numerator=_field(m, "numerator", where, required=kind == "rate"),
            denominator=_field(m, "denominator", where, required=False),
            caveats=_names(m.get("caveats"), where, caveats, "caveat"),
        )

    segments = {}
    for name, s in _read(directory, "segments.yml", "segments").items():
        where = f"named filter {name}"
        segments[name] = Segment(
            name,
            _field(s, "label", where),
            _field(s, "where", where),
            _field(s, "description", where),
            _names(s.get("joins"), where, joins, "join"),
            _names(s.get("caveats"), where, caveats, "caveat"),
        )

    companies, seen = {}, {}
    for name, aliases in _read(directory, "companies.yml", "companies").items():
        for alias in [name, *aliases]:
            key = alias.lower()
            if key in seen and seen[key] != name:
                raise SemanticError(f"companies.yml: '{alias}' means both {seen[key]} and {name}")
            seen[key] = name
        companies[name] = tuple(aliases)

    named = [
        ("join", joins),
        ("dimension", dimensions),
        ("metric", metrics),
        ("named filter", segments),
        ("caveat", caveats),
    ]
    for kind, names in named:
        bad = [n for n in names if not NAME.fullmatch(n)]
        if bad:
            raise SemanticError(f"{kind} names must be lower_snake_case: {', '.join(bad)}")
    clash = set(dimensions) & set(metrics)
    if clash:
        raise SemanticError(f"a dimension and a metric share a name: {', '.join(sorted(clash))}")

    return SemanticLayer(
        base_table=_field(base, "table", "models.yml base"),
        base_alias=_field(base, "alias", "models.yml base"),
        joins=joins,
        dimensions=dimensions,
        metrics=metrics,
        segments=segments,
        companies=companies,
        caveats=caveats,
        glossary=_read(directory, "glossary.yml", "glossary"),
    )


# --- Compiling a request ------------------------------------------------------------------


@dataclass(frozen=True)
class MetricQuery:
    metrics: tuple[str, ...]
    by: tuple[str, ...] = ()  # dimension names; the time dimension takes a grain: received:month
    filters: dict[str, tuple] = field(default_factory=dict)  # dimension -> values (any of)
    segments: tuple[str, ...] = ()  # named filters
    received_from: date | None = None
    received_to: date | None = None
    top: int | None = None  # keep the N rows with the highest first metric


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    columns: tuple[str, ...]
    percent_columns: tuple[str, ...]
    caveats: tuple[str, ...]  # warning texts the answer must carry
    notes: tuple[str, ...]  # how the request was interpreted, such as company names


def sql_literal(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return f"date '{value.isoformat()}'"
    if isinstance(value, int | float):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _lookup(mapping: dict, name: str, kind: str):
    if name in mapping:
        return mapping[name]
    close = difflib.get_close_matches(name, list(mapping), n=3)
    hint = f" Did you mean {' or '.join(close)}?" if close else ""
    raise SemanticError(f"unknown {kind} '{name}'.{hint} Known: {', '.join(mapping)}")


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    word = str(value).strip().lower()
    if word in TRUE_WORDS | FALSE_WORDS:
        return word in TRUE_WORDS
    raise SemanticError(f"'{value}' isn't true or false")


def compile_query(layer: SemanticLayer, query: MetricQuery) -> CompiledQuery:
    """Turn a request into SQL over the marts, using only the layer's definitions."""
    if not query.metrics:
        raise SemanticError("ask for at least one metric")
    metrics = [_lookup(layer.metrics, name, "metric") for name in query.metrics]
    select, group, where, joins, caveats, notes = [], [], [], [], [], []

    def use(join: str | None, caveat_ids: tuple[str, ...]) -> None:
        if join and join not in joins:
            joins.append(join)
        caveats.extend(c for c in caveat_ids if c not in caveats)

    for item in query.by:
        name, _, grain = item.partition(":")
        dim = _lookup(layer.dimensions, name, "dimension")
        if dim.type == "time":
            grain = grain or "month"
            if grain not in TIME_GRAINS:
                raise SemanticError(f"unknown time grain '{grain}'; use {', '.join(TIME_GRAINS)}")
            column = f"{dim.name}_{grain}"
            select.append(f"cast(date_trunc('{grain}', {dim.sql}) as date) as {column}")
        elif grain:
            raise SemanticError(f"only the time dimension takes a grain, not '{name}'")
        else:
            column = dim.name
            select.append(f"{dim.sql} as {column}")
        if column in group:
            raise SemanticError(f"'{item}' is listed twice")
        group.append(column)
        use(dim.join, dim.caveats)

    for name, values in query.filters.items():
        dim = _lookup(layer.dimensions, name, "dimension")
        if dim.type == "time":
            raise SemanticError("filter dates with received_from and received_to")
        if not values:
            raise SemanticError(f"no values given for '{name}'")
        if dim.name == "company":
            resolved = []
            for value in values:
                published = layer.company_name(str(value))
                if published is None:
                    notes.append(f'"{value}" isn\'t a known company name; matched exactly as given')
                    resolved.append(value)
                else:
                    if published != value:
                        notes.append(f'"{value}" means {published}')
                    resolved.append(published)
            values = tuple(resolved)
        if dim.type == "boolean":
            values = tuple(_as_bool(v) for v in values)
        literals = [sql_literal(v) for v in values]
        if len(literals) == 1:
            where.append(f"{dim.sql} = {literals[0]}")
        else:
            where.append(f"{dim.sql} in ({', '.join(literals)})")
        use(dim.join, dim.caveats)

    for name in query.segments:
        segment = _lookup(layer.segments, name, "named filter")
        where.append(f"({segment.where})")
        for join in segment.joins:
            use(join, ())
        use(None, segment.caveats)

    time = layer.time_dimension
    if query.received_from and query.received_to and query.received_from > query.received_to:
        raise SemanticError("received_from is after received_to")
    if query.received_from:
        where.append(f"{time.sql} >= {sql_literal(query.received_from)}")
    if query.received_to:
        where.append(f"{time.sql} <= {sql_literal(query.received_to)}")

    for metric in metrics:
        select.append(f"{metric.expression()} as {metric.name}")
        use(None, metric.caveats)

    lines = ["select", ",\n".join(f"    {s}" for s in select)]
    lines.append(f"from {layer.base_table} as {layer.base_alias}")
    for join in (j for j in layer.joins.values() if j.name in joins):
        lines.append(f"join {join.table} as {join.alias} on {join.on}")
    if where:
        lines.append("where " + "\n  and ".join(where))
    if group:
        lines.append("group by " + ", ".join(group))
    if query.top:
        lines.append("order by " + ", ".join([f"{metrics[0].name} desc nulls last", *group]))
        lines.append(f"limit {int(query.top)}")
    elif group:
        lines.append("order by " + ", ".join(group))

    return CompiledQuery(
        sql="\n".join(lines),
        columns=tuple(group + [m.name for m in metrics]),
        percent_columns=tuple(m.name for m in metrics if m.type == "rate"),
        caveats=tuple(layer.caveats[c] for c in caveats),
        notes=tuple(notes),
    )


def run_query(conn: duckdb.DuckDBPyConnection, compiled: CompiledQuery) -> list[tuple]:
    return conn.execute(compiled.sql).fetchall()


TIME_FORMATS = {"year": "%Y", "quarter": "%Y-%m", "month": "%Y-%m", "week": "%Y-%m-%d"}


def format_value(value, percent: bool = False, column: str = "") -> str:
    """A value as people read it: 85.7%, 1,234, 2016 for a year, 2016-05 for a month."""
    if value is None:
        return ""
    if percent:
        return f"{value:.1f}%"
    grain = column.rpartition("_")[2]
    if isinstance(value, date) and grain in TIME_FORMATS:
        if grain == "quarter":
            return f"{value.year}-Q{(value.month - 1) // 3 + 1}"
        return value.strftime(TIME_FORMATS[grain])
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


# --- Checking against a warehouse ---------------------------------------------------------


def check_layer(
    conn: duckdb.DuckDBPyConnection, layer: SemanticLayer
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Run every definition against a built warehouse.

    Returns (rows to show, problems). Each metric, dimension and named filter must run;
    each published company name must exist in dim_company.
    """
    rows, problems = [], []

    def attempt(kind: str, name: str, request: MetricQuery, describe) -> None:
        try:
            result = run_query(conn, compile_query(layer, request))
        except (duckdb.Error, SemanticError) as exc:
            problems.append(f"{kind} {name}: {str(exc).splitlines()[0]}")
            rows.append((kind, name, "ERROR"))
            return
        rows.append((kind, name, describe(result)))

    for name, metric in layer.metrics.items():
        attempt(
            "metric",
            name,
            MetricQuery(metrics=(name,)),
            lambda r, m=metric: format_value(r[0][0], percent=m.type == "rate"),
        )
    for name, dim in layer.dimensions.items():
        by = f"{name}:year" if dim.type == "time" else name
        attempt(
            "dimension",
            name,
            MetricQuery(metrics=("complaints",), by=(by,)),
            lambda r: f"{len(r):,} values",
        )
    for name in layer.segments:
        attempt(
            "named filter",
            name,
            MetricQuery(metrics=("complaints",), segments=(name,)),
            lambda r: f"{format_value(r[0][0])} complaints",
        )
    for name in layer.companies:
        request = MetricQuery(metrics=("complaints",), filters={"company": (name,)})
        found = run_query(conn, compile_query(layer, request))[0][0]
        rows.append(("company", name, f"{found:,} complaints" if found else "MISSING"))
        if not found:
            problems.append(f"company {name}: no complaints under this exact name")
    return rows, problems


# --- The catalog document -----------------------------------------------------------------


def _cell(text: str | None) -> str:
    return (text or "").replace("|", "\\|")


def render_catalog(layer: SemanticLayer) -> str:
    """The metric catalog as Markdown, generated so it can never drift from the YAML."""
    out = [
        "# Metric catalog",
        "",
        "Generated from `semantic/*.yml` by `python run_pipeline.py catalog`. Don't edit by "
        "hand: change the YAML and regenerate. Warnings are listed by name under each "
        "definition and spelled out at the end.",
        "",
        "## Metrics",
        "",
        "| Metric | Meaning | Definition | Warnings |",
        "| --- | --- | --- | --- |",
    ]
    for m in layer.metrics.values():
        out.append(
            f"| `{m.name}` ({m.label}) | {_cell(m.description)} | `{_cell(m.expression())}` "
            f"| {', '.join(m.caveats)} |"
        )
    out += ["", "## Dimensions", "", "| Dimension | Meaning | Column | Warnings |"]
    out.append("| --- | --- | --- | --- |")
    for d in layer.dimensions.values():
        name = f"`{d.name}:<{'|'.join(TIME_GRAINS)}>`" if d.type == "time" else f"`{d.name}`"
        out.append(
            f"| {_cell(name)} ({d.label}) | {_cell(d.description)} | `{d.sql}` "
            f"| {', '.join(d.caveats)} |"
        )
    out += ["", "## Named filters", "", "| Named filter | Meaning | Filter | Warnings |"]
    out.append("| --- | --- | --- | --- |")
    for s in layer.segments.values():
        out.append(
            f"| `{s.name}` ({s.label}) | {_cell(s.description)} | `{_cell(s.where)}` "
            f"| {', '.join(s.caveats)} |"
        )
    out += ["", "## Company names", "", "| Published name | Short names |", "| --- | --- |"]
    for name, aliases in layer.companies.items():
        out.append(f"| {_cell(name)} | {_cell(', '.join(aliases))} |")
    out += ["", "## Warnings", "", "| Warning | Text |", "| --- | --- |"]
    for name, text in layer.caveats.items():
        out.append(f"| `{name}` | {_cell(text)} |")
    out += ["", "## Glossary", "", "| Term | Meaning |", "| --- | --- |"]
    for term, meaning in layer.glossary.items():
        out.append(f"| {_cell(term)} | {_cell(meaning)} |")
    return "\n".join(out) + "\n"
