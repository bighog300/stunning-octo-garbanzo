with deduped as (
    select
        m.event_id,
        m.artist_id,
        a.artist_name,
        a.source_domain,
        m.match_type,
        1.0::numeric as confidence_score,
        row_number() over (
            partition by m.event_id, m.artist_id
            order by a.artist_name
        ) as row_num
    from {{ ref('int_event_artist_matches') }} m
    inner join {{ ref('int_artist_normalized') }} a
        on a.artist_id = m.artist_id
)
select
    event_id,
    artist_id,
    artist_name,
    source_domain,
    match_type,
    confidence_score
from deduped
where row_num = 1
