\connect artio

-- Ensure app.artist_profiles keeps the runtime shape and latest edit join in real Docker runs.
-- This file is mounted into /docker-entrypoint-initdb.d and can be re-applied manually.
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
    lbe.edited_bio AS edited_artist_bio,
    lbe.edited_by AS bio_edited_by,
    lbe.edit_notes AS bio_edit_notes,
    lbe.edited_at AS bio_last_edited_at,
    r.artwork_count,
    r.last_seen
FROM artist_rollup r
LEFT JOIN latest_profile_row p
    ON p.artist_name = r.artist_name
   AND p.source_domain = r.source_domain
LEFT JOIN latest_bio_edits lbe
    ON lbe.artist_name = r.artist_name
   AND lbe.source_domain = r.source_domain;
