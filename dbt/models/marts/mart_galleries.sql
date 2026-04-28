with deduped as (
    select *
    from (
        select
            g.*,
            row_number() over (
                partition by coalesce(nullif(g.source_record_id, ''), g.source_url)
                order by g.crawl_timestamp desc nulls last, g.created_at desc nulls last
            ) as dedupe_rank
        from {{ ref('int_gallery_normalized') }} g
    ) ranked
    where dedupe_rank = 1
),
event_links as (
    select
        d.raw_gallery_id,
        jsonb_agg(
            distinct jsonb_build_object(
                'event_id', e.event_id,
                'event_title', e.event_title,
                'city', e.city,
                'country', e.country,
                'source_domain', e.source_domain
            )
        ) filter (where e.event_id is not null) as linked_events
    from deduped d
    left join {{ ref('mart_events') }} e
        on lower(regexp_replace(coalesce(e.venue_name, ''), '\s+', ' ', 'g')) = d.normalized_gallery_name
       and lower(regexp_replace(coalesce(e.city, ''), '\s+', ' ', 'g')) = d.normalized_city
       and lower(regexp_replace(coalesce(e.country, ''), '\s+', ' ', 'g')) = d.normalized_country
       and e.source_domain = d.source_domain
    group by d.raw_gallery_id
),
artist_links as (
    select
        d.raw_gallery_id,
        coalesce(
            (
                select jsonb_agg(
                    distinct jsonb_build_object(
                        'artist_name', artist_item->>'name',
                        'artist_profile_url', artist_item->>'profile_url'
                    )
                )
                from jsonb_array_elements(coalesce(d.raw_payload->'represented_artists', '[]'::jsonb)) artist_item
            ),
            '[]'::jsonb
        ) as linked_artists
    from deduped d
),
artwork_links as (
    select
        d.raw_gallery_id,
        jsonb_agg(
            distinct jsonb_build_object(
                'artwork_id', a.raw_artwork_id,
                'artwork_title', a.artwork_title,
                'artist_name', a.artist_name,
                'source_url', a.source_url
            )
        ) filter (where a.raw_artwork_id is not null) as linked_artworks
    from deduped d
    left join {{ ref('stg_artworks') }} a
        on lower(regexp_replace(coalesce(a.gallery_name, ''), '\s+', ' ', 'g')) = d.normalized_gallery_name
       and a.source_domain = d.source_domain
    group by d.raw_gallery_id
)
select
    (
        substr(md5(d.normalized_gallery_key), 1, 8)
        || '-' || substr(md5(d.normalized_gallery_key), 9, 4)
        || '-' || substr(md5(d.normalized_gallery_key), 13, 4)
        || '-' || substr(md5(d.normalized_gallery_key), 17, 4)
        || '-' || substr(md5(d.normalized_gallery_key), 21, 12)
    )::uuid as gallery_id,
    d.raw_gallery_id,
    d.source_domain,
    d.source_url,
    d.source_record_id,
    d.gallery_name,
    d.address as gallery_address,
    d.city,
    d.region,
    d.country,
    nullif(trim(d.phone_normalized), '') as phone,
    d.email_normalized as email,
    d.website_url_normalized as website_url,
    d.instagram_url_normalized as instagram_url,
    d.facebook_url_normalized as facebook_url,
    d.contact_person,
    d.description,
    d.normalized_gallery_key,
    d.contact_quality_score,
    d.quality_flags,
    coalesce(el.linked_events, '[]'::jsonb) as linked_events,
    coalesce(al.linked_artists, '[]'::jsonb) as linked_artists,
    coalesce(aw.linked_artworks, '[]'::jsonb) as linked_artworks,
    d.raw_payload,
    d.crawl_timestamp,
    d.created_at
from deduped d
left join event_links el on el.raw_gallery_id = d.raw_gallery_id
left join artist_links al on al.raw_gallery_id = d.raw_gallery_id
left join artwork_links aw on aw.raw_gallery_id = d.raw_gallery_id
