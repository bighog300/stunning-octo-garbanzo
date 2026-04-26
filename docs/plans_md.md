# plans.md

## Project: Artio Data Pipeline — Execution Plan

This file breaks the build into **atomic, testable tasks** for Codex (or any agent) to execute in order. Each task has:

- Objective
- Files to create/update
- Commands to run
- Validation checks (must pass before moving on)

**Rule:** Do not proceed to the next task until all validation checks pass.

---

## Phase 0 — Repo Scaffold & Environment

### Task 0.1 — Create repo scaffold

**Objective** Create the base directory structure.

**Create directories**

```text
/docs
/infra/postgres/init
/crawlers/artio_crawlers/spiders
/crawlers/artio_crawlers/utils
/crawlers/tests/fixtures
/dbt/models/staging
/dbt/models/intermediate
/dbt/models/marts
/dbt/macros
/dbt/seeds
/dbt/tests
/airflow/dags
/app
```

**Validation**

```bash
tree -L 3
```

All directories exist.

---

### Task 0.2 — Create base files

**Files**

```text
.env.example
README.md
docker-compose.yml (already provided)
```

**.env.example contents (minimum)**

```env
ARTIO_POSTGRES_HOST=postgres
ARTIO_POSTGRES_PORT=5432
ARTIO_POSTGRES_DB=artio
ARTIO_POSTGRES_USER=artio
ARTIO_POSTGRES_PASSWORD=artio
AIRFLOW_FERNET_KEY=
AIRFLOW_WEBSERVER_SECRET_KEY=artio-dev-secret
SUPERSET_SECRET_KEY=artio-superset-dev-secret
```

**Validation**

```bash
cp .env.example .env
```

---

## Phase 1 — PostgreSQL Setup

### Task 1.1 — Create databases

**File**

```text
infra/postgres/init/00_create_databases.sql
```

**Content**

```sql
CREATE DATABASE artio;
CREATE DATABASE airflow;
CREATE DATABASE superset;
```

---

### Task 1.2 — Create schemas

**File**

```text
infra/postgres/init/01_create_schemas.sql
```

**Content**

```sql
\connect artio

CREATE SCHEMA raw;
CREATE SCHEMA analytics;
CREATE SCHEMA app;
```

---

### Task 1.3 — Create raw tables

**File**

```text
infra/postgres/init/02_create_raw_tables.sql
```

**Tables**

```sql
\connect artio

CREATE TABLE raw.sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name TEXT,
    source_domain TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE raw.crawl_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name TEXT,
    spider_name TEXT,
    run_status TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    records_found INT DEFAULT 0,
    records_inserted INT DEFAULT 0,
    records_failed INT DEFAULT 0
);

CREATE TABLE raw.artworks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name TEXT,
    source_domain TEXT,
    source_url TEXT,
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
    crawl_timestamp TIMESTAMPTZ DEFAULT now(),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE raw.crawl_errors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    crawl_run_id UUID,
    source_url TEXT,
    error_type TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

---

### Task 1.4 — Create app tables

**File**

```text
infra/postgres/init/03_create_app_tables.sql
```

**Tables**

```sql
\connect artio

CREATE TABLE app.review_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artwork_id UUID,
    review_status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE app.approved_artworks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artwork_id UUID,
    public_visibility BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

---

### Task 1.5 — Validate Postgres

**Run**

```bash
docker compose up -d postgres
```

**Check schemas**

```bash
docker compose exec postgres psql -U postgres -d artio -c "\dn"
```

**Check tables**

```bash
docker compose exec postgres psql -U postgres -d artio -c "\dt raw.*"
```

**Success criteria**

```text
Schemas exist: raw, analytics, app
Tables exist in raw and app
```

---

## Phase 2 — Scrapy (Met Museum)

### Task 2.1 — Scrapy scaffold

**Files**

```text
crawlers/Dockerfile
crawlers/requirements.txt
crawlers/scrapy.cfg
crawlers/artio_crawlers/items.py
crawlers/artio_crawlers/pipelines.py
crawlers/artio_crawlers/settings.py
crawlers/artio_crawlers/db.py
```

**Requirements**

```text
scrapy
psycopg2-binary
python-dotenv
```

---

### Task 2.2 — Implement metmuseum spider

**File**

```text
crawlers/artio_crawlers/spiders/metmuseum.py
```

**Objective** Scrape 25–100 artwork records.

---

### Task 2.3 — Validate spider

**Run**

```bash
docker compose exec scrapy scrapy crawl metmuseum_artworks -a max_records=25
```

**Check DB**

```bash
SELECT COUNT(*) FROM raw.artworks;
```

**Success criteria**

```text
≥ 25 rows inserted
```

---

## Phase 3 — dbt

### Task 3.1 — dbt scaffold

Create dbt project files.

---

### Task 3.2 — stg\_artworks

Create staging model.

---

### Task 3.3 — mart\_artworks

Create final mart.

---

### Task 3.4 — Validate dbt

```bash
dbt run
dbt test
```

**Success**

```text
mart_artworks populated
```

---

## Phase 4 — Airflow

### Task 4.1 — DAG file

Create DAG using spec.

---

### Task 4.2 — Run DAG

```bash
airflow dags trigger artio_daily_art_pipeline
```

**Success**

```text
Pipeline completes without failure
```

---

## Phase 5 — App View

### Task 5.1 — Create view

```sql
CREATE VIEW app.artwork_records AS
SELECT * FROM analytics.mart_artworks;
```

---

## Phase 6 — Final Validation

**Checklist**

```text
[ ] Spider inserts data
[ ] dbt builds marts
[ ] DAG runs
[ ] app view works
```

---

## STOP RULE

Do NOT proceed if:

```text
Data not appearing
Errors ignored
Tests failing
```

Fix before continuing.

---

## Next Action for Codex

Start with:

```text
Phase 0 → Task 0.1
```

