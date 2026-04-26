# Artio Airflow DAG Specification

## 1. Purpose

This document defines how Apache Airflow orchestrates the Artio data pipeline.

Airflow coordinates the full flow:

```text
Scrapy crawl → raw PostgreSQL validation → dbt run/test → Superset refresh → notification
```

The goal is to make crawling, transformation, quality checks, and monitoring repeatable, observable, and recoverable.

---

## 2. Airflow Responsibilities

Airflow should:

- Schedule crawler runs.
- Trigger Scrapy spiders.
- Pass runtime parameters to spiders.
- Track task success/failure.
- Run lightweight raw ingestion checks.
- Run dbt transformations and tests.
- Refresh Superset datasets or dashboards if needed.
- Send success/failure notifications.
- Provide retry and recovery behavior.

Airflow should not:

- Parse website HTML directly.
- Perform dbt transformation logic.
- Store business review state.
- Replace Artio approval workflows.
- Contain large amounts of source-specific scraping logic.

---

## 3. DAG Overview

Primary MVP DAG:

```text
artio_daily_art_pipeline
```

High-level task flow:

```text
start
  ↓
create_crawl_run
  ↓
run_scrapy_spider
  ↓
validate_raw_ingestion
  ↓
dbt_deps
  ↓
dbt_seed
  ↓
dbt_run
  ↓
dbt_test
  ↓
refresh_superset
  ↓
notify_success
  ↓
end
```

Failure path:

```text
any_failed_task → notify_failure
```

---

## 4. MVP DAG: artio_daily_art_pipeline

## 4.1 Purpose

Runs the end-to-end pipeline for one or more approved art sources.

For MVP, this DAG should run one source first:

```text
The Metropolitan Museum of Art
```

Spider:

```text
metmuseum_artworks
```

---

## 4.2 Schedule

Recommended MVP schedule:

```text
Manual during development
Daily during active testing
Monthly for stable museum sources
```

Initial Airflow schedule:

```python
schedule_interval=None
```

After MVP validation:

```python
schedule_interval="0 2 * * *"
```

This means daily at 02:00 server time.

For museum sources, later use:

```python
schedule_interval="0 3 1 * *"
```

This means monthly on the 1st at 03:00.

---

## 4.3 DAG Configuration

Recommended DAG settings:

```python
default_args = {
    "owner": "artio-data",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
    "email_on_retry": False,
}
```

Recommended DAG definition:

```python
with DAG(
    dag_id="artio_daily_art_pipeline",
    default_args=default_args,
    start_date=datetime(2026, 1, 1),
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
    tags=["artio", "scrapy", "dbt", "superset"],
) as dag:
    ...
```

---

## 5. Runtime Parameters

The DAG should support runtime configuration.

Example Airflow run config:

```json
{
  "source_name": "The Metropolitan Museum of Art",
  "spider_name": "metmuseum_artworks",
  "max_records": 500,
  "max_pages": 10,
  "dry_run": false,
  "dbt_select": "+mart_artworks"
}
```

Defaults:

```text
source_name = The Metropolitan Museum of Art
spider_name = metmuseum_artworks
max_records = 500
max_pages = 10
dry_run = false
dbt_select = +mart_artworks
```

---

## 6. Task Definitions

## 6.1 start

Simple marker task.

Operator:

```text
EmptyOperator
```

Purpose:

```text
Establish DAG start point
```

---

## 6.2 create_crawl_run

Creates a `raw.crawl_runs` row before Scrapy starts.

Operator options:

```text
PythonOperator
PostgresOperator
```

Inputs:

```text
source_name
spider_name
airflow_dag_id
airflow_task_id
started_at
```

Output:

```text
crawl_run_id
```

The `crawl_run_id` should be pushed to XCom so downstream tasks can use it.

Expected status:

```text
started
```

---

## 6.3 run_scrapy_spider

Runs the configured Scrapy spider.

Operator options:

```text
BashOperator
DockerOperator
KubernetesPodOperator
```

MVP recommendation:

```text
DockerOperator or BashOperator inside the crawler container
```

Example command:

```bash
scrapy crawl metmuseum_artworks \
  -a crawl_run_id={{ ti.xcom_pull(task_ids='create_crawl_run') }} \
  -a max_records={{ dag_run.conf.get('max_records', 500) }} \
  -a max_pages={{ dag_run.conf.get('max_pages', 10) }} \
  -a dry_run={{ dag_run.conf.get('dry_run', false) }}
```

