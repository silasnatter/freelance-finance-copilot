select
    category_id,
    category_name,
    sort_order
from {{ ref('stg_bank__categories') }}
