select
    *,
    -- Wise is a pure business pass-through, so all of its fees are business costs.
    cast(
        case
            when bank = 'wise' or flow in ('income', 'expense') then fee_eur
            else 0
        end as decimal(18, 2)
    ) as business_fee_eur
from {{ ref('stg_bank__transactions') }}
