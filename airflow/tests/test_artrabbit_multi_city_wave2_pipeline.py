import re

import pytest

airflow_models = pytest.importorskip("airflow.models")
DagBag = airflow_models.DagBag

DAG_ID = "artrabbit_multi_city_wave2_pipeline"
EXPECTED_CITY_CONFIGS = {
    "birmingham": {"country": "united-kingdom", "max_pages": 15, "max_records": 500},
    "bristol": {"country": "united-kingdom", "max_pages": 15, "max_records": 500},
    "leeds": {"country": "united-kingdom", "max_pages": 12, "max_records": 400},
    "newcastle": {"country": "united-kingdom", "max_pages": 12, "max_records": 400},
    "brighton": {"country": "united-kingdom", "max_pages": 12, "max_records": 400},
    "cardiff": {"country": "united-kingdom", "max_pages": 10, "max_records": 300},
    "dundee": {"country": "united-kingdom", "max_pages": 8, "max_records": 250},
    "aberdeen": {"country": "united-kingdom", "max_pages": 8, "max_records": 250},
}
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

    for city in EXPECTED_CITY_CONFIGS:
        assert f"crawl_{city}" in task_ids


def test_crawl_tasks_use_correct_spider_and_pool():
    dag = _dag()

    for city in EXPECTED_CITY_CONFIGS:
        task = dag.get_task(f"crawl_{city}")
        assert "scrapy crawl art_rabbit_events" in task.bash_command
        assert "scrapy crawl artrabbit_events" not in task.bash_command
        assert task.pool == "artrabbit_pool"
        assert task.pool_slots == 1


def test_crawl_tasks_have_static_city_arguments():
    dag = _dag()

    for city, cfg in EXPECTED_CITY_CONFIGS.items():
        task = dag.get_task(f"crawl_{city}")
        cmd = task.bash_command

        assert f"-a city={city}" in cmd
        assert f"-a country={cfg['country']}" in cmd
        assert f"-a max_pages={cfg['max_pages']}" in cmd
        assert f"-a max_records={cfg['max_records']}" in cmd
        assert "-a full_crawl=True" in cmd
        assert "-a use_sample_data=False" in cmd


def test_crawl_tasks_do_not_contain_malformed_single_brace_templates():
    dag = _dag()

    malformed_patterns = [
        r"\{\s*dag_run\.conf\.get\(",
        r"\{\s*ti\.xcom_pull\(",
    ]

    for city in EXPECTED_CITY_CONFIGS:
        task = dag.get_task(f"crawl_{city}")
        cmd = task.bash_command

        for pattern in malformed_patterns:
            assert re.search(pattern, cmd) is None


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
