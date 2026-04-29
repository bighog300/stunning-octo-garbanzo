import pytest

airflow_models = pytest.importorskip("airflow.models")
DagBag = airflow_models.DagBag

DAG_ID = "artrabbit_wales_pipeline"
EXPECTED_CITIES = ["cardiff", "swansea", "newport", "bangor", "wrexham"]
EXPECTED_DBT_SELECTION = "stg_events mart_events stg_galleries int_gallery_normalized mart_galleries"


class _FakeCursor:
    def __init__(self, counts, city_counts=None):
        self.counts = list(counts)
        self.city_counts = city_counts or []
        self.calls = 0
        self.executed_queries = []

    def execute(self, query, params):
        self.calls += 1
        self.executed_queries.append(query)

    def fetchone(self):
        return (self.counts[self.calls - 1],)

    def fetchall(self):
        return self.city_counts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _run_validate(monkeypatch, counts, crawl_run_id="run-test", city_counts=None):
    from airflow.dags import artrabbit_wales_pipeline as pipeline

    fake_cursor = _FakeCursor(counts=counts, city_counts=city_counts)
    monkeypatch.setattr(pipeline, "_conn", lambda: _FakeConn(fake_cursor))
    ti = type("TI", (), {"xcom_pull": lambda self, task_ids: crawl_run_id})()
    pipeline.validate_raw_ingestion(ti=ti)
    return fake_cursor


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


def test_crawl_tasks_use_static_city_args_and_no_broken_templates():
    dag = _dag()

    expected_city_args = {
        "cardiff": ("united-kingdom", 12, 400),
        "swansea": ("united-kingdom", 8, 250),
        "newport": ("united-kingdom", 6, 200),
        "bangor": ("united-kingdom", 5, 150),
        "wrexham": ("united-kingdom", 5, 150),
    }

    for city in EXPECTED_CITIES:
        country, max_pages, max_records = expected_city_args[city]
        task = dag.get_task(f"crawl_{city}")
        command = task.bash_command

        assert f"-a city={city}" in command
        assert f"-a country={country}" in command
        assert f"-a max_pages={max_pages}" in command
        assert f"-a max_records={max_records}" in command
        assert "-a full_crawl=True" in command
        assert "-a use_sample_data=False" in command

        assert "{ dag_run.conf.get(" not in command
        assert "{ ti.xcom_pull(" not in command


def test_crawl_tasks_are_chained_sequentially():
    dag = _dag()

    expected_chain = [
        "create_crawl_run",
        "crawl_cardiff",
        "crawl_swansea",
        "crawl_newport",
        "crawl_bangor",
        "crawl_wrexham",
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


def test_validate_raw_ingestion_passes_with_strict_events_and_recent_galleries(monkeypatch):
    fake_cursor = _run_validate(
        monkeypatch,
        counts=[3, 5, 2],
        crawl_run_id="run-123",
        city_counts=[("cardiff", 3), ("swansea", 2)],
    )
    gallery_query = fake_cursor.executed_queries[2]
    assert "from raw.galleries" in gallery_query
    assert "crawl_run_id" not in gallery_query


def test_validate_raw_ingestion_passes_with_recent_event_fallback_and_recent_galleries(monkeypatch):
    _run_validate(
        monkeypatch,
        counts=[0, 4, 1],
        crawl_run_id="run-456",
        city_counts=[("cardiff", 2), ("newport", 2)],
    )


def test_validate_raw_ingestion_fails_when_both_event_counts_zero(monkeypatch):
    from airflow.dags import artrabbit_wales_pipeline as pipeline

    with pytest.raises(ValueError, match="Expected at least 1 artrabbit.com event row"):
        _run_validate(
            monkeypatch,
            counts=[0, 0, 3],
            crawl_run_id="run-789",
            city_counts=[],
        )


def test_validate_raw_ingestion_fails_when_recent_gallery_count_zero(monkeypatch):
    with pytest.raises(ValueError, match="Expected at least 1 recent artrabbit.com gallery row"):
        _run_validate(
            monkeypatch,
            counts=[2, 5, 0],
            crawl_run_id="run-999",
            city_counts=[("cardiff", 5)],
        )
