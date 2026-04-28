\connect artio

CREATE SCHEMA IF NOT EXISTS superset;

CREATE OR REPLACE VIEW superset.gallery_quality_summary AS
SELECT
    COALESCE(NULLIF(btrim(gr.source_domain), ''), 'unknown') AS source_domain,
    COALESCE(NULLIF(btrim(gr.gallery_record_type), ''), 'unknown') AS gallery_record_type,
    COUNT(*)::BIGINT AS total_galleries,
    COUNT(*) FILTER (WHERE NOT COALESCE(gr.is_approved, false) AND NOT COALESCE(gr.is_hidden, false))::BIGINT AS needs_review,
    COUNT(*) FILTER (WHERE COALESCE(gr.is_approved, false))::BIGINT AS approved,
    COUNT(*) FILTER (WHERE COALESCE(gr.is_hidden, false))::BIGINT AS hidden,
    COUNT(*) FILTER (WHERE COALESCE(gr.missing_email, false))::BIGINT AS missing_email,
    COUNT(*) FILTER (WHERE COALESCE(gr.missing_phone, false))::BIGINT AS missing_phone,
    COUNT(*) FILTER (WHERE COALESCE(gr.missing_website, false))::BIGINT AS missing_website,
    COUNT(*) FILTER (WHERE COALESCE(gr.missing_social, false))::BIGINT AS missing_social,
    ROUND(AVG(gr.quality_score)::NUMERIC, 2) AS avg_quality_score,
    MAX(gr.crawl_timestamp) AS latest_crawl
FROM app.gallery_records gr
GROUP BY
    COALESCE(NULLIF(btrim(gr.source_domain), ''), 'unknown'),
    COALESCE(NULLIF(btrim(gr.gallery_record_type), ''), 'unknown');

CREATE OR REPLACE VIEW superset.event_quality_summary AS
SELECT
    COALESCE(NULLIF(btrim(er.source_domain), ''), 'unknown') AS source_domain,
    COUNT(*)::BIGINT AS total_events,
    COUNT(*) FILTER (WHERE NOT COALESCE(er.is_approved, false) AND NOT COALESCE(er.is_hidden, false))::BIGINT AS needs_review,
    COUNT(*) FILTER (WHERE COALESCE(er.is_approved, false))::BIGINT AS approved,
    COUNT(*) FILTER (WHERE COALESCE(er.is_hidden, false))::BIGINT AS hidden,
    COUNT(*) FILTER (WHERE er.start_date IS NULL AND er.end_date IS NULL AND er.opening_datetime IS NULL)::BIGINT AS missing_date,
    COUNT(*) FILTER (WHERE COALESCE(NULLIF(btrim(er.venue_name), ''), '') = '')::BIGINT AS missing_venue,
    ROUND(AVG(COALESCE((er.raw_payload ->> 'quality_score')::NUMERIC, 0))::NUMERIC, 2) AS avg_quality_score,
    MAX(er.crawl_timestamp) AS latest_crawl
FROM app.event_records er
GROUP BY COALESCE(NULLIF(btrim(er.source_domain), ''), 'unknown');

CREATE OR REPLACE VIEW superset.moderation_summary AS
WITH artists AS (
    SELECT
        'artists'::TEXT AS entity_type,
        COUNT(*)::BIGINT AS total,
        COUNT(*) FILTER (
            WHERE NOT COALESCE(ap.is_hidden, false)
              AND COALESCE(NULLIF(btrim(ap.canonical_artist_name), ''), '') <> ''
        )::BIGINT AS approved,
        COUNT(*) FILTER (WHERE COALESCE(ap.is_hidden, false))::BIGINT AS hidden,
        COUNT(*) FILTER (
            WHERE NOT COALESCE(ap.is_hidden, false)
              AND COALESCE(NULLIF(btrim(ap.canonical_artist_name), ''), '') = ''
        )::BIGINT AS needs_review
    FROM app.artist_profiles ap
),
artworks AS (
    SELECT
        'artworks'::TEXT AS entity_type,
        COUNT(*)::BIGINT AS total,
        COUNT(*) FILTER (WHERE COALESCE(ar.public_visibility, false))::BIGINT AS approved,
        COUNT(*) FILTER (WHERE COALESCE(ar.artist_is_hidden, false))::BIGINT AS hidden,
        COUNT(*) FILTER (
            WHERE COALESCE(ar.review_status, 'pending') IN ('pending', 'unreviewed')
              AND NOT COALESCE(ar.public_visibility, false)
        )::BIGINT AS needs_review
    FROM app.artwork_records ar
),
events AS (
    SELECT
        'events'::TEXT AS entity_type,
        COUNT(*)::BIGINT AS total,
        COUNT(*) FILTER (WHERE COALESCE(er.is_approved, false))::BIGINT AS approved,
        COUNT(*) FILTER (WHERE COALESCE(er.is_hidden, false))::BIGINT AS hidden,
        COUNT(*) FILTER (WHERE NOT COALESCE(er.is_approved, false) AND NOT COALESCE(er.is_hidden, false))::BIGINT AS needs_review
    FROM app.event_records er
),
galleries AS (
    SELECT
        'galleries'::TEXT AS entity_type,
        COUNT(*)::BIGINT AS total,
        COUNT(*) FILTER (WHERE COALESCE(gr.is_approved, false))::BIGINT AS approved,
        COUNT(*) FILTER (WHERE COALESCE(gr.is_hidden, false))::BIGINT AS hidden,
        COUNT(*) FILTER (WHERE NOT COALESCE(gr.is_approved, false) AND NOT COALESCE(gr.is_hidden, false))::BIGINT AS needs_review
    FROM app.gallery_records gr
)
SELECT * FROM artists
UNION ALL
SELECT * FROM artworks
UNION ALL
SELECT * FROM events
UNION ALL
SELECT * FROM galleries;

CREATE OR REPLACE VIEW superset.crawl_health_summary AS
SELECT
    COALESCE(NULLIF(btrim(source_domain), ''), 'unknown') AS source_domain,
    entity_type,
    SUM(row_count)::BIGINT AS raw_count,
    MAX(latest_crawl) AS latest_crawl
FROM (
    SELECT
        ra.source_domain,
        'artworks'::TEXT AS entity_type,
        COUNT(*)::BIGINT AS row_count,
        MAX(ra.crawl_timestamp) AS latest_crawl
    FROM raw.artworks ra
    GROUP BY ra.source_domain

    UNION ALL

    SELECT
        rg.source_domain,
        'galleries'::TEXT AS entity_type,
        COUNT(*)::BIGINT AS row_count,
        MAX(rg.crawl_timestamp) AS latest_crawl
    FROM raw.galleries rg
    GROUP BY rg.source_domain

    UNION ALL

    SELECT
        re.source_domain,
        'events'::TEXT AS entity_type,
        COUNT(*)::BIGINT AS row_count,
        MAX(re.crawl_timestamp) AS latest_crawl
    FROM raw.events re
    GROUP BY re.source_domain

    UNION ALL

    SELECT
        me.source_domain,
        'events_mart'::TEXT AS entity_type,
        COUNT(*)::BIGINT AS row_count,
        MAX(me.crawl_timestamp) AS latest_crawl
    FROM analytics.mart_events me
    GROUP BY me.source_domain
) h
GROUP BY
    COALESCE(NULLIF(btrim(source_domain), ''), 'unknown'),
    entity_type;
