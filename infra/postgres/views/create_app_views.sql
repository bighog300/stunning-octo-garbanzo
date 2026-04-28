\connect artio

-- Run this script only after dbt has built analytics.mart_artworks (for example after `dbt run`).
-- This view intentionally lives outside init scripts because mart_artworks does not exist at initial DB bootstrap time.
CREATE OR REPLACE VIEW app.artwork_records AS
WITH latest_artwork AS (
    -- Latest-crawl wins when multiple raw rows share a source_record_id.
    -- For NULL source_record_id values, keep each raw row by partitioning on raw_artwork_id.
    SELECT ranked.*
    FROM (
        SELECT
            m.*,
            ROW_NUMBER() OVER (
                PARTITION BY COALESCE(r.source_record_id, m.raw_artwork_id::text)
                ORDER BY m.crawl_timestamp DESC NULLS LAST, r.id DESC
            ) AS dedupe_rank
        FROM analytics.mart_artworks m
        LEFT JOIN raw.artworks r
            ON r.id = m.raw_artwork_id
    ) ranked
    WHERE ranked.dedupe_rank = 1
),
latest_review AS (
    SELECT DISTINCT ON (artwork_id)
        artwork_id,
        review_status,
        reviewed_at,
        reviewed_by,
        review_notes
    FROM app.review_queue
    ORDER BY artwork_id, reviewed_at DESC NULLS LAST, created_at DESC
),
latest_approval AS (
    SELECT DISTINCT ON (artwork_id)
        artwork_id,
        public_visibility,
        approved_at,
        approved_by,
        notes AS approval_notes
    FROM app.approved_artworks
    ORDER BY artwork_id, approved_at DESC
)
SELECT
    m.artwork_id,
    m.raw_artwork_id,
    m.artist_id,
    COALESCE(amo.canonical_artist_name, m.artist_name) AS artist_name,
    m.artist_name AS original_artist_name,
    COALESCE(amo.is_hidden, false) AS artist_is_hidden,
    amo.canonical_artist_name,
    amo.reason AS artist_moderation_reason,
    m.artwork_title,
    m.year_start,
    m.year_end,
    m.artwork_date_text,
    m.medium_text,
    m.medium_category,
    m.dimensions_text,
    m.height_cm,
    m.width_cm,
    m.depth_cm,
    m.price_text,
    m.price_numeric,
    m.currency_code,
    m.source_name,
    m.source_domain,
    m.source_url,
    m.image_url,
    m.thumbnail_url,
    m.description,
    m.quality_score,
    m.duplicate_group_key,
    m.is_duplicate_candidate,
    m.crawl_timestamp,
    m.created_at,
    lr.review_status,
    lr.reviewed_at,
    lr.reviewed_by,
    lr.review_notes,
    COALESCE(la.public_visibility, false) AS public_visibility,
    la.approved_at,
    la.approved_by,
    la.approval_notes
FROM latest_artwork m
LEFT JOIN app.artist_moderation_overrides amo
    ON amo.artist_name = m.artist_name
   AND amo.source_domain = m.source_domain
LEFT JOIN latest_review lr
    ON lr.artwork_id = m.artwork_id
LEFT JOIN latest_approval la
    ON la.artwork_id = m.artwork_id;

CREATE OR REPLACE VIEW app.event_records AS
WITH linked_artists AS (
    SELECT
        event_id,
        array_agg(DISTINCT artist_name ORDER BY artist_name) FILTER (WHERE artist_name IS NOT NULL) AS linked_artists
    FROM analytics.mart_artist_activity
    GROUP BY event_id
),
events_with_source_title AS (
    SELECT
        me.*,
        me.event_title AS original_event_title
    FROM analytics.mart_events me
)
SELECT
    me.event_id,
    me.source_name,
    me.source_domain,
    me.source_url,
    me.source_record_id,
    COALESCE(emo.event_type, me.event_type) AS event_type,
    me.event_type AS original_event_type,
    emo.event_type AS canonical_event_type,
    COALESCE(emo.canonical_event_title, me.original_event_title) AS event_title,
    me.original_event_title,
    emo.canonical_event_title,
    me.venue_name,
    me.venue_address,
    me.city,
    me.country,
    me.start_date,
    me.end_date,
    me.opening_datetime,
    me.description,
    me.image_url,
    re.raw_payload,
    COALESCE(la.linked_artists, ARRAY[]::TEXT[]) AS linked_artists,
    me.artist_count,
    COALESCE(emo.is_hidden, false) AS is_hidden,
    COALESCE(emo.is_approved, false) AS is_approved,
    (emo.id IS NOT NULL) AS moderation_override_exists,
    emo.moderation_reason,
    emo.moderator_notes,
    emo.updated_at,
    me.crawl_timestamp,
    me.created_at
