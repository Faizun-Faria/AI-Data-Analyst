-- One row per complaint that passed every hard rule. Soft issues stay visible as flags,
-- and batch_id traces each row back to the export it arrived in.

with passed as (

    select * from {{ ref('int_complaints_checked') }}
    where failed_rule is null

),

responses as (

    select * from {{ ref('company_responses') }}

)

select
    passed.complaint_id,
    passed.date_received,
    passed.date_sent_to_company,
    passed.company_key,
    passed.product_key,
    passed.issue,
    passed.sub_issue,
    passed.state,
    passed.state_raw,
    passed.zip_code,
    passed.submitted_via,
    passed.company_response,
    coalesce(responses.response_status, 'unknown') as response_status,
    coalesce(responses.relief_type, 'unknown') as relief_type,
    passed.company_public_response,
    passed.is_timely_response,
    passed.is_older_american,
    passed.is_servicemember,
    passed.has_narrative,
    passed.is_state_unrecognized,
    passed.is_sent_before_received,
    passed.batch_id

from passed
left join responses
    on passed.company_response = responses.company_response
