"""Phase 3: the semantic layer, run against a warehouse of seven planted complaints.

Each complaint is planted to test one definition, so every expected number below can be
worked out by hand from the two lists.
"""

import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest
import yaml
from test_warehouse import build_warehouse

import run_pipeline
from query_cf import semantic
from query_cf.semantic import MetricQuery, SemanticError, compile_query, load_layer

ROOT = Path(__file__).resolve().parent.parent
WF = "WELLS FARGO & COMPANY"

OLD = [
    {  # bank account opening, in the broad pre-2017 issue
        "Complaint ID": "1",
        "Company": WF,
        "Product": "Bank account or service",
        "Sub-product": "Checking account",
        "Issue": "Account opening, closing, or management",
        "Date received": "2016-03-10",
        "Date sent to company": "2016-03-10",
    },
    {  # a credit card nobody asked for, in its pre-2017 issue
        "Complaint ID": "2",
        "Company": WF,
        "Sub-product": "",
        "Issue": "Unsolicited issuance of credit card",
        "Date received": "2016-05-02",
        "Date sent to company": "2016-05-02",
    },
    {  # answered late, with monetary relief
        "Complaint ID": "3",
        "Date received": "2016-05-03",
        "Date sent to company": "2016-05-03",
        "Timely response?": "No",
        "Company response to consumer": "Closed with monetary relief",
    },
]
NEW = [
    {  # bank account opened without consent, in the post-2023 sub-issue
        "Complaint ID": "4",
        "Company": WF,
        "Product": "Checking or savings account",
        "Sub-product": "Checking account",
        "Issue": "Opening an account",
        "Sub-issue": "Account opened without my consent or knowledge",
        "Date received": "2024-01-15",
        "Date sent to company": "2024-01-15",
    },
    {  # a gift card filed under "Credit card or prepaid card": belongs to Prepaid card
        "Complaint ID": "5",
        "Product": "Credit card or prepaid card",
        "Sub-product": "Gift card",
        "Issue": "Trouble using the card",
        "Date received": "2022-02-01",
        "Date sent to company": "2022-02-01",
    },
    {  # a card opened without consent, still open
        "Complaint ID": "6",
        "Issue": "Getting a credit card",
        "Sub-issue": "Card opened without my consent or knowledge",
        "Date received": "2025-06-01",
        "Date sent to company": "2025-06-01",
        "Company response to consumer": "In progress",
    },
    {  # non-monetary relief, with a narrative
        "Complaint ID": "7",
        "Issue": "Fees or interest",
        "Date received": "2025-07-01",
        "Date sent to company": "2025-07-01",
        "Company response to consumer": "Closed with non-monetary relief",
        "Consumer complaint narrative": "They raised my rate without telling me.",
    },
]


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    db, ok = build_warehouse(tmp_path_factory.mktemp("semantic"), old_rows=OLD, new_rows=NEW)
    assert ok, "dbt build failed; see the dbt output above"
    return db


@pytest.fixture(scope="module")
def layer():
    return load_layer()


def ask(db, layer, **request):
    conn = duckdb.connect(str(db), read_only=True)
    try:
        return semantic.run_query(conn, compile_query(layer, MetricQuery(**request)))
    finally:
        conn.close()


# --- The definitions themselves -------------------------------------------------------------


def test_every_definition_loads(layer):
    assert "complaints" in layer.metrics
    assert layer.time_dimension.name == "received"
    assert layer.company_name("chase") == "JPMORGAN CHASE & CO."


def test_the_catalog_document_matches_the_definitions(layer):
    catalog = (ROOT / "docs" / "08-metric-catalog.md").read_text(encoding="utf-8")
    assert catalog == semantic.render_catalog(layer), "run: python run_pipeline.py catalog"


def copy_layer(tmp_path):
    folder = tmp_path / "semantic"
    shutil.copytree(semantic.SEMANTIC_DIR, folder)
    return folder


def test_a_short_name_used_for_two_companies_is_rejected(tmp_path):
    folder = copy_layer(tmp_path)
    data = yaml.safe_load((folder / "companies.yml").read_text(encoding="utf-8"))
    data["companies"]["CITIBANK, N.A."].append("Chase")
    (folder / "companies.yml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(SemanticError, match="means both"):
        load_layer(folder)


def test_an_unknown_warning_is_rejected(tmp_path):
    folder = copy_layer(tmp_path)
    data = yaml.safe_load((folder / "metrics.yml").read_text(encoding="utf-8"))
    data["metrics"]["complaints"]["caveats"] = ["no_such_warning"]
    (folder / "metrics.yml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(SemanticError, match="unknown caveat 'no_such_warning'"):
        load_layer(folder)


# --- Compiling requests ----------------------------------------------------------------------


def test_the_same_request_always_gives_the_same_sql(layer):
    request = MetricQuery(
        metrics=("complaints", "relief_rate"),
        by=("received:year", "product_group"),
        filters={"company": ("Wells Fargo",)},
    )
    assert compile_query(layer, request).sql == compile_query(layer, request).sql


def test_only_the_tables_a_request_needs_are_joined(layer):
    by_issue = compile_query(layer, MetricQuery(metrics=("complaints",), by=("issue",))).sql
    by_company = compile_query(layer, MetricQuery(metrics=("complaints",), by=("company",))).sql
    assert "join" not in by_issue
    assert "marts.dim_company" in by_company and "marts.dim_product" not in by_company


def test_filter_values_are_quoted_safely(layer, warehouse):
    request = {"metrics": ("complaints",), "filters": {"company": ("O'Brien Bank",)}}
    compiled = compile_query(layer, MetricQuery(**request))
    assert "c.company_name = 'O''Brien Bank'" in compiled.sql
    assert ask(warehouse, layer, **request) == [(0,)]


def test_unknown_names_are_rejected_with_a_suggestion(layer):
    with pytest.raises(SemanticError, match="Did you mean complaints"):
        compile_query(layer, MetricQuery(metrics=("complaint",)))


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        ({"by": ("received:fortnight",)}, "unknown time grain"),
        ({"by": ("issue:month",)}, "only the time dimension takes a grain"),
        ({"by": ("issue", "issue")}, "listed twice"),
        ({"filters": {"received": ("2020-01-01",)}}, "received_from and received_to"),
        ({"filters": {"timely_response": ("maybe",)}}, "isn't true or false"),
    ],
)
def test_impossible_requests_are_rejected(layer, request_, message):
    with pytest.raises(SemanticError, match=message):
        compile_query(layer, MetricQuery(metrics=("complaints",), **request_))


