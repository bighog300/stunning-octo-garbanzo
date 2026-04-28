import pytest

airflow_models = pytest.importorskip("airflow.models")
DagBag = airflow_models.DagBag

DAG_ID = "artuk_artworks_pipeline"


def _dag():
    dag_bag = DagBag(dag_folder="/workspace/stunning-octo-garbanzo/airflow/dags", include_examples=False)
    assert not dag_bag.import_errors, f"DAG import errors: {dag_bag.import_errors}"
    dag = dag_bag.get_dag(DAG_ID)
    assert dag is not None
    return dag


def test_dag_imports_successfully():
    dag = _dag()
    assert dag.dag_id == DAG_ID


def test_spider_name_and_pool_are_correct():
    dag = _dag()
    task = dag.get_task("run_artuk_spider")

    assert "scrapy crawl artuk_artworks" in task.bash_command
    assert task.pool == "artuk_pool"
    assert task.pool_slots == 1


def test_run_task_uses_jinja_double_brace_template_values():
    dag = _dag()
    task = dag.get_task("run_artuk_spider")
    command = task.bash_command

    assert "{{ ti.xcom_pull(task_ids='create_crawl_run') }}" in command
    assert "{{ dag_run.conf.get('max_pages', 5) }}" in command
    assert "{{ dag_run.conf.get('max_records', 100) }}" in command
    assert "{{ dag_run.conf.get('full_crawl', false) }}" in command
    assert "{{ dag_run.conf.get('use_sample_data', false) }}" in command
    assert "{{ dag_run.conf.get('search_query', '') }}" in command


def test_dbt_and_view_tasks_exist():
    dag = _dag()

    for task_id in ["dbt_deps", "dbt_run", "dbt_test", "apply_app_views", "apply_superset_views"]:
        assert dag.get_task(task_id) is not None


def test_run_task_reports_blocked_outcome_to_xcom():
    dag = _dag()
    task = dag.get_task("run_artuk_spider")

    assert task.do_xcom_push is True
    assert "Art UK returned 403; source may require API/feed/permission." in task.bash_command
    assert "echo blocked" in task.bash_command
