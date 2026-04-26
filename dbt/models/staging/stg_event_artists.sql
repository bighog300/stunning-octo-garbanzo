select
    id as raw_event_artist_id,
    event_id,
    {{ clean_text('artist_name') }} as artist_name,
    {{ clean_text('artist_name_normalized') }} as artist_name_normalized,
    {{ clean_text('artist_profile_url') }} as artist_profile_url,
    {{ clean_text('match_type') }} as match_type
from {{ source('raw', 'event_artists') }}
