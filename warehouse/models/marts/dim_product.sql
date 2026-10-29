-- One row per product and sub-product pair, with the product group that stays stable
-- across the CFPB's 2017 and 2023 renames. A pair listed in
-- seeds/product_group_overrides.csv takes its group from there; every other pair takes
-- the group of its product from seeds/product_groups.csv.

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
    coalesce(overrides.product_group, product_groups.product_group) as product_group,
    pairs.first_complaint_received,
    pairs.last_complaint_received

from pairs
left join {{ ref('product_group_overrides') }} as overrides
    on pairs.product = overrides.product
    and pairs.sub_product = overrides.sub_product
left join {{ ref('product_groups') }} as product_groups
    on pairs.product = product_groups.product
