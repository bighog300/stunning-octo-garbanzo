\connect artio

-- Create a placeholder app view during DB bootstrap so downstream tools can query it
-- before analytics.mart_artworks is materialized by dbt.
CREATE OR REPLACE VIEW app.artwork_records AS
SELECT
    NULL::UUID AS artwork_id,
    NULL::TEXT AS raw_artwork_id,
    NULL::UUID AS artist_id,
    NULL::TEXT AS artist_name,
    NULL::TEXT AS original_artist_name,
    NULL::BOOLEAN AS artist_is_hidden,
    NULL::TEXT AS canonical_artist_name,
    NULL::TEXT AS artist_moderation_reason,
    NULL::TEXT AS artwork_title,
    NULL::INTEGER AS year_start,
    NULL::INTEGER AS year_end,
    NULL::TEXT AS artwork_date_text,
    NULL::TEXT AS medium_text,
    NULL::TEXT AS medium_category,
    NULL::TEXT AS dimensions_text,
    NULL::NUMERIC AS height_cm,
    NULL::NUMERIC AS width_cm,
    NULL::NUMERIC AS depth_cm,
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
    NULL::TEXT AS duplicate_group_key,
    NULL::BOOLEAN AS is_duplicate_candidate,
    NULL::TEXT AS review_status,
    NULL::TIMESTAMPTZ AS reviewed_at,
    NULL::TEXT AS reviewed_by,
    NULL::TEXT AS review_notes,
    NULL::BOOLEAN AS public_visibility,
    NULL::TIMESTAMPTZ AS approved_at,
    NULL::TEXT AS approved_by,
    NULL::TEXT AS approval_notes,
    NULL::TIMESTAMPTZ AS crawl_timestamp,
    NULL::TIMESTAMPTZ AS created_at
WHERE false;

CREATE OR REPLACE VIEW app.event_records AS
SELECT
    NULL::UUID AS event_id,
    NULL::TEXT AS source_name,
    NULL::TEXT AS source_domain,
    NULL::TEXT AS source_url,
    NULL::TEXT AS source_record_id,
    NULL::TEXT AS event_type,
    NULL::TEXT AS event_title,
    NULL::TEXT AS venue_name,
    NULL::TEXT AS venue_address,
    NULL::TEXT AS city,
    NULL::TEXT AS country,
    NULL::DATE AS start_date,
    NULL::DATE AS end_date,
    NULL::TIMESTAMPTZ AS opening_datetime,
    NULL::TEXT AS description,
    NULL::TEXT AS image_url,
    NULL::INTEGER AS artist_count,
    NULL::TIMESTAMPTZ AS crawl_timestamp,
    NULL::TIMESTAMPTZ AS created_at
WHERE false;

CREATE OR REPLACE VIEW app.artist_event_links AS
SELECT
    NULL::UUID AS artist_activity_id,
    NULL::UUID AS event_id,
    NULL::TEXT AS artist_name,
    NULL::TEXT AS artist_name_normalized,
    NULL::TEXT AS artist_profile_url,
    NULL::TEXT AS match_type,
    NULL::TEXT AS event_type,
    NULL::TEXT AS event_title,
    NULL::TEXT AS city,
    NULL::TEXT AS country,
    NULL::DATE AS start_date,
    NULL::DATE AS end_date,
    NULL::TEXT AS source_domain,
    NULL::TEXT AS source_url,
    NULL::TIMESTAMPTZ AS crawl_timestamp
WHERE false;

CREATE OR REPLACE VIEW app.artist_profiles AS
SELECT
    NULL::TEXT AS artist_name,
    NULL::TEXT AS source_domain,
    NULL::TEXT AS profile_url,
    NULL::TEXT AS artist_bio,
    NULL::TEXT AS original_artist_bio,
    NULL::TEXT AS edited_bio,
    NULL::TEXT AS edited_by,
    NULL::TIMESTAMPTZ AS edited_at,
    NULL::TEXT AS edited_artist_bio,
    NULL::TEXT AS bio_edited_by,
    NULL::TEXT AS bio_edit_notes,
    NULL::TIMESTAMPTZ AS bio_last_edited_at,
    NULL::BIGINT AS artwork_count,
    NULL::TIMESTAMPTZ AS last_seen
WHERE false;