Responsibilities:

```text
Run spider
Write raw.artworks
Write raw.crawl_errors
Update raw.crawl_runs counts where possible
```

---

## 6.4 validate_raw_ingestion

Checks whether the crawl produced usable raw data.

Operator:

```text
PythonOperator or SQLCheckOperator
```

Example checks:

```text
crawl_run exists
crawl_run status is success or partial_success
records_found >= minimum threshold
records_failed below maximum threshold
raw.artworks contains records for crawl_run_id
```

MVP thresholds:

```text
minimum_records_found = 1
maximum_failure_rate = 50%
```

Failure behavior:

```text
Fail pipeline if no records were found unless dry_run=true
```

---

## 6.5 dbt_deps

Installs dbt package dependencies.

Operator:

```text
BashOperator
```

Command:

```bash
cd /opt/artio_dbt && dbt deps
```

---

## 6.6 dbt_seed

Loads static seed files.

Operator:

```text
BashOperator
```

Command:

```bash
cd /opt/artio_dbt && dbt seed --profiles-dir /opt/artio_dbt
```

Seed examples:

```text
medium_categories.csv
currency_symbols.csv
```

---

## 6.7 dbt_run

Runs dbt transformations.

Operator:

```text
BashOperator
```

Default command:

```bash
cd /opt/artio_dbt && dbt run --profiles-dir /opt/artio_dbt --select {{ dag_run.conf.get('dbt_select', '+mart_artworks') }}
```

For full pipeline:

```bash
dbt run --profiles-dir /opt/artio_dbt
```

---

## 6.8 dbt_test

Runs dbt data quality tests.

Operator:

```text
BashOperator
```

Command:

```bash
cd /opt/artio_dbt && dbt test --profiles-dir /opt/artio_dbt --select {{ dag_run.conf.get('dbt_select', '+mart_artworks') }}
```

Failure behavior:

```text
Critical tests should fail the DAG
Warning-level checks should be implemented as reports or non-blocking models
```

---

## 6.9 refresh_superset

Refreshes Superset metadata, datasets, or dashboard caches.

Operator options:

```text
PythonOperator
SimpleHttpOperator
BashOperator with Superset CLI
```

MVP behavior:

```text
Optional / can be skipped if Superset reads live PostgreSQL tables
```

Production behavior:

```text
Refresh dataset metadata
Warm dashboard cache if caching is enabled
```

---

## 6.10 notify_success

Sends a success notification.

Notification channels:

```text
Airflow UI only for MVP
Email later
Slack/Discord/Webhook later
```

Message should include:

```text
DAG ID
Run ID
Spider name
Source name
Records found
Records inserted
Records failed
dbt status
Superset status
```

---

## 6.11 notify_failure

Sends a failure notification when any critical task fails.

Message should include:

```text
DAG ID
Run ID
Failed task
Exception summary
Spider name
Source name
Airflow log URL
Recommended action
```

---

## 7. Task Dependencies

MVP dependency graph:

```text
start
  >> create_crawl_run
  >> run_scrapy_spider
  >> validate_raw_ingestion
  >> dbt_deps
  >> dbt_seed
  >> dbt_run
  >> dbt_test
  >> refresh_superset
  >> notify_success
  >> end
```

Failure callback:

```text
on_failure_callback = notify_failure
```

---

## 8. Multiple Source Pattern

Once MVP works, use one of two approaches.

### Option A: One DAG per source

Examples:

```text
artio_metmuseum_pipeline
artio_tate_pipeline
artio_saatchi_pipeline
```

Pros:

```text
Simple isolation
Easy source-specific schedules
Easier debugging
```

Cons:

```text
More DAG files to maintain
```

### Option B: Dynamic task mapping

Single DAG dynamically maps over active sources.

Example source config:

```json
[
  {"source_name": "Met Museum", "spider_name": "metmuseum_artworks", "max_records": 500},
  {"source_name": "Tate", "spider_name": "tate_artworks", "max_records": 500}
]
```

Pros:

```text
Scales better as source count grows
Centralized orchestration
```

Cons:

```text
More complex to debug early
```

MVP recommendation:

```text
Start with one DAG per source, then migrate to dynamic mapping later.
```

---

## 9. Retry Strategy

Recommended task retries:

