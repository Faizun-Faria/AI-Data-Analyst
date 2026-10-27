# User stories

Fourteen stories, each tied to the build phase that delivers it. "Maintainer" is whoever runs the pipeline.

| ID | Phase | Story |
| --- | --- | --- |
| [US-01](#us-01) | 1. Ingest | Audit every export that lands |
| [US-02](#us-02) | 1. Ingest | Describe each source in config |
| [US-03](#us-03) | 2. Warehouse | Quarantine rows that fail data quality rules |
| [US-04](#us-04) | 2. Warehouse | Check completeness: source rows vs landed rows |
| [US-05](#us-05) | 2. Warehouse | Model complaints as a star schema |
| [US-06](#us-06) | 3. Semantic layer | Define every metric once |
| [US-07](#us-07) | 4. AI analyst | Ask in plain English, see the working |
| [US-08](#us-08) | 4. AI analyst | Refuse undefined metrics |
| [US-09](#us-09) | 4. AI analyst | Ask one clarifying question when unsure |
| [US-10](#us-10) | 4. AI analyst | Block anything but read-only queries |
| [US-11](#us-11) | 4. AI analyst | Log every question and answer |
| [US-12](#us-12) | 5. Evaluation | Score accuracy by difficulty |
| [US-13](#us-13) | 6. App and formats | Get the right format for the question |
| [US-14](#us-14) | 8. Operate | Rebuild from raw with one command |

---

### US-01

**As a** risk analyst, **I want** every export recorded with its batch ID, checksum, row count and extract time, **so that** I can prove which data an answer was built on.

- Given an export is ingested, when it lands, then `ingestion_audit` holds its batch ID, SHA-256 checksum, row count, extract timestamp and status `landed`.
- Given the same export is ingested again, when the run finishes, then no new batch is created and no file is copied again.
- Given an export can't be downloaded or opened, when the run finishes, then the attempt is recorded as `failed` with the error, nothing lands, and the next run retries it.

### US-02

**As a** maintainer, **I want** each source described in its own YAML config, **so that** adding or changing a source is a config change, not a code change.

- Given a config in `config/sources/`, when the pipeline runs, then it replays that source's exports in the listed order.
- Given a config is missing a required field or lists an export twice, when the pipeline starts, then it stops with an error naming the file and field.
- Given a source is disabled, when the pipeline runs, then it is skipped and says so.

### US-03

**As a** risk analyst, **I want** rows that fail data quality rules held in a quarantine table, **so that** bad rows never reach the numbers I report.

- Given a row fails a rule (for example a missing Complaint ID or an unparseable date), when the warehouse builds, then the row is in the quarantine table with the rule it failed and its batch ID.
- Given a quarantined row, when the marts build, then it is not in any mart.
- Given a batch, when I query quarantine, then I can see how many of its rows failed each rule.

### US-04

**As a** complaints operations lead, **I want** a completeness check of source rows against landed rows, **so that** I know no complaints were silently dropped.

- Given a batch, when the warehouse builds, then staged rows plus quarantined rows equal the row count in `ingestion_audit`.
- Given the counts don't match, when the warehouse builds, then the build fails and names the batch.

### US-05

**As a** risk analyst, **I want** complaints modelled as a star schema, **so that** questions by company, product and time are simple and consistent.

- Given the marts are built, then there is a complaint fact table with company, product and date dimensions.
- Given the dbt tests run, then keys are unique and not null, and every foreign key resolves to its dimension.

### US-06

**As a** complaints operations lead, **I want** every metric defined once, in plain words and as a formula, **so that** the same question always gets the same number.

- Given a metric, then its definition holds a name, a plain-English description, its SQL expression, its grain and the dimensions it may be cut by.
- Given a term used in a definition (for example "timely response"), then the glossary defines it.
- Given two metrics, then no two share a name.

### US-07

**As a** complaints operations lead, **I want** to ask a question in plain English and get an answer with the SQL, row count and assumptions shown, **so that** I can quote it with confidence.

- Given a question that maps to defined metrics, when I ask it, then I get an answer plus the SQL that produced it, the number of rows it read and the assumptions it made.
- Given the same question asked twice, then the SQL is the same.

### US-08

**As a** risk analyst, **I want** the analyst to refuse metrics that aren't defined, **so that** it never guesses a definition.

- Given a question that needs an undefined metric, when I ask it, then the analyst says which metric is missing, names the closest defined metrics, and runs no SQL.

### US-09

**As a** risk analyst, **I want** the analyst to ask one clarifying question when my question is ambiguous, **so that** I get the answer I meant.

- Given an ambiguous question (for example no time period, or a company name that matches several companies), when I ask it, then the analyst asks exactly one clarifying question before running any SQL.

### US-10

**As a** maintainer, **I want** every generated query checked before it runs, **so that** the analyst can only read allowed tables.

- Given generated SQL, when it is checked, then it is parsed with sqlglot before anything runs.
- Given a query that writes, deletes, creates or alters anything, or reads a table outside the allowlist, then it is blocked, not run, and the block is logged.

### US-11

**As a** risk analyst, **I want** every question and answer logged, **so that** any answer can be audited later.

- Given a question, when it is answered or refused, then the log holds the question, the plan, the SQL, the row count, the answer, the model version and a timestamp.

### US-12

**As a** maintainer, **I want** a 50-question evaluation set with answers computed directly in SQL, **so that** I know the analyst's accuracy before any model change.

- Given the evaluation set, then every question is tagged easy, medium or hard and has an expected answer computed in SQL.
- Given CI runs, then accuracy is reported overall and by difficulty.
- Given a model change, then the evaluation set is re-run before the change ships.

### US-13

**As a** complaints operations lead, **I want** the answer in the format that fits the question, **so that** I can use it straight away.

- Given a question about one figure, then I get a number.
- Given a question about a trend, then I get a Plotly chart.
- Given an open question, then I get a short written report.

### US-14

**As a** maintainer, **I want** to rebuild the warehouse from the raw zone with one command, **so that** any number can be reproduced from scratch.

- Given a deleted warehouse file, when I run the rebuild, then the warehouse is rebuilt from the landed batches without downloading anything.
- Given the rebuild finishes, then the evaluation set passes as before.
