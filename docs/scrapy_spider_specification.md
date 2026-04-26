# Artio Scrapy Spider Specification

## 1. Purpose

This document defines how Scrapy spiders should be designed, implemented, tested, and operated for the Artio data pipeline.

The spiders are responsible for collecting raw artwork and artist data from approved art-related websites and writing it into the `raw` PostgreSQL schema.

This document connects directly to:

```text
Source Website Inventory
Data Schema Specification
Airflow DAG Specification
dbt Transformation Specification
```

---

## 2. Spider Responsibilities

Each spider should:

- Crawl a single approved source website.
- Extract artwork and artist metadata.
- Preserve source URLs and provenance.
- Store raw records in PostgreSQL.
- Log crawl runs and crawl errors.
- Respect source-specific crawl rules.
- Avoid destructive normalization.
- Produce data that dbt can clean and normalize later.

Each spider should not:

- Write directly to `analytics` or `app` schemas.
- Make approval/rejection decisions.
- Perform heavy deduplication beyond source URL/content hash checks.
- Aggressively crawl protected or high-risk sites.
- Download large image sets during MVP unless explicitly approved.

---

## 3. Recommended Project Structure

```text
artio-crawlers/
  scrapy.cfg
  requirements.txt
  Dockerfile
  README.md
  artio_crawlers/
    __init__.py
    items.py
    pipelines.py
    middlewares.py
    settings.py
    db.py
    utils/
      hashing.py
      urls.py
      parsing.py
      logging.py
    spiders/
      metmuseum.py
      tate.py
      saatchi.py
      artsy.py
  tests/
    fixtures/
      metmuseum_artwork.html
    test_metmuseum.py
```

---

## 4. Spider Naming Convention

Spider names should follow this pattern:

```text
<source_domain_slug>_<record_type>
```

Examples:

```text
metmuseum_artworks
tate_artworks
saatchi_artworks
artsy_artworks
mutualart_artworks
```

For artist-only crawls:

```text
metmuseum_artists
tate_artists
```

---

## 5. Core Scrapy Items

## 5.1 ArtworkItem

The main item emitted by artwork spiders.

```python
class ArtworkItem(scrapy.Item):
    source_name = scrapy.Field()
    source_domain = scrapy.Field()
    source_url = scrapy.Field()
    source_record_id = scrapy.Field()

    artist_name = scrapy.Field()
    artwork_title = scrapy.Field()
    artwork_date_text = scrapy.Field()
    medium_text = scrapy.Field()
    dimensions_text = scrapy.Field()
    price_text = scrapy.Field()
    currency_text = scrapy.Field()

    gallery_name = scrapy.Field()
    institution_name = scrapy.Field()
    department_name = scrapy.Field()

    image_url = scrapy.Field()
    thumbnail_url = scrapy.Field()
    description = scrapy.Field()

    raw_payload = scrapy.Field()
    content_hash = scrapy.Field()
    crawl_timestamp = scrapy.Field()
```

---

## 5.2 ArtistItem

Used when a source has dedicated artist pages.

```python
class ArtistItem(scrapy.Item):
    source_name = scrapy.Field()
    source_domain = scrapy.Field()
    source_url = scrapy.Field()
    source_record_id = scrapy.Field()

    artist_name = scrapy.Field()
    birth_year_text = scrapy.Field()
    death_year_text = scrapy.Field()
    nationality_text = scrapy.Field()
    biography = scrapy.Field()
    image_url = scrapy.Field()

    raw_payload = scrapy.Field()
    content_hash = scrapy.Field()
    crawl_timestamp = scrapy.Field()
```

---

## 6. Required Fields

A spider should always try to return these fields:

```text
source_name
source_domain
source_url
artwork_title
artist_name
crawl_timestamp
raw_payload
content_hash
```

Some museum records may not have a known artist. In those cases, `institution_name` or `department_name` should still be captured.

---

## 7. Field Extraction Rules

## 7.1 Source URL

Use the final canonical detail-page URL whenever possible.

```text
source_url = response.url
```

If canonical tags are available, prefer them:

```html
<link rel="canonical" href="...">
```

---

## 7.2 Source Domain

Normalize to the root domain.

Examples:

