from __future__ import annotations

from datetime import datetime, timedelta
import logging
import os
import uuid

import psycopg2
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator


SOURCE_DOMAIN = "artrabbit.com"
SPIDER_NAME = "art_rabbit_events"
LOGGER = logging.getLogger(__name__)


CITY_CONFIGS = [
    {"city": "birmingham", "country": "united-kingdom", "max_pages": 15, "max_records": 500},
    {"city": "bristol", "country": "united-kingdom", "max_pages": 15, "max_records": 500},
    {"city": "leeds", "country": "united-kingdom", "max_pages": 12, "max_records": 400},
    {"city": "newcastle", "country": "united-kingdom", "max_pages": 12, "max_records": 400},
    {"city": "brighton", "country": "united-kingdom", "max_pages": 12, "max_records": 400},
    {"city": "cardiff", "country": "united-kingdom", "max_pages": 10, "max_records": 300},
    {"city": "dundee", "country": "united-kingdom", "max_pages": 8, "max_records": 250},
    {"city": "aberdeen", "country": "united-kingdom", "max_pages": 8, "max_records": 250},
]


DEFAULT_ARGS = {
    "owner": "artio-data",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=15),
}


def _conn():
    return psycopg2.connect(
        host=os.getenv("ARTIO_POSTGRES_HOST", "postgres"),
        port=os.getenv("ARTIO_POSTGRES_PORT", "5432"),
        dbname=os.getenv("ARTIO_POSTGRES_DB", "artio"),
        user=os.getenv("ARTIO_POSTGRES_USER", "artio"),
        password=os.getenv("ARTIO_POSTGRES_PASSWORD", "artio"),
    )


