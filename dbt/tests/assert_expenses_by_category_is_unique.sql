-- One row per year and category.
select year, category_id
from {{ ref('mart_expenses_by_category') }}
group by 1, 2
having count(*) > 1
