# Artio App Integration

The pipeline exposes clean records through:

```text
app.artwork_records
```

Create this view after dbt has created `analytics.mart_artworks`:

```sql
CREATE OR REPLACE VIEW app.artwork_records AS
SELECT
    a.*,
    COALESCE(rq.review_status, 'pending') AS review_status,
    COALESCE(aa.public_visibility, false) AS public_visibility
FROM analytics.mart_artworks a
LEFT JOIN app.review_queue rq
    ON a.artwork_id = rq.artwork_id
LEFT JOIN app.approved_artworks aa
    ON a.artwork_id = aa.artwork_id;
```
