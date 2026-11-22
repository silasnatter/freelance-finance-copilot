with dates as (
    select cast(unnest(generate_series(date '2020-01-01', date '2035-12-31', interval 1 day)) as date) as date_day
)

select
    date_day,
    cast(extract(year from date_day) as integer) as year,
    cast(extract(quarter from date_day) as integer) as quarter,
    cast(extract(month from date_day) as integer) as month,
    strftime(date_day, '%Y-%m') as year_month,
    cast(isodow(date_day) as integer) as iso_weekday,
    isodow(date_day) >= 6 as is_weekend
from dates
