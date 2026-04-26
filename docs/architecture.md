# Artio Data Pipeline Architecture

## 1. Purpose

This document defines the architecture for the Artio data pipeline: an open-source stack that crawls art-related websites, stores raw records, transforms them into clean Artio-ready data, and exposes them for dashboards and app consumption.

The proposed stack is:

```text
Scrapy → PostgreSQL raw schema → dbt → PostgreSQL analytics schema → Superset / Artio
```

Airflow orchestrates the full workflow.

---

## 2. Goals

The system should:

- Crawl art-related websites and collect structured artwork, artist, gallery, price, image, and source metadata.
- Store unmodified scraped records for traceability.
- Transform raw records into normalized tables suitable for Artio.
- Support review, search, filtering, and enrichment inside the Artio app.
- Provide operational dashboards for crawl health, missing data, duplicates, and source coverage.
- Be deployable first on Docker Compose, with a path toward a more scalable production deployment later.

---

## 3. Non-goals for MVP

The first version will not attempt to:

- Crawl every target art site at once.
- Build a fully distributed crawler fleet.
- Download and permanently host all artwork images.
- Perform advanced computer vision on images.
- Fully automate copyright or licensing decisions.
- Replace human review for ambiguous records.

---

## 4. System Overview

### High-level flow

```text
Art websites
   ↓
Scrapy spiders
   ↓
PostgreSQL raw schema
   ↓
dbt transformations and tests
   ↓
PostgreSQL analytics schema
   ↓
Superset dashboards
   ↓
Artio backend / Artio UI
```

### Component responsibilities

| Component | Responsibility |
|---|---|
| Scrapy | Crawl websites and extract raw art records |
| PostgreSQL | Store raw and transformed records |
| Airflow | Schedule and orchestrate pipeline tasks |
| dbt | Clean, normalize, deduplicate, and test records |
| Superset | Provide dashboards and data exploration |
| Artio Backend | Serve clean records to the Artio app |
| Artio UI | Allow users to search, review, approve, and manage records |

---

## 5. Core Components

## 5.1 Scrapy

Scrapy is responsible for crawling art-related websites and extracting source data.

Each source website should usually have its own spider.

Example spiders:

```text
spiders/
  artsy.py
  gallery_site.py
  museum_collection.py
  auction_house.py
```

Scrapy outputs records into PostgreSQL raw tables.

Scrapy should capture:

- Artwork title
- Artist name
- Artwork year or date range
- Medium
- Dimensions
- Price text
- Currency, if available
- Gallery, museum, or source name
- Image URL
- Detail page URL
- Source domain
- Crawl timestamp
- Raw extracted payload
- Raw HTML hash or content hash

Scrapy should not be responsible for heavy normalization. It should extract and store data as faithfully as possible.

---

## 5.2 PostgreSQL

PostgreSQL stores both raw and transformed data.

Recommended schemas:

```text
raw
analytics
app
```

### raw schema

The `raw` schema stores crawler output with minimal modification.

Example tables:

```text
raw.artworks
raw.artists
raw.sources
raw.crawl_runs
raw.crawl_errors
```

### analytics schema

The `analytics` schema stores dbt-produced models.

Example tables:

```text
analytics.stg_artworks
analytics.stg_artists
analytics.int_artwork_normalized
analytics.int_artist_deduped
analytics.mart_artworks
analytics.mart_artists
analytics.mart_sources
analytics.mart_crawl_quality
```

### app schema

The `app` schema can contain Artio-specific views or tables.

Example tables or views:

```text
app.artwork_records
app.artist_records
app.review_queue
app.approved_artworks
app.rejected_artworks
```

The Artio app should consume from `analytics` or `app`, not directly from `raw`.

---

## 5.3 dbt

dbt transforms raw scraped data into clean, normalized, Artio-ready tables.

Typical dbt model layers:

```text
models/
  staging/
    stg_artworks.sql
    stg_artists.sql
    stg_sources.sql
  intermediate/
    int_artwork_normalized.sql
    int_artist_deduped.sql
    int_price_parsed.sql
    int_dimensions_parsed.sql
  marts/
    mart_artworks.sql
    mart_artists.sql
    mart_sources.sql
    mart_crawl_quality.sql
```

dbt should handle:

- Standardizing artist names
- Normalizing artwork titles
- Parsing dates and date ranges
- Parsing prices and currencies
- Parsing dimensions
- Standardizing medium categories
- Detecting duplicate artwork records
- Flagging missing critical metadata
- Creating Artio-ready views

Example dbt quality tests:

```text
artist_name is not null
artwork_title is not null
source_url is unique where possible
crawl_timestamp is not null
price_numeric is valid when price_text exists
year_start <= year_end
```

---

## 5.4 Airflow

Airflow orchestrates the full pipeline.

Primary responsibilities:

- Schedule crawls
- Run Scrapy spiders
- Validate raw ingestion
- Run dbt transformations
- Run dbt tests
- Refresh Superset datasets if needed
- Notify on success or failure

Example DAG:

```text
crawl_art_sites
  ├── crawl_site_a
  ├── crawl_site_b
  ├── crawl_site_c
  ↓
validate_raw_records
  ↓
dbt_run
  ↓
dbt_test
  ↓
refresh_superset
  ↓
notify_pipeline_result
```

For MVP, use a single daily DAG with one spider.

Later, split into:

```text
crawl_daily_sources
crawl_weekly_sources
crawl_high_priority_sources
reprocess_raw_records
refresh_artio_views
```

---

## 5.5 Superset

