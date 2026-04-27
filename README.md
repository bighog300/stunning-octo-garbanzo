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

Offline/local fallback validation (no external network dependency):

```bash
docker compose exec scrapy scrapy crawl metmuseum_artworks -a max_records=25 -a use_sample_data=true
```

4. Run dbt (deps, seed, run, test):

```bash
docker compose exec dbt dbt deps --profiles-dir /opt/artio/dbt
docker compose exec dbt dbt seed --profiles-dir /opt/artio/dbt
docker compose exec dbt dbt run --profiles-dir /opt/artio/dbt
docker compose exec dbt dbt test --profiles-dir /opt/artio/dbt
```

5. `app.artwork_records` and `app.artist_profiles` are created as placeholder views during PostgreSQL initialization so Superset/API queries can run immediately (they return zero rows until dbt finishes and views are refreshed).

6. Replace the placeholder with the real app view(s) after dbt:

```bash
docker compose exec postgres psql -U postgres -d artio \
  -f /docker-entrypoint-initdb.d/09_apply_canonical_artist_mapping.sql
```

For an existing Postgres volume, re-apply the mounted SQL file directly inside the container:

```bash
docker compose exec postgres psql -U postgres -d artio \
  -f /docker-entrypoint-initdb.d/09_apply_canonical_artist_mapping.sql
```

## Validation checks

```bash
docker compose exec postgres psql -U postgres -d artio -c "select count(*) from raw.artworks;"
docker compose exec postgres psql -U postgres -d artio -c "select count(*) from analytics.mart_artworks;"
docker compose exec postgres psql -U postgres -d artio -c "select count(*) from app.artwork_records;"
```

Airflow DAG `refresh_app_views` runs after `dbt_test` and re-applies `infra/postgres/views/create_app_views.sql`, replacing placeholders with full definitions (including `app.artist_profiles`) backed by analytics/app models.

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

## Superset dashboard bootstrap

Copy the bootstrap assets into the Superset container volume and run the CLI:

```bash
docker compose cp superset/bootstrap_artio_dashboard.py superset:/app/superset_home/bootstrap_artio_dashboard.py
docker compose cp superset/artio_dashboard_queries.sql superset:/app/superset_home/artio_dashboard_queries.sql
docker compose exec superset python /app/superset_home/bootstrap_artio_dashboard.py
```

Environment variables read by the script (defaults shown):

```text
SUPERSET_URL=http://superset:8088
SUPERSET_USERNAME=admin
SUPERSET_PASSWORD=admin
ARTIO_DATABASE_URI=postgresql://postgres:postgres@postgres:5432/artio
```

## Reproducible Superset dashboards

Use the Superset assets CLI to keep dashboards reproducible across environments:

```bash
python scripts/superset_assets_cli.py export
python scripts/superset_assets_cli.py import --overwrite
python scripts/superset_assets_cli.py list
python scripts/superset_assets_cli.py bootstrap --overwrite
python scripts/superset_assets_cli.py bootstrap-artist-profile
```

Workflow:

1. Build/update the dashboard manually in Superset once.
2. Export assets to `superset/assets/artio_dashboards.zip`:

```bash
python scripts/superset_assets_cli.py export
```

3. Commit `superset/assets/artio_dashboards.zip` into the repository.
4. On a new environment, start Superset and import the committed zip:

```bash
python scripts/superset_assets_cli.py import --overwrite
```

`bootstrap` runs `superset/bootstrap_artio_dashboard.py` first and then imports `superset/assets/artio_dashboards.zip` when present.


## Art.co.za extraction audit (Phase 4D)

Run a non-destructive recrawl (dry-run) and compare extraction quality against current `raw.artworks` records:

```bash
python -m artio_cli.audit_artcoza_extraction --print-json
```

This command:

- samples baseline rows from `raw.artworks` where `source_domain = 'art.co.za'`,
- runs `artcoza_artworks` in `dry_run=true` mode (no raw/app writes),
- writes a before/after JSON report to `app/reports/artcoza_extraction_audit.json`.

You can also reuse a pre-generated crawl export:

```bash
python -m artio_cli.audit_artcoza_extraction --recrawl-jsonl /path/to/artcoza.jsonl
```

When running the audit inside Docker, the `api` service now includes `artio_cli` on
`PYTHONPATH=/opt/artio`:

```bash
docker compose up -d --build api
docker compose exec api python -m artio_cli.audit_artcoza_extraction --help
```

If you need to pass crawler output between `scrapy` and `api`, use the shared host-mounted
folder `./reports/tmp` (mounted at `/opt/artio/reports/tmp` in both containers):

```bash
docker compose exec scrapy cp /tmp/artcoza_artworks_new.json /opt/artio/reports/tmp/artcoza_artworks_new.json
docker compose exec api python -m artio_cli.audit_artcoza_extraction --recrawl-jsonl /opt/artio/reports/tmp/artcoza_artworks_new.json
```

## Artio moderation CLI

Use the local CLI to run and validate the moderation API + web UI:

```bash
python scripts/artio_moderation_cli.py start
python scripts/artio_moderation_cli.py health
python scripts/artio_moderation_cli.py seed-review-queue --limit 100
python scripts/artio_moderation_cli.py open
```

## Artio API: artist profile endpoints (Phase 1)

The FastAPI service now exposes artist browsing/profile endpoints backed by `app.artist_profiles`,
`app.artwork_records`, and (when available) `app.artist_event_links`.

Start/rebuild only the API service:

```bash
docker compose up -d --build api
```

Browse artists:

```bash
curl "http://localhost:8000/api/artists"
curl "http://localhost:8000/api/artists?search=william"
curl "http://localhost:8000/api/artists?source_domain=art.co.za&limit=50&offset=0"
```

Get one artist profile (URL-encode artist name as needed):

```bash
curl "http://localhost:8000/api/artists/Vincent%20van%20Gogh"
```
