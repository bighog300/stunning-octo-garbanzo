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
    m.*,
    lr.review_status,
    lr.reviewed_at,
    lr.reviewed_by,
    lr.review_notes,
    COALESCE(la.public_visibility, false) AS public_visibility,
    la.approved_at,
    la.approved_by,
    la.approval_notes
FROM analytics.mart_artworks m
LEFT JOIN latest_review lr
    ON lr.artwork_id = m.artwork_id
LEFT JOIN latest_approval la
    ON la.artwork_id = m.artwork_id;

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
WITH base_profiles AS (
    SELECT DISTINCT ON (artist_name, source_domain)
        artist_name,
        source_domain,
        source_url AS profile_url,
        description AS original_artist_bio,
        COUNT(*) OVER (PARTITION BY artist_name, source_domain) AS artwork_count,
        MAX(crawl_timestamp) OVER (PARTITION BY artist_name, source_domain) AS last_seen
    FROM app.artwork_records
    WHERE artist_name IS NOT NULL
      AND description IS NOT NULL
    ORDER BY artist_name, source_domain, crawl_timestamp DESC NULLS LAST
),
latest_bio_edits AS (
    SELECT DISTINCT ON (artist_name, source_domain)
        artist_name,
        source_domain,
        edited_bio,
        edited_by,
        edit_notes,
        created_at
    FROM app.artist_profile_edits
    ORDER BY artist_name, source_domain, created_at DESC
)
SELECT
    bp.artist_name,
    bp.source_domain,
    bp.profile_url,
    bp.original_artist_bio,
    lbe.edited_bio AS edited_artist_bio,
    COALESCE(lbe.edited_bio, bp.original_artist_bio) AS artist_bio,
    lbe.edited_by AS bio_edited_by,
    lbe.edit_notes AS bio_edit_notes,
    lbe.created_at AS bio_last_edited_at,
    bp.artwork_count,
    bp.last_seen
FROM base_profiles bp
LEFT JOIN latest_bio_edits lbe
    ON lbe.artist_name = bp.artist_name
   AND lbe.source_domain = bp.source_domain;
