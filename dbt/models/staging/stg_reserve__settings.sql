select
    cast(start_date as date) as start_date,
    cast(start_balance_eur as decimal(18, 2)) as start_balance_eur,
    cast(income_share as decimal(5, 4)) as income_share
from {{ source('raw', 'reserve_settings') }}
