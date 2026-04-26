select
    ea.raw_event_artist_id as artist_activity_id,
    ea.event_id,
    ea.artist_name,
    ea.artist_name_normalized,
    ea.artist_profile_url,
    ea.match_type,
    e.event_type,
    e.event_title,
    e.city,
    e.country,
    e.start_date,
    e.end_date,
    e.source_domain,
    e.source_url,
    e.crawl_timestamp
from {{ ref('stg_event_artists') }} ea
inner join {{ ref('stg_events') }} e
    on e.raw_event_id = ea.event_id
