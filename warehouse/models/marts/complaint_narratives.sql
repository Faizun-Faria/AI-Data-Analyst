-- The narrative text of each complaint in fct_complaints that has one. Kept apart from the
-- fact table because it's long text that most questions don't need.

select
    staged.complaint_id,
    staged.narrative

from {{ ref('stg_cfpb__complaints') }} as staged
inner join {{ ref('int_complaints_checked') }} as checked
    on staged.bronze_row_id = checked.bronze_row_id
where checked.failed_rule is null
    and staged.narrative is not null
