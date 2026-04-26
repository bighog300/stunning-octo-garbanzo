select
    raw_artwork_id,
    dimensions_text,
    null::numeric as height_cm,
    null::numeric as width_cm,
    null::numeric as depth_cm,
    null::text as dimension_unit_original,
    case when dimensions_text is null then 'missing' else 'failed' end as dimension_parse_status
from {{ ref('stg_artworks') }}
