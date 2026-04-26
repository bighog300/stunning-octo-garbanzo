# Artio Superset Dashboard Specification

## 1. Purpose

This document defines how Apache Superset is used to monitor, explore, and analyze data produced by the Artio pipeline.

Superset is **not** the end-user product (Artio is). It is an internal analytics and observability layer for:

- Pipeline health
- Data quality
- Source coverage
- Trend analysis

---

## 2. Goals

Superset dashboards should allow you to:

- Monitor crawler performance
- Detect pipeline failures early
- Identify missing or low-quality data
- Track growth of the dataset
- Explore artwork, artist, and source trends
- Support debugging and operational decisions

---

## 3. Data Sources

Superset should connect to:

```text
analytics.mart_artworks
analytics.mart_artists
analytics.mart_sources
analytics.mart_crawl_quality
raw.crawl_runs (optional)
raw.crawl_errors (optional)
```

Primary schema:

```text
analytics
```

---

## 4. Core Dashboards

## 4.1 Pipeline Health Dashboard

### Purpose

Monitor whether the pipeline is running correctly.

### Dataset

```text
analytics.mart_crawl_quality
```

### Charts

- **Crawl runs over time** (line chart)
- **Records found per run** (bar chart)
- **Records failed per run** (bar chart)
- **Error rate (%)** (line chart)
- **Last successful crawl per source** (table)

### Key Metrics

```text
records_found
records_failed
error_count
avg_quality_score
```

---

## 4.2 Data Quality Dashboard

### Purpose

Identify incomplete or low-quality records.

### Dataset

```text
analytics.mart_crawl_quality
analytics.mart_artworks
```

### Charts

- **Missing artist count over time**
- **Missing title count over time**
- **Missing image rate (%)**
- **Duplicate candidate count**
- **Average quality score over time**

### Filters

```text
source_domain
crawl_date
quality_score range
```

---

## 4.3 Artwork Explorer Dashboard

### Purpose

Explore artworks across sources.

### Dataset

```text
analytics.mart_artworks
```

### Charts

- **Artworks by source** (bar chart)
- **Artworks by medium category** (pie or bar chart)
- **Artworks by year (timeline)**
- **Top artists by artwork count**
- **Price distribution (histogram)**

### Filters

```text
artist_name
source_domain
medium_category
year range
price range
quality_score
```

---

## 4.4 Artist Overview Dashboard

### Purpose

Understand artist coverage.

### Dataset

```text
analytics.mart_artists
```

### Charts

- **Artists by nationality**
- **Artists by artwork count**
- **New artists over time**

---

## 4.5 Source Performance Dashboard

### Purpose

Compare source quality and performance.

### Dataset

```text
analytics.mart_sources
analytics.mart_crawl_quality
```

### Charts

- **Total records by source**
- **Error rate by source**
- **Duplicate rate by source**
- **Missing field rate by source**
- **Average quality score by source**

---

## 4.6 Duplicate Analysis Dashboard

### Purpose

Track duplicate candidates.

### Dataset

```text
analytics.mart_artworks
```

### Charts

- **Duplicate candidate count over time**
- **Top duplicate groups (table)**
- **Duplicate rate by source**

---

## 5. Key Metrics Definitions

| Metric | Definition |
|------|-----------|
| records_found | Total records discovered in a crawl |
| records_failed | Records that failed extraction or storage |
| error_rate | records_failed / records_found |
| missing_artist_rate | missing_artist_count / records_found |
| missing_title_rate | missing_title_count / records_found |
| duplicate_rate | duplicate_candidate_count / records_found |
| avg_quality_score | Average of quality_score across records |

---

## 6. Filters and Interactivity

All dashboards should support:

```text
source_domain filter
crawl_date filter
quality_score filter
artist filter (where applicable)
```

Global filters should be enabled for dashboards.

---

## 7. Dataset Configuration

For each dataset:

### Time Column

```text
crawl_timestamp
```

or

```text
crawl_date
```

### Default Metrics

```text
COUNT(*)
SUM(records_found)
AVG(quality_score)
```

### Default Sort

```text
crawl_timestamp DESC
```

---

## 8. Performance Considerations

To keep dashboards fast:

- Use `analytics` tables (not raw tables) where possible
- Limit dataset size with filters
- Use indexed columns (source_domain, crawl_timestamp)
- Avoid heavy joins in Superset queries

---

## 9. Access Control

Recommended roles:

```text
admin → full access
analyst → view dashboards, create charts
viewer → read-only dashboards
```

Superset should be protected behind authentication.

---

## 10. MVP Scope

For MVP, create 3 dashboards:

```text
1. Pipeline Health Dashboard
2. Data Quality Dashboard
3. Artwork Explorer Dashboard
```

---

## 11. Setup Steps

1. Connect Superset to PostgreSQL
2. Add analytics schema datasets
3. Create charts for each dataset
4. Assemble dashboards
5. Add filters
6. Save and share dashboards

---

## 12. Acceptance Criteria

Superset setup is complete when:

```text
[ ] Superset connects to PostgreSQL
[ ] analytics tables are visible
[ ] dashboards display data
[ ] filters work correctly
[ ] dashboards load within acceptable time
[ ] pipeline failures are visible
```

---

## 13. Future Enhancements

- Alerts on pipeline failures
- Scheduled dashboard reports
- Embedded dashboards inside Artio admin UI
- Advanced anomaly detection

---

## 14. Next Document

Next document:

```text
Deployment Runbook
```

