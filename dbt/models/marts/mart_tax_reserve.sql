with year_to_date as (
    select
        month_start,
        year,
        year_month,
        sum(profit_eur) over (
            partition by year order by month_start rows unbounded preceding
        ) as profit_ytd_eur,
        sum(tax_payments_eur) over (
            partition by year order by month_start rows unbounded preceding
        ) as tax_paid_ytd_eur
    from {{ ref('mart_monthly_pnl') }}
),

reserve as (
    select
        *,
        cast({{ var('tax_reserve_rate') }} as decimal(5, 4)) as reserve_rate,
        cast(
            greatest(profit_ytd_eur, 0) * {{ var('tax_reserve_rate') }} as decimal(18, 2)
        ) as reserve_target_ytd_eur
    from year_to_date
)

select
    month_start,
    year,
    year_month,
    cast(profit_ytd_eur as decimal(18, 2)) as profit_ytd_eur,
    reserve_rate,
    reserve_target_ytd_eur,
    cast(tax_paid_ytd_eur as decimal(18, 2)) as tax_paid_ytd_eur,
    cast(reserve_target_ytd_eur - tax_paid_ytd_eur as decimal(18, 2)) as reserve_open_eur,
    true as is_estimate
from reserve
order by month_start
