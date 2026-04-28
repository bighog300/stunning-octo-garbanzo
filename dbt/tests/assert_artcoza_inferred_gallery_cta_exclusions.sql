with examples as (
    select *
    from (
        values
            (
                'art.co.za',
                'inferred_from_event',
                'List Your Gallery on Art.co.za | Art in South Africa',
                'List Your Gallery on Art.co.za | Art in South Africa',
                true
            ),
            (
                'art.co.za',
                'inferred_from_event',
                'List Your Art Exhibition on Art.co.za | Art in South Africa',
                'List Your Art Exhibition on Art.co.za | Art in South Africa',
                true
            ),
            (
                'art.co.za',
                'inferred_from_event',
                'Everard Read Johannesburg',
                'Slow Down Tiger at Everard Read Johannesburg | Art.co.za Art Exhibition Listings',
                false
            )
    ) as t(source_domain, gallery_record_type, gallery_name, original_gallery_name, expected_excluded)
),
evaluated as (
    select
        e.*,
        (
            e.source_domain = 'art.co.za'
            and e.gallery_record_type = 'inferred_from_event'
            and (
                (
                    coalesce(e.gallery_name, '') ~* '(list your gallery|list your art exhibition|submit your gallery|advertise|login|register|sign up)'
                    or coalesce(e.original_gallery_name, '') ~* '(list your gallery|list your art exhibition|submit your gallery|advertise|login|register|sign up)'
                )
                or (
                    (
                        coalesce(e.gallery_name, '') ilike '%Art in South Africa%'
                        or coalesce(e.original_gallery_name, '') ilike '%Art in South Africa%'
                    )
                    and (
                        coalesce(e.gallery_name, '') ilike '%Art.co.za%'
                        or coalesce(e.original_gallery_name, '') ilike '%Art.co.za%'
                    )
                )
                or (
                    char_length(trim(coalesce(e.gallery_name, ''))) <= 3
                    or lower(coalesce(e.gallery_name, '')) in (
                        'home',
                        'gallery',
                        'galleries',
                        'events',
                        'art in south africa'
                    )
                )
            )
        ) as actual_excluded
    from examples e
)
select
    source_domain,
    gallery_record_type,
    gallery_name,
    original_gallery_name,
    expected_excluded,
    actual_excluded
from evaluated
where actual_excluded <> expected_excluded
