-- How many rows each rule caught, per batch. 'quarantine' rows never reach the marts;
-- 'flag' rows do, with the matching flag column set in fct_complaints.

with checked as (

    select * from {{ ref('int_complaints_checked') }}

),

passed as (

    select * from checked where failed_rule is null

),

counts as (

    select batch_id, 'quarantine' as kind, failed_rule as rule, count(*) as row_count
    from checked where failed_rule is not null group by batch_id, failed_rule

    union all
    select batch_id, 'flag', 'sent_before_received', count(*)
    from passed where is_sent_before_received group by batch_id

    union all
    select batch_id, 'flag', 'state_missing', count(*)
    from passed where state_raw is null group by batch_id

    union all
    select batch_id, 'flag', 'state_unrecognized', count(*)
    from passed where is_state_unrecognized group by batch_id

    union all
    select batch_id, 'flag', 'company_response_missing', count(*)
    from passed where company_response is null group by batch_id

    union all
    select batch_id, 'flag', 'issue_missing', count(*)
    from passed where issue is null group by batch_id

)

select * from counts
order by batch_id, kind desc, rule