```text
www.metmuseum.org → metmuseum.org
www.tate.org.uk → tate.org.uk
```

---

## 7.3 Artist Name

Capture the source-provided artist name exactly enough for traceability.

Examples:

```text
Vincent van Gogh
Pablo Picasso
Unknown
Unidentified Artist
```

Do not perform advanced artist deduplication in Scrapy.

---

## 7.4 Artwork Title

Capture the visible title from the artwork detail page or structured metadata.

If the source title is missing, store NULL and log a `missing_required_field` warning.

---

## 7.5 Date / Year

Store the source-provided date string as `artwork_date_text`.

Examples:

```text
1889
ca. 1850
19th century
1920–1925
```

Parsing into `year_start` and `year_end` is a dbt responsibility.

---

## 7.6 Medium

Store source-provided medium text.

Examples:

```text
Oil on canvas
Gelatin silver print
Bronze
Ink on paper
```

Medium category normalization is handled by dbt.

---

## 7.7 Dimensions

Store source-provided dimensions text exactly as available.

Examples:

```text
24 × 36 in.
61 × 91.4 cm
10 1/2 x 8 in.
```

Structured parsing is handled by dbt.

---

## 7.8 Price

Store visible price text if available.

Examples:

```text
$5,000
£2,500
Price on request
Sold
```

Do not infer hidden prices.

---

## 7.9 Images

For MVP, store image URLs only.

Recommended fields:

```text
image_url
thumbnail_url
```

Do not download or permanently host image files unless approved in the compliance policy.

---

## 7.10 Raw Payload

Each item should include the extracted source-level payload.

Example:

```json
{
  "title": "Irises",
  "artist": "Vincent van Gogh",
  "date": "1890",
  "medium": "Oil on canvas",
  "source_selectors": {
    "title": "h1",
    "artist": ".artist-name"
  }
}
```

---

## 8. Content Hashing

Each record should include a `content_hash` to detect changes.

Recommended hash input:

```text
source_url + artist_name + artwork_title + artwork_date_text + medium_text + dimensions_text + image_url
```

Hash algorithm:

```text
SHA-256
```

Purpose:

- Detect changed records
- Avoid unnecessary updates
- Support traceability

---

## 9. PostgreSQL Pipeline

Scrapy should write to:

```text
raw.artworks
raw.artists
raw.crawl_runs
raw.crawl_errors
```

### Pipeline steps

```text
Validate required fields
Normalize source domain
Create content hash
Attach crawl_run_id
Upsert raw record
Log failures
```

### Upsert rule

Preferred conflict key:

```text
source_domain + source_url
```

If the record already exists:

- Update raw fields if content hash changed
- Update `updated_at`
- Preserve original `created_at`

---

## 10. Crawl Run Tracking

Every spider run should create a `raw.crawl_runs` record.

At start:

```text
run_status = started
started_at = now()
records_found = 0
```

At completion:

```text
run_status = success / partial_success / failed
finished_at = now()
records_found = count seen
records_inserted = count inserted
records_updated = count updated
records_failed = count failed
```

The Airflow task should pass context into the spider where possible:

```text
airflow_dag_id
airflow_task_id
crawl_run_id
```

---

## 11. Error Handling

Errors should be written to:

```text
raw.crawl_errors
```

Recommended error types:

```text
request_failed
http_error
parse_error
missing_required_field
database_error
blocked
unknown
```

Each error should include:

```text
crawl_run_id
source_id
spider_name
source_url
error_type
error_message
http_status
retry_count
raw_context
created_at
```

---

## 12. Crawl Settings

Default Scrapy settings for polite crawling:

```python
ROBOTSTXT_OBEY = True
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1.5
RANDOMIZE_DOWNLOAD_DELAY = True
RETRY_ENABLED = True
RETRY_TIMES = 2
COOKIES_ENABLED = False
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
```

High-risk sites should use stricter settings:

```python
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 5
AUTOTHROTTLE_MAX_DELAY = 30
```

---

## 13. User Agent Policy

Use a clear, honest user agent where appropriate.

Example:

```text
ArtioResearchBot/0.1 (+contact-email-or-site)
```

If a source prohibits bots or automated access, do not crawl it without approval.

---

## 14. robots.txt and Compliance

Before running a spider:

