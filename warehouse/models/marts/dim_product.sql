-- One row per product and sub-product pair, with the product group that stays stable
-- across the CFPB's 2017 and 2023 renames (seeds/product_groups.csv).

with pairs as (

    select
        product_key,
        product,
        sub_product,
        min(date_received) as first_complaint_received,
        max(date_received) as last_complaint_received
    from {{ ref('int_complaints_checked') }}
    where failed_rule is null
    group by product_key, product, sub_product

)

select
    pairs.product_key,
    pairs.product,
    pairs.sub_product,
    product_groups.product_group,
    pairs.first_complaint_received,
    pairs.last_complaint_received

from pairs
left join {{ ref('product_groups') }} as product_groups
    on pairs.product = product_groups.product
