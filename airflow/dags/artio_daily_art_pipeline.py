from __future__ import annotations

from datetime import datetime, timedelta
import os
import subprocess
import uuid

import psycopg2
from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator


def _conn():
    return psycopg2.connect(
        host=os.getenv("ARTIO_POSTGRES_HOST", "postgres"),
        port=os.getenv("ARTIO_POSTGRES_PORT", "5432"),
        dbname=os.getenv("ARTIO_POSTGRES_DB", "artio"),
        user=os.getenv("ARTIO_POSTGRES_USER", "artio"),
        password=os.getenv("ARTIO_POSTGRES_PASSWORD", "artio"),
    )


def create_crawl_run(**context):
    spider_name = context["dag_run"].conf.get("spider_name", "metmuseum_artworks") if context.get("dag_run") else "metmuseum_artworks"
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
                    "The Metropolitan Museum of Art",
                    spider_name,
                    context["dag"].dag_id,
                    context["task"].task_id,
                ),
            )
    return crawl_run_id


def validate_raw_ingestion(**context):
    dag_run = context.get("dag_run")
    min_records = dag_run.conf.get("min_records", 1) if dag_run else 1
    logical_date = dag_run.logical_date if dag_run else context["execution_date"]

    # MVP: validate by recent inserts so retries do not fail on crawl_run_id/XCom mismatch
    # when create_crawl_run and run_scrapy_spider execute in different retry attempts.
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select count(*)
                from raw.artworks
                where crawl_timestamp >= greatest(
                    %s::timestamptz,
                    now() - interval '30 minutes'
                )
                """,
                (logical_date,),
            )
            count = cur.fetchone()[0]

    print(
        "validate_raw_ingestion found %s records in raw.artworks "
        "since max(logical_date, now()-30m) with min_records=%s"
        % (count, min_records)
    )

    if count < min_records:
        raise ValueError(
            "Expected at least %s recently ingested raw.artworks records, found %s"
            % (min_records, count)
        )


default_args = {
    "owner": "artio-data",
    "depends_on_past": False,
    "retries": 1,
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
) as dag:
    start = EmptyOperator(task_id="start")

    create_run = PythonOperator(
        task_id="create_crawl_run",
        python_callable=create_crawl_run,
    )

    run_spider = BashOperator(
        task_id="run_scrapy_spider",
        bash_command="""
        cd /opt/artio/crawlers && \
        scrapy crawl {{ dag_run.conf.get('spider_name', 'metmuseum_artworks') }} \
          -a crawl_run_id={{ ti.xcom_pull(task_ids='create_crawl_run') }} \
          -a max_records={{ dag_run.conf.get('max_records', 25) }} \
          -a max_pages={{ dag_run.conf.get('max_pages', 3) }} \
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

    dbt_seed = BashOperator(
        task_id="dbt_seed",
        bash_command="cd /opt/artio/dbt && dbt seed --profiles-dir /opt/artio/dbt",
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command="cd /opt/artio/dbt && dbt run --profiles-dir /opt/artio/dbt",
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command="cd /opt/artio/dbt && dbt test --profiles-dir /opt/artio/dbt",
    )

    refresh_app_views = BashOperator(
        task_id="refresh_app_views",
        bash_command="""
        export PGPASSWORD="${ARTIO_POSTGRES_PASSWORD}" && \
        psql \
          -v ON_ERROR_STOP=1 \
          -h "${ARTIO_POSTGRES_HOST}" \
          -p "${ARTIO_POSTGRES_PORT}" \
          -U "${ARTIO_POSTGRES_USER}" \
          -d "${ARTIO_POSTGRES_DB}" \
          -f /opt/artio/infra/postgres/views/create_app_views.sql
        """,
    )

    refresh_superset = EmptyOperator(task_id="refresh_superset")
    notify_success = EmptyOperator(task_id="notify_success")
    end = EmptyOperator(task_id="end")

    start >> create_run >> run_spider >> validate >> dbt_deps >> dbt_seed >> dbt_run >> dbt_test >> refresh_app_views >> refresh_superset >> notify_success >> end
