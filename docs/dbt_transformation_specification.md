# Artio dbt Transformation Specification

## 1. Purpose

This document defines how dbt transforms raw scraped art records into clean, normalized, tested datasets for Artio and Superset.

The dbt layer is responsible for turning crawler output into reliable data products.

The pipeline flow is:

```text
raw PostgreSQL tables → dbt staging → dbt intermediate models → dbt marts → Artio / Superset
```

---

## 2. dbt Responsibilities

dbt should:

- Read from the `raw` schema.
- Clean and standardize scraped text fields.
- Parse prices, dates, and dimensions.
- Normalize source and artist information.
- Identify duplicate candidates.
- Score record quality.
- Produce Artio-ready mart tables.
- Produce Superset-ready monitoring tables.
- Run data quality tests.

---

## 3. dbt Non-Responsibilities

dbt should not:

- Crawl websites.
- Write to the `raw` schema.
- Store user review decisions.
- Replace the Artio approval workflow.
- Download or process images.
- Make irreversible human-curation decisions.

---

## 4. Project Structure

Recommended dbt project structure:

```text
artio_dbt/
  dbt_project.yml
  profiles.yml.example
  packages.yml
  models/
    sources.yml
    staging/
      stg_sources.sql
      stg_crawl_runs.sql
      stg_crawl_errors.sql
      stg_artworks.sql
      stg_artists.sql
      staging.yml
    intermediate/
      int_price_parsed.sql
      int_dimensions_parsed.sql
      int_dates_parsed.sql
      int_artist_deduped.sql
      int_artwork_normalized.sql
      int_duplicate_candidates.sql
      intermediate.yml
    marts/
      mart_artworks.sql
      mart_artists.sql
      mart_sources.sql
      mart_crawl_quality.sql
      marts.yml
  macros/
    clean_text.sql
    slugify.sql
    parse_currency.sql
    quality_score.sql
  seeds/
    medium_categories.csv
    currency_symbols.csv
  tests/
    assert_valid_year_ranges.sql
    assert_no_invalid_prices.sql
```

---

## 5. Model Layers

## 5.1 Sources

Sources define the raw tables dbt reads from.

Example `sources.yml`:

```yaml
version: 2

sources:
  - name: raw
    schema: raw
    tables:
      - name: sources
      - name: crawl_runs
      - name: crawl_errors
      - name: artworks
      - name: artists
```

---

## 5.2 Staging Models

Staging models perform light cleanup and standardization.

Rules:

- One staging model per raw table.
- Keep one-to-one relationship with raw records where possible.
- Do not perform major business logic here.
- Rename fields into consistent names.
- Standardize empty strings to NULL.
- Trim whitespace.

Staging models:

```text
stg_sources
stg_crawl_runs
stg_crawl_errors
stg_artworks
stg_artists
```

---

## 5.3 Intermediate Models

Intermediate models perform parsing, normalization, enrichment, and candidate matching.

Models:

```text
int_price_parsed
int_dimensions_parsed
int_dates_parsed
int_artist_deduped
int_artwork_normalized
int_duplicate_candidates
```

---

## 5.4 Mart Models

Mart models are final tables for Artio and Superset.

Models:

```text
mart_artworks
mart_artists
mart_sources
mart_crawl_quality
```

---

## 6. Naming Conventions

| Layer | Prefix | Example |
|---|---|---|
| Staging | stg_ | stg_artworks |
| Intermediate | int_ | int_price_parsed |
| Mart | mart_ | mart_artworks |

Column naming rules:

```text
Use snake_case
Use *_text for raw source strings
Use *_clean for cleaned strings
Use *_numeric for numeric parsed values
Use *_at for timestamps
Use *_date for dates
Use *_id for identifiers
```

---

## 7. Materialization Strategy

Recommended materializations:

```text
staging: view
intermediate: table
marts: table
```

For MVP:

```yaml
models:
  artio_dbt:
    staging:
      +materialized: view
    intermediate:
      +materialized: table
    marts:
      +materialized: table
```

