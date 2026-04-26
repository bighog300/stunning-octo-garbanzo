# Artio Data Schema Specification

## 1. Purpose

This document defines the database schemas, tables, fields, keys, and ownership rules for the Artio data pipeline.

The schema is designed to support this flow:

```text
Scrapy → raw schema → dbt → analytics schema → app schema → Artio / Superset
```

The goal is to keep scraped source data traceable while producing clean, reliable records for the Artio app.

---

## 2. Schema Overview

Recommended PostgreSQL schemas:

```text
raw
analytics
app
```

| Schema | Owner | Purpose |
|---|---|---|
| raw | Scrapy | Store unmodified or lightly processed crawler output |
| analytics | dbt | Store cleaned, normalized, tested data models |
| app | Artio backend | Store app-facing views, review state, approvals, rejections, enrichments |

---

## 3. Design Principles

1. Scrapy writes only to `raw`.
2. dbt reads from `raw` and writes to `analytics`.
3. Artio reads from `analytics` or `app`, not directly from `raw`.
4. Superset reads primarily from `analytics`.
5. Raw data should be preserved for traceability.
6. Clean records should be reproducible from raw records.
7. Human review state belongs in `app`, not `raw` or `analytics`.
8. Source URLs should be treated as primary deduplication anchors where possible.

---

## 4. Data Types and Conventions

### Common ID conventions

Use UUIDs for durable internal identifiers.

```sql
id UUID PRIMARY KEY
```

### Timestamps

Use timezone-aware timestamps.

```sql
created_at TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at TIMESTAMPTZ
crawl_timestamp TIMESTAMPTZ
```

### Source URLs

Store canonical source URLs where possible.

```sql
source_url TEXT NOT NULL
source_domain TEXT NOT NULL
```

### Raw payloads

Use `JSONB` for flexible source data.

```sql
raw_payload JSONB
```

---

## 5. raw Schema

The `raw` schema stores crawler output and crawl metadata.

Scrapy owns this schema.

---

## 5.1 raw.sources

Stores crawlable source websites.

```sql
CREATE TABLE raw.sources (
    id UUID PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_domain TEXT NOT NULL UNIQUE,
    base_url TEXT NOT NULL,
    source_type TEXT,
    crawl_frequency TEXT,
    risk_level TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ
);
```

### Fields

| Field | Type | Required | Description |
|---|---:|---:|---|
| id | UUID | Yes | Internal source ID |
| source_name | TEXT | Yes | Human-readable source name |
| source_domain | TEXT | Yes | Domain, e.g. `metmuseum.org` |
| base_url | TEXT | Yes | Main website URL |
| source_type | TEXT | No | Museum, gallery, marketplace, auction, aggregator |
| crawl_frequency | TEXT | No | Daily, weekly, monthly |
| risk_level | TEXT | No | Low, medium, high |
| is_active | BOOLEAN | Yes | Whether source is currently crawled |
| notes | TEXT | No | Operational notes |

---

## 5.2 raw.crawl_runs

Tracks every crawler execution.

