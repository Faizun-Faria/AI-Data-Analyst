-- Every staged row, with the first hard rule it breaks (if any). Rows with a failed_rule
-- go to quarantine_complaints; the rest feed the marts. Soft issues are only flags.

with staged as (

    select * exclude (narrative) from {{ ref('stg_cfpb__complaints') }}

),

rule_checked as (

    select
        *,
        case
            when complaint_id is null then 'complaint_id_invalid'
            when date_received is null then 'date_received_invalid'
            when date_received < date '{{ var("archive_start") }}'
                or date_received > date '{{ var("archive_end") }}'
                then 'date_received_out_of_range'
            when product is null then 'product_missing'
            when company is null then 'company_missing'
        end as row_failed_rule
    from staged

),

ranked as (

    -- When a Complaint ID repeats, keep the copy from the latest export, preferring a
    -- copy that passes the other rules. The others are quarantined as duplicates.
    select
        *,
        row_number() over (
            partition by complaint_id
            order by row_failed_rule is null desc, export_number desc nulls last, bronze_row_id desc
        ) as complaint_id_rank
    from rule_checked

)

select
    * exclude (row_failed_rule, complaint_id_rank),
    coalesce(
        row_failed_rule,
        case when complaint_id_rank > 1 then 'complaint_id_duplicate' end
    ) as failed_rule
from ranked
