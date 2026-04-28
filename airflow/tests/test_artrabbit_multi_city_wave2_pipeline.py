import pytest

airflow_models = pytest.importorskip("airflow.models")
DagBag = airflow_models.DagBag

DAG_ID = "artrabbit_multi_city_wave2_pipeline"
EXPECTED_CITIES = [
    "birmingham",
    "bristol",
    "leeds",
    "newcastle",
    "brighton",
    "cardiff",
    "dundee",
    "aberdeen",
]
EXPECTED_DBT_SELECTION = "stg_events mart_events stg_galleries int_gallery_normalized mart_galleries"


def _dag():
    dag_bag = DagBag(dag_folder="/workspace/stunning-octo-garbanzo/airflow/dags", include_examples=False)
    assert not dag_bag.import_errors, f"DAG import errors: {dag_bag.import_errors}"
    dag = dag_bag.get_dag(DAG_ID)
    assert dag is not None
    return dag


def test_dag_imports_successfully():
    dag = _dag()
    assert dag.dag_id == DAG_ID


def test_crawl_tasks_exist_for_all_cities():
    dag = _dag()
    task_ids = {task.task_id for task in dag.tasks}

    for city in EXPECTED_CITIES:
        assert f"crawl_{city}" in task_ids


def test_crawl_tasks_use_correct_spider_and_pool():
    dag = _dag()

    for city in EXPECTED_CITIES:
        task = dag.get_task(f"crawl_{city}")
        assert "scrapy crawl art_rabbit_events" in task.bash_command
        assert "scrapy crawl artrabbit_events" not in task.bash_command
        assert task.pool == "artrabbit_pool"
        assert task.pool_slots == 1


def test_crawl_tasks_are_chained_sequentially():
    dag = _dag()

    expected_chain = [
        "create_crawl_run",
        "crawl_birmingham",
        "crawl_bristol",
        "crawl_leeds",
        "crawl_newcastle",
        "crawl_brighton",
        "crawl_cardiff",
        "crawl_dundee",
        "crawl_aberdeen",
        "validate_raw_ingestion",
        "dbt_deps",
        "dbt_run",
        "dbt_test",
        "apply_app_views",
        "apply_superset_views",
    ]

    for upstream_task_id, downstream_task_id in zip(expected_chain, expected_chain[1:]):
        upstream = dag.get_task(upstream_task_id)
        assert downstream_task_id in upstream.downstream_task_ids


def test_dbt_run_includes_expected_models():
    dag = _dag()
    task = dag.get_task("dbt_run")

    assert EXPECTED_DBT_SELECTION in task.bash_command


def test_apply_superset_views_task_exists():
    dag = _dag()

    assert dag.get_task("apply_superset_views") is not None
