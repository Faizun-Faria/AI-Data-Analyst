# Metric catalog

Generated from `semantic/*.yml` by `python run_pipeline.py catalog`. Don't edit by hand: change the YAML and regenerate. Warnings are listed by name under each definition and spelled out at the end.

## Metrics

| Metric | Meaning | Definition | Warnings |
| --- | --- | --- | --- |
| `complaints` (Complaints) | Number of complaints received. | `count(*)` | reports_not_findings, credit_reporting_share |
| `companies` (Companies) | Number of different companies complained about. | `count(distinct f.company_key)` |  |
| `open_complaints` (Open complaints) | Complaints the company had not yet closed when the archive was published. | `count(*) filter (where f.response_status = 'in progress')` | open_complaints |
| `untimely_responses` (Untimely responses) | Complaints whose company response is "Untimely response". | `count(*) filter (where f.response_status = 'untimely')` |  |
| `timely_response_rate` (Timely response rate) | Percentage of complaints the company answered within the time the CFPB expects. | `100.0 * count(*) filter (where f.is_timely_response) / nullif(count(*), 0)` |  |
| `relief_rate` (Relief rate) | Percentage of closed complaints with a known outcome in which the consumer got relief, monetary or not. | `100.0 * count(*) filter (where (f.relief_type in ('monetary', 'non-monetary', 'type not recorded')) and (f.response_status = 'closed' and f.relief_type <> 'unknown')) / nullif(count(*) filter (where (f.response_status = 'closed' and f.relief_type <> 'unknown')), 0)` | relief_known_outcome, open_complaints |
| `monetary_relief_rate` (Monetary relief rate) | Percentage of closed complaints with a known outcome in which the consumer got money back or other monetary relief. | `100.0 * count(*) filter (where (f.relief_type = 'monetary') and (f.response_status = 'closed' and f.relief_type <> 'unknown')) / nullif(count(*) filter (where (f.response_status = 'closed' and f.relief_type <> 'unknown')), 0)` | relief_known_outcome, open_complaints |
| `narrative_share` (Share with narrative) | Percentage of complaints whose narrative was published. | `100.0 * count(*) filter (where f.has_narrative) / nullif(count(*), 0)` | narrative_coverage |

## Dimensions

| Dimension | Meaning | Column | Warnings |
| --- | --- | --- | --- |
| `received:<day\|week\|month\|quarter\|year>` (Date received) | The day the CFPB received the complaint. | `f.date_received` | partial_years |
| `product_group` (Product group) | A product group that stays the same across the CFPB's renames, such as Credit card or Bank account. Use this, not product, to compare years. | `p.product_group` |  |
| `product` (Product) | The product name as published at the time. | `p.product` | product_renames |
| `sub_product` (Sub-product) | The sub-product as published, such as "Store credit card"; often empty before April 2017. | `p.sub_product` | product_renames |
| `issue` (Issue) | What the complaint is about, as the consumer chose it from the CFPB's list. | `f.issue` | issue_taxonomy |
| `sub_issue` (Sub-issue) | A finer issue; many issues had no sub-issues before April 2017. | `f.sub_issue` | issue_taxonomy |
| `company` (Company) | The company complained about, by its exact published name. Common short names, such as "Wells Fargo", are resolved through companies.yml. | `c.company_name` |  |
| `state` (State) | The consumer's state as a US postal code; empty when missing or not a real code. | `f.state` |  |
| `submitted_via` (Submitted via) | How the complaint reached the CFPB, such as Web, Referral or Phone. | `f.submitted_via` |  |
| `company_response` (Company response) | The company's response as published, such as "Closed with monetary relief". | `f.company_response` |  |
| `response_status` (Response status) | closed, in progress, untimely or unknown. | `f.response_status` | open_complaints |
| `relief_type` (Relief type) | monetary, non-monetary, type not recorded, none, pending or unknown. | `f.relief_type` | relief_known_outcome |
| `timely_response` (Timely response) | Whether the company answered within the time the CFPB expects. | `f.is_timely_response` |  |
| `older_american` (Older American) | The complaint is tagged "Older American". | `f.is_older_american` |  |
| `servicemember` (Servicemember) | The complaint is tagged "Servicemember". | `f.is_servicemember` |  |
| `has_narrative` (Has narrative) | The consumer's own description of the complaint was published. | `f.has_narrative` | narrative_coverage |

## Named filters

| Named filter | Meaning | Filter | Warnings |
| --- | --- | --- | --- |
| `mvp_scope` (MVP scope) | Credit card complaints from the last five years of the archive, the scope of phases 4 and 5. | `p.product_group = 'Credit card' and f.date_received between date '2021-09-01' and date '2026-08-31'` |  |
| `account_opening_issues` (Bank account opening problems) | Bank account complaints about opening an account. Before April 2017 the only matching issue also covers closing and managing accounts, so this is broader there. | `p.product_group = 'Bank account' and f.issue in ('Account opening, closing, or management', 'Opening an account')` | issue_taxonomy, unauthorised_categories |
| `accounts_opened_without_consent` (Accounts or cards opened without consent) | Bank accounts or credit cards opened that the consumer didn't ask for. Credit cards are covered from December 2011; bank accounts only from April 2017. | `f.issue = 'Unsolicited issuance of credit card' or f.sub_issue in ('Account opened as a result of fraud', 'Account opened without my consent or knowledge', 'Card opened as result of identity theft or fraud', 'Card opened without my consent or knowledge')` | unauthorised_categories |

