select
    raw_artwork_id,
    artwork_date_text,
    case
        when artwork_date_text ~ '^[0-9]{4}$' then artwork_date_text::integer
        else null
    end as year_start,
    case
        when artwork_date_text ~ '^[0-9]{4}$' then artwork_date_text::integer
        else null
    end as year_end,
    case
        when artwork_date_text is null then 'missing'
        when artwork_date_text ~ '^[0-9]{4}$' then 'parsed'
        else 'failed'
    end as date_parse_status
from {{ ref('stg_artworks') }}
