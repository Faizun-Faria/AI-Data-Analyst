-- For every current batch: rows counted at ingestion = rows loaded into bronze = rows in
-- fct_complaints + rows in quarantine. tests/assert_batches_complete.sql fails the build
-- if any batch doesn't add up, and run_pipeline.py names it.

with audited as (

    select batch_id, export_name, row_count as audited_rows
    from {{ source('pipeline', 'ingestion_audit') }}
    where source = 'cfpb' and status = 'landed'
    qualify row_number() over (partition by export_name order by attempt_id desc) = 1

),

loaded as (

    select batch_id, any_value(export_name) as export_name, count(*) as loaded_rows
    from {{ source('bronze', 'cfpb_complaints') }}
    group by batch_id

),

batches as (

    select
        coalesce(audited.batch_id, loaded.batch_id) as batch_id,
        coalesce(audited.export_name, loaded.export_name) as export_name,
        coalesce(audited.audited_rows, 0) as audited_rows,
        coalesce(loaded.loaded_rows, 0) as loaded_rows
    from audited
    full outer join loaded on audited.batch_id = loaded.batch_id

),

in_marts as (

    select batch_id, count(*) as fact_rows
    from {{ ref('fct_complaints') }}
    group by batch_id

),

quarantined as (

    select batch_id, count(*) as quarantined_rows
    from {{ ref('quarantine_complaints') }}
    group by batch_id

)

select
    batches.*,
    coalesce(in_marts.fact_rows, 0) as fact_rows,
    coalesce(quarantined.quarantined_rows, 0) as quarantined_rows,
    batches.audited_rows = batches.loaded_rows
        and batches.loaded_rows
            = coalesce(in_marts.fact_rows, 0) + coalesce(quarantined.quarantined_rows, 0)
        as is_complete
from batches
left join in_marts on batches.batch_id = in_marts.batch_id
left join quarantined on batches.batch_id = quarantined.batch_id
