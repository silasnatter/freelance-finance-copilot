-- Total profit in the mart must match the underlying bookings to the cent.
with bookings as (
    select
        sum(case when flow in ('income', 'expense') then business_amount_eur else 0 end)
        - sum(business_fee_eur) as profit_eur
    from {{ ref('fct_transactions') }}
),

mart as (
    select sum(profit_eur) as profit_eur
    from {{ ref('mart_monthly_pnl') }}
)

select bookings.profit_eur as bookings_profit, mart.profit_eur as mart_profit
from bookings
cross join mart
where bookings.profit_eur is distinct from mart.profit_eur
