with event_text_sources as (
    select
        raw_event_id as event_id,
        event_title as source_text
    from {{ ref('stg_events') }}

    union all

    select
        raw_event_id as event_id,
        description as source_text
    from {{ ref('stg_events') }}

    union all

    select
        raw_event_id as event_id,
        coalesce(
            raw_payload->>'artists',
            raw_payload->>'artist',
            raw_payload->>'participants',
            raw_payload->>'performers'
        ) as source_text
    from {{ ref('stg_events') }}
), tokenized as (
    select
        ets.event_id,
        trim(token) as candidate_artist_name
    from event_text_sources ets,
    regexp_split_to_table(
        coalesce(ets.source_text, ''),
        '\s*(?:,|\band\b|&)\s*'
    ) as token
), filtered as (
    select
        event_id,
        candidate_artist_name
    from tokenized
    where candidate_artist_name is not null
      and length(candidate_artist_name) > 3
      and candidate_artist_name ~ '[A-Za-z]'
      and lower(candidate_artist_name) not in (
          'exhibition', 'gallery', 'opening', 'preview', 'talk', 'panel', 'workshop',
          'artist talk', 'group show', 'private view', 'book now', 'tickets', 'event'
      )
      and lower(candidate_artist_name) not like '%gallery%'
), normalized as (
    select
        event_id,
        candidate_artist_name,
        nullif(
            trim(
                regexp_replace(
                    regexp_replace(
                        regexp_replace(lower(candidate_artist_name), '[^a-z0-9\s]', ' ', 'g'),
                        '\s+',
                        ' ',
                        'g'
                    ),
                    '\m(artist|studio)\M',
                    '',
                    'g'
                )
            ),
            ''
        ) as normalized_candidate_artist_name
    from filtered
)
select distinct
    event_id,
    candidate_artist_name,
    normalized_candidate_artist_name
from normalized
where normalized_candidate_artist_name is not null