## Company names

| Published name | Short names |
| --- | --- |
| WELLS FARGO & COMPANY | Wells Fargo |
| BANK OF AMERICA, NATIONAL ASSOCIATION | Bank of America, BofA |
| JPMORGAN CHASE & CO. | JPMorgan Chase, JPMorgan, Chase |
| CITIBANK, N.A. | Citibank, Citi |
| CAPITAL ONE FINANCIAL CORPORATION | Capital One |
| SYNCHRONY FINANCIAL | Synchrony |
| AMERICAN EXPRESS COMPANY | American Express, Amex |
| DISCOVER BANK | Discover |
| U.S. BANCORP | U.S. Bank, US Bank |
| NAVY FEDERAL CREDIT UNION | Navy Federal |
| PNC Bank N.A. | PNC |
| TD BANK US HOLDING COMPANY | TD Bank |
| TRUIST FINANCIAL CORPORATION | Truist |
| BARCLAYS BANK DELAWARE | Barclays |
| GOLDMAN SACHS BANK USA | Goldman Sachs |
| ALLY FINANCIAL INC. | Ally |
| Bread Financial Holdings, Inc. | Bread Financial |
| Paypal Holdings, Inc | PayPal |
| Chime Financial Inc | Chime |
| Navient Solutions, LLC. | Navient |
| TRANSUNION INTERMEDIATE HOLDINGS, INC. | TransUnion |
| EQUIFAX, INC. | Equifax |
| Experian Information Solutions Inc. | Experian |

## Warnings

| Warning | Text |
| --- | --- |
| `reports_not_findings` | Complaints are unverified consumer reports: a count shows what was reported, not what happened. |
| `credit_reporting_share` | Credit reporting makes up about 81% of all complaints, so totals across products mostly reflect credit reporting. |
| `partial_years` | 2011 covers December only and 2026 runs to 31 August; compare whole years, or the same months of each year. |
| `product_renames` | The CFPB renamed products in April 2017 and August 2023; use the product group to compare across those dates. |
| `issue_taxonomy` | Issue and sub-issue names changed in April 2017 and August 2023; an issue that starts or stops on those dates was renamed, not solved. |
| `open_complaints` | Nearly 10% of 2026 complaints were still in progress when the archive was published, so outcomes for recent months are incomplete. |
| `relief_known_outcome` | Relief rates count closed complaints with a known outcome only; the old "Closed" and "Untimely response" values say nothing about relief and are left out. |
| `narrative_coverage` | Narratives start in 2015 and were published only with the consumer's consent; coverage peaked near 48% in 2017 and fell to 2.5% in 2026 as the CFPB stopped publishing them. A change in narrative counts says nothing about consumers. |
| `unauthorised_categories` | Before April 2017 there is no bank-account category for accounts opened without consent; "Account opening, closing, or management" covers all opening, closing and management problems. From April 2017 to August 2023 the categories describe accounts or cards opened "as a result of fraud"; from August 2023, "without my consent or knowledge". Unsolicited credit cards have their own issue before April 2017. |

## Glossary

| Term | Meaning |
| --- | --- |
| CFPB | The Consumer Financial Protection Bureau, the US agency that collected and published these complaints. |
| Complaint | One consumer's report about a financial product or service, as published by the CFPB. |
| Date received | The day the CFPB received the complaint. Every time-based metric uses this date. |
| Product group | A grouping of products that stays the same across the CFPB's renames in April 2017 and August 2023. |
| Issue | What the complaint is about, chosen by the consumer from the CFPB's list at the time; sub-issues refine it. |
| Company response | How the company said it closed the complaint, such as "Closed with explanation". |
| Relief | Something the consumer got as a result of the complaint; monetary relief is money, non-monetary relief is any other change, such as a corrected report. |
| Open complaint | A complaint still "In progress" when the archive was published. |
| Timely response | The company answered within the time the CFPB expects, as recorded in "Timely response?". |
| Narrative | The consumer's own description of the complaint, published only with their consent. |
| Tags | Markers the CFPB adds for complaints from older Americans and servicemembers. |
| Batch | One landed export of the archive; every complaint traces back to the batch it arrived in. |
| Quarantine | Rows that broke a hard data-quality rule; they never reach the metrics. |
| Named filter | A business idea defined once, such as "accounts opened without consent", that a question can use by name. |
| Company alias | A short company name, such as "Wells Fargo", that maps to one exact published name. |
| MVP scope | Credit card complaints received from 2021-09-01 to 2026-08-31, the scope of phases 4 and 5. |
