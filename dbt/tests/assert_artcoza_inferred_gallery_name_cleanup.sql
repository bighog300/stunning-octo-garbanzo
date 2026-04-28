with mart_galleries_dependency as (
    select 1 as ensure_dependency
    from {{ ref('mart_galleries') }}
    limit 1
),
examples as (
    select *
    from (
        values
            (
                'art.co.za',
                'Creatively Contrasted: New Views On The Permanent Collection at Oliewenhuis Art Museum | Art.co.za Art Exhibition Listings',
                'Oliewenhuis Art Museum'
            ),
            (
                'art.co.za',
                'International Museum Day at Hk Contemporary | Art.co.za Art Exhibition Listings',
                'Hk Contemporary'
            ),
            (
                'art.co.za',
                'Hk Contemporary | Art.co.za Art Gallery Listings',
                'Hk Contemporary'
            ),
            (
                'art.co.za',
                'Slow Down Tiger at Everard Read Johannesburg | Art.co.za Art Exhibition Listings',
                'Everard Read Johannesburg'
            ),
            (
                'art.co.za',
                'Blue Door Print Studio | Art.co.za Art Training',
                'Blue Door Print Studio'
            ),
            (
                'art.co.za',
                'Ibi Artworx | Art.co.za Art Training',
                'Ibi Artworx'
            ),
            (
                'art.co.za',
                'Art Classes With Marrianna Booyens | Art.co.za Art Training',
                'Art Classes With Marrianna Booyens'
            ),
            (
                'art.co.za',
                'Self-exploration Portrait Painting Workshops & Mixed-media Art Workshops | Art.co.za Art Training',
                'Self-exploration Portrait Painting Workshops & Mixed-media Art Workshops'
            )
    ) as t(source_domain, original_gallery_name, expected_gallery_name)
),
normalized as (
    select
        e.*,
        regexp_replace(
            btrim(
                case
                    when lower(coalesce(nullif(btrim(e.source_domain), ''), '')) = 'art.co.za' then
                        coalesce(
                            nullif(
                                regexp_replace(
                                    btrim(e.original_gallery_name),
                                    '^(.*)\s+at\s+(.*)\s+\|\s+Art\.co\.za Art Exhibition Listings$',
                                    '\2',
                                    'i'
                                ),
                                btrim(e.original_gallery_name)
                            ),
                            regexp_replace(
                                regexp_replace(
                                    regexp_replace(
                                        regexp_replace(
                                            btrim(e.original_gallery_name),
                                            '\s+\|\s+Art\.co\.za Art Exhibition Listings$',
                                            '',
                                            'i'
                                        ),
                                        '\s+\|\s+Art\.co\.za Art Gallery Listings$',
                                        '',
                                        'i'
                                    ),
                                    '\s+\|\s+Art\.co\.za Art Training$',
                                    '',
                                    'i'
                                ),
                                '\s+\|\s+Art\.co\.za$',
                                '',
                                'i'
                            )
                        )
                    else btrim(e.original_gallery_name)
                end
            ),
            '\s+',
            ' ',
            'g'
        ) as cleaned_gallery_name
    from examples e
)
select
    n.source_domain,
    n.original_gallery_name,
    n.expected_gallery_name,
    n.cleaned_gallery_name
from normalized n
cross join mart_galleries_dependency d
where n.cleaned_gallery_name <> n.expected_gallery_name
   or n.cleaned_gallery_name like '%| Art.co.za Art Exhibition Listings%'
   or n.cleaned_gallery_name like '%| Art.co.za Art Gallery Listings%'
   or n.cleaned_gallery_name like '%| Art.co.za Art Training%'
   or n.cleaned_gallery_name like '%| Art.co.za%'
