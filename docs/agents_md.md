# AGENTS.md

## Project: Artio Data Pipeline

This repository builds the Artio art-data pipeline using:

```text
Scrapy → PostgreSQL raw schema → dbt → PostgreSQL analytics schema → Superset / Artio
```

Airflow orchestrates the pipeline.

This file is the operating guide for Codex or any coding agent working in this repository.

---

## 1. Primary Objective

Build a working MVP that can:

1. Crawl one approved art source.
2. Store raw artwork records in PostgreSQL.
3. Transform raw records into clean analytics marts with dbt.
4. Run the full pipeline from Airflow.
5. Expose clean records for the Artio app.
6. Allow Superset to visualize pipeline quality and artwork data.

The MVP source is:

```text
The Metropolitan Museum of Art
```

The MVP spider is:

```text
metmuseum_artworks
```

---

## 2. Repository Structure

Expected structure:

```text
/
  AGENTS.md
  README.md
  docker-compose.yml
  .env.example

  docs/
    architecture.md
    source_website_inventory.md
    data_schema_specification.md
    scrapy_spider_specification.md
    dbt_transformation_specification.md
    airflow_dag_specification.md
    artio_integration_specification.md
    superset_dashboard_specification.md
    deployment_runbook.md
    crawling_compliance_policy.md

  infra/
    postgres/
      init/
        00_create_databases.sql
        01_create_schemas.sql
        02_create_raw_tables.sql
        03_create_app_tables.sql

  crawlers/
    Dockerfile
    requirements.txt
    scrapy.cfg
    artio_crawlers/
      __init__.py
      items.py
      pipelines.py
      settings.py
      db.py
      utils/
        __init__.py
        hashing.py
        urls.py
        parsing.py
      spiders/
        __init__.py
        metmuseum.py
    tests/
      fixtures/
      test_metmuseum.py

  dbt/
    dbt_project.yml
    profiles.yml
    packages.yml
    models/
      sources.yml
      staging/
        stg_artworks.sql
        stg_sources.sql
        stg_crawl_runs.sql
        stg_crawl_errors.sql
        staging.yml
      intermediate/
        int_dates_parsed.sql
        int_dimensions_parsed.sql
        int_price_parsed.sql
        int_artwork_normalized.sql
        intermediate.yml
      marts/
        mart_artworks.sql
        mart_crawl_quality.sql
        marts.yml
    macros/
      clean_text.sql
      slugify.sql
      quality_score.sql
    seeds/
      medium_categories.csv
      currency_symbols.csv
    tests/
      assert_valid_year_ranges.sql
      assert_quality_score_between_0_and_100.sql

  airflow/
    dags/
      artio_daily_art_pipeline.py
    logs/
    plugins/

  app/
    README.md
```

Do not invent a different structure unless there is a strong reason.

---

## 3. Build Order

Build in this order:

```text
1. Docker Compose foundation
2. PostgreSQL databases, schemas, roles, and tables
3. Scrapy project scaffold
4. Met Museum spider
5. dbt project scaffold
6. dbt staging models
7. dbt intermediate models
8. dbt marts
9. Airflow DAG
10. Artio-facing app views
11. Superset connection notes / dashboard SQL
12. Tests and verification
```

Do not attempt to build all spiders or all dashboards before the MVP vertical slice works.

---

## 4. MVP Vertical Slice

The first working slice must be:

```text
metmuseum_artworks spider
  ↓
raw.artworks
  ↓
dbt stg_artworks
  ↓
dbt int_artwork_normalized
  ↓
dbt mart_artworks
  ↓
app.artwork_records view
  ↓
Airflow DAG runs end-to-end
```

MVP success means:

```text
[ ] Docker stack starts
[ ] PostgreSQL has raw, analytics, and app schemas
[ ] Scrapy spider inserts at least 25 artwork records
[ ] dbt run completes
[ ] dbt test completes
[ ] analytics.mart_artworks contains records
[ ] app.artwork_records returns records
[ ] Airflow DAG can run the full pipeline manually
```

