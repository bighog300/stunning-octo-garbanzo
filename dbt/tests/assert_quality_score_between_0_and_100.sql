select *
from {{ ref('mart_artworks') }}
where quality_score < 0 or quality_score > 100