Later, large tables may use incremental materialization.

---

## 8. Source Freshness

Track freshness for key raw tables:

```yaml
sources:
  - name: raw
    schema: raw
    tables:
      - name: artworks
        loaded_at_field: crawl_timestamp
        freshness:
          warn_after:
            count: 7
            period: day
          error_after:
            count: 30
            period: day
```

For monthly museum crawls, thresholds can be relaxed.

---

## 9. Text Cleaning Rules

Apply basic text cleaning in staging.

Rules:

```text
Trim leading/trailing whitespace
Collapse repeated spaces
Convert empty strings to NULL
Remove obvious HTML entities
Preserve original meaning
Do not aggressively lowercase names or titles in final display fields
```

Example macro:

```sql
{% macro clean_text(column_name) %}
    nullif(trim(regexp_replace({{ column_name }}, '\s+', ' ', 'g')), '')
{% endmacro %}
```

---

## 10. stg_artworks

Purpose:

- Clean raw artwork records.
- Standardize field names.
- Preserve raw identifiers and provenance.

Expected fields:

```text
raw_artwork_id
source_id
crawl_run_id
source_domain
source_url
source_record_id
artist_name_clean
artwork_title_clean
artwork_date_text
medium_text
dimensions_text
price_text
currency_text
gallery_name
institution_name
department_name
image_url
thumbnail_url
description
content_hash
crawl_timestamp
raw_created_at
raw_updated_at
```

Required transformations:

```text
Trim all text fields
Normalize source_domain
Convert blank strings to NULL
Keep source_url unchanged except trimming
Keep source_record_id if available
```

---

## 11. stg_artists

Purpose:

- Clean raw artist records.
- Preserve source-level artist references.

Expected fields:

```text
raw_artist_id
source_id
crawl_run_id
source_domain
source_url
source_record_id
artist_name_clean
birth_year_text
death_year_text
nationality_text
biography
image_url
content_hash
crawl_timestamp
```

---

## 12. Price Parsing

Model:

```text
int_price_parsed
```

Input:

```text
stg_artworks.price_text
stg_artworks.currency_text
```

Output fields:

```text
raw_artwork_id
price_text
price_numeric
currency_code
price_min
price_max
price_is_range
price_is_available
price_parse_status
```

### Price parsing rules

Recognize examples:

```text
$5,000 → 5000 USD
£2,500 → 2500 GBP
€1,200 → 1200 EUR
USD 10,000 → 10000 USD
Price on request → NULL, price_on_request
Sold → NULL, not_available
Not for sale → NULL, not_available
$5,000–$7,000 → min 5000, max 7000, range
```

### Currency inference

Priority:

1. Explicit currency code
2. Currency symbol in price text
3. Source default currency if configured
4. NULL

Currency symbol seed table:

```text
$ → USD
£ → GBP
€ → EUR
¥ → JPY
```

Do not infer currency from country unless a source-level rule is explicitly defined.

---

## 13. Dimension Parsing

Model:

```text
int_dimensions_parsed
```

Input:

```text
stg_artworks.dimensions_text
```

Output fields:

```text
raw_artwork_id
dimensions_text
height_cm
width_cm
depth_cm
dimension_unit_original
dimension_parse_status
```

### Supported patterns for MVP

```text
24 × 36 in.
24 x 36 in
61 × 91.4 cm
10 1/2 x 8 in.
10.5 x 8 in
```

### Conversion rule

```text
1 inch = 2.54 cm
```

### Parse statuses

```text
parsed
partial
failed
missing
```

---

## 14. Date Parsing

Model:

```text
int_dates_parsed
```

Input:

```text
stg_artworks.artwork_date_text
```

Output fields:

```text
raw_artwork_id
artwork_date_text
year_start
year_end
date_parse_status
```

### Supported MVP patterns

