with transactions as (
    select * from {{ ref('fct_transactions') }}
),

bounds as (
    select
        cast(date_trunc('month', min(booking_date)) as date) as first_month,
        cast(date_trunc('month', max(booking_date)) as date) as last_month
    from transactions
),

months as (
    select distinct
        cast(date_trunc('month', dates.date_day) as date) as month_start,
        dates.year,
        dates.year_month
    from {{ ref('dim_date') }} as dates
    cross join bounds
    where cast(date_trunc('month', dates.date_day) as date)
        between bounds.first_month and bounds.last_month
),

monthly as (
    select
        cast(date_trunc('month', booking_date) as date) as month_start,
        sum(case when flow = 'income' then business_amount_eur else 0 end) as revenue_eur,
        -sum(case when flow = 'expense' then business_amount_eur else 0 end) as expenses_eur,
        sum(business_fee_eur) as fees_eur,
        -sum(case when flow = 'tax' then business_amount_eur else 0 end) as tax_payments_eur,
        count(*) filter (where flow = 'needs_review') as open_review_bookings
    from transactions
    group by 1
)

select
    months.month_start,
    months.year,
    cast(extract(quarter from months.month_start) as integer) as quarter,
    months.year_month,
    cast(coalesce(monthly.revenue_eur, 0) as decimal(18, 2)) as revenue_eur,
    cast(coalesce(monthly.expenses_eur, 0) as decimal(18, 2)) as expenses_eur,
    cast(coalesce(monthly.fees_eur, 0) as decimal(18, 2)) as fees_eur,
    cast(
        coalesce(monthly.revenue_eur, 0)
        - coalesce(monthly.expenses_eur, 0)
        - coalesce(monthly.fees_eur, 0)
        as decimal(18, 2)
    ) as profit_eur,
    cast(coalesce(monthly.tax_payments_eur, 0) as decimal(18, 2)) as tax_payments_eur,
    cast(coalesce(monthly.open_review_bookings, 0) as integer) as open_review_bookings
from months
left join monthly using (month_start)
order by months.month_start