```text
[ ] robots.txt reviewed
[ ] terms reviewed
[ ] crawl frequency approved
[ ] image storage policy approved
[ ] spider configured with safe rate limits
```

Spiders should default to:

```python
ROBOTSTXT_OBEY = True
```

---

## 15. Pagination Patterns

Spiders may encounter:

```text
Page-number pagination
Cursor pagination
Infinite scroll
API-backed listing pages
Sitemap-based discovery
Search result pages
```

Preferred discovery order:

1. Official API if available and allowed
2. Sitemap URLs
3. Server-rendered listing pages
4. Search result pages
5. Headless rendering only if needed

---

## 16. JavaScript-Heavy Sites

For JS-heavy sites, options are:

```text
Discover API endpoint
Use scrapy-playwright selectively
Skip source for MVP
```

Do not use Playwright for every request unless necessary.

Recommended rule:

```text
Use normal Scrapy first. Escalate to Playwright only for pages that require JS rendering.
```

---

## 17. MVP Spider: Met Museum

The first MVP spider should target:

```text
The Metropolitan Museum of Art collection pages
```

Spider name:

```text
metmuseum_artworks
```

### Goals

- Crawl a limited set of artwork detail pages.
- Extract core artwork metadata.
- Store records in `raw.artworks`.
- Log crawl run metadata.
- Feed dbt staging models.

### Initial fields

```text
source_name = The Metropolitan Museum of Art
source_domain = metmuseum.org
source_url
source_record_id
artist_name
artwork_title
artwork_date_text
medium_text
dimensions_text
institution_name
image_url
department_name
description
raw_payload
content_hash
crawl_timestamp
```

### Initial crawl limit

For MVP testing:

```text
100–500 records
```

### Schedule

```text
Manual first
Daily during development
Monthly in production
```

---

## 18. Spider Configuration Inputs

Each spider should accept runtime parameters where useful.

Examples:

```bash
scrapy crawl metmuseum_artworks \
  -a max_pages=10 \
  -a max_records=500 \
  -a crawl_run_id=<uuid>
```

Common arguments:

```text
max_pages
max_records
start_url
crawl_run_id
dry_run
```

---

## 19. Local Development Workflow

Recommended commands:

```bash
scrapy list
scrapy crawl metmuseum_artworks -a max_records=25
scrapy parse <url> --spider=metmuseum_artworks
pytest tests/
```

For database testing:

```bash
scrapy crawl metmuseum_artworks -a max_records=25 -s DATABASE_ENABLED=True
```

For dry run:

```bash
scrapy crawl metmuseum_artworks -a max_records=25 -a dry_run=true
```

---

## 20. Testing Requirements

Each spider should have tests for:

```text
Detail page parsing
Listing page parsing
Pagination discovery
Missing artist handling
Missing title handling
Image URL extraction
Content hash stability
Required field validation
```

Use saved HTML fixtures where possible.

Example test files:

```text
tests/fixtures/metmuseum_artwork.html
tests/test_metmuseum.py
```

---

## 21. Acceptance Criteria

A spider is ready when:

```text
[ ] Source inventory entry exists
[ ] Compliance checklist completed
[ ] Spider has safe crawl settings
[ ] Spider extracts required fields
[ ] Spider writes to raw.artworks
[ ] Crawl run is logged
[ ] Errors are logged
[ ] Tests pass
[ ] Airflow can run the spider
[ ] dbt can consume the output
```

---

## 22. Future Enhancements

Potential future improvements:

```text
Proxy support for approved use cases
Playwright fallback for JS-heavy pages
Image download pipeline
Change detection reports
Sitemap ingestion
Artist page enrichment
Fuzzy duplicate detection
Crawl prioritization
Queue-based crawler workers
```

---

## 23. Open Questions

1. What contact identity should be used in the crawler user agent?
2. Should Artio download images later or only store external URLs?
3. Which website should be the second spider after Met Museum?
4. Should high-risk marketplace sites be excluded from MVP?
5. Should spiders run inside Airflow workers or as separate containers?
6. Should raw HTML snapshots be stored for debugging?
7. Should crawl failures trigger notifications immediately?

---

## 24. Next Document

Next document:

```text
dbt Transformation Specification
```

