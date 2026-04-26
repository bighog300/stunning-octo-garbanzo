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
    crawl_run_id = context["ti"].xcom_pull(task_ids="create_crawl_run")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from raw.artworks where crawl_run_id = %s", (crawl_run_id,))
            count = cur.fetchone()[0]
    if count < 1:
        raise ValueError(f"No raw artwork records found for crawl_run_id={crawl_run_id}")


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
          -a max_pages={{ dag_run.conf.get('max_pages', 3) }}
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

    refresh_superset = EmptyOperator(task_id="refresh_superset")
    notify_success = EmptyOperator(task_id="notify_success")
    end = EmptyOperator(task_id="end")

    start >> create_run >> run_spider >> validate >> dbt_deps >> dbt_seed >> dbt_run >> dbt_test >> refresh_superset >> notify_success >> end
