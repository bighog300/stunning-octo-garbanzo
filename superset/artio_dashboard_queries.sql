-- Artio Artwork Records Overview dashboard query pack
-- Dataset: app.artwork_records

-- 1) Total artworks KPI
SELECT COUNT(*) AS total_artworks
FROM app.artwork_records;

-- 2) Total artists KPI
SELECT COUNT(DISTINCT artist_name) AS total_artists
FROM app.artwork_records;

-- 3) Sources KPI
SELECT COUNT(DISTINCT source_domain) AS total_sources
FROM app.artwork_records;

-- 4) Avg quality score KPI
SELECT AVG(quality_score) AS avg_quality_score
FROM app.artwork_records;

-- 5) Artworks by source bar chart
SELECT
    source_domain,
    COUNT(*) AS artwork_count
FROM app.artwork_records
GROUP BY source_domain
ORDER BY artwork_count DESC;

-- 6) Records by review status pie chart
SELECT
    COALESCE(review_status, 'unreviewed') AS review_status,
    COUNT(*) AS record_count
FROM app.artwork_records
GROUP BY COALESCE(review_status, 'unreviewed')
ORDER BY record_count DESC;

-- 7) Top artists by artwork count bar chart
SELECT
    artist_name,
    COUNT(*) AS artwork_count
FROM app.artwork_records
WHERE artist_name IS NOT NULL AND artist_name <> ''
GROUP BY artist_name
ORDER BY artwork_count DESC
LIMIT 15;

-- 8) Missing fields by source table
SELECT
    source_domain,
    COUNT(*) AS records,
    SUM(CASE WHEN artist_name IS NULL OR artist_name = '' THEN 1 ELSE 0 END) AS missing_artist,
    SUM(CASE WHEN artwork_title IS NULL OR artwork_title = '' THEN 1 ELSE 0 END) AS missing_title,
    SUM(CASE WHEN image_url IS NULL OR image_url = '' THEN 1 ELSE 0 END) AS missing_image
FROM app.artwork_records
GROUP BY source_domain
ORDER BY records DESC;

-- 9) Quality score distribution histogram (for SQL chart fallback)
SELECT
    FLOOR(quality_score / 10.0) * 10 AS quality_bucket,
    COUNT(*) AS records
FROM app.artwork_records
WHERE quality_score IS NOT NULL
GROUP BY FLOOR(quality_score / 10.0) * 10
ORDER BY quality_bucket;

-- 10) Artwork review table
SELECT
    artwork_id,
    artist_name,
    artwork_title,
    source_domain,
    quality_score,
    review_status,
    reviewed_at,
    reviewed_by,
    review_notes
FROM app.artwork_records
ORDER BY reviewed_at DESC NULLS LAST, created_at DESC
LIMIT 100;

-- ============================================================================
-- Events / Exhibitions / Training / News fallback query pack
-- Dataset: app.event_records and app.artist_event_links
-- ============================================================================

-- E1) Events by type
SELECT
    COALESCE(event_type, 'unknown') AS event_type,
    COUNT(*) AS event_count
FROM app.event_records
GROUP BY COALESCE(event_type, 'unknown')
ORDER BY event_count DESC;

-- E2) Upcoming exhibitions (today onward)
SELECT
    event_id,
    event_title,
    venue_name,
    city,
    start_date,
    end_date,
    source_url
FROM app.event_records
WHERE event_type = 'exhibition'
  AND COALESCE(end_date, start_date) >= CURRENT_DATE
ORDER BY COALESCE(start_date, end_date) ASC NULLS LAST
LIMIT 100;

-- E3) Events by city
SELECT
    COALESCE(city, 'Unknown') AS city,
    COUNT(*) AS event_count
FROM app.event_records
GROUP BY COALESCE(city, 'Unknown')
ORDER BY event_count DESC;

-- E4) Most active artists
SELECT
    artist_name,
    COUNT(*) AS activity_count
FROM app.artist_event_links
WHERE artist_name IS NOT NULL AND artist_name <> ''
GROUP BY artist_name
ORDER BY activity_count DESC
LIMIT 25;

-- E5) Artist activity table
SELECT
    artist_name,
    event_type,
    event_title,
    city,
    start_date,
    end_date,
    source_domain,
    source_url
FROM app.artist_event_links
ORDER BY start_date DESC NULLS LAST
LIMIT 200;
