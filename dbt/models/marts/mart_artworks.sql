select
    artwork_id,
    raw_artwork_id,
    null::uuid as artist_id,
    artist_name,
    artwork_title,
    year_start,
    year_end,
    artwork_date_text,
    medium_text,
    medium_category,
    dimensions_text,
    height_cm,
    width_cm,
    depth_cm,
    price_text,
    price_numeric,
    currency_code,
    source_name,
    source_domain,
    source_url,
    source_record_id,
    image_url,
    thumbnail_url,
    description,
    {{ quality_score() }} as quality_score,
    null::text as duplicate_group_key,
    false as is_duplicate_candidate,
    crawl_timestamp,
    created_at
from {{ ref('int_artwork_normalized') }}
where
    -- source_url is often NULL for valid art.co.za listings where the crawler only captures
    -- stable record IDs/images; require stronger fallback identity/asset signals instead.
    source_url is not null
    or (
        source_domain = 'art.co.za'
        and coalesce(source_record_id, image_url, thumbnail_url) is not null
        and coalesce(artwork_title, artist_name) is not null
    )
