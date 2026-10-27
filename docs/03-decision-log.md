# Decision log

Newest decisions are added at the bottom. A reversed decision stays in the log, and a new entry records the reversal.

| ID | Date | Decision | Why | Alternatives considered |
| --- | --- | --- | --- | --- |
| D-001 | 2026-10-24 | Build an AI data analyst over complaints data, with an audited warehouse and a semantic layer underneath it. | AI that a regulated business can audit; one build shows data engineering, analytics engineering, AI and BA work. | A BI dashboard only; a chatbot over raw tables. |
| D-002 | 2026-10-24 | Use the CFPB narratives archive as the main dataset and replay its 21 exports in order, one batch per export. | The CFPB stopped publishing narratives in August 2026, so the archive is fixed; replaying exports gives a realistic incremental-ingestion story. | The live complaints API, which no longer carries narratives. |
| D-003 | 2026-10-24 | DuckDB for the warehouse. | Fast local analytics, free, no server, installs with pip. | Postgres (a server to run); Snowflake or BigQuery (accounts and cost). |
| D-004 | 2026-10-24 | dbt Core with `dbt-duckdb` for transformations. | Tests, documentation and lineage in the industry-standard tool. | Plain SQL scripts. |
| D-005 | 2026-10-24 | A semantic layer of YAML metric and dimension definitions that the AI reads before writing SQL. | The AI uses precise, documented definitions instead of guessing from raw tables. | Let the model read raw table schemas. |
| D-006 | 2026-10-24 | Parse every generated query with sqlglot; allow only read-only queries on allowlisted tables. | Generated SQL can't change data or reach outside the defined tables, and every block can be explained. | A read-only database user alone. |
| D-007 | 2026-10-24 | No Docker: everything installs with pip or runs in the cloud. Prefect on Windows, Airflow standalone on Mac or Linux. | One-command setup on an ordinary laptop. | Docker Compose for the whole stack. |
| D-008 | 2026-10-24 | MVP is phases 0-5, scoped to one product and the last five years, and is published at the MVP gate. | A working, tested analyst in about 50-70 hours. | Build all nine phases before publishing. |
| D-009 | 2026-10-24 | Keep the FSPO document layer off until its terms of use are checked for bulk download; use a sample if anything is unclear. | Respect the publisher's terms. | Bulk-download straight away. |
| D-010 | 2026-10-24 | Never send complaint narratives to an LLM provider that trains on inputs; check the API's data-use terms first. | Keeps consumers' own words out of third-party training data. | Any provider. |
| D-011 | 2026-10-27 | The raw zone is a local folder by default, and S3 when `COMPLAINT_RADAR_RAW` is an `s3://` URI. Both use the same `<source>/<batch_id>/<file>` layout. | The pipeline and its tests run without an AWS account; S3 is a setting, not a rewrite. | S3 only. |
| D-012 | 2026-10-27 | Audit every ingestion attempt, not only successes, and derive the batch ID from the export's SHA-256. | A crash or failure leaves a trace; identical bytes can't land twice, so re-runs are safe. | Random batch IDs; audit successes only. |
| D-013 | 2026-10-27 | Count rows with a CSV parser, not by counting lines. | Narratives hold line breaks inside quoted fields, so line counts overstate rows. Checked on the August 2026 export: the parser count matches DuckDB's `read_csv` count. | `wc -l`-style line counts. |
| D-014 | 2026-10-27 | An export whose columns differ from the config still lands, flagged in `ingestion_audit.columns_match`. | The raw zone keeps exactly what was delivered; the warehouse tests decide what is usable. | Reject the export at ingestion. |