Superset provides internal dashboards for the pipeline and the art dataset.

Initial dashboards:

```text
Crawl health
New records by day
Records by source
Missing metadata
Duplicate candidates
Artist coverage
Artwork price distribution
Image URL coverage
```

Superset should connect to the `analytics` schema.

Superset is for internal intelligence and quality monitoring. Artio remains the user-facing app.

---

## 5.6 Artio Backend

The Artio backend consumes clean records and exposes them to the Artio UI.

Recommended access layer:

```text
PostgreSQL analytics/app schema → Artio backend API → Artio UI
```

Suggested endpoints:

```text
GET /artworks
GET /artworks/:id
GET /artists
GET /artists/:id
GET /sources
GET /review-queue
POST /records/:id/approve
POST /records/:id/reject
POST /records/:id/enrich
```

Artio should not depend on crawler internals.

---

## 6. Data Flow

## 6.1 Crawl flow

```text
Airflow triggers Scrapy spider
   ↓
Scrapy requests source pages
   ↓
Scrapy extracts records
   ↓
Scrapy writes to raw.artworks and raw.crawl_runs
   ↓
Scrapy logs failures to raw.crawl_errors
```

## 6.2 Transformation flow

```text
Airflow triggers dbt run
   ↓
dbt reads raw tables
   ↓
dbt creates staging models
   ↓
dbt creates intermediate normalized models
   ↓
dbt creates mart tables for Artio and Superset
   ↓
dbt tests validate output quality
```

## 6.3 App consumption flow

```text
Artio backend queries analytics/app tables
   ↓
Artio UI displays records
   ↓
User reviews, approves, rejects, or enriches records
   ↓
Review actions are stored in app tables
```

---

## 7. MVP Deployment Architecture

For the MVP, deploy everything with Docker Compose on a single server or local machine.

Recommended services:

```text
postgres
redis
airflow-webserver
airflow-scheduler
airflow-worker
scrapy-worker
dbt-runner
superset
nginx
```

For a very small MVP, Redis and Airflow workers may be skipped if using Airflow LocalExecutor.

### MVP environment

```text
Docker Compose
PostgreSQL container or managed Postgres
Airflow LocalExecutor or CeleryExecutor
Superset container
Scrapy project container
dbt project mounted into Airflow/dbt container
```

### Production direction

Later, the system can move toward:

```text
Managed PostgreSQL
Dedicated crawler workers
Object storage for image snapshots
Kubernetes or ECS
Separate Airflow deployment
Centralized logging
Monitoring and alerting
```

---

## 8. Security and Access

### Internal services

Airflow and Superset should not be publicly exposed without authentication.

Recommended access pattern:

```text
Nginx reverse proxy
HTTPS
Basic auth or SSO for internal tools
Private database network
Restricted database users
```

### Database users

Recommended database roles:

```text
scrapy_writer: can insert into raw schema
dbt_runner: can read raw and write analytics
superset_reader: can read analytics
artio_app: can read analytics/app and write review actions
admin: full database access
```

---

## 9. Data Governance and Compliance

The pipeline should include a crawling policy before adding each source.

For each website, record:

- Source name
- Source URL
- robots.txt status
- Terms of service notes
- Crawl frequency
- Allowed pages
- Disallowed pages
- Whether images are stored or only linked
- Takedown process
- Contact method if available

For MVP, prefer storing image URLs rather than downloading and hosting images.

---

## 10. Observability

Track pipeline health through Airflow, Superset, and database tables.

Important metrics:

```text
crawl run status
records extracted per run
errors per source
new records per day
duplicate rate
missing artist rate
missing title rate
missing image rate
dbt test failures
last successful crawl timestamp
```

Recommended tables:

```text
raw.crawl_runs
raw.crawl_errors
analytics.mart_crawl_quality
```

---

## 11. Failure Handling

Expected failure types:

```text
site layout changed
request timeout
blocked request
missing fields
invalid price format
duplicate source URL
image URL broken
dbt test failure
Superset refresh failure
```

Handling approach:

- Scrapy should log failed URLs and reasons.
- Airflow should retry transient failures.
- dbt should fail the pipeline on critical data quality issues.
- Non-critical missing metadata should be flagged, not discarded.
- Artio should show low-confidence records in a review queue.

---

## 12. MVP Scope

The MVP should include:

```text
1 target art website
1 Scrapy spider
1 raw artwork table
1 crawl run log table
3–5 dbt models
1 Airflow DAG
1 Superset dashboard
1 Artio API endpoint or read view
```

### MVP success criteria

The MVP is successful when:

- A spider crawls one source successfully.
- Raw records are stored in PostgreSQL.
- dbt creates clean artwork records.
- Superset shows crawl and data quality metrics.
- Artio can read and display clean records.
- Failed or incomplete records are traceable.

---

## 13. Open Questions

These need to be answered before implementation:

1. Which art website should be crawled first?
2. Will Artio store only metadata, or also downloaded images?
3. Does Artio need an approval workflow before records become public?
4. What database does Artio currently use?
5. Is Artio deployed with Docker already?
6. What backend framework does Artio use?
7. How often should sources be crawled?
8. Should duplicate detection be strict or fuzzy?
9. Do records need version history?
10. Who can access Superset and Airflow?

---

## 14. Recommended Next Documents

After this architecture document, create:

1. Source Website Inventory
2. Data Schema Specification
3. Scrapy Spider Specification
4. dbt Transformation Specification
5. Airflow DAG Specification
6. Deployment Runbook
7. Artio Integration Specification
8. Crawling and Compliance Policy

