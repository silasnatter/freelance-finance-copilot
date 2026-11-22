-- Costs by category must match monthly expenses plus fees for every year.
with categories as (
    select year, sum(amount_eur) as amount_eur
    from {{ ref('mart_expenses_by_category') }}
    group by 1
),

monthly as (
    select year, sum(expenses_eur + fees_eur) as amount_eur
    from {{ ref('mart_monthly_pnl') }}
    group by 1
)

select coalesce(categories.year, monthly.year) as year
from categories
full outer join monthly using (year)
where coalesce(categories.amount_eur, 0) <> coalesce(monthly.amount_eur, 0)
