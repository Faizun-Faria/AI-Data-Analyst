-- One row per day of the archive window. 2011 (December only) and 2026 (to 31 August)
-- are partial years, so year-on-year comparisons must allow for them.

with days as (

    select cast(unnest(generate_series(
        date '{{ var("archive_start") }}', date '{{ var("archive_end") }}', interval 1 day
    )) as date) as date_day

)

select
    date_day,
    year(date_day) as year,
    quarter(date_day) as quarter,
    month(date_day) as month,
    monthname(date_day) as month_name,
    strftime(date_day, '%Y-%m') as year_month,
    cast(date_trunc('week', date_day) as date) as week_start,
    dayname(date_day) as day_name,
    isodow(date_day) >= 6 as is_weekend,
    year(date_day) in (
        year(date '{{ var("archive_start") }}'), year(date '{{ var("archive_end") }}')
    ) as is_partial_year

from days
