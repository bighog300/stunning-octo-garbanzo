select
    gen_random_uuid() as artwork_id,
    a.raw_artwork_id,
    a.artist_name,
    a.artwork_title,
    d.year_start,
    d.year_end,
    a.artwork_date_text,
    a.medium_text,
    coalesce(mc.medium_category, 'unknown') as medium_category,
    a.dimensions_text,
    dim.height_cm,
    dim.width_cm,
    dim.depth_cm,
    a.price_text,
    p.price_numeric,
    p.currency_code,
    a.source_name,
    a.source_domain,
    a.source_url,
    a.source_record_id,
    a.image_url,
    a.thumbnail_url,
    a.description,
    a.crawl_timestamp,
    a.created_at
from {{ ref('stg_artworks') }} a
left join {{ ref('int_dates_parsed') }} d using (raw_artwork_id)
left join {{ ref('int_price_parsed') }} p using (raw_artwork_id)
left join {{ ref('int_dimensions_parsed') }} dim using (raw_artwork_id)
left join {{ ref('medium_categories') }} mc
    on lower(coalesce(a.medium_text, '')) like '%' || lower(mc.keyword) || '%'
