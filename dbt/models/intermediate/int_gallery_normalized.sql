with base as (
    select
        raw_gallery_id,
        source_domain,
        source_url,
        source_record_id,
        initcap(gallery_name) as gallery_name,
        address,
        city,
        region,
        country,
        regexp_replace(coalesce(phone, ''), '[^0-9+]+', ' ', 'g') as phone_normalized,
        lower(email) as email_normalized,
        case when website_url ~* '^https?://' then lower(website_url) else lower(concat('https://', website_url)) end as website_url_normalized,
        regexp_replace(lower(instagram_url), '^https?://(www\.)?instagram\.com/', 'https://instagram.com/') as instagram_url_normalized,
        regexp_replace(lower(facebook_url), '^https?://(www\.)?facebook\.com/', 'https://facebook.com/') as facebook_url_normalized,
        contact_person,
        description,
        raw_payload,
        crawl_timestamp,
        created_at
    from {{ ref('stg_galleries') }}
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
    from base
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
