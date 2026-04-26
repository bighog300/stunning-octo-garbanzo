# Artio Deployment Runbook

## 1. Purpose

This runbook defines how to deploy, run, and operate the Artio data pipeline:

```text
Scrapy + Airflow + dbt + PostgreSQL + Superset + Artio
```

It covers:

- Local setup
- Production deployment
- Environment configuration
- Operations
- Troubleshooting

---

## 2. Architecture Overview

```text
Docker Compose (MVP)

Services:
- postgres
- airflow-webserver
- airflow-scheduler
- airflow-worker (optional)
- scrapy container
- dbt container
- superset
- nginx (optional)
```

---

## 3. Prerequisites

### Required

```text
Docker
Docker Compose
Git
Python (optional local dev)
```

### Optional

```text
Makefile
.env file management
Reverse proxy (nginx)
```

---

## 4. Environment Variables

Create `.env` file:

```env
POSTGRES_DB=artio
POSTGRES_USER=artio_user
POSTGRES_PASSWORD=secure_password
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

AIRFLOW__CORE__EXECUTOR=LocalExecutor
AIRFLOW__CORE__FERNET_KEY=your_fernet_key
AIRFLOW__WEBSERVER__SECRET_KEY=your_secret

DBT_PROFILES_DIR=/opt/artio_dbt

SUPERSET_SECRET_KEY=your_superset_secret

ARTIO_ENV=development
```

---

## 5. Docker Compose Setup

### 5.1 Start services

```bash
docker compose up -d
```

### 5.2 Initialize Airflow

```bash
docker compose run airflow-webserver airflow db init
```

Create admin user:

```bash
docker compose run airflow-webserver airflow users create \
  --username admin \
  --password admin \
  --firstname Admin \
  --lastname User \
  --role Admin \
  --email admin@example.com
```

---

## 6. Database Setup

Connect to PostgreSQL:

```bash
docker exec -it postgres psql -U artio_user -d artio
```

Create schemas:

```sql
CREATE SCHEMA raw;
CREATE SCHEMA analytics;
CREATE SCHEMA app;
```

---

## 7. Scrapy Setup

Run spider locally:

```bash
docker exec -it scrapy-container \
  scrapy crawl metmuseum_artworks -a max_records=50
```

Verify:

```sql
SELECT COUNT(*) FROM raw.artworks;
```

---

## 8. dbt Setup

Run dbt:

```bash
docker exec -it dbt-container bash
cd /opt/artio_dbt

dbt deps
dbt seed
dbt run
dbt test
```

Verify:

```sql
SELECT COUNT(*) FROM analytics.mart_artworks;
```

---

## 9. Airflow Setup

Access UI:

```text
http://localhost:8080
```

Trigger DAG:

```bash
airflow dags trigger artio_daily_art_pipeline
```

---

## 10. Superset Setup

Access UI:

```text
http://localhost:8088
```

Steps:

```text
Add database connection
Select PostgreSQL
Add analytics schema
Create datasets
Build dashboards
```

---

## 11. Artio App Connection

Backend config:

```env
DATABASE_URL=postgresql://artio_user:password@postgres:5432/artio
```

Ensure Artio reads from:

```text
app.artwork_records
```

---

## 12. Deployment Steps (MVP)

```text
1. Clone repositories
2. Configure .env
3. Run docker compose up
4. Initialize Airflow
5. Create schemas
6. Run Scrapy spider
7. Run dbt
8. Start Airflow DAG
9. Configure Superset
10. Connect Artio app
```

---

## 13. Monitoring

Check:

```text
Airflow DAG runs
raw.crawl_runs table
analytics.mart_crawl_quality
Superset dashboards
```

---

## 14. Backup Strategy

Minimum:

```bash
docker exec postgres pg_dump -U artio_user artio > backup.sql
```

Schedule daily backups.

---

## 15. Troubleshooting

### No records in DB

```text
Check Scrapy logs
Check selectors
Check site blocking
```

### dbt failure

```text
Run dbt debug
Check database connection
Inspect failing model
```

### Airflow DAG fails

```text
Check task logs
Check environment variables
Check container health
```

### Superset empty

```text
Check dataset connection
Check SQL queries
Check schema permissions
```

---

## 16. Production Upgrade Path

Move to:

```text
Managed PostgreSQL
Separate worker containers
Kubernetes or ECS
Reverse proxy with HTTPS
Central logging
Alerting system
```

---

## 17. Acceptance Criteria

Deployment is successful when:

```text
[ ] All containers running
[ ] Airflow DAG runs successfully
[ ] Scrapy writes data
[ ] dbt builds marts
[ ] Superset dashboards show data
[ ] Artio reads records
```

---

## 18. Next Document

```text
Crawling & Compliance Policy
```