```text
1889 → 1889 / 1889
ca. 1850 → 1850 / 1850
c. 1850 → 1850 / 1850
1920–1925 → 1920 / 1925
19th century → 1801 / 1900
late 19th century → 1875 / 1900
```

### Parse statuses

```text
parsed
range_parsed
century_parsed
failed
missing
```

---

## 15. Medium Normalization

Use a seed file:

```text
seeds/medium_categories.csv
```

Example seed:

```csv
keyword,medium_category
oil,painting
canvas,painting
watercolor,painting
bronze,sculpture
marble,sculpture
silver print,photography
photograph,photography
ink,drawing
paper,drawing
ceramic,ceramics
```

Output field:

```text
medium_category
```

If no match:

```text
unknown
```

---

## 16. Artist Deduplication

Model:

```text
int_artist_deduped
```

Goal:

Create stable artist identities across sources.

### MVP artist key

```text
artist_slug = slugify(artist_name_clean)
```

If birth/death years are available later, improve matching:

```text
artist_slug + birth_year + death_year
```

### Do not automatically merge ambiguous artists

Ambiguous examples:

```text
Unknown
Unidentified Artist
Workshop of...
After...
Attributed to...
```

These should be flagged for review.

Expected fields:

```text
artist_id
artist_name
artist_slug
birth_year
death_year
nationality
source_count
artwork_count
first_seen_at
last_seen_at
artist_confidence_score
```

---

## 17. Artwork Normalization

Model:

```text
int_artwork_normalized
```

Goal:

Combine staging, parsed price, parsed dimensions, parsed dates, and artist identity.

Expected fields:

```text
artwork_candidate_id
raw_artwork_id
artist_id
artist_name
artwork_title
artwork_slug
year_start
year_end
medium_text
medium_category
dimensions_text
height_cm
width_cm
depth_cm
price_text
price_numeric
currency_code
source_name
source_domain
source_url
image_url
thumbnail_url
description
quality_score
duplicate_group_key
crawl_timestamp
```

---

## 18. Duplicate Candidate Detection

Model:

```text
int_duplicate_candidates
```

MVP duplicate group key:

```text
artist_slug + artwork_slug + year_start
```

If year is missing:

```text
artist_slug + artwork_slug
```

Do not delete duplicates automatically.

Instead, output:

```text
duplicate_group_key
duplicate_group_count
is_duplicate_candidate
```

Artio can then place duplicate candidates into review.

---

## 19. Quality Scoring

Quality scoring helps prioritize records for review.

Model or macro:

```text
quality_score
```

Suggested score out of 100:

```text
+20 artist present
+20 artwork title present
+10 year parsed
+10 medium present
+10 dimensions parsed
+10 image URL present
+10 valid source URL
+10 description present
```

Penalty examples:

```text
-20 duplicate candidate
-10 price parse failed when price_text exists
-10 dimension parse failed when dimensions_text exists
```

Score should be capped between 0 and 100.

---

## 20. mart_artworks

Primary clean artwork table for Artio and Superset.

Expected fields:

```text
artwork_id
raw_artwork_id
artist_id
artist_name
artwork_title
year_start
year_end
artwork_date_text
medium_text
medium_category
dimensions_text
height_cm
width_cm
depth_cm
price_text
price_numeric
currency_code
source_name
source_domain
source_url
image_url
thumbnail_url
description
quality_score
duplicate_group_key
is_duplicate_candidate
crawl_timestamp
created_at
```

### mart_artworks rules

```text
Only include records with a non-null source_url
Prefer non-null artwork_title, but do not fully discard missing title records during MVP
Preserve source attribution
Use generated artwork_id separate from raw_artwork_id
```

---

## 21. mart_artists

Clean artist table for Artio.

Expected fields:

```text
artist_id
artist_name
artist_slug
birth_year
death_year
nationality
biography
image_url
source_count
artwork_count
first_seen_at
last_seen_at
artist_confidence_score
```

---

## 22. mart_sources

Source monitoring table.

Expected fields:

