-- Private spending, transfers and open bookings must never reach profit.
select transaction_id
from {{ ref('fct_transactions') }}
where flow in ('transfer', 'conversion', 'private', 'investment', 'needs_review')
    and business_amount_eur <> 0
