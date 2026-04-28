with dependency as (
    select 1 as ensure_dependency
    from {{ ref('int_gallery_normalized') }}
    limit 1
),
examples as (
    select *
    from (
        values
            (
                'art.co.za',
                'Artist Proof Studio | Art.Co.Za Art Gallery Listings',
                'https://example.com/gallery?utm_source=artcoza&utm_medium=referral&foo=bar',
                'https://instagram.com/artcoza',
                'https://facebook.com/artcoza',
                'Artist Proof Studio',
                'https://example.com/gallery?foo=bar',
                null::text,
                null::text
            ),
            (
                'art.co.za',
                'Ann Bryant Art Gallery | Art.Co.Za Art Gallery Listings',
                'https://example.org/path?utm_campaign=spring&utm_content=hero',
                'https://www.instagram.com/artcoza',
                'https://www.facebook.com/artcoza',
                'Ann Bryant Art Gallery',
                'https://example.org/path',
                null::text,
                null::text
            )
    ) as t(
        source_domain,
        original_gallery_name,
        website_url,
        instagram_url,
        facebook_url,
        expected_gallery_name,
        expected_website_url,
        expected_instagram_url,
        expected_facebook_url
    )
),
normalized as (
    select
        e.*,
        regexp_replace(
            btrim(
                case
                    when lower(coalesce(nullif(btrim(e.source_domain), ''), '')) = 'art.co.za' then
                        regexp_replace(
                            btrim(e.original_gallery_name),
                            '\s*\|\s*Art\.co\.za(?:\s+Art\s+Gallery\s+Listings)?\s*$',
                            '',
                            'i'
                        )
                    else btrim(e.original_gallery_name)
                end
            ),
            '\s+',
            ' ',
            'g'
        ) as cleaned_gallery_name,
        case
            when coalesce(e.website_url, '') = '' then null
            else lower(e.website_url)
        end as website_url_pre_normalized,
        regexp_replace(lower(e.instagram_url), '^https?://(www\.)?instagram\.com/', 'https://instagram.com/') as instagram_url_pre_normalized,
        regexp_replace(lower(e.facebook_url), '^https?://(www\.)?facebook\.com/', 'https://facebook.com/') as facebook_url_pre_normalized
    from examples e
),
finalized as (
    select
        n.*,
        case
            when coalesce(n.website_url_pre_normalized, '') = '' then null
            when coalesce(cleaned_query.retained_query, '') = '' then split_part(n.website_url_pre_normalized, '?', 1)
            else concat(split_part(n.website_url_pre_normalized, '?', 1), '?', cleaned_query.retained_query)
        end as cleaned_website_url,
        case
            when regexp_replace(coalesce(n.instagram_url_pre_normalized, ''), '/+$', '') in ('https://instagram.com/artcoza') then null
            else n.instagram_url_pre_normalized
        end as cleaned_instagram_url,
        case
            when regexp_replace(coalesce(n.facebook_url_pre_normalized, ''), '/+$', '') in ('https://facebook.com/artcoza') then null
            else n.facebook_url_pre_normalized
        end as cleaned_facebook_url
    from normalized n
    left join lateral (
        select
            string_agg(param, '&' order by ordinality) filter (
                where param is not null
                  and param <> ''
                  and split_part(param, '=', 1) !~* '^utm_(source|medium|campaign|term|content)$'
            ) as retained_query
        from unnest(string_to_array(split_part(coalesce(n.website_url_pre_normalized, ''), '?', 2), '&')) with ordinality as p(param, ordinality)
    ) cleaned_query
        on true
)
select
    f.source_domain,
    f.original_gallery_name,
    f.cleaned_gallery_name,
    f.expected_gallery_name,
    f.cleaned_website_url,
    f.expected_website_url,
    f.cleaned_instagram_url,
    f.expected_instagram_url,
    f.cleaned_facebook_url,
    f.expected_facebook_url
from finalized f
cross join dependency d
where f.cleaned_gallery_name <> f.expected_gallery_name
   or coalesce(f.cleaned_website_url, '') <> coalesce(f.expected_website_url, '')
   or coalesce(f.cleaned_instagram_url, '') <> coalesce(f.expected_instagram_url, '')
   or coalesce(f.cleaned_facebook_url, '') <> coalesce(f.expected_facebook_url, '')
