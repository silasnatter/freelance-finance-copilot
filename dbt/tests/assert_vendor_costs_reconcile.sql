-- Costs by vendor must match monthly expenses for every year.
with vendors as (
    select year, sum(cost_eur) as amount_eur
    from {{ ref('mart_costs_by_vendor') }}
    group by 1
),

monthly as (
    select year, sum(expenses_eur) as amount_eur
    from {{ ref('mart_monthly_pnl') }}
    group by 1
)

select coalesce(vendors.year, monthly.year) as year
from vendors
full outer join monthly using (year)
where coalesce(vendors.amount_eur, 0) <> coalesce(monthly.amount_eur, 0)