def test_the_answer_carries_the_warnings_of_what_it_used(layer):
    compiled = compile_query(
        layer, MetricQuery(metrics=("narrative_share",), by=("received:year",))
    )
    assert any("Narratives start in 2015" in c for c in compiled.caveats)
    assert any("2011 covers December only" in c for c in compiled.caveats)


# --- Answers from the planted warehouse -------------------------------------------------------


def test_product_groups_including_prepaid_cards_filed_with_credit_cards(layer, warehouse):
    rows = ask(warehouse, layer, metrics=("complaints",), by=("product_group",))
    assert rows == [("Bank account", 2), ("Credit card", 4), ("Prepaid card", 1)]


def test_rates_follow_their_definitions(layer, warehouse):
    metrics = (
        "complaints",
        "companies",
        "open_complaints",
        "untimely_responses",
        "timely_response_rate",
        "relief_rate",
        "monetary_relief_rate",
        "narrative_share",
    )
    [row] = ask(warehouse, layer, metrics=metrics)
    values = dict(zip(metrics, row, strict=True))
    assert values["complaints"] == 7
    assert values["companies"] == 2
    assert values["open_complaints"] == 1
    assert values["untimely_responses"] == 0
    assert values["timely_response_rate"] == pytest.approx(100 * 6 / 7)
    # Six closed complaints with a known outcome; the open one is left out.
    assert values["relief_rate"] == pytest.approx(100 * 2 / 6)
    assert values["monetary_relief_rate"] == pytest.approx(100 * 1 / 6)
    assert values["narrative_share"] == pytest.approx(100 * 1 / 7)


@pytest.mark.parametrize(
    ("segment", "expected"),
    [
        ("accounts_opened_without_consent", 3),  # complaints 2, 4 and 6
        ("account_opening_issues", 2),  # complaints 1 and 4
        ("mvp_scope", 2),  # credit cards from September 2021: complaints 6 and 7
    ],
)
def test_named_filters_catch_the_planted_complaints(layer, warehouse, segment, expected):
    assert ask(warehouse, layer, metrics=("complaints",), segments=(segment,)) == [(expected,)]


def test_short_company_names_resolve(layer, warehouse):
    for name in ("Wells Fargo", "wells fargo & company"):
        assert ask(warehouse, layer, metrics=("complaints",), filters={"company": (name,)}) == [
            (3,)
        ]


def test_time_grains_and_date_ranges(layer, warehouse):
    rows = ask(
        warehouse,
        layer,
        metrics=("complaints",),
        by=("received:year",),
        received_from=date(2016, 5, 1),
    )
    assert [(d.year, n) for d, n in rows] == [(2016, 2), (2022, 1), (2024, 1), (2025, 2)]


def test_check_semantic_runs_every_definition(layer, warehouse):
    conn = duckdb.connect(str(warehouse), read_only=True)
    try:
        rows, problems = semantic.check_layer(conn, layer)
    finally:
        conn.close()
    assert [r for r in rows if r[2] == "ERROR"] == []
    # Only Wells Fargo is planted, so every other published name is reported missing.
    assert len(problems) == len(layer.companies) - 1
    assert all(p.startswith("company ") for p in problems)


# --- The commands ---------------------------------------------------------------------------


def test_query_command_shows_sql_answer_and_warnings(warehouse, capsys):
    code = run_pipeline.main(
        [
            *("--db", str(warehouse), "query", "complaints"),
            *("--by", "product_group", "--where", "company=Wells Fargo"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "c.company_name = 'WELLS FARGO & COMPANY'" in out
    assert "Bank account   2" in out
    assert 'Note: "Wells Fargo" means WELLS FARGO & COMPANY' in out
    assert "Warning: Complaints are unverified consumer reports" in out


def test_query_command_rejects_unknown_metrics(warehouse, capsys):
    assert run_pipeline.main(["--db", str(warehouse), "query", "complaint"]) == 2
    assert "Did you mean complaints" in capsys.readouterr().out


def test_catalog_command_writes_the_catalog(tmp_path, layer):
    out = tmp_path / "catalog.md"
    assert run_pipeline.main(["catalog", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == semantic.render_catalog(layer)


def test_values_print_as_people_read_them():
    assert semantic.format_value(date(2016, 1, 1), column="received_year") == "2016"
    assert semantic.format_value(date(2016, 4, 1), column="received_quarter") == "2016-Q2"
    assert semantic.format_value(date(2016, 5, 1), column="received_month") == "2016-05"
    assert semantic.format_value(1234567) == "1,234,567"
    assert semantic.format_value(85.714, percent=True) == "85.7%"
