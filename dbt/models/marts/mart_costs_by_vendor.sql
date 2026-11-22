select
    cast(extract(year from transactions.booking_date) as integer) as year,
    coalesce(nullif(transactions.counterparty, ''), left(transactions.reference, 40)) as vendor,
    categories.category_name,
    cast(-sum(transactions.business_amount_eur) as decimal(18, 2)) as cost_eur,
    cast(count(*) as integer) as bookings
from {{ ref('fct_transactions') }} as transactions
inner join {{ ref('dim_category') }} as categories using (category_id)
where transactions.flow = 'expense'
group by 1, 2, 3
order by 1, 2
