# Superset analytics assets (repo-managed)

This repository includes Superset-ready SQL views so dashboards can be recreated consistently across environments without editing Superset metadata tables directly.

## 1) Apply schema permissions and Superset views

From the repository root, run:

```bash
cat infra/postgres/init/11_grant_superset_schema_permissions.sql | docker compose exec -T postgres psql -U postgres -d artio
cat infra/postgres/views/create_superset_views.sql | docker compose exec -T postgres psql -U postgres -d artio
```

The first command ensures the `artio` role can manage objects inside `superset` schema (needed by Airflow's `apply_superset_views` task).

This creates/updates:

- `superset.gallery_quality_summary`
- `superset.event_quality_summary`
- `superset.moderation_summary`
- `superset.crawl_health_summary`

## 2) Add datasets in Superset UI

1. Open Superset (default: http://localhost:8088).
2. Go to **Data → Datasets → + Dataset**.
3. Select your Postgres database connection that points to `artio`.
4. For each table, set:
   - **Schema**: `superset`
   - **Table**: one of
     - `gallery_quality_summary`
     - `event_quality_summary`
     - `moderation_summary`
     - `crawl_health_summary`
5. Save each dataset.

> Tip: mark dimensions (`source_domain`, `entity_type`, `gallery_record_type`) and metrics (`total_*`, `approved`, `needs_review`, `hidden`, `raw_count`) in dataset configuration for easier chart building.

## 3) Suggested charts

### Dataset: `superset.gallery_quality_summary`

- **Stacked bar**: `source_domain` by `gallery_record_type` with `total_galleries`.
- **Stacked bar**: `source_domain` with `approved`, `needs_review`, `hidden`.
- **Table**: `source_domain` quality gaps (`missing_email`, `missing_phone`, `missing_website`, `missing_social`).
- **Line chart**: `latest_crawl` trend by `source_domain` (latest ingestion visibility).

### Dataset: `superset.event_quality_summary`

- **Bar chart**: `source_domain` with `total_events`.
- **Stacked bar**: `approved`, `needs_review`, `hidden` by `source_domain`.
- **Table**: data completeness by source (`missing_date`, `missing_venue`).
- **Big number**: average of `avg_quality_score`.

### Dataset: `superset.moderation_summary`

- **Horizontal bar**: `entity_type` with `total`.
- **Stacked bar**: `entity_type` with `approved`, `needs_review`, `hidden`.
- **Pie chart**: moderation backlog (`needs_review`) split by entity type.

### Dataset: `superset.crawl_health_summary`

- **Bar chart**: `raw_count` by `source_domain`, grouped by `entity_type`.
- **Table**: `source_domain`, `entity_type`, `raw_count`, `latest_crawl`.
- **Pivot table**: source vs entity volume monitoring.

## 4) Export/import notes for Docker Compose

Use the repo script wrappers to keep assets reproducible.

### List Superset assets

```bash
python scripts/superset_assets_cli.py list
```

### Export dashboards/charts/datasets to repo zip

```bash
python scripts/superset_assets_cli.py export --path superset/assets/artio_dashboards.zip
```

### Import dashboards/charts/datasets from repo zip

```bash
python scripts/superset_assets_cli.py import --path superset/assets/artio_dashboards.zip --overwrite
```

These commands work with the default Docker Compose service names (`superset`, `postgres`) and avoid direct edits to Superset's metadata database.
