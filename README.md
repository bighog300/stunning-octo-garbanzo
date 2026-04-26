# Artio Data Pipeline Bootstrap

This is the bootstrap repository for the Artio data pipeline.

Stack:

```text
Scrapy → PostgreSQL raw schema → dbt → PostgreSQL analytics schema → Superset / Artio
```

Airflow orchestrates the workflow.

## First run

```bash
cp .env.example .env
docker compose up -d postgres
docker compose ps
```

Verify schemas:

```bash
docker compose exec postgres psql -U postgres -d artio -c "\dn"
```

Start full stack:

```bash
docker compose up -d
```

Airflow:

```text
http://localhost:8080
username: admin
password: admin
```

Superset:

```text
http://localhost:8088
username: admin
password: admin
```

## MVP validation path

```bash
docker compose exec scrapy scrapy crawl metmuseum_artworks -a max_records=25
docker compose exec postgres psql -U postgres -d artio -c "select count(*) from raw.artworks;"
docker compose exec dbt dbt seed
docker compose exec dbt dbt run
docker compose exec dbt dbt test
docker compose exec postgres psql -U postgres -d artio -c "select count(*) from analytics.mart_artworks;"
```

## Docs

Place the downloaded canvas docs inside `/docs`.
