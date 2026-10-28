-- One row per company named in a complaint that reached the marts.

select
    company_key,
    company as company_name,
    min(date_received) as first_complaint_received,
    max(date_received) as last_complaint_received

from {{ ref('int_complaints_checked') }}
where failed_rule is null
group by company_key, company
