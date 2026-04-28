with base as (
    select
        raw_gallery_id,
        source_domain,
        source_url,
        source_record_id,
        gallery_name as original_gallery_name,
        regexp_replace(
            btrim(
                case
                    when lower(coalesce(nullif(btrim(source_domain), ''), '')) = 'art.co.za' then
                        regexp_replace(
                            btrim(gallery_name),
                            '\s*\|\s*Art\.co\.za(?:\s+Art\s+Gallery\s+Listings)?\s*$',
                            '',
                            'i'
                        )
                    else btrim(gallery_name)
                end
            ),
            '\s+',
            ' ',
            'g'
        ) as gallery_name,
        address,
        city,
        region,
        country,
        regexp_replace(coalesce(phone, ''), '[^0-9+]+', ' ', 'g') as phone_normalized,
        lower(email) as email_normalized,
        case
            when coalesce(website_url, '') = '' then null
            when website_url ~* '^https?://' then lower(website_url)
            else lower(concat('https://', website_url))
        end as website_url_pre_normalized,
        regexp_replace(lower(instagram_url), '^https?://(www\.)?instagram\.com/', 'https://instagram.com/') as instagram_url_pre_normalized,
        regexp_replace(lower(facebook_url), '^https?://(www\.)?facebook\.com/', 'https://facebook.com/') as facebook_url_pre_normalized,
        contact_person,
        description,
        raw_payload,
        crawl_timestamp,
        created_at
    from {{ ref('stg_galleries') }}
),
url_params as (
    select
        b.raw_gallery_id,
        string_agg(param, '&' order by ordinality) filter (
            where param is not null
              and param <> ''
              and split_part(param, '=', 1) !~* '^utm_(source|medium|campaign|term|content)$'
        ) as retained_query
    from base b
    left join lateral unnest(string_to_array(split_part(coalesce(b.website_url_pre_normalized, ''), '?', 2), '&')) with ordinality as p(param, ordinality)
        on true
    group by b.raw_gallery_id
),
normalized as (
    select
        b.raw_gallery_id,
        b.source_domain,
        b.source_url,
        b.source_record_id,
        initcap(nullif(b.gallery_name, '')) as gallery_name,
        b.original_gallery_name,
        b.address,
        b.city,
        b.region,
        b.country,
        b.phone_normalized,
        b.email_normalized,
        case
            when coalesce(b.website_url_pre_normalized, '') = '' then null
            when coalesce(u.retained_query, '') = '' then split_part(b.website_url_pre_normalized, '?', 1)
            else concat(split_part(b.website_url_pre_normalized, '?', 1), '?', u.retained_query)
        end as website_url_normalized,
        case
            when regexp_replace(coalesce(b.instagram_url_pre_normalized, ''), '/+$', '') in ('https://instagram.com/artcoza') then null
            else b.instagram_url_pre_normalized
        end as instagram_url_normalized,
        case
            when regexp_replace(coalesce(b.facebook_url_pre_normalized, ''), '/+$', '') in ('https://facebook.com/artcoza') then null
            else b.facebook_url_pre_normalized
        end as facebook_url_normalized,
        b.contact_person,
        b.description,
        b.raw_payload,
        b.crawl_timestamp,
        b.created_at
    from base b
    left join url_params u
        on u.raw_gallery_id = b.raw_gallery_id
),
scored as (
    select
        *,
        lower(regexp_replace(coalesce(gallery_name, ''), '\s+', ' ', 'g')) as normalized_gallery_name,
        lower(regexp_replace(coalesce(city, ''), '\s+', ' ', 'g')) as normalized_city,
        lower(regexp_replace(coalesce(country, ''), '\s+', ' ', 'g')) as normalized_country,
        concat_ws('|',
            lower(regexp_replace(coalesce(gallery_name, ''), '\s+', ' ', 'g')),
            lower(regexp_replace(coalesce(city, ''), '\s+', ' ', 'g')),
            lower(regexp_replace(coalesce(country, ''), '\s+', ' ', 'g')),
            coalesce(source_domain, '')
        ) as normalized_gallery_key
    from normalized
)
select
    *,
    (
        (case when coalesce(gallery_name, '') <> '' then 1 else 0 end) +
        (case when coalesce(address, '') <> '' then 1 else 0 end) +
        (case when coalesce(city, '') <> '' then 1 else 0 end) +
        (case when coalesce(country, '') <> '' then 1 else 0 end) +
        (case when coalesce(phone_normalized, '') <> '' then 1 else 0 end) +
        (case when coalesce(email_normalized, '') <> '' then 1 else 0 end) +
        (case when coalesce(website_url_normalized, '') <> '' then 1 else 0 end) +
        (case when coalesce(instagram_url_normalized, '') <> '' or coalesce(facebook_url_normalized, '') <> '' then 1 else 0 end)
    )::int as contact_quality_score,
    array_remove(array[
        case when coalesce(email_normalized, '') = '' then 'missing_email' end,
        case when coalesce(phone_normalized, '') = '' then 'missing_phone' end,
        case when coalesce(website_url_normalized, '') = '' then 'missing_website' end,
        case when coalesce(instagram_url_normalized, '') = '' and coalesce(facebook_url_normalized, '') = '' then 'missing_social' end
    ], null)::text[] as quality_flags
from scored
