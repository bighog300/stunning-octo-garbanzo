with source_artists as (
    select
        id as artist_id,
        {{ clean_text('source_domain') }} as source_domain,
        {{ clean_text('artist_name') }} as artist_name
    from {{ source('raw', 'artists') }}
    where {{ clean_text('artist_name') }} is not null
), normalized as (
    select
        artist_id,
        source_domain,
        artist_name,
        nullif(
            trim(
                regexp_replace(
                    regexp_replace(
                        regexp_replace(lower(artist_name), '[^a-z0-9\s]', ' ', 'g'),
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
        ) as normalized_artist_name
    from source_artists
)
select
    artist_id,
    source_domain,
    artist_name,
    normalized_artist_name
from normalized
where normalized_artist_name is not null
