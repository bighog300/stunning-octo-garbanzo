import pytest
from unittest.mock import MagicMock

airflow_models = pytest.importorskip("airflow.models")
DagBag = airflow_models.DagBag

DAG_ID = "axisweb_artists_pipeline"


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
    task = dag.get_task("run_axisweb_spider")

    assert "scrapy crawl axisweb_artists" in task.bash_command
    assert task.pool == "axisweb_pool"
    assert task.pool_slots == 1


def test_run_task_uses_jinja_double_brace_template_values():
    dag = _dag()
    task = dag.get_task("run_axisweb_spider")
    command = task.bash_command

    assert "{{ ti.xcom_pull(task_ids='create_crawl_run') }}" in command
    assert "{{ dag_run.conf.get('max_pages', 5) }}" in command
    assert "{{ dag_run.conf.get('max_records', 100) }}" in command
    assert "{{ dag_run.conf.get('full_crawl', false) }}" in command
    assert "{{ dag_run.conf.get('use_sample_data', false) }}" in command


def test_required_tasks_exist():
    dag = _dag()

    for task_id in [
        "create_crawl_run",
        "run_axisweb_spider",
        "validate_raw_ingestion",
        "dbt_deps",
        "dbt_run",
        "dbt_test",
        "apply_app_views",
        "apply_superset_views",
    ]:
        assert dag.get_task(task_id) is not None


def _context(crawl_run_id="run-123"):
    ti = MagicMock()
    ti.xcom_pull.return_value = crawl_run_id
    return {"ti": ti}


def _mock_conn(monkeypatch, fetch_values):
    from airflow.dags import axisweb_artists_pipeline as mod

    cur = MagicMock()
    cur.fetchone.side_effect = fetch_values

    conn_cm = MagicMock()
    conn_cm.__enter__.return_value = conn_cm
    conn_cm.__exit__.return_value = False
    conn_cm.cursor.return_value.__enter__.return_value = cur
    conn_cm.cursor.return_value.__exit__.return_value = False

    monkeypatch.setattr(mod, "_conn", lambda: conn_cm)
    return cur


def test_validate_raw_ingestion_strict_count_passes(monkeypatch):
    from airflow.dags.axisweb_artists_pipeline import validate_raw_ingestion

    cur = _mock_conn(monkeypatch, [(True, True), (3,), (7,)])

    result = validate_raw_ingestion(**_context("run-123"))

    assert result["strict_artist_count"] == 3
    assert result["recent_artist_count"] == 7
    assert result["artist_count"] == 3
    strict_query = cur.execute.call_args_list[1][0][0].lower()
    assert "crawl_run_id = %s" in strict_query


def test_validate_raw_ingestion_recent_fallback_passes(monkeypatch):
    from airflow.dags.axisweb_artists_pipeline import validate_raw_ingestion

    cur = _mock_conn(monkeypatch, [(True, True), (0,), (5,)])

    result = validate_raw_ingestion(**_context("run-123"))

    assert result["strict_artist_count"] == 0
    assert result["recent_artist_count"] == 5
    assert result["artist_count"] == 5


def test_validate_raw_ingestion_both_zero_fails(monkeypatch):
    from airflow.dags.axisweb_artists_pipeline import validate_raw_ingestion

    _mock_conn(monkeypatch, [(True, True), (0,), (0,)])

    with pytest.raises(ValueError, match="Expected at least 1 axisweb.org artist row, found 0"):
        validate_raw_ingestion(**_context("run-123"))


def test_validate_raw_ingestion_query_includes_recent_fallback(monkeypatch):
    from airflow.dags.axisweb_artists_pipeline import validate_raw_ingestion

    cur = _mock_conn(monkeypatch, [(True, True), (0,), (1,)])

    validate_raw_ingestion(**_context("run-123"))

    recent_query = cur.execute.call_args_list[2][0][0].lower()
    assert "crawl_timestamp >= now() - interval '1 day'" in recent_query