| Task | Retries | Notes |
|---|---:|---|
| create_crawl_run | 1 | Database issues only |
| run_scrapy_spider | 2 | Network failures are common |
| validate_raw_ingestion | 0 | Should fail clearly |
| dbt_deps | 1 | Dependency/network issues |
| dbt_seed | 1 | Usually stable |
| dbt_run | 1 | May fail from transient DB issue |
| dbt_test | 0 | Test failures should be investigated |
| refresh_superset | 1 | Non-critical in MVP |
| notify_success | 0 | Non-critical |
| notify_failure | 0 | Avoid notification loops |

---

## 10. Failure Rules

## 10.1 Spider failure

If spider exits with non-zero status:

```text
DAG fails
crawl_run status should be failed
notify_failure runs
```

---

## 10.2 No records found

If no records are found:

```text
Fail pipeline unless dry_run=true
```

Reason:

```text
No records may indicate site layout change, blocking, or broken selector logic
```

---

## 10.3 dbt run failure

If dbt cannot build models:

```text
DAG fails
Superset refresh is skipped
Artio should continue using previous successful mart tables
```

---

## 10.4 dbt test failure

If critical tests fail:

```text
DAG fails
Superset refresh is skipped
Notify failure
```

If warning checks fail:

```text
DAG succeeds with warning record in mart_crawl_quality
```

---

## 11. Airflow Connections

Recommended Airflow connections:

```text
postgres_artio
superset_api
notification_webhook
```

### postgres_artio

Used by Python or SQL tasks to query pipeline state.

Fields:

```text
host
port
database
username
password
schema
```

### superset_api

Used if the DAG refreshes Superset through API.

Fields:

```text
base_url
username
password or token
```

### notification_webhook

Used for Slack, Discord, or other webhook notifications later.

---

## 12. Airflow Variables

Recommended variables:

```text
ARTIO_ENV
ARTIO_DEFAULT_MAX_RECORDS
ARTIO_DEFAULT_MAX_PAGES
ARTIO_DBT_PROJECT_DIR
ARTIO_CRAWLER_PROJECT_DIR
ARTIO_SUPERSET_REFRESH_ENABLED
ARTIO_NOTIFICATION_ENABLED
```

Example values:

```text
ARTIO_ENV=development
ARTIO_DEFAULT_MAX_RECORDS=500
ARTIO_DEFAULT_MAX_PAGES=10
ARTIO_DBT_PROJECT_DIR=/opt/artio_dbt
ARTIO_CRAWLER_PROJECT_DIR=/opt/artio_crawlers
ARTIO_SUPERSET_REFRESH_ENABLED=false
ARTIO_NOTIFICATION_ENABLED=false
```

---

## 13. Logs and Observability

Airflow should expose:

```text
Task logs
Retry history
DAG run history
Task duration
Failure stack traces
```

Database should expose:

```text
raw.crawl_runs
raw.crawl_errors
analytics.mart_crawl_quality
```

Superset dashboards should expose:

```text
crawl success rate
records by source
errors by source
latest successful crawl
missing metadata rates
duplicate candidate counts
```

---

## 14. Environment Strategy

Recommended environments:

```text
local
staging
production
```

### local

Purpose:

```text
Developer testing
Manual DAG runs
Small crawl limits
```

### staging

Purpose:

```text
Test source changes
Validate new spiders
Validate dbt changes
```

### production

Purpose:

```text
Scheduled crawls
Stable Artio-facing data
Monitoring
Backups
```

---

## 15. Local Development Commands

Start Airflow stack:

```bash
docker compose up airflow-webserver airflow-scheduler postgres
```

Trigger DAG manually:

```bash
airflow dags trigger artio_daily_art_pipeline
```

Trigger with config:

```bash
airflow dags trigger artio_daily_art_pipeline \
  --conf '{"spider_name":"metmuseum_artworks","max_records":100,"max_pages":3}'
```

Check tasks:

```bash
airflow tasks list artio_daily_art_pipeline
```

---

## 16. Production Deployment Notes

For MVP production:

```text
Docker Compose is acceptable
Use persistent volumes
Use external backups for PostgreSQL
Protect Airflow behind authentication
Use HTTPS
Set max_active_runs=1
Limit crawler concurrency
```

For later production:

```text
Move PostgreSQL to managed database
Use CeleryExecutor or KubernetesExecutor
Run crawlers in isolated workers
Add centralized logging
Add alerting
Add secrets manager
```

