select *
from {{ ref('mart_artworks') }}
where year_start is not null
  and year_end is not null
  and year_start > year_end
