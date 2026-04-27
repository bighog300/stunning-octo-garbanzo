-- source_url cannot be mandatory for art.co.za rows because some valid records
-- are represented by stable IDs/images without a canonical listing URL.
-- Fail only rows lacking both source_url and fallback artwork identity signals.
select *
from {{ ref('mart_artworks') }}
where source_url is null
  and (
    source_domain <> 'art.co.za'
    or coalesce(source_record_id, image_url, thumbnail_url) is null
    or coalesce(artwork_title, artist_name) is null
  )
