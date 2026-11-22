select
    transaction_id,
    bank,
    cast(booked_at as timestamp) as booked_at,
    cast(booking_date as date) as booking_date,
    flow,
    counterparty,
    reference,
    cast(amount_original as decimal(18, 4)) as amount_original,
    currency_original,
    cast(amount_eur as decimal(18, 2)) as amount_eur,
    cast(business_amount_eur as decimal(18, 2)) as business_amount_eur,
    cast(fx_rate as decimal(18, 6)) as fx_rate,
    cast(fee_eur as decimal(18, 2)) as fee_eur
from {{ source('raw', 'bank_transactions') }}
