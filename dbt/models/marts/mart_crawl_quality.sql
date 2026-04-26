select
    source_domain,
    source_name,
    crawl_timestamp::date as crawl_date,
    count(*) as records_found,
    count(*) filter (where artwork_title is null) as missing_title_count,
    count(*) filter (where artist_name is null) as missing_artist_count,
    count(*) filter (where image_url is null) as missing_image_count,
    avg(quality_score) as avg_quality_score,
    now() as dbt_run_timestamp
from {{ ref('mart_artworks') }}
group by 1, 2, 3