def create_crawl_run(**context):
    crawl_run_id = str(uuid.uuid4())
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                insert into raw.crawl_runs (id, source_name, spider_name, run_status, started_at, airflow_dag_id, airflow_task_id)
                values (%s, %s, %s, 'started', now(), %s, %s)
                ''',
                (
                    crawl_run_id,
                    "ArtRabbit",
                    SPIDER_NAME,
                    context["dag"].dag_id,
                    context["task"].task_id,
                ),
            )
    return crawl_run_id


def validate_raw_ingestion(**context):
    execution_date = context.get("execution_date")
    if execution_date is None:
        raise ValueError("execution_date is required for Wave 2 ingestion validation")

    configured_cities = [c["city"].lower() for c in CITY_CONFIGS]

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select count(*)
                from raw.events
                where source_domain = %s
                  and crawl_timestamp >= %s
                  and lower(city) = any(%s)
                """,
                (SOURCE_DOMAIN, execution_date, configured_cities),
            )
            strict_total_events = cur.fetchone()[0]

            cur.execute(
                """
                select count(*)
                from raw.events
                where source_domain = %s
                  and crawl_timestamp >= now() - interval '1 day'
                  and lower(city) = any(%s)
                """,
                (SOURCE_DOMAIN, configured_cities),
            )
            recent_total_events = cur.fetchone()[0]

            cur.execute(
                """
                select lower(city), count(*)
                from raw.events
                where source_domain = %s
                  and crawl_timestamp >= now() - interval '1 day'
                  and lower(city) = any(%s)
                group by lower(city)
                """,
                (SOURCE_DOMAIN, configured_cities),
            )
            city_count_rows = cur.fetchall()

    total_events = strict_total_events if strict_total_events > 0 else recent_total_events
    city_counts = {city: 0 for city in configured_cities}
    city_counts.update({row[0]: row[1] for row in city_count_rows if row[0] in city_counts})
    cities_with_records = [city for city, count in city_counts.items() if count > 0]

    LOGGER.info(
        "ArtRabbit wave2 raw ingestion diagnostics: execution_date=%s strict_total_events=%s recent_total_events=%s total_events=%s cities_with_records=%s/%s city_counts=%s",
        execution_date,
        strict_total_events,
        recent_total_events,
        total_events,
        len(cities_with_records),
        len(configured_cities),
        city_counts,
    )

    if total_events == 0:
        raise ValueError(f"Expected > 0 new {SOURCE_DOMAIN} event rows, found 0")
    if not cities_with_records:
        raise ValueError(f"Expected at least 1 configured Wave 2 city with records, found none: {city_counts}")

    return {"total_events": total_events, "city_counts": city_counts}


# Create the crawl pool once in Airflow:
# airflow pools set artrabbit_pool 1 "Rate-limited ArtRabbit crawl pool"
with DAG(
    dag_id="artrabbit_multi_city_wave2_pipeline",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
    max_active_tasks=2,
    tags=["artio", "scrapy", "dbt", "superset", "artrabbit"],
) as dag:
    start = EmptyOperator(task_id="start")

    create_run = PythonOperator(
        task_id="create_crawl_run",
        python_callable=create_crawl_run,
    )

    crawl_tasks = {}
    for city_config in CITY_CONFIGS:
        city = city_config["city"]
        crawl_tasks[city] = BashOperator(
            task_id=f"crawl_{city}",
            pool="artrabbit_pool",
            pool_slots=1,
            bash_command=f"""
            cd /opt/artio/crawlers
            scrapy crawl {SPIDER_NAME} \\
              -a crawl_run_id={{{{ ti.xcom_pull(task_ids='create_crawl_run') }}}} \\
              -a city={city_config['city']} \\
              -a country={city_config['country']} \\
              -a full_crawl=True \\
              -a max_pages={city_config['max_pages']} \\
              -a max_records={city_config['max_records']} \\
              -a use_sample_data=False
            """,
        )

    validate = PythonOperator(
        task_id="validate_raw_ingestion",
        python_callable=validate_raw_ingestion,
    )

    dbt_deps = BashOperator(
        task_id="dbt_deps",
        bash_command="cd /opt/artio/dbt && dbt deps --profiles-dir /opt/artio/dbt",
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command="cd /opt/artio/dbt && dbt run --profiles-dir /opt/artio/dbt --select stg_events stg_galleries int_gallery_normalized int_artist_normalized stg_event_artist_candidates int_event_artist_matches mart_event_artists mart_events mart_galleries",
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command="cd /opt/artio/dbt && dbt test --profiles-dir /opt/artio/dbt --select stg_events stg_galleries mart_events mart_galleries",
    )

    apply_app_views = BashOperator(
        task_id="apply_app_views",
        bash_command="""
        export PGPASSWORD=\"${ARTIO_POSTGRES_PASSWORD}\" && \\
        psql -v ON_ERROR_STOP=1 \\
          -h \"${ARTIO_POSTGRES_HOST}\" \\
          -p \"${ARTIO_POSTGRES_PORT}\" \\
          -U \"${ARTIO_POSTGRES_USER}\" \\
          -d \"${ARTIO_POSTGRES_DB}\" \\
          -f /opt/artio/infra/postgres/views/create_app_views.sql
        """,
    )

    apply_superset_views = BashOperator(
        task_id="apply_superset_views",
        bash_command="""
        export PGPASSWORD=\"${ARTIO_POSTGRES_PASSWORD}\" && \\
        psql -v ON_ERROR_STOP=1 \\
          -h \"${ARTIO_POSTGRES_HOST}\" \\
          -p \"${ARTIO_POSTGRES_PORT}\" \\
          -U \"${ARTIO_POSTGRES_USER}\" \\
          -d \"${ARTIO_POSTGRES_DB}\" \\
          -f /opt/artio/infra/postgres/views/create_superset_views.sql
        """,
    )

    end = EmptyOperator(task_id="end")

    (
        start
        >> create_run
        >> crawl_tasks["birmingham"]
        >> crawl_tasks["bristol"]
        >> crawl_tasks["leeds"]
        >> crawl_tasks["newcastle"]
        >> crawl_tasks["brighton"]
        >> crawl_tasks["cardiff"]
        >> crawl_tasks["dundee"]
        >> crawl_tasks["aberdeen"]
        >> validate
        >> dbt_deps
        >> dbt_run
        >> dbt_test
        >> apply_app_views
        >> apply_superset_views
        >> end
    )