---

## 17. Security Requirements

Airflow should not expose secrets in logs.

Requirements:

```text
Use Airflow Connections for credentials
Use environment variables for container secrets
Do not commit profiles.yml with passwords
Do not expose Airflow publicly without authentication
Restrict database user permissions
```

Recommended database users:

```text
airflow_runner
scrapy_writer
dbt_runner
superset_reader
artio_app
```

---

## 18. DAG Code Skeleton

Example skeleton:

```python
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator


def create_crawl_run(**context):
    # Insert into raw.crawl_runs and return crawl_run_id
    pass


def validate_raw_ingestion(**context):
    # Check crawl_run_id produced records
    pass


def notify_failure(context):
    # Send notification or log failure summary
    pass


default_args = {
    "owner": "artio-data",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="artio_daily_art_pipeline",
    default_args=default_args,
    start_date=datetime(2026, 1, 1),
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
    tags=["artio", "scrapy", "dbt", "superset"],
    on_failure_callback=notify_failure,
) as dag:

    start = EmptyOperator(task_id="start")

    create_run = PythonOperator(
        task_id="create_crawl_run",
        python_callable=create_crawl_run,
    )

    run_spider = BashOperator(
        task_id="run_scrapy_spider",
        bash_command="""
        cd /opt/artio_crawlers && \
        scrapy crawl {{ dag_run.conf.get('spider_name', 'metmuseum_artworks') }} \
          -a crawl_run_id={{ ti.xcom_pull(task_ids='create_crawl_run') }} \
          -a max_records={{ dag_run.conf.get('max_records', 500) }} \
          -a max_pages={{ dag_run.conf.get('max_pages', 10) }}
        """,
    )

    validate = PythonOperator(
        task_id="validate_raw_ingestion",
        python_callable=validate_raw_ingestion,
    )

    dbt_deps = BashOperator(
        task_id="dbt_deps",
        bash_command="cd /opt/artio_dbt && dbt deps",
    )

    dbt_seed = BashOperator(
        task_id="dbt_seed",
        bash_command="cd /opt/artio_dbt && dbt seed --profiles-dir /opt/artio_dbt",
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command="cd /opt/artio_dbt && dbt run --profiles-dir /opt/artio_dbt --select {{ dag_run.conf.get('dbt_select', '+mart_artworks') }}",
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command="cd /opt/artio_dbt && dbt test --profiles-dir /opt/artio_dbt --select {{ dag_run.conf.get('dbt_select', '+mart_artworks') }}",
    )

    refresh_superset = EmptyOperator(task_id="refresh_superset")

    notify_success = EmptyOperator(task_id="notify_success")

    end = EmptyOperator(task_id="end")

    start >> create_run >> run_spider >> validate >> dbt_deps >> dbt_seed >> dbt_run >> dbt_test >> refresh_superset >> notify_success >> end
```

---

## 19. MVP Acceptance Criteria

The Airflow layer is ready when:

```text
[ ] Airflow starts successfully in Docker Compose
[ ] artio_daily_art_pipeline appears in Airflow UI
[ ] DAG can be triggered manually
[ ] DAG creates a crawl_run record
[ ] DAG runs metmuseum_artworks spider
[ ] DAG validates raw ingestion
[ ] DAG runs dbt seed
[ ] DAG runs dbt run
[ ] DAG runs dbt test
[ ] DAG logs success or failure clearly
[ ] Failed spider run causes DAG failure
[ ] Failed critical dbt test causes DAG failure
```

---

## 20. Future DAGs

Future DAGs may include:

```text
artio_monthly_museum_sources
artio_weekly_marketplace_sources
artio_reprocess_raw_records
artio_refresh_dbt_only
artio_superset_refresh_only
artio_quality_report
artio_duplicate_detection
artio_image_validation
```

---

## 21. Open Questions

1. Should Airflow run Scrapy inside the Airflow worker or as a separate container?
2. Should the MVP use BashOperator, DockerOperator, or KubernetesPodOperator?
3. Should source-specific schedules be separate DAGs?
4. What notification channel should be used first?
5. Should failed records be retried automatically or only logged?
6. Should Superset refresh be active in MVP or skipped?
7. Should dry runs write to the database or only log output?

---

## 22. Next Document

Next document:

```text
Artio Integration Specification
```

