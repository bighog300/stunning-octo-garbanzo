with known_artist_case as (
    select
        trim(regexp_replace(regexp_replace(regexp_replace(lower('David Hockney'), '[^a-z0-9\s]', ' ', 'g'), '\s+', ' ', 'g'), '\m(artist|studio)\M', '', 'g')) as normalized_artist,
        trim(regexp_replace(regexp_replace(regexp_replace(lower('Exhibition: David Hockney and Friends'), '[^a-z0-9\s]', ' ', 'g'), '\s+', ' ', 'g'), '\m(artist|studio)\M', '', 'g')) as normalized_title
), generic_tokens as (
    select trim(token) as token
    from regexp_split_to_table('Exhibition opening and gallery preview', '\s*(?:,|\band\b|&)\s*') as token
), generic_filtered as (
    select token
    from generic_tokens
    where token is not null
      and length(token) > 3
      and token ~ '[A-Za-z]'
      and lower(token) not in (
          'exhibition', 'gallery', 'opening', 'preview', 'talk', 'panel', 'workshop',
          'artist talk', 'group show', 'private view', 'book now', 'tickets', 'event'
      )
      and lower(token) not like '%gallery%'
), duplicate_links as (
    select event_id, artist_id, count(*) as link_count
    from {{ ref('mart_event_artists') }}
    group by event_id, artist_id
    having count(*) > 1
), failures as (
    select 'known_artist_should_match' as failure
    from known_artist_case
    where normalized_title not like '%' || normalized_artist || '%'

    union all

    select 'generic_text_should_not_match' as failure
    from generic_filtered

    union all

    select 'duplicate_event_artist_links' as failure
    from duplicate_links
)
select * from failures
