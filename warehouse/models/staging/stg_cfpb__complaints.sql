-- One row per published complaint row, typed and trimmed. Nothing is dropped here: the
-- quality models decide which rows reach the marts.

with source as (

    select rowid as bronze_row_id, * from {{ source('bronze', 'cfpb_complaints') }}

),

typed as (

    select
        bronze_row_id,
        batch_id,
        export_name,
        try_cast(regexp_extract(export_name, 'Export_(\d+)_', 1) as integer) as export_number,

        nullif(trim("Complaint ID"), '') as complaint_id_raw,
        case
            when regexp_full_match(trim("Complaint ID"), '\d+')
                then cast(trim("Complaint ID") as bigint)
        end as complaint_id,

        nullif(trim("Date received"), '') as date_received_raw,
        cast(try_strptime(trim("Date received"), '%Y-%m-%d') as date) as date_received,
        cast(try_strptime(trim("Date sent to company"), '%Y-%m-%d') as date)
            as date_sent_to_company,

        nullif(trim("Product"), '') as product,
        nullif(trim("Sub-product"), '') as sub_product,
        nullif(trim("Issue"), '') as issue,
        nullif(trim("Sub-issue"), '') as sub_issue,
        nullif(trim("Company"), '') as company,
        nullif(trim("State"), '') as state_raw,
        nullif(trim("ZIP code"), '') as zip_code,
        nullif(trim("Submitted via"), '') as submitted_via,
        nullif(trim("Company response to consumer"), '') as company_response,
        nullif(trim("Company public response"), '') as company_public_response,

        case trim("Timely response?") when 'Yes' then true when 'No' then false end
            as is_timely_response,
        coalesce(contains("Tags", 'Older American'), false) as is_older_american,
        coalesce(contains("Tags", 'Servicemember'), false) as is_servicemember,

        nullif(trim("Consumer complaint narrative"), '') as narrative

    from source

)

select
    typed.*,
    typed.narrative is not null as has_narrative,
    states.state_code as state,
    typed.state_raw is not null and states.state_code is null as is_state_unrecognized,
    coalesce(typed.date_sent_to_company < typed.date_received, false) as is_sent_before_received,
    md5(typed.company) as company_key,
    md5(typed.product || '|' || coalesce(typed.sub_product, '')) as product_key

from typed
left join {{ ref('us_state_codes') }} as states
    on typed.state_raw = states.state_code