---

## 5. Non-negotiable Constraints

### 5.1 Data ownership

```text
Scrapy writes only to raw.*
dbt writes only to analytics.*
Artio writes only to app.*
Superset reads analytics.* and optionally app.*
```

Never write crawler output directly into `analytics` or `app`.

---

### 5.2 Compliance

Default Scrapy settings must respect responsible crawling:

```python
ROBOTSTXT_OBEY = True
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1.5
AUTOTHROTTLE_ENABLED = True
```

Do not bypass CAPTCHA, login walls, paywalls, or access controls.

For MVP, store image URLs only. Do not bulk-download images.

---

### 5.3 Source choice

Only implement the Met Museum spider first.

Do not implement Artsy, Saatchi, MutualArt, or other higher-risk sources until the MVP passes.

---

### 5.4 Raw data preservation

Raw source values must be preserved in `raw.artworks`.

Heavy normalization belongs in dbt.

---

## 6. Environment Variables

Use environment variables for credentials.

Expected variables:

```text
ARTIO_POSTGRES_HOST
ARTIO_POSTGRES_PORT
ARTIO_POSTGRES_DB
ARTIO_POSTGRES_USER
ARTIO_POSTGRES_PASSWORD
AIRFLOW_FERNET_KEY
AIRFLOW_WEBSERVER_SECRET_KEY
SUPERSET_SECRET_KEY
```

Provide `.env.example` but never commit real secrets.

---

## 7. Database Requirements

Create these databases:

```text
artio
airflow
superset
```

Create these schemas in `artio`:

```text
raw
analytics
app
```

Minimum required tables:

```text
raw.sources
raw.crawl_runs
raw.artworks
raw.artists
raw.crawl_errors
app.review_queue
app.approved_artworks
app.rejected_artworks
app.record_enrichments
```

Minimum required view:

```text
app.artwork_records
```

---

## 8. Scrapy Requirements

The Scrapy project must include:

```text
items.py
pipelines.py
settings.py
db.py
spiders/metmuseum.py
```

The `metmuseum_artworks` spider should support runtime arguments:

```text
max_records
max_pages
crawl_run_id
dry_run
```

The spider must emit fields compatible with `raw.artworks`:

```text
source_name
source_domain
source_url
source_record_id
artist_name
artwork_title
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
raw_payload
content_hash
crawl_timestamp
```

The spider must not require browser automation for MVP unless absolutely necessary.

---

## 9. dbt Requirements

The dbt project must connect to PostgreSQL and define raw sources.

Minimum models:

```text
stg_artworks
stg_sources
stg_crawl_runs
stg_crawl_errors
int_dates_parsed
int_dimensions_parsed
int_price_parsed
int_artwork_normalized
mart_artworks
mart_crawl_quality
```

Minimum tests:

```text
mart_artworks.artwork_id not null
mart_artworks.artwork_id unique
mart_artworks.source_url not null
mart_artworks.source_domain not null
quality_score between 0 and 100
year_start <= year_end when both are present
```

---

## 10. Airflow Requirements

Create one MVP DAG:

```text
artio_daily_art_pipeline
```

The DAG should run manually by default:

```python
schedule_interval = None
catchup = False
max_active_runs = 1
```

Task order:

```text
start
create_crawl_run
run_scrapy_spider
validate_raw_ingestion
dbt_deps
dbt_seed
dbt_run
dbt_test
refresh_superset
notify_success
end
```

For MVP, `refresh_superset` may be a no-op `EmptyOperator`.

---

## 11. Superset Requirements

Superset should connect to the `artio` PostgreSQL database.

Primary datasets:

```text
analytics.mart_artworks
analytics.mart_crawl_quality
```

Do not block the MVP if dashboard creation is manual.

At minimum, document how to connect Superset to Postgres.

---

## 12. Artio Integration Requirements

