# Warehouse design (phase 2)

The warehouse turns the 21 landed exports into tested, typed tables that the semantic layer and the AI analyst read. Every design choice below comes from a finding in the [data profile](04-data-profile.md).

## What the profile showed, and what the warehouse does about it

| Finding | Decision |
| --- | --- |
| All 21 exports parse under strict CSV rules, every row count matches `ingestion_audit`, and every export has the same 16 columns | One staging model fits every export. The load step uses the same strict CSV settings the profile used |
| Exports split the timeline by month received, with no gaps or overlaps | One batch per export: every complaint traces to exactly one batch |
| 361,832 complaints were received 15-31 Aug 2026 (export 21), after the archive page's stated end of 14 Aug | Kept. The valid date window is 2011-12-01 to 2026-08-31 (D-016) |
| Complaint IDs: none empty, all whole numbers, none repeated | `complaint_id` is the fact table's key. A duplicate rule stays as a guard for future loads |
| Product names changed around 24 Apr 2017 and 24 Aug 2023 | `seeds/product_groups.csv` maps all 21 names to stable product groups (D-018) |
| "Credit card or prepaid card" (2017-2023) mixes two products | Mapped to Credit card for now; a finer split by sub-product can come with the semantic layer |
| 476,377 complaints (2.7%) are "In progress"; three older response values exist | `seeds/company_responses.csv` derives `response_status` and `relief_type` |
| Narratives: 22% of rows, falling from about 42% (2018-2022) to 0% by August 2026 | Narratives get their own table; complaints carry `has_narrative` (D-019) |
| Credit reporting is 81% of rows; 2011 and 2026 are partial years | `dim_date.is_partial_year`; metric definitions in phase 3 handle both |
| Tags hold "Older American", "Servicemember" or both | Two true/false columns |
| "Timely response?" is always Yes or No | A true/false column |

## Data flow

```text
data/raw/*.zip                         landed in phase 1
  └─ run_pipeline.py load ──────────── bronze.cfpb_complaints     every published row as text, plus batch_id
       └─ run_pipeline.py transform    (dbt build: seeds, models, tests)
            reference.*                product_groups, company_responses, us_state_codes
            staging.stg_cfpb__complaints       typed and trimmed (a view)
            quality.int_complaints_checked     + failed_rule: the first hard rule broken
            quality.quarantine_complaints      rows with a failed_rule; never reach the marts
            marts.fct_complaints               one row per complaint, keys + flags + batch_id
            marts.dim_company · dim_product · dim_date
            marts.complaint_narratives         complaint_id + narrative
            quality.completeness_by_batch      every configured export landed; audited = loaded = in marts + quarantined
            quality.dq_summary                 rows caught by each rule, per batch
```

`load` copies each export's current batch into bronze and records it in `load_audit`. When a newer batch of an export lands, its old rows are replaced in one transaction. A batch already loaded is skipped.

## Data quality rules

**Hard rules: the row goes to quarantine.** The first rule a row breaks is stored in `failed_rule`.

| Rule | Rows in the profile |
| --- | --- |
| `complaint_id_invalid`: missing, or not a whole number | 0 |
| `date_received_invalid`: missing, or not a real date | 0 |
| `date_received_out_of_range`: before 2011-12-01 or after 2026-08-31 | 0 |
| `product_missing` | 0 |
| `company_missing` | 0 |
| `complaint_id_duplicate`: the same ID again; the copy from the latest export is kept | 0 |

**Soft rules: the row stays in the marts, with a flag.** These rows are still usable, so dropping them would understate totals.

| Flag | Rows in the profile |
| --- | --- |
| `sent_before_received` (`is_sent_before_received`) | 7,050 |
| `state_missing` (`state` is null) | 62,658 |
| `state_unrecognized` (`is_state_unrecognized`; original value kept in `state_raw`) | at least 1,474 (the profile counted values that aren't two capital letters) |
| `company_response_missing` | 21 |
| `issue_missing` | 6 |

## Star schema

| Table | Grain | Key columns |
| --- | --- | --- |
| `fct_complaints` | One complaint | `complaint_id`; `date_received` → `dim_date`; `company_key` → `dim_company`; `product_key` → `dim_product`; `batch_id` |
| `dim_company` | One company | `company_key` (md5 of the name), `company_name`, first and last complaint dates |
| `dim_product` | One product and sub-product pair | `product_key` (md5), `product`, `sub_product`, `product_group` |
| `dim_date` | One day, 2011-12-01 to 2026-08-31 | `date_day`, year, quarter, month, `year_month`, `week_start`, `is_partial_year` |
| `complaint_narratives` | One complaint with a narrative | `complaint_id`, `narrative` |

## Tests

- **Keys:** `fct_complaints.complaint_id` is unique and never empty; every date, company and product key exists in its dimension.
- **Lookups:** a product missing from `product_groups.csv`, or a company response missing from `company_responses.csv`, fails the build, so a new value can't slip through unmapped.
- **Allowed values:** `failed_rule`, `response_status` and `relief_type` may only hold known values.
- **Completeness:** `tests/assert_batches_complete.sql` fails the build when any batch's counts don't add up, or when an export listed in `config/sources/cfpb.yaml` has no landed batch at all; `run_pipeline.py transform` prints which one (user story US-04). `load` reports a missing export first and exits with an error.
- **CI on made-up data:** `tests/test_warehouse.py` builds the warehouse from two small exports with planted problems and checks each row lands where this design says. It also checks that an unmapped product and a lost row both fail the build.
