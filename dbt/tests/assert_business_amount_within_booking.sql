-- A business share can never exceed the booking or have the opposite sign.
select transaction_id
from {{ ref('fct_transactions') }}
where abs(business_amount_eur) > abs(amount_eur)
    or business_amount_eur * amount_eur < 0
