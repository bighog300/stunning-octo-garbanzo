\connect artio

-- Fails (returns rows) when app.artwork_records does not keep the latest raw row
-- per source_record_id using crawl_timestamp DESC, id DESC precedence.
WITH ranked_raw AS (
    SELECT
        r.id AS raw_artwork_id,
        r.source_record_id,
        ROW_NUMBER() OVER (
            PARTITION BY r.source_record_id
            ORDER BY r.crawl_timestamp DESC NULLS LAST, r.id DESC
        ) AS rn
    FROM raw.artworks r
    WHERE r.source_record_id IS NOT NULL
),
app_joined AS (
    SELECT
        a.raw_artwork_id::uuid AS raw_artwork_id,
        rr.source_record_id,
        rr.rn
    FROM app.artwork_records a
    JOIN ranked_raw rr
      ON rr.raw_artwork_id = a.raw_artwork_id::uuid
    WHERE rr.source_record_id IS NOT NULL
)
SELECT *
FROM app_joined
WHERE rn <> 1;
