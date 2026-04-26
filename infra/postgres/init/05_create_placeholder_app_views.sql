\connect artio

-- Create a placeholder app view during DB bootstrap so downstream tools can query it
-- before analytics.mart_artworks is materialized by dbt.
CREATE OR REPLACE VIEW app.artwork_records AS
SELECT
    NULL::UUID AS artwork_id,
    NULL::TEXT AS artist_name,
    NULL::TEXT AS artwork_title,
    NULL::INTEGER AS year_start,
    NULL::INTEGER AS year_end,
    NULL::TEXT AS medium_text,
    NULL::TEXT AS medium_category,
    NULL::TEXT AS dimensions_text,
    NULL::TEXT AS price_text,
    NULL::NUMERIC AS price_numeric,
    NULL::TEXT AS currency_code,
    NULL::TEXT AS source_name,
    NULL::TEXT AS source_domain,
    NULL::TEXT AS source_url,
    NULL::TEXT AS image_url,
    NULL::TEXT AS thumbnail_url,
    NULL::TEXT AS description,
    NULL::INTEGER AS quality_score,
    NULL::TEXT AS review_status,
    NULL::BOOLEAN AS public_visibility,
    NULL::TIMESTAMPTZ AS crawl_timestamp
WHERE false;
