\connect artio

-- Ensure app.artist_profiles keeps the runtime shape and latest edit join in real Docker runs.
-- This file is mounted into /docker-entrypoint-initdb.d and can be re-applied manually.
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
        created_at AS edited_at
    FROM app.artist_profile_edits
    ORDER BY artist_name, source_domain, created_at DESC
)
SELECT
    bp.artist_name,
    bp.source_domain,
    bp.profile_url,
    COALESCE(lbe.edited_bio, bp.original_artist_bio) AS artist_bio,
    bp.original_artist_bio,
    lbe.edited_bio,
    lbe.edited_by,
    lbe.edited_at,
    lbe.edited_bio AS edited_artist_bio,
    lbe.edited_by AS bio_edited_by,
    lbe.edit_notes AS bio_edit_notes,
    lbe.edited_at AS bio_last_edited_at,
    bp.artwork_count,
    bp.last_seen
FROM base_profiles bp
LEFT JOIN latest_bio_edits lbe
    ON lbe.artist_name = bp.artist_name
   AND lbe.source_domain = bp.source_domain;
