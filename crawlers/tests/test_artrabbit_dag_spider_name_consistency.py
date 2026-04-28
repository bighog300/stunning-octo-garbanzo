from __future__ import annotations

from pathlib import Path
import re


def test_artrabbit_dag_uses_registered_spider_name() -> None:
    spider_source = Path("crawlers/artio_crawlers/spiders/artrabbit_events.py").read_text(encoding="utf-8")
    dag_source = Path("airflow/dags/artrabbit_daily_pipeline.py").read_text(encoding="utf-8")

    spider_name_match = re.search(r'^\s*name\s*=\s*"([^"]+)"', spider_source, flags=re.MULTILINE)
    dag_spider_name_match = re.search(r'^\s*SPIDER_NAME\s*=\s*"([^"]+)"', dag_source, flags=re.MULTILINE)

    assert spider_name_match is not None
    assert dag_spider_name_match is not None

    spider_name = spider_name_match.group(1)
    dag_spider_name = dag_spider_name_match.group(1)

    assert dag_spider_name == spider_name == "art_rabbit_events"
    assert "scrapy crawl {SPIDER_NAME}" in dag_source
    assert "scrapy crawl artrabbit_events" not in dag_source
    assert "{{{{ dag_run.conf.get" in dag_source
    assert re.search(r"(?<!\{)\{ dag_run\.conf\.get\([^)]*\) \}(?!\})", dag_source) is None
