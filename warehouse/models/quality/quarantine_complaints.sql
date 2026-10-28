-- Rows that break a hard rule. They never reach the marts; each keeps its batch and the
-- rule it broke, so failures can be counted per batch and inspected.

select * from {{ ref('int_complaints_checked') }}
where failed_rule is not null
