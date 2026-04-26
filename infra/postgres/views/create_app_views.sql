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
