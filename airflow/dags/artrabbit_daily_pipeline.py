from __future__ import annotations

from datetime import datetime, timedelta
import os
import uuid

import psycopg2
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator


SOURCE_DOMAIN = "artrabbit.com"
SPIDER_NAME = "art_rabbit_events"


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
    crawl_run_id = context["ti"].xcom_pull(task_ids="create_crawl_run")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select count(*)
                from raw.events
                where source_domain = %s and (crawl_run_id = %s or %s is null)
                """,
                (SOURCE_DOMAIN, crawl_run_id, crawl_run_id),
            )
            event_count = cur.fetchone()[0]

            cur.execute(
                """
                select count(*)
                from raw.galleries
                where source_domain = %s
                  and crawl_timestamp >= now() - interval '1 day'
                """,
                (SOURCE_DOMAIN,),
            )
            gallery_count = cur.fetchone()[0]

    if event_count < 1:
        raise ValueError(f"Expected at least 1 {SOURCE_DOMAIN} event row, found {event_count}")
    if gallery_count < 1:
        raise ValueError(f"Expected at least 1 {SOURCE_DOMAIN} gallery row, found {gallery_count}")


DEFAULT_ARGS = {
    "owner": "artio-data",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="artrabbit_daily_pipeline",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
    tags=["artio", "scrapy", "dbt", "superset", "artrabbit"],
) as dag:
    start = EmptyOperator(task_id="start")

    create_run = PythonOperator(
        task_id="create_crawl_run",
        python_callable=create_crawl_run,
    )

    run_artrabbit_spider = BashOperator(
        task_id="run_artrabbit_spider",
        bash_command=f"""
        cd /opt/artio/crawlers && scrapy crawl {SPIDER_NAME} \
          -a crawl_run_id={{ ti.xcom_pull(task_ids='create_crawl_run') }} \
          -a city={{ dag_run.conf.get('city', 'london') }} \
          -a country={{ dag_run.conf.get('country', 'united-kingdom') }} \
          -a max_pages={{ dag_run.conf.get('max_pages', 10) }} \
          -a max_records={{ dag_run.conf.get('max_records', 500) }} \
          -a full_crawl={{ dag_run.conf.get('full_crawl', false) }} \
          -a use_sample_data={{ dag_run.conf.get('use_sample_data', false) }}
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
        bash_command="cd /opt/artio/dbt && dbt run --profiles-dir /opt/artio/dbt --select stg_events stg_galleries int_events_enriched int_galleries_enriched mart_events mart_galleries",
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command="cd /opt/artio/dbt && dbt test --profiles-dir /opt/artio/dbt --select stg_events stg_galleries mart_events mart_galleries",
    )

    apply_app_views = BashOperator(
        task_id="apply_app_views",
        bash_command="""
        export PGPASSWORD=\"${ARTIO_POSTGRES_PASSWORD}\" && \
        psql -v ON_ERROR_STOP=1 \
          -h \"${ARTIO_POSTGRES_HOST}\" \
          -p \"${ARTIO_POSTGRES_PORT}\" \
          -U \"${ARTIO_POSTGRES_USER}\" \
          -d \"${ARTIO_POSTGRES_DB}\" \
          -f /opt/artio/infra/postgres/views/create_app_views.sql
        """,
    )

    apply_superset_views = BashOperator(
        task_id="apply_superset_views",
        bash_command="""
        if [ -f /opt/artio/infra/postgres/views/create_superset_views.sql ]; then
          export PGPASSWORD=\"${ARTIO_POSTGRES_PASSWORD}\" && \
          psql -v ON_ERROR_STOP=1 \
            -h \"${ARTIO_POSTGRES_HOST}\" \
            -p \"${ARTIO_POSTGRES_PORT}\" \
            -U \"${ARTIO_POSTGRES_USER}\" \
            -d \"${ARTIO_POSTGRES_DB}\" \
            -f /opt/artio/infra/postgres/views/create_superset_views.sql
        else
          echo "No superset views SQL found; skipping"
        fi
        """,
    )

    end = EmptyOperator(task_id="end")

    (
        start
        >> create_run
        >> run_artrabbit_spider
        >> validate
        >> dbt_deps
        >> dbt_run
        >> dbt_test
        >> apply_app_views
        >> apply_superset_views
        >> end
    )