Create the `app.artwork_records` view.

The app-facing view must expose:

```text
artwork_id
artist_name
artwork_title
year_start
year_end
medium_text
medium_category
dimensions_text
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
review_status
public_visibility
crawl_timestamp
```

Do not require a full Artio frontend implementation for the pipeline MVP.

---

## 13. Testing Commands

Expected commands:

```bash
docker compose up -d
```

Check containers:

```bash
docker compose ps
```

Run Scrapy manually:

```bash
docker compose exec scrapy scrapy crawl metmuseum_artworks -a max_records=25
```

Run dbt:

```bash
docker compose exec dbt dbt deps

docker compose exec dbt dbt seed

docker compose exec dbt dbt run

docker compose exec dbt dbt test
```

Trigger Airflow DAG:

```bash
docker compose exec airflow-webserver airflow dags trigger artio_daily_art_pipeline
```

Check database records:

```bash
docker compose exec postgres psql -U postgres -d artio -c "select count(*) from raw.artworks;"

docker compose exec postgres psql -U postgres -d artio -c "select count(*) from analytics.mart_artworks;"

docker compose exec postgres psql -U postgres -d artio -c "select count(*) from app.artwork_records;"
```

---

## 14. Definition of Done

A task is done only when:

```text
[ ] Code is implemented
[ ] Required files are in the expected locations
[ ] Commands run without errors
[ ] Data appears in the expected tables/views
[ ] Tests or validation queries pass
[ ] No secrets are hardcoded
[ ] No unrelated components are modified
```

---

## 15. Coding Style

### Python

Use:

```text
Python 3.11+
Type hints where practical
Small functions
Clear error handling
Structured logging
```

### SQL

Use:

```text
snake_case identifiers
explicit column lists
clear CTEs
comments for non-obvious parsing logic
```

### dbt

Use:

```text
ref()
source()
macros for repeated logic
schema YAML tests
```

---

## 16. Do Not Do

Do not:

```text
Build multiple spiders before Met Museum works
Hardcode real credentials
Disable robots.txt globally without explicit approval
Download images in bulk
Write Scrapy data to analytics/app schemas
Modify dbt marts manually
Expose Airflow or Superset publicly without auth
Skip tests because the pipeline “looks fine”
```

---

## 17. Preferred Implementation Strategy

Work in small commits or checkpoints:

```text
Checkpoint 1: Docker Compose starts
Checkpoint 2: Postgres init scripts create DB/schema/tables
Checkpoint 3: Scrapy spider writes raw.artworks
Checkpoint 4: dbt creates mart_artworks
Checkpoint 5: Airflow DAG runs end-to-end
Checkpoint 6: app.artwork_records view works
Checkpoint 7: Superset connection documented
```

At each checkpoint, run the relevant validation commands.

---

## 18. First Task for Codex

Start here:

```text
Create the repo scaffold and PostgreSQL init scripts.
```

Files to create first:

```text
.env.example
README.md
infra/postgres/init/00_create_databases.sql
infra/postgres/init/01_create_schemas.sql
infra/postgres/init/02_create_raw_tables.sql
infra/postgres/init/03_create_app_tables.sql
```

Then validate with:

```bash
docker compose up -d postgres

docker compose exec postgres psql -U postgres -d artio -c "select schema_name from information_schema.schemata where schema_name in ('raw','analytics','app');"
```

---

## 19. Documentation Source of Truth

Use the `/docs` directory as the source of truth.

If implementation differs from documentation:

1. Prefer the documentation unless it is technically impossible.
2. If implementation must differ, update the relevant doc.
3. Keep AGENTS.md aligned with the current build approach.

---

## 20. Final MVP Target

The final MVP should prove:

```text
A real art source can be crawled responsibly.
Raw data is stored with provenance.
dbt produces clean, testable marts.
Airflow runs the pipeline end-to-end.
Artio can read clean records.
Superset can monitor the pipeline.
```

