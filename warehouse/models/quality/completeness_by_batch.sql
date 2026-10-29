-- For every current batch: rows counted at ingestion = rows loaded into bronze = rows in
-- fct_complaints + rows in quarantine. An export the source config lists but that has no
-- landed batch at all appears with an empty batch_id and is never complete.
-- tests/assert_batches_complete.sql fails the build if anything doesn't add up, and
-- run_pipeline.py names it.

with expected as (

    select export_name
    from {{ source('pipeline', 'expected_exports') }}
    where source = 'cfpb'

),

audited as (

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

missing as (

    select
        cast(null as varchar) as batch_id,
        export_name,
        0 as audited_rows,
        0 as loaded_rows
    from expected
    where export_name not in (select export_name from batches)

),

all_exports as (

    select * from batches
    union all
    select * from missing

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
    all_exports.*,
    coalesce(in_marts.fact_rows, 0) as fact_rows,
    coalesce(quarantined.quarantined_rows, 0) as quarantined_rows,
    all_exports.batch_id is not null
        and all_exports.audited_rows = all_exports.loaded_rows
        and all_exports.loaded_rows
            = coalesce(in_marts.fact_rows, 0) + coalesce(quarantined.quarantined_rows, 0)
        as is_complete
from all_exports
left join in_marts on all_exports.batch_id = in_marts.batch_id
left join quarantined on all_exports.batch_id = quarantined.batch_id
