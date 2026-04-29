import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

airflow_models = pytest.importorskip("airflow.models")
DagBag = airflow_models.DagBag
pipeline_module = pytest.importorskip("airflow.dags.artrabbit_multi_city_wave2_pipeline")

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
EXPECTED_DBT_SELECTION = "stg_events stg_galleries int_gallery_normalized int_artist_normalized stg_event_artist_candidates int_event_artist_matches mart_event_artists mart_events mart_galleries"


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


def test_dbt_run_orders_artist_linking_before_mart_events():
    dag = _dag()
    cmd = dag.get_task("dbt_run").bash_command
    assert cmd.index("int_artist_normalized") < cmd.index("stg_event_artist_candidates")
    assert cmd.index("stg_event_artist_candidates") < cmd.index("int_event_artist_matches")
    assert cmd.index("int_event_artist_matches") < cmd.index("mart_event_artists")
    assert cmd.index("mart_event_artists") < cmd.index("mart_events")


def test_apply_superset_views_task_exists():
    dag = _dag()

    assert dag.get_task("apply_superset_views") is not None


class _FakeCursor:
    def __init__(self, scripted_results):
        self.scripted_results = list(scripted_results)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.calls.append((query, params))
        self._last_result = self.scripted_results.pop(0)

    def fetchone(self):
        return self._last_result

    def fetchall(self):
        return self._last_result


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


def _build_context():
    ti = MagicMock()
    ti.xcom_pull.return_value = "run-123"
    return {"ti": ti, "execution_date": "2026-04-28T19:53:32.980412+00:00"}


def _run_validate(monkeypatch, scripted_results):
    fake_cursor = _FakeCursor(scripted_results)
    monkeypatch.setattr(pipeline_module, "_conn", lambda: _FakeConn(fake_cursor))
    result = pipeline_module.validate_raw_ingestion(**_build_context())
    return result, fake_cursor


def test_validate_raw_ingestion_strict_rows_pass(monkeypatch):
    result, _ = _run_validate(monkeypatch, [(3,), (7,), [("bristol", 4), ("leeds", 3)]])
    assert result["total_events"] == 3


def test_validate_raw_ingestion_recent_fallback_passes(monkeypatch):
    result, _ = _run_validate(monkeypatch, [(0,), (5,), [("birmingham", 5)]])
    assert result["total_events"] == 5


def test_validate_raw_ingestion_mixed_city_casing_passes(monkeypatch):
    result, _ = _run_validate(monkeypatch, [(0,), (2,), [("BRISTOL".lower(), 1), ("DUNDEE".lower(), 1)]])
    assert result["city_counts"]["bristol"] == 1
    assert result["city_counts"]["dundee"] == 1


def test_validate_raw_ingestion_newcastle_zero_does_not_fail(monkeypatch):
    result, _ = _run_validate(monkeypatch, [(0,), (4,), [("cardiff", 4)]])
    assert result["city_counts"]["newcastle"] == 0
    assert result["city_counts"]["cardiff"] == 4


def test_validate_raw_ingestion_fails_when_strict_and_recent_zero(monkeypatch):
    with pytest.raises(ValueError, match=r"Expected > 0 new artrabbit\.com event rows, found 0"):
        _run_validate(monkeypatch, [(0,), (0,), []])


def test_validate_raw_ingestion_fails_when_no_configured_cities_have_records(monkeypatch):
    with pytest.raises(ValueError, match=r"Expected at least 1 configured Wave 2 city with records"):
        _run_validate(monkeypatch, [(2,), (2,), []])


def test_validate_raw_ingestion_uses_lower_city_filters_and_matching_params(monkeypatch):
    _, fake_cursor = _run_validate(monkeypatch, [(1,), (1,), [("bristol", 1)]])

    assert len(fake_cursor.calls) == 3

    strict_query, strict_params = fake_cursor.calls[0]
    recent_query, recent_params = fake_cursor.calls[1]
    city_counts_query, city_counts_params = fake_cursor.calls[2]

    assert "lower(city) = any(%s)" in strict_query
    assert "lower(city) = any(%s)" in recent_query
    assert "lower(city) = any(%s)" in city_counts_query

    assert strict_params[0] == pipeline_module.SOURCE_DOMAIN
    assert strict_params[1] == _build_context()["execution_date"]
    assert strict_params[2] == [cfg["city"] for cfg in pipeline_module.CITY_CONFIGS]

    assert recent_params[0] == pipeline_module.SOURCE_DOMAIN
    assert recent_params[1] == [cfg["city"] for cfg in pipeline_module.CITY_CONFIGS]

    assert city_counts_params[0] == pipeline_module.SOURCE_DOMAIN
    assert city_counts_params[1] == [cfg["city"] for cfg in pipeline_module.CITY_CONFIGS]


def test_validate_raw_ingestion_has_single_total_events_assignment_and_no_forbidden_patterns():
    dag_file = Path("/workspace/stunning-octo-garbanzo/airflow/dags/artrabbit_multi_city_wave2_pipeline.py")
    content = dag_file.read_text()

    assert "total_events = cur.fetchone()[0]" not in content
    assert "total_events = strict_total_events or recent_total_events" not in content
    assert content.count("total_events =") == 1
