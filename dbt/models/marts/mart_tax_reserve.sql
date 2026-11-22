with settings as (
    select * from {{ ref('stg_reserve__settings') }}
),

months as (
    select pnl.month_start, pnl.year, pnl.year_month
    from {{ ref('mart_monthly_pnl') }} as pnl
    cross join settings
    where pnl.month_start >= cast(date_trunc('month', settings.start_date) as date)
),

monthly as (
    select
        cast(date_trunc('month', transactions.booking_date) as date) as month_start,
        sum(case when transactions.flow = 'income' then transactions.business_amount_eur else 0 end)
            as revenue_eur,
        -sum(
            case
                when transactions.flow = 'expense' and transactions.paid_from_reserve
                    then transactions.business_amount_eur
                else 0
            end
        ) as insurance_eur,
        -sum(case when transactions.flow = 'tax' then transactions.business_amount_eur else 0 end)
            as tax_eur
    from {{ ref('fct_transactions') }} as transactions
    cross join settings
    where transactions.booking_date >= settings.start_date
    group by 1
),

running as (
    select
        months.month_start,
        months.year,
        months.year_month,
        sum(coalesce(monthly.revenue_eur, 0)) over cumulative as revenue_eur,
        sum(coalesce(monthly.insurance_eur, 0)) over cumulative as insurance_paid_eur,
        sum(coalesce(monthly.tax_eur, 0)) over cumulative as tax_paid_eur
    from months
    left join monthly using (month_start)
    window cumulative as (order by months.month_start rows unbounded preceding)
),

calculated as (
    select
        running.*,
        settings.start_balance_eur,
        settings.income_share,
        cast(running.revenue_eur * settings.income_share as decimal(18, 2)) as reserve_added_eur
    from running
    cross join settings
)

select
    month_start,
    year,
    year_month,
    start_balance_eur,
    income_share,
    reserve_added_eur,
    cast(insurance_paid_eur as decimal(18, 2)) as insurance_paid_eur,
    cast(tax_paid_eur as decimal(18, 2)) as tax_paid_eur,
    cast(
        start_balance_eur + reserve_added_eur - insurance_paid_eur - tax_paid_eur
        as decimal(18, 2)
    ) as target_balance_eur,
    true as is_estimate
from calculated
order by month_start
