# Complaint Radar

Ask a question about 15 years of US financial complaints in plain English, and get back a number, a chart or a short report, with the SQL behind it shown.

The AI part only works because of what sits underneath it: an audited complaints warehouse, and a semantic layer that defines every metric, so the analyst reads precise definitions instead of guessing from raw tables.

> **Status:** phase 0 (framing) is done. Ingestion is next; see the [roadmap](#roadmap).

![Architecture: data sources feed audited ingestion, a dbt warehouse and a semantic layer; the AI analyst answers only from defined metrics](docs/images/architecture.png)

## Why

Regulated firms need answers they can audit. A plain-English answer is only useful if you can see how it was produced: which metric definition it used, which SQL ran, how many rows it read, and which batch of data those rows came from. Complaint Radar is built so that every answer traces back that far.

Framing documents:

- [Problem statement](docs/00-problem-statement.md)
- [Personas](docs/01-personas.md)
- [User stories with acceptance criteria](docs/02-user-stories.md)
- [Decision log](docs/03-decision-log.md)

## Data

| Source | What it holds | How it's used |
| --- | --- | --- |
| [CFPB Consumer Complaint Database narratives archive](https://www.consumerfinance.gov/foia-requests/foia-electronic-reading-room/cfpb-consumer-complaint-database-narratives-archive/) | US complaints received 1 Dec 2011 to 14 Aug 2026, in 21 zipped CSV exports (about 1.4 GB), with product, issue, company, company response and consumer narrative | Main dataset. Each export is replayed as a new batch, oldest first |
| FSPO decisions | Anonymised full text of the Irish Financial Services and Pensions Ombudsman's legally binding decisions since 2018 | Optional document layer, off until its terms of use are checked |

The CFPB stopped publishing complaint narratives in August 2026, so the archive is a fixed dataset. That also makes it a source of ground truth: any answer the analyst gives can be checked against a number computed directly in SQL.

**Complaint narratives are unverified consumer statements.** Answers describe what was reported, not what happened.

## Roadmap

The MVP is phases 0-5, published at the MVP gate; phases 6-8 follow.

- [x] **0. Frame:** problem statement, two personas, 14 user stories with acceptance criteria, decision log
- [ ] **1. Ingest:** a YAML config per source; batch ID, extract timestamp, SHA-256 and row count in an `ingestion_audit` table; safe re-runs
- [ ] **2. Warehouse:** dbt on DuckDB, with staging and mart models, data tests, a quarantine table, a completeness check and a star schema
- [ ] **3. Semantic layer:** every metric and dimension defined, with join paths, column descriptions and a glossary
- [ ] **4. AI analyst:** question → plan → SQL → sqlglot safety check → run → answer with SQL, row count and assumptions; every question logged
- [ ] **5. Evaluation:** 50 questions with answers computed in SQL; accuracy by difficulty, run in CI
- [ ] **6. App and formats:** Streamlit chat app returning a number, a chart or a short report; public demo with usage limits
- [ ] **7. Showcase:** "Were unauthorised-account complaints rising at Wells Fargo before September 2016?", answered through the analyst
- [ ] **8. Operate:** scheduled runs, CI running tests and evals, a runbook, rebuild from raw

## Cost and upkeep

These figures are measured from phase 4 onward, and none are estimated.

| Item | Value |
| --- | --- |
| Cost per 100 questions answered | Not measured yet (phase 4) |
| Monthly cost of the public demo | Not measured yet (phase 6) |
| Pinned model version | Set in phase 4. The evaluation set is re-run before any model change |
| Known failure points | Ambiguous questions (the analyst asks one clarifying question) and undefined metrics (refused, with the closest defined metrics). Detection checks arrive in phases 4-5 |

## Data use

- Complaint narratives are never sent to an LLM provider that trains on inputs; the API's data-use terms are checked first.
- Raw exports and the warehouse will not be committed to this repo; the pipeline rebuilds them from the public archive.

## License

[MIT](LICENSE)
