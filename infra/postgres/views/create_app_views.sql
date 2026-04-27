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
)
SELECT
    me.event_id,
    me.source_name,
    me.source_domain,
    me.source_url,
    me.source_record_id,
    COALESCE(emo.event_type, me.event_type) AS event_type,
    me.event_type AS original_event_type,
    COALESCE(emo.canonical_event_title, me.event_title) AS event_title,
    me.event_title AS original_event_title,
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
FROM analytics.mart_events me
LEFT JOIN raw.events re
    ON re.id = me.event_id
LEFT JOIN linked_artists la
    ON la.event_id = me.event_id
LEFT JOIN app.event_moderation_overrides emo
    ON emo.event_id = me.event_id;

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