```text
source_id
source_name
source_domain
source_type
risk_level
is_active
last_successful_crawl_at
total_crawl_runs
total_records
total_errors
missing_required_field_rate
duplicate_rate
avg_quality_score
```

---

## 23. mart_crawl_quality

Superset-facing pipeline quality table.

Expected fields:

```text
source_id
source_name
source_domain
crawl_date
records_found
records_inserted
records_failed
error_count
missing_artist_count
missing_title_count
missing_image_count
duplicate_candidate_count
avg_quality_score
dbt_run_timestamp
```

---

## 24. dbt Tests

## 24.1 Generic tests

Recommended tests:

```yaml
version: 2

models:
  - name: mart_artworks
    columns:
      - name: artwork_id
        tests:
          - not_null
          - unique
      - name: source_url
        tests:
          - not_null
      - name: source_domain
        tests:
          - not_null
      - name: crawl_timestamp
        tests:
          - not_null
```

---

## 24.2 Accepted values tests

```yaml
      - name: price_parse_status
        tests:
          - accepted_values:
              values: ['parsed', 'range_parsed', 'not_available', 'price_on_request', 'failed', 'missing']
```

---

## 24.3 Custom tests

Custom tests:

```text
assert_valid_year_ranges
assert_no_negative_prices
assert_quality_score_between_0_and_100
assert_no_null_source_urls
```

Example logic:

```sql
select *
from {{ ref('mart_artworks') }}
where year_start is not null
  and year_end is not null
  and year_start > year_end
```

---

## 25. dbt Commands

Local development:

```bash
dbt debug
dbt seed
dbt run
dbt test
```

Run only staging:

```bash
dbt run --select staging
```

Run artwork marts:

```bash
dbt run --select mart_artworks
```

Run with dependencies:

```bash
dbt run --select +mart_artworks
```

Production Airflow task:

```bash
dbt deps && dbt seed && dbt run && dbt test
```

---

## 26. Airflow Integration

Airflow should run dbt after Scrapy completes.

Suggested task sequence:

```text
crawl_source
validate_raw_ingestion
dbt_deps
dbt_seed
dbt_run
dbt_test
refresh_superset
```

If `dbt test` fails:

```text
Pipeline should fail for critical tests
Pipeline may warn for non-critical quality checks
```

---

## 27. Critical vs Warning Tests

Critical tests should fail the pipeline:

```text
artwork_id is null
source_url is null
source_domain is null
invalid year range
quality_score outside 0–100
```

Warning tests should not block the pipeline:

```text
artist_name missing
image_url missing
medium missing
dimensions missing
price parse failed
```

---

## 28. MVP dbt Scope

The MVP should implement:

```text
stg_artworks
stg_sources
stg_crawl_runs
int_dates_parsed
int_dimensions_parsed
int_price_parsed
int_artwork_normalized
mart_artworks
mart_crawl_quality
```

Optional for MVP:

```text
int_artist_deduped
mart_artists
mart_sources
```

---

## 29. Acceptance Criteria

The dbt layer is ready when:

```text
[ ] dbt connects to PostgreSQL
[ ] raw sources are defined
[ ] staging models run successfully
[ ] price parsing works for common formats
[ ] date parsing works for common formats
[ ] dimension parsing works for common formats
[ ] mart_artworks is created
[ ] mart_crawl_quality is created
[ ] critical dbt tests pass
[ ] Superset can read mart tables
[ ] Artio can read mart_artworks or app.artwork_records
```

---

## 30. Open Questions

1. Should `mart_artworks` include only reviewable records or all clean records?
2. Should artist deduplication be MVP or phase 2?
3. Should dbt create `app` views, or should Artio migrations own them?
4. How strict should title and artist requirements be for museum records?
5. Should price normalization support multiple currencies from day one?
6. Should quality score affect automatic review queue priority?
7. Should Superset use marts only, or also selected intermediate models?

---

## 31. Next Document

Next document:

```text
Airflow DAG Specification
```

