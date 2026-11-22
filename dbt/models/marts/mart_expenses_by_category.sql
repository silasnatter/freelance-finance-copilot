with costs as (
    select
        cast(extract(year from booking_date) as integer) as year,
        category_id,
        -business_amount_eur as amount_eur
    from {{ ref('fct_transactions') }}
    where flow = 'expense'

    union all

    select
        cast(extract(year from booking_date) as integer) as year,
        'bank_fees' as category_id,
        business_fee_eur as amount_eur
    from {{ ref('fct_transactions') }}
    where business_fee_eur <> 0
),

summed as (
    select
        year,
        category_id,
        sum(amount_eur) as amount_eur,
        count(*) as bookings
    from costs
    group by 1, 2
)

select
    summed.year,
    summed.category_id,
    categories.category_name,
    categories.sort_order,
    cast(summed.amount_eur as decimal(18, 2)) as amount_eur,
    cast(summed.bookings as integer) as bookings
from summed
inner join {{ ref('dim_category') }} as categories using (category_id)
order by summed.year, categories.sort_order
