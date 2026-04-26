FROM apache/airflow:2.9.3

USER root

RUN apt-get update \
    && apt-get install --no-install-recommends -y postgresql-client \
    && rm -rf /var/lib/apt/lists/*

USER airflow

RUN pip install --no-cache-dir \
    scrapy==2.11.2 \
    psycopg2-binary==2.9.9 \
    python-dotenv==1.0.1 \
    itemadapter==0.9.0 \
    dbt-postgres==1.8.2
