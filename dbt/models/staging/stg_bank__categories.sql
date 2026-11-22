select
    id as category_id,
    name as category_name,
    cast(sort_order as integer) as sort_order
from {{ source('raw', 'categories') }}
