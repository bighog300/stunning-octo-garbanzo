select
    raw_artwork_id,
    price_text,
    null::numeric as price_numeric,
    null::text as currency_code,
    null::numeric as price_min,
    null::numeric as price_max,
    false as price_is_range,
    price_text is not null as price_is_available,
    case
        when price_text is null then 'missing'
        when lower(price_text) like '%price on request%' then 'price_on_request'
        when lower(price_text) like '%sold%' then 'not_available'
        else 'failed'
    end as price_parse_status
from {{ ref('stg_artworks') }}