FROM events_with_source_title me
LEFT JOIN raw.events re
    ON re.id = me.event_id
LEFT JOIN linked_artists la
    ON la.event_id = me.event_id
LEFT JOIN app.event_moderation_overrides emo
    ON emo.event_id = me.event_id;

CREATE OR REPLACE VIEW app.gallery_records AS
WITH scraped AS (
    SELECT
        mg.gallery_id,
        mg.gallery_name,
        mg.original_gallery_name,
        lower(regexp_replace(COALESCE(mg.gallery_name, ''), '\s+', ' ', 'g')) AS normalized_gallery_name,
        mg.gallery_address,
        mg.city,
        mg.country,
        mg.source_domain,
        mg.source_url,
        'scraped'::text AS gallery_record_type,
        mg.phone,
        mg.email,
        mg.website_url,
        mg.instagram_url,
        mg.facebook_url,
        mg.linked_events,
        mg.linked_artists,
        mg.linked_artworks,
        mg.contact_quality_score AS quality_score,
        mg.quality_flags,
        COALESCE(NULLIF(btrim(mg.gallery_address), ''), '') = '' AS missing_address,
        COALESCE(NULLIF(btrim(mg.city), ''), '') = '' AS missing_city,
        COALESCE(NULLIF(btrim(mg.country), ''), '') = '' AS missing_country,
        COALESCE(NULLIF(btrim(mg.website_url), ''), '') = '' AS missing_website,
        COALESCE(NULLIF(btrim(mg.email), ''), '') = '' AS missing_email,
        COALESCE(NULLIF(btrim(mg.phone), ''), '') = '' AS missing_phone,
        COALESCE(NULLIF(btrim(mg.instagram_url), ''), '') = '' AND COALESCE(NULLIF(btrim(mg.facebook_url), ''), '') = '' AS missing_social,
        jsonb_array_length(COALESCE(mg.linked_events, '[]'::jsonb)) = 0 AS missing_linked_events,
        mg.raw_payload,
        mg.crawl_timestamp
    FROM analytics.mart_galleries mg
),
inferred_events AS (
    SELECT
        me.*,
        lower(regexp_replace(COALESCE(NULLIF(btrim(me.source_domain), ''), 'unknown-source'), '\s+', ' ', 'g')) AS n_source_domain,
        btrim(me.venue_name) AS original_gallery_name,
        regexp_replace(
            btrim(
                CASE
                    WHEN lower(COALESCE(NULLIF(btrim(me.source_domain), ''), '')) = 'art.co.za' THEN
                        COALESCE(
                            NULLIF(
                                regexp_replace(
                                    btrim(me.venue_name),
                                    '^(.*)\s+at\s+(.*)\s+\|\s+Art\.co\.za Art Exhibition Listings$',
                                    '\2',
                                    'i'
                                ),
                                btrim(me.venue_name)
                            ),
                            regexp_replace(
                                regexp_replace(
                                    regexp_replace(
                                        regexp_replace(
                                            btrim(me.venue_name),
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
                    ELSE btrim(me.venue_name)
                END
            ),
            '\s+',
            ' ',
            'g'
        ) AS cleaned_gallery_name,
        lower(regexp_replace(COALESCE(NULLIF(btrim(
            regexp_replace(
                btrim(
                    CASE
                        WHEN lower(COALESCE(NULLIF(btrim(me.source_domain), ''), '')) = 'art.co.za' THEN
                            COALESCE(
                                NULLIF(
                                    regexp_replace(
                                        btrim(me.venue_name),
                                        '^(.*)\s+at\s+(.*)\s+\|\s+Art\.co\.za Art Exhibition Listings$',
                                        '\2',
                                        'i'
                                    ),
                                    btrim(me.venue_name)
                                ),
                                regexp_replace(
                                    regexp_replace(
                                        regexp_replace(
                                            regexp_replace(
                                                btrim(me.venue_name),
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
                        ELSE btrim(me.venue_name)
                    END
                ),
                '\s+',
                ' ',
                'g'
            )
        ), ''), ''), '\s+', ' ', 'g')) AS n_gallery_name,
        lower(regexp_replace(COALESCE(NULLIF(btrim(me.city), ''), 'unknown-city'), '\s+', ' ', 'g')) AS n_city,
        lower(regexp_replace(COALESCE(NULLIF(btrim(me.country), ''), 'unknown-country'), '\s+', ' ', 'g')) AS n_country
    FROM analytics.mart_events me
    WHERE COALESCE(NULLIF(btrim(me.venue_name), ''), '') <> ''
      AND NOT EXISTS (
          SELECT 1
          FROM analytics.mart_galleries mg
          WHERE mg.source_domain = me.source_domain
            AND lower(regexp_replace(COALESCE(mg.gallery_name, ''), '\s+', ' ', 'g')) = lower(regexp_replace(COALESCE(me.venue_name, ''), '\s+', ' ', 'g'))
            AND lower(regexp_replace(COALESCE(mg.city, ''), '\s+', ' ', 'g')) = lower(regexp_replace(COALESCE(me.city, ''), '\s+', ' ', 'g'))
            AND lower(regexp_replace(COALESCE(mg.country, ''), '\s+', ' ', 'g')) = lower(regexp_replace(COALESCE(me.country, ''), '\s+', ' ', 'g'))
      )
),
inferred AS (
    SELECT
        (
            substr(md5(me.n_gallery_name || '|' || me.n_city || '|' || me.n_country || '|' || me.n_source_domain), 1, 8)
            || '-' || substr(md5(me.n_gallery_name || '|' || me.n_city || '|' || me.n_country || '|' || me.n_source_domain), 9, 4)
            || '-' || substr(md5(me.n_gallery_name || '|' || me.n_city || '|' || me.n_country || '|' || me.n_source_domain), 13, 4)
            || '-' || substr(md5(me.n_gallery_name || '|' || me.n_city || '|' || me.n_country || '|' || me.n_source_domain), 17, 4)
            || '-' || substr(md5(me.n_gallery_name || '|' || me.n_city || '|' || me.n_country || '|' || me.n_source_domain), 21, 12)
        )::uuid AS gallery_id,
        MIN(NULLIF(btrim(me.cleaned_gallery_name), '')) AS gallery_name,
        MIN(me.original_gallery_name) AS original_gallery_name,
        me.n_gallery_name AS normalized_gallery_name,
        MIN(NULLIF(btrim(me.venue_address), '')) AS gallery_address,
        MIN(NULLIF(btrim(me.city), '')) AS city,
        MIN(NULLIF(btrim(me.country), '')) AS country,
        MIN(NULLIF(btrim(me.source_domain), '')) AS source_domain,
        MIN(NULLIF(btrim(me.source_url), '')) AS source_url,
        'inferred_from_event'::text AS gallery_record_type,
        NULL::text AS phone,
        NULL::text AS email,
        NULL::text AS website_url,
        NULL::text AS instagram_url,
        NULL::text AS facebook_url,
        jsonb_agg(DISTINCT jsonb_build_object('event_id', me.event_id, 'event_title', me.event_title, 'source_url', me.source_url)) AS linked_events,
        '[]'::jsonb AS linked_artists,
        '[]'::jsonb AS linked_artworks,
        0::int AS quality_score,
        array_remove(array[
            case
                when bool_or(
                    me.cleaned_gallery_name like '%|%'
                    or me.cleaned_gallery_name ilike '%Art.co.za%'
                ) then 'noisy_inferred_name'
            end
        ], null)::text[] AS quality_flags,
        COALESCE(NULLIF(btrim(MIN(me.venue_address)), ''), '') = '' AS missing_address,
        COALESCE(NULLIF(btrim(MIN(me.city)), ''), '') = '' AS missing_city,
        COALESCE(NULLIF(btrim(MIN(me.country)), ''), '') = '' AS missing_country,
        true AS missing_website,
        true AS missing_email,
        true AS missing_phone,
        true AS missing_social,
        false AS missing_linked_events,
        '[]'::jsonb AS raw_payload,
        MAX(me.crawl_timestamp) AS crawl_timestamp
    FROM inferred_events me
    GROUP BY me.n_gallery_name, me.n_city, me.n_country, me.n_source_domain
    HAVING NOT (
        MIN(NULLIF(btrim(me.source_domain), '')) = 'art.co.za'
        AND (
            bool_or(
                COALESCE(me.cleaned_gallery_name, '') ~* '(list your gallery|list your art exhibition|submit your gallery|advertise|login|register|sign up)'
                OR COALESCE(me.original_gallery_name, '') ~* '(list your gallery|list your art exhibition|submit your gallery|advertise|login|register|sign up)'
            )
            OR bool_or(
                (
                    COALESCE(me.cleaned_gallery_name, '') ilike '%Art in South Africa%'
                    OR COALESCE(me.original_gallery_name, '') ilike '%Art in South Africa%'
                )
                AND (
                    COALESCE(me.cleaned_gallery_name, '') ilike '%Art.co.za%'
                    OR COALESCE(me.original_gallery_name, '') ilike '%Art.co.za%'
                )
            )
            OR (
                char_length(trim(COALESCE(MIN(NULLIF(btrim(me.cleaned_gallery_name), '')), ''))) <= 3
                OR lower(COALESCE(MIN(NULLIF(btrim(me.cleaned_gallery_name), '')), '')) IN (
                    'home',
                    'gallery',
                    'galleries',
                    'events',
                    'art in south africa'
                )
            )
        )
    )
),
unioned AS (
    SELECT * FROM scraped
    UNION ALL
    SELECT * FROM inferred
)
SELECT
    u.gallery_id,
    u.gallery_name,
    u.original_gallery_name,
    u.normalized_gallery_name,
    u.gallery_address,
    u.city,
    u.country,
    u.source_domain,
    u.source_url,
    u.gallery_record_type,
    u.phone,
    u.email,
    u.website_url,
    u.instagram_url,
    u.facebook_url,
    u.linked_events,
    u.linked_artists,
    u.linked_artworks,
    COALESCE(gmo.is_hidden, false) AS is_hidden,
    COALESCE(gmo.is_approved, false) AS is_approved,
    gmo.canonical_gallery_name,
    gmo.canonical_gallery_type,
    gmo.canonical_address,
    gmo.canonical_city,
    gmo.canonical_country,
    gmo.canonical_phone,
    gmo.canonical_email,
    gmo.canonical_website_url,
    gmo.canonical_instagram_url,
    gmo.canonical_facebook_url,
    gmo.moderation_reason,
    gmo.moderator_notes,
    gmo.updated_at,
    u.quality_score,
    u.quality_flags,
    u.missing_address,
    u.missing_city,
    u.missing_country,
    u.missing_website,
    u.missing_email,
    u.missing_phone,
    u.missing_social,
    u.missing_linked_events,
    u.raw_payload,
    u.crawl_timestamp
FROM unioned u
LEFT JOIN app.gallery_moderation_overrides gmo
    ON gmo.gallery_id = u.gallery_id;

CREATE OR REPLACE VIEW app.artist_event_links AS
SELECT
    artist_activity_id,
    event_id,
    artist_name,
    artist_name_normalized,
    artist_profile_url,
    match_type,
    event_type,
    event_title,
    city,
    country,
    start_date,
    end_date,
    source_domain,
    source_url,
    crawl_timestamp
FROM analytics.mart_artist_activity;

CREATE OR REPLACE VIEW app.artist_profiles AS
WITH artist_rollup AS (
    SELECT
        ar.artist_name,
        ar.source_domain,
        COUNT(*) AS artwork_count,
        MAX(ar.crawl_timestamp) AS last_seen
    FROM app.artwork_records ar
    WHERE ar.artist_name IS NOT NULL
    GROUP BY ar.artist_name, ar.source_domain
),
latest_profile_row AS (
    SELECT DISTINCT ON (ar.artist_name, ar.source_domain)
        ar.artist_name,
        ar.source_domain,
        ar.source_url AS profile_url,
        ar.description AS original_artist_bio
    FROM app.artwork_records ar
    WHERE ar.artist_name IS NOT NULL
    ORDER BY
        ar.artist_name,
        ar.source_domain,
        (ar.source_url IS NOT NULL AND ar.description IS NOT NULL) DESC,
        ar.crawl_timestamp DESC NULLS LAST
),
latest_bio_edits AS (
    SELECT DISTINCT ON (artist_name, source_domain)
        artist_name,
        source_domain,
        edited_bio,
        edited_by,
        edit_notes,
        created_at AS edited_at
    FROM app.artist_profile_edits
    ORDER BY artist_name, source_domain, created_at DESC
),
bio_inputs AS (
    SELECT
        r.artist_name,
        r.source_domain,
        p.profile_url,
        p.original_artist_bio,
        lbe.edited_bio,
        lbe.edited_by,
        lbe.edit_notes,
        lbe.edited_at,
        r.artwork_count,
        r.last_seen,
        COALESCE(amo.is_hidden, false) AS is_hidden,
        amo.canonical_artist_name,
        amo.reason AS moderation_reason,
        amo.updated_by AS moderation_updated_by,
        amo.updated_at AS moderation_updated_at
    FROM artist_rollup r
    LEFT JOIN latest_profile_row p
        ON p.artist_name = r.artist_name
       AND p.source_domain = r.source_domain
    LEFT JOIN latest_bio_edits lbe
        ON lbe.artist_name = r.artist_name
       AND lbe.source_domain = r.source_domain
    LEFT JOIN app.artist_moderation_overrides amo
        ON amo.artist_name = r.artist_name
       AND amo.source_domain = r.source_domain
),
bio_cleaning AS (
    SELECT
        bi.*,
        COALESCE(bi.original_artist_bio, '') AS bio_raw,
        COALESCE(bi.original_artist_bio, '') ~* '[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}' AS contains_email,
        COALESCE(bi.original_artist_bio, '') ~* '(?:\+?\d[\d\-\s().]{7,}\d)' AS contains_phone,
        COALESCE(bi.original_artist_bio, '') ~* '(about the artist|artworks\s*[▼v]|painting prints|earlier works)' AS navigation_noise,
        regexp_replace(
            regexp_replace(COALESCE(bi.original_artist_bio, ''), '[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}', ' ', 'gi'),
            '(?:\+?\d[\d\-\s().]{7,}\d)',
            ' ',
            'g'
        ) AS bio_contact_removed
    FROM bio_inputs bi
),
bio_dedup AS (
    SELECT
        bc.*,
        (
            SELECT COALESCE(string_agg(paragraph, E'\n\n' ORDER BY paragraph_index), '')
            FROM (
                SELECT DISTINCT ON (lower(btrim(paragraph)))
                    paragraph_index,
                    btrim(paragraph) AS paragraph
                FROM regexp_split_to_table(
                    regexp_replace(
                        regexp_replace(
                            regexp_replace(
                                bc.bio_contact_removed,
                                '(?im)^\s*(about the artist|artworks\s*[▼v]|painting prints|earlier works)\s*$',
                                ' ',
                                'g'
                            ),
                            '(?im)^\s*(?:19|20)\d{2}\s*[-–:|].*$',
                            ' ',
                            'g'
                        ),
                        '[\r\t]+',
                        ' ',
                        'g'
                    ),
                    E'\n{2,}'
                ) WITH ORDINALITY AS split_paragraph(paragraph, paragraph_index)
                WHERE btrim(paragraph) <> ''
            ) normalized_paragraphs
        ) AS bio_paragraphs_cleaned
    FROM bio_cleaning bc
),
bio_sentence_dedup AS (
    SELECT
        bd.*,
        (
            SELECT COALESCE(string_agg(sentence, '. ' ORDER BY sentence_index), '')
            FROM (
                SELECT DISTINCT ON (lower(btrim(sentence)))
                    sentence_index,
                    btrim(sentence) AS sentence
                FROM regexp_split_to_table(
                    regexp_replace(bd.bio_paragraphs_cleaned, E'\s+', ' ', 'g'),
                    '[.!?]+'
                ) WITH ORDINALITY AS split_sentence(sentence, sentence_index)
                WHERE btrim(sentence) <> ''
            ) normalized_sentences
        ) AS bio_sentence_cleaned
    FROM bio_dedup bd
),
bio_scored AS (
    SELECT
        bsd.*,
        NULLIF(btrim(regexp_replace(bsd.bio_sentence_cleaned, '\s+', ' ', 'g')), '') AS cleaned_artist_bio,
        (bsd.bio_contact_removed <> COALESCE(bsd.original_artist_bio, ''))
            OR (COALESCE(bsd.bio_paragraphs_cleaned, '') <> COALESCE(bsd.bio_contact_removed, ''))
            OR (COALESCE(bsd.bio_sentence_cleaned, '') <> COALESCE(bsd.bio_paragraphs_cleaned, '')) AS duplicate_content,
        length(
            COALESCE(NULLIF(btrim(regexp_replace(bsd.bio_sentence_cleaned, '\s+', ' ', 'g')), ''), '')
        ) < 80 AS too_short,
        CASE
            WHEN length(regexp_replace(COALESCE(bsd.original_artist_bio, ''), '[^A-Za-z]', '', 'g')) < 20 THEN false
            ELSE (
                length(regexp_replace(COALESCE(bsd.original_artist_bio, ''), '[^A-Z]', '', 'g'))::numeric
                / NULLIF(length(regexp_replace(COALESCE(bsd.original_artist_bio, ''), '[^A-Za-z]', '', 'g')), 0)
            ) > 0.60
        END AS noisy_uppercase
    FROM bio_sentence_dedup bsd
)
SELECT
    bs.artist_name,
    bs.source_domain,
    bs.profile_url,
    COALESCE(bs.edited_bio, bs.cleaned_artist_bio, bs.original_artist_bio) AS artist_bio,
    bs.original_artist_bio,
    bs.cleaned_artist_bio,
    GREATEST(
        0,
        LEAST(
            100,
            100
            - CASE WHEN bs.contains_email THEN 30 ELSE 0 END
            - CASE WHEN bs.contains_phone THEN 20 ELSE 0 END
            - CASE WHEN bs.navigation_noise THEN 20 ELSE 0 END
            - CASE WHEN bs.duplicate_content THEN 10 ELSE 0 END
            - CASE WHEN bs.too_short THEN 10 ELSE 0 END
            - CASE WHEN bs.noisy_uppercase THEN 10 ELSE 0 END
        )
    )::INT AS bio_quality_score,
    array_remove(
        ARRAY[
            CASE WHEN bs.contains_email THEN 'contains_email' END,
            CASE WHEN bs.contains_phone THEN 'contains_phone' END,
            CASE WHEN bs.navigation_noise THEN 'navigation_noise' END,
            CASE WHEN bs.too_short THEN 'too_short' END,
            CASE WHEN bs.duplicate_content THEN 'duplicate_content' END
        ],
        NULL
    ) AS bio_quality_flags,
    bs.edited_bio,
    bs.edited_by,
    bs.edited_at,
    bs.artwork_count,
    bs.last_seen,
    bs.is_hidden,
    bs.canonical_artist_name,
    bs.moderation_reason,
    bs.moderation_updated_by,
    bs.moderation_updated_at,
    bs.edited_bio AS edited_artist_bio,
    bs.edited_by AS bio_edited_by,
    bs.edit_notes AS bio_edit_notes,
    bs.edited_at AS bio_last_edited_at
FROM bio_scored bs;
