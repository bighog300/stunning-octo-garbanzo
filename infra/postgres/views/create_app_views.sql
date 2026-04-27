\connect artio

-- Run this script only after dbt has built analytics.mart_artworks (for example after `dbt run`).
-- This view intentionally lives outside init scripts because mart_artworks does not exist at initial DB bootstrap time.
CREATE OR REPLACE VIEW app.artwork_records AS
WITH latest_review AS (
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
FROM analytics.mart_artworks m
LEFT JOIN app.artist_moderation_overrides amo
    ON amo.artist_name = m.artist_name
   AND amo.source_domain = m.source_domain
LEFT JOIN latest_review lr
    ON lr.artwork_id = m.artwork_id
LEFT JOIN latest_approval la
    ON la.artwork_id = m.artwork_id
WHERE NOT COALESCE(amo.is_hidden, false)
   OR amo.canonical_artist_name IS NOT NULL;

CREATE OR REPLACE VIEW app.event_records AS
SELECT
    event_id,
    source_name,
    source_domain,
    source_url,
    source_record_id,
    event_type,
    event_title,
    venue_name,
    venue_address,
    city,
    country,
    start_date,
    end_date,
    opening_datetime,
    description,
    image_url,
    artist_count,
    crawl_timestamp,
    created_at
FROM analytics.mart_events;

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
)
SELECT
    r.artist_name,
    r.source_domain,
    p.profile_url,
    COALESCE(lbe.edited_bio, p.original_artist_bio) AS artist_bio,
    p.original_artist_bio,
    lbe.edited_bio,
    lbe.edited_by,
    lbe.edited_at,
    r.artwork_count,
    r.last_seen,
    COALESCE(amo.is_hidden, false) AS is_hidden,
    amo.canonical_artist_name,
    amo.reason AS moderation_reason,
    amo.updated_by AS moderation_updated_by,
    amo.updated_at AS moderation_updated_at,
    lbe.edited_bio AS edited_artist_bio,
    lbe.edited_by AS bio_edited_by,
    lbe.edit_notes AS bio_edit_notes,
    lbe.edited_at AS bio_last_edited_at
FROM artist_rollup r
LEFT JOIN latest_profile_row p
    ON p.artist_name = r.artist_name
   AND p.source_domain = r.source_domain
LEFT JOIN latest_bio_edits lbe
    ON lbe.artist_name = r.artist_name
   AND lbe.source_domain = r.source_domain
LEFT JOIN app.artist_moderation_overrides amo
    ON amo.artist_name = r.artist_name
   AND amo.source_domain = r.source_domain;