```sql
CREATE TABLE raw.crawl_runs (
    id UUID PRIMARY KEY,
    source_id UUID REFERENCES raw.sources(id),
    spider_name TEXT NOT NULL,
    run_status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    records_found INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    error_message TEXT,
    airflow_dag_id TEXT,
    airflow_task_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### run_status values

```text
started
success
failed
partial_success
cancelled
```

---

## 5.3 raw.artworks

Stores raw artwork records extracted from source websites.

```sql
CREATE TABLE raw.artworks (
    id UUID PRIMARY KEY,
    source_id UUID REFERENCES raw.sources(id),
    crawl_run_id UUID REFERENCES raw.crawl_runs(id),
    source_url TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    source_record_id TEXT,
    artist_name TEXT,
    artwork_title TEXT,
    artwork_date_text TEXT,
    medium_text TEXT,
    dimensions_text TEXT,
    price_text TEXT,
    currency_text TEXT,
    gallery_name TEXT,
    institution_name TEXT,
    department_name TEXT,
    image_url TEXT,
    thumbnail_url TEXT,
    description TEXT,
    raw_payload JSONB,
    content_hash TEXT,
    crawl_timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ
);
```

### Required minimum fields

For a record to be useful, it should ideally include:

```text
source_url
source_domain
artist_name OR institution_name
artwork_title
crawl_timestamp
```

### Deduplication anchor

Preferred raw deduplication key:

```text
source_domain + source_url
```

Fallback:

```text
source_domain + content_hash
```

---

## 5.4 raw.artists

Stores raw artist records where a source provides separate artist pages.

```sql
CREATE TABLE raw.artists (
    id UUID PRIMARY KEY,
    source_id UUID REFERENCES raw.sources(id),
    crawl_run_id UUID REFERENCES raw.crawl_runs(id),
    source_url TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    source_record_id TEXT,
    artist_name TEXT NOT NULL,
    birth_year_text TEXT,
    death_year_text TEXT,
    nationality_text TEXT,
    biography TEXT,
    image_url TEXT,
    raw_payload JSONB,
    content_hash TEXT,
    crawl_timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ
);
```

---

## 5.5 raw.crawl_errors

Stores failed URLs and extraction errors.

```sql
CREATE TABLE raw.crawl_errors (
    id UUID PRIMARY KEY,
    crawl_run_id UUID REFERENCES raw.crawl_runs(id),
    source_id UUID REFERENCES raw.sources(id),
    spider_name TEXT NOT NULL,
    source_url TEXT,
    error_type TEXT NOT NULL,
    error_message TEXT,
    http_status INTEGER,
    retry_count INTEGER DEFAULT 0,
    raw_context JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### error_type values

```text
request_failed
http_error
parse_error
missing_required_field
database_error
blocked
unknown
```

---

## 6. analytics Schema

The `analytics` schema stores dbt-managed models.

dbt owns this schema.

No application should manually write to these tables.

---

## 6.1 analytics.stg_artworks

Clean staging layer for raw artwork records.

Expected fields:

```sql
id UUID,
raw_artwork_id UUID,
source_id UUID,
source_name TEXT,
source_domain TEXT,
source_url TEXT,
artist_name_clean TEXT,
artwork_title_clean TEXT,
artwork_date_text TEXT,
medium_text TEXT,
dimensions_text TEXT,
price_text TEXT,
currency_text TEXT,
image_url TEXT,
thumbnail_url TEXT,
description TEXT,
crawl_timestamp TIMESTAMPTZ,
created_at TIMESTAMPTZ
```

Purpose:

- Trim whitespace
- Normalize casing where safe
- Remove obvious HTML artifacts
- Standardize blank values to NULL
- Keep source-level provenance

---

## 6.2 analytics.int_price_parsed

Parses price text into structured values.

Expected fields:

```sql
raw_artwork_id UUID,
price_text TEXT,
price_numeric NUMERIC,
currency_code TEXT,
price_min NUMERIC,
price_max NUMERIC,
price_is_range BOOLEAN,
price_is_available BOOLEAN,
price_parse_status TEXT
```

### price_parse_status values

```text
parsed
range_parsed
not_available
price_on_request
failed
missing
```

---

## 6.3 analytics.int_dimensions_parsed

Parses dimensions into structured values.

Expected fields:

```sql
raw_artwork_id UUID,
dimensions_text TEXT,
height_cm NUMERIC,
width_cm NUMERIC,
depth_cm NUMERIC,
dimension_unit_original TEXT,
dimension_parse_status TEXT
```

### dimension_parse_status values

```text
parsed
partial
failed
missing
```

---

## 6.4 analytics.int_artist_deduped

Creates normalized artist identities.

Expected fields:

```sql
artist_id UUID,
artist_name_clean TEXT,
artist_slug TEXT,
birth_year INTEGER,
death_year INTEGER,
nationality TEXT,
source_count INTEGER,
first_seen_at TIMESTAMPTZ,
last_seen_at TIMESTAMPTZ
```

Deduplication strategy:

```text
Lowercase name
Remove extra spaces
Normalize punctuation
Optionally compare birth/death year when available
```

---

## 6.5 analytics.int_artwork_normalized

Creates normalized artwork candidates.

Expected fields:

```sql
artwork_candidate_id UUID,
raw_artwork_id UUID,
artist_id UUID,
artist_name_clean TEXT,
artwork_title_clean TEXT,
artwork_slug TEXT,
year_start INTEGER,
year_end INTEGER,
medium_category TEXT,
source_url TEXT,
source_domain TEXT,
image_url TEXT,
price_numeric NUMERIC,
currency_code TEXT,
height_cm NUMERIC,
width_cm NUMERIC,
depth_cm NUMERIC,
quality_score NUMERIC,
duplicate_group_key TEXT,
crawl_timestamp TIMESTAMPTZ
```

---

## 6.6 analytics.mart_artworks

Primary clean artwork table used by Superset and Artio.

```sql
CREATE TABLE analytics.mart_artworks (
    artwork_id UUID PRIMARY KEY,
    raw_artwork_id UUID NOT NULL,
    artist_id UUID,
    artist_name TEXT,
    artwork_title TEXT NOT NULL,
    year_start INTEGER,
    year_end INTEGER,
    artwork_date_text TEXT,
    medium_text TEXT,
    medium_category TEXT,
    dimensions_text TEXT,
    height_cm NUMERIC,
    width_cm NUMERIC,
    depth_cm NUMERIC,
    price_text TEXT,
    price_numeric NUMERIC,
    currency_code TEXT,
    source_name TEXT,
    source_domain TEXT NOT NULL,
    source_url TEXT NOT NULL,
    image_url TEXT,
    thumbnail_url TEXT,
    description TEXT,
    quality_score NUMERIC,
    duplicate_group_key TEXT,
    crawl_timestamp TIMESTAMPTZ,
    created_at TIMESTAMPTZ
);
```

### Important fields for Artio

```text
artwork_id
artist_id
artist_name
artwork_title
year_start
year_end
medium_category
price_numeric
currency_code
source_url
image_url
quality_score
```

---

## 6.7 analytics.mart_artists

Clean artist table.

```sql
CREATE TABLE analytics.mart_artists (
    artist_id UUID PRIMARY KEY,
    artist_name TEXT NOT NULL,
    artist_slug TEXT,
    birth_year INTEGER,
    death_year INTEGER,
    nationality TEXT,
    biography TEXT,
    image_url TEXT,
    source_count INTEGER,
    artwork_count INTEGER,
    first_seen_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ
);
```

---

## 6.8 analytics.mart_sources

Clean source summary table.

```sql
CREATE TABLE analytics.mart_sources (
    source_id UUID PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    source_type TEXT,
    risk_level TEXT,
    is_active BOOLEAN,
    last_successful_crawl_at TIMESTAMPTZ,
    total_records INTEGER,
    total_errors INTEGER,
    missing_required_field_rate NUMERIC,
    duplicate_rate NUMERIC
);
```

---

## 6.9 analytics.mart_crawl_quality

Quality monitoring table for Superset.

```sql
CREATE TABLE analytics.mart_crawl_quality (
    source_id UUID,
    source_name TEXT,
    source_domain TEXT,
    crawl_date DATE,
    records_found INTEGER,
    records_inserted INTEGER,
    records_failed INTEGER,
    error_count INTEGER,
    missing_artist_count INTEGER,
    missing_title_count INTEGER,
    missing_image_count INTEGER,
    duplicate_candidate_count INTEGER,
    avg_quality_score NUMERIC
);
```

---

## 7. app Schema

The `app` schema stores Artio-facing state and review data.

Artio owns this schema.

---

## 7.1 app.review_queue

Stores records that need human review before being approved.

```sql
CREATE TABLE app.review_queue (
    id UUID PRIMARY KEY,
    artwork_id UUID NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT DEFAULT 'normal',
    assigned_to TEXT,
    review_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by TEXT
);
```

### review_status values

```text
pending
approved
rejected
needs_enrichment
duplicate
```

---

## 7.2 app.approved_artworks

Stores records approved for use in Artio.

```sql
CREATE TABLE app.approved_artworks (
    id UUID PRIMARY KEY,
    artwork_id UUID NOT NULL,
    approved_by TEXT,
    approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    public_visibility BOOLEAN NOT NULL DEFAULT false,
    notes TEXT
);
```

---

## 7.3 app.rejected_artworks

Stores rejected records and reasons.

```sql
CREATE TABLE app.rejected_artworks (
    id UUID PRIMARY KEY,
    artwork_id UUID NOT NULL,
    rejection_reason TEXT NOT NULL,
    rejected_by TEXT,
    rejected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes TEXT
);
```

### rejection_reason values

```text
duplicate
missing_required_data
bad_source
copyright_concern
not_relevant
low_quality
other
```

---

## 7.4 app.artwork_records

Recommended Artio-facing view.

```sql
CREATE VIEW app.artwork_records AS
SELECT
    a.artwork_id,
    a.artist_id,
    a.artist_name,
    a.artwork_title,
    a.year_start,
    a.year_end,
    a.medium_text,
    a.medium_category,
    a.dimensions_text,
    a.price_numeric,
    a.currency_code,
    a.source_name,
    a.source_domain,
    a.source_url,
    a.image_url,
    a.thumbnail_url,
    a.description,
    a.quality_score,
    rq.review_status,
    aa.public_visibility
FROM analytics.mart_artworks a
LEFT JOIN app.review_queue rq
    ON a.artwork_id = rq.artwork_id
LEFT JOIN app.approved_artworks aa
    ON a.artwork_id = aa.artwork_id;
```

---

## 8. Indexing Strategy

Recommended indexes:

```sql
CREATE INDEX idx_raw_artworks_source_url
ON raw.artworks(source_domain, source_url);

CREATE INDEX idx_raw_artworks_crawl_timestamp
ON raw.artworks(crawl_timestamp);

CREATE INDEX idx_mart_artworks_artist
ON analytics.mart_artworks(artist_name);

CREATE INDEX idx_mart_artworks_title
ON analytics.mart_artworks(artwork_title);

CREATE INDEX idx_mart_artworks_source
ON analytics.mart_artworks(source_domain);

CREATE INDEX idx_review_queue_status
ON app.review_queue(review_status);
```

For search-heavy Artio usage, add full-text indexes later:

```sql
CREATE INDEX idx_mart_artworks_search
ON analytics.mart_artworks
USING GIN (to_tsvector('english', coalesce(artist_name, '') || ' ' || coalesce(artwork_title, '') || ' ' || coalesce(medium_text, '')));
```

---

## 9. Data Quality Rules

Critical rules:

```text
source_url must not be null
source_domain must not be null
crawl_timestamp must not be null
artwork_title should not be null in mart_artworks
source_url should be unique per source where possible
```

Recommended quality scoring inputs:

```text
artist present
artwork title present
year/date present
medium present
dimensions present
image URL present
source URL present
price parsed if price exists
```

Example scoring:

```text
+20 artist present
+20 title present
+10 year present
+10 medium present
+10 dimensions present
+10 image URL present
+10 valid source URL
+10 description present
```

---

## 10. Ownership Matrix

| Table/View | Owner | Writer | Reader |
|---|---|---|---|
| raw.sources | Pipeline admin | Admin/Scrapy setup | Scrapy/dbt |
| raw.crawl_runs | Scrapy/Airflow | Scrapy/Airflow | dbt/Superset |
| raw.artworks | Scrapy | Scrapy | dbt |
| raw.artists | Scrapy | Scrapy | dbt |
| raw.crawl_errors | Scrapy | Scrapy | dbt/Superset |
| analytics.* | dbt | dbt | Superset/Artio |
| app.review_queue | Artio | Artio | Artio/Superset |
| app.approved_artworks | Artio | Artio | Artio/Superset |
| app.rejected_artworks | Artio | Artio | Artio/Superset |

---

## 11. MVP Minimum Schema

For the first working version, only these are required:

```text
raw.sources
raw.crawl_runs
raw.artworks
raw.crawl_errors
analytics.mart_artworks
analytics.mart_crawl_quality
app.review_queue
app.artwork_records
```

This is enough to support:

- One spider
- Raw storage
- Clean records
- Superset monitoring
- Artio browsing/review

---

## 12. Open Questions

1. Should Artio use UUIDs or existing app IDs?
2. Does Artio already have users/roles that should connect to review actions?
3. Should approved records be copied into app tables or exposed through views?
4. Should image URLs be stored only, or should images be downloaded later?
5. Should duplicate detection happen automatically or be human-reviewed?
6. Should rejected records be hidden permanently or re-reviewable later?
7. Does Artio need version history for edited/enriched records?

---

## 13. Next Document

Next document:

```text
Scrapy Spider Specification
```

