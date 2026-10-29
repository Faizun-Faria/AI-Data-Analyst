# Semantic layer (phase 3)

The semantic layer defines, once, every metric, dimension, named filter and company name the analyst may use, and turns a request into SQL from those definitions alone. Every choice below comes from a finding in the [semantic profile](06-semantic-profile.md); the generated [metric catalog](08-metric-catalog.md) lists the definitions themselves.

## What the exploration showed, and what the layer does about it

| Finding | Decision |
| --- | --- |
| Each large company appears under one published name for the whole archive, such as "WELLS FARGO & COMPANY". Matching part of a name is unsafe: "CITI" also matches Citizens Financial Group and Tri-Cities Finance, and "DISCOVER" matches Account Discovery Systems | `semantic/companies.yml` maps short names to exact published names; nothing matches part of a name (D-027) |
| "Credit card or prepaid card" (2017-2023) holds about 19,500 prepaid-card complaints in five sub-products | `warehouse/seeds/product_group_overrides.csv` moves them to Prepaid card, so both groups run unbroken from 2014 to 2026 (D-026) |
| Before April 2017, bank account complaints have no sub-issues; account opening shares one issue, "Account opening, closing, or management" (37,959 complaints), with closing and managing accounts | `account_opening_issues` is broader before April 2017, and says so; `accounts_opened_without_consent` covers bank accounts only from April 2017 (D-028) |
| Accounts opened without consent were "as a result of fraud" from 2017 to 2023 and "without my consent or knowledge" from August 2023; credit cards had "Unsolicited issuance of credit card" until April 2017 | One named filter spans all three eras, with a warning that spells them out |
| 476,090 complaints from 2026, nearly 10%, were still in progress when the archive was published | Relief rates count closed complaints with a known outcome only, and warn about recent months (D-029) |
| Narratives start in 2015, peak at 47.5% of complaints in 2017 and fall to 2.5% in 2026 | `narrative_share` and `has_narrative` carry a warning that coverage reflects publishing policy, not consumers |
| The median days from receipt to the company is 0 in every year since 2015 | No days-to-company metric (D-029) |
| The Bank account group also holds about 2,600 complaints about credit reports | Named filters select by issue, not by product group alone |

## How it works

| File | Holds |
| --- | --- |
| `semantic/models.yml` | The fact table and how the company and product tables join to it |
| `semantic/dimensions.yml` | 16 ways to group or filter: date received (by day, week, month, quarter or year), product group, issue, company, state, response and more |
| `semantic/metrics.yml` | 8 metrics: complaints, companies, open complaints, untimely responses, and the timely response, relief, monetary relief and narrative rates |
| `semantic/segments.yml` | Named filters: the MVP scope, bank account opening problems, and accounts or cards opened without consent |
| `semantic/companies.yml` | 23 companies, each with its exact published name and the short names questions use |
| `semantic/caveats.yml` | 9 warnings, each attached to the definitions it affects |
| `semantic/glossary.yml` | Plain-English meanings of 16 terms |

`query_cf/semantic.py` checks every definition when it loads, then turns a request (metrics, dimensions to group by, filters, named filters and a date range) into SQL. A request only joins the tables it needs, and the same request always gives the same SQL, so an answer can be traced to exactly the definitions behind it. Every answer carries the warnings of the definitions it used.

```bash
python run_pipeline.py query complaints relief_rate --by received:year --where company="Wells Fargo"
python run_pipeline.py check-semantic   # runs every definition on the warehouse
python run_pipeline.py catalog          # regenerates docs/08-metric-catalog.md
```

## What this means for the showcase question

> Were unauthorised-account complaints rising at Wells Fargo before September 2016?

The structured data can't answer this directly: before April 2017 there is no bank-account category for accounts opened without consent. Phase 7 will combine three pieces and label each one: Wells Fargo's bank account opening problems by month (the broad issue), its unsolicited credit cards by month, and its 2015-2016 narratives that describe accounts opened without consent. The answer is still not known.

## Tests

- Every metric, dimension and named filter is run against a warehouse built from seven planted complaints, and each must return the number worked out by hand.
- Requests the layer can't answer, such as an unknown metric or a grain on a non-time dimension, are rejected with a reason; filter values are quoted safely.
- A short name used for two companies, or a warning that isn't defined, stops the layer from loading.
- `docs/08-metric-catalog.md` must match the YAML exactly, so the catalog can't drift from the definitions.
- `check-semantic` runs every definition on the real warehouse and confirms each published company name exists.
