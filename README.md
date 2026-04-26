# Artio Data Pipeline Bootstrap

This is the bootstrap repository for the Artio data pipeline.

Stack:

```text
Scrapy → PostgreSQL raw schema → dbt → PostgreSQL analytics schema → Superset / Artio
```

Airflow orchestrates the workflow.

## First run (local bootstrap)

1. Copy environment defaults:

```bash
cp .env.example .env
```

Generate an Airflow Fernet key and set `AIRFLOW_FERNET_KEY` in `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

2. Start the full stack:

```bash
docker compose up -d
```

3. Run the spider manually:

```bash
docker compose exec scrapy scrapy crawl metmuseum_artworks -a max_records=25 -a max_pages=3
```

4. Run dbt (deps, seed, run, test):

```bash
docker compose exec dbt dbt deps --profiles-dir /opt/artio/dbt
docker compose exec dbt dbt seed --profiles-dir /opt/artio/dbt
docker compose exec dbt dbt run --profiles-dir /opt/artio/dbt
docker compose exec dbt dbt test --profiles-dir /opt/artio/dbt
```

5. Create app view(s) manually after dbt:

```bash
docker compose exec -T postgres psql -U postgres -d artio < infra/postgres/views/create_app_views.sql
```

## Validation checks

```bash
docker compose exec postgres psql -U postgres -d artio -c "select count(*) from raw.artworks;"
docker compose exec postgres psql -U postgres -d artio -c "select count(*) from analytics.mart_artworks;"
docker compose exec postgres psql -U postgres -d artio -c "select count(*) from app.artwork_records;"
```

## Airflow

```text
http://localhost:8080
username: admin
password: admin
```

## Superset

```text
http://localhost:8088
username: admin
password: admin
```

## Docs

Place the downloaded canvas docs inside `/docs`.
