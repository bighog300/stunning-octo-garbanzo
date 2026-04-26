#!/usr/bin/env python3
"""Bootstrap Artio Superset assets via REST API.

Creates (idempotently where possible):
- Database connection for Artio Postgres
- Dataset for app.artwork_records
- Dashboard: Artio Artwork Records Overview
- Charts used by the dashboard
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_SUPERSET_URL = "http://superset:8088"
DEFAULT_SUPERSET_USERNAME = "admin"
DEFAULT_SUPERSET_PASSWORD = "admin"
DEFAULT_ARTIO_DATABASE_URI = "postgresql://postgres:postgres@postgres:5432/artio"
DATABASE_NAME = "Artio Postgres"
DATASET_SCHEMA = "app"
DATASET_TABLE = "artwork_records"
DASHBOARD_TITLE = "Artio Artwork Records Overview"


@dataclass
class SupersetClient:
    base_url: str
    username: str
    password: str
    session: requests.Session

    @classmethod
    def from_env(cls) -> "SupersetClient":
        return cls(
            base_url=os.getenv("SUPERSET_URL", DEFAULT_SUPERSET_URL).rstrip("/"),
            username=os.getenv("SUPERSET_USERNAME", DEFAULT_SUPERSET_USERNAME),
            password=os.getenv("SUPERSET_PASSWORD", DEFAULT_SUPERSET_PASSWORD),
            session=requests.Session(),
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, expected_status: tuple[int, ...] = (200,), **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(method, self._url(path), timeout=30, **kwargs)
        if response.status_code not in expected_status:
            raise RuntimeError(
                f"Superset API error {response.status_code} on {method} {path}: {response.text[:1000]}"
            )
        if response.text:
            return response.json()
        return {}

    def login(self) -> None:
        payload = {
            "username": self.username,
            "password": self.password,
            "provider": "db",
            "refresh": True,
        }
        data = self._request("POST", "/api/v1/security/login", expected_status=(200,), json=payload)
        access_token = data.get("access_token")
        if not access_token:
            raise RuntimeError("No access token returned by Superset login endpoint")
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        csrf = self._request("GET", "/api/v1/security/csrf_token/")
        csrf_token = csrf.get("result")
        if csrf_token:
            self.session.headers.update({"X-CSRFToken": csrf_token, "Referer": self.base_url})

    def get_database_by_name(self, database_name: str) -> dict[str, Any] | None:
        query = {
            "q": json.dumps({
                "filters": [{"col": "database_name", "opr": "eq", "value": database_name}],
                "page": 0,
                "page_size": 1,
            })
        }
        data = self._request("GET", "/api/v1/database/", params=query)
        result = data.get("result", [])
        return result[0] if result else None

    def create_database(self, database_name: str, sqlalchemy_uri: str) -> int:
        payload = {
            "database_name": database_name,
            "sqlalchemy_uri": sqlalchemy_uri,
            "expose_in_sqllab": True,
            "allow_ctas": False,
            "allow_cvas": False,
            "allow_dml": False,
        }
        data = self._request("POST", "/api/v1/database/", expected_status=(201,), json=payload)
        return data["id"]

    def get_dataset(self, database_id: int, schema: str, table_name: str) -> dict[str, Any] | None:
        query = {
            "q": json.dumps({
                "filters": [
                    {"col": "schema", "opr": "eq", "value": schema},
                    {"col": "table_name", "opr": "eq", "value": table_name},
                ],
                "page": 0,
                "page_size": 100,
            })
        }
        data = self._request("GET", "/api/v1/dataset/", params=query)
        result = data.get("result", [])
        for dataset in result:
            if dataset.get("schema") != schema or dataset.get("table_name") != table_name:
                continue

            dataset_database_id = dataset.get("database", {}).get("id")
            if dataset_database_id is None:
                dataset_database_id = dataset.get("database_id")
            if dataset_database_id is None:
                dataset_database_id = dataset.get("database")

            if dataset_database_id is None or dataset_database_id == database_id:
                return dataset
        return None

    def create_dataset(self, database_id: int, schema: str, table_name: str) -> int:
        payload = {
            "database": database_id,
            "schema": schema,
            "table_name": table_name,
        }
        data = self._request("POST", "/api/v1/dataset/", expected_status=(201,), json=payload)
        return data["id"]

    def get_dashboard_by_title(self, title: str) -> dict[str, Any] | None:
        query = {
            "q": json.dumps({
                "filters": [{"col": "dashboard_title", "opr": "eq", "value": title}],
                "page": 0,
                "page_size": 1,
            })
        }
        data = self._request("GET", "/api/v1/dashboard/", params=query)
        result = data.get("result", [])
        return result[0] if result else None

    def create_dashboard(self, title: str) -> int:
        data = self._request(
            "POST",
            "/api/v1/dashboard/",
            expected_status=(201,),
            json={"dashboard_title": title, "published": True},
        )
        return data["id"]

    def get_chart_by_name(self, slice_name: str, dataset_id: int) -> dict[str, Any] | None:
        query = {
            "q": json.dumps({
                "filters": [
                    {"col": "slice_name", "opr": "eq", "value": slice_name},
                    {"col": "datasource_id", "opr": "eq", "value": dataset_id},
                    {"col": "datasource_type", "opr": "eq", "value": "table"},
                ],
                "page": 0,
                "page_size": 1,
            })
        }
        data = self._request("GET", "/api/v1/chart/", params=query)
        result = data.get("result", [])
        return result[0] if result else None

    def create_chart(self, dataset_id: int, slice_name: str, viz_type: str, params: dict[str, Any], query_context: dict[str, Any]) -> int:
        payload = {
            "slice_name": slice_name,
            "viz_type": viz_type,
            "datasource_id": dataset_id,
            "datasource_type": "table",
            "params": json.dumps(params),
            "query_context": json.dumps(query_context),
        }
        data = self._request("POST", "/api/v1/chart/", expected_status=(201,), json=payload)
        return data["id"]

    def attach_charts_to_dashboard(self, dashboard_id: int, chart_ids: list[int]) -> None:
        if not chart_ids:
            return
        self._request(
            "POST",
            f"/api/v1/dashboard/{dashboard_id}/charts",
            expected_status=(200, 201),
            json={"chart_ids": chart_ids},
        )


def chart_definitions(dataset_id: int) -> list[dict[str, Any]]:
    def metric(label: str, expression: str) -> dict[str, Any]:
        return {"expressionType": "SQL", "label": label, "sqlExpression": expression}

    charts = [
        {
            "slice_name": "Total artworks KPI",
            "viz_type": "big_number_total",
            "params": {"metric": metric("total_artworks", "COUNT(*)")},
            "query_context": {
                "datasource": {"id": dataset_id, "type": "table"},
                "queries": [{"metrics": [metric("total_artworks", "COUNT(*)")], "row_limit": 1}],
            },
        },
        {
            "slice_name": "Total artists KPI",
            "viz_type": "big_number_total",
            "params": {"metric": metric("total_artists", "COUNT(DISTINCT artist_name)")},
            "query_context": {
                "datasource": {"id": dataset_id, "type": "table"},
                "queries": [{"metrics": [metric("total_artists", "COUNT(DISTINCT artist_name)")], "row_limit": 1}],
            },
        },
        {
            "slice_name": "Sources KPI",
            "viz_type": "big_number_total",
            "params": {"metric": metric("total_sources", "COUNT(DISTINCT source_domain)")},
            "query_context": {
                "datasource": {"id": dataset_id, "type": "table"},
                "queries": [{"metrics": [metric("total_sources", "COUNT(DISTINCT source_domain)")], "row_limit": 1}],
            },
        },
        {
            "slice_name": "Avg quality score KPI",
            "viz_type": "big_number_total",
            "params": {"metric": metric("avg_quality_score", "AVG(quality_score)")},
            "query_context": {
                "datasource": {"id": dataset_id, "type": "table"},
                "queries": [{"metrics": [metric("avg_quality_score", "AVG(quality_score)")], "row_limit": 1}],
            },
        },
        {
            "slice_name": "Artworks by source bar chart",
            "viz_type": "dist_bar",
            "params": {"groupby": ["source_domain"], "metrics": [metric("artwork_count", "COUNT(*)")], "row_limit": 20},
            "query_context": {
                "datasource": {"id": dataset_id, "type": "table"},
                "queries": [{"columns": ["source_domain"], "metrics": [metric("artwork_count", "COUNT(*)")], "orderby": [[metric("artwork_count", "COUNT(*)"), False]], "row_limit": 20}],
            },
        },
        {
            "slice_name": "Records by review status pie chart",
            "viz_type": "pie",
            "params": {"groupby": ["review_status"], "metric": metric("record_count", "COUNT(*)"), "row_limit": 20},
            "query_context": {
                "datasource": {"id": dataset_id, "type": "table"},
                "queries": [{"columns": ["review_status"], "metrics": [metric("record_count", "COUNT(*)")], "row_limit": 20}],
            },
        },
        {
            "slice_name": "Top artists by artwork count bar chart",
            "viz_type": "dist_bar",
            "params": {"groupby": ["artist_name"], "metrics": [metric("artwork_count", "COUNT(*)")], "row_limit": 15},
            "query_context": {
                "datasource": {"id": dataset_id, "type": "table"},
                "queries": [{"columns": ["artist_name"], "metrics": [metric("artwork_count", "COUNT(*)")], "orderby": [[metric("artwork_count", "COUNT(*)"), False]], "row_limit": 15}],
            },
        },
        {
            "slice_name": "Missing fields by source table",
            "viz_type": "table",
            "params": {
                "groupby": ["source_domain"],
                "metrics": [
                    metric("records", "COUNT(*)"),
                    metric("missing_artist", "SUM(CASE WHEN artist_name IS NULL OR artist_name = '' THEN 1 ELSE 0 END)"),
                    metric("missing_title", "SUM(CASE WHEN artwork_title IS NULL OR artwork_title = '' THEN 1 ELSE 0 END)"),
                    metric("missing_image", "SUM(CASE WHEN image_url IS NULL OR image_url = '' THEN 1 ELSE 0 END)"),
                ],
            },
            "query_context": {
                "datasource": {"id": dataset_id, "type": "table"},
                "queries": [{"columns": ["source_domain"], "metrics": [
                    metric("records", "COUNT(*)"),
                    metric("missing_artist", "SUM(CASE WHEN artist_name IS NULL OR artist_name = '' THEN 1 ELSE 0 END)"),
                    metric("missing_title", "SUM(CASE WHEN artwork_title IS NULL OR artwork_title = '' THEN 1 ELSE 0 END)"),
                    metric("missing_image", "SUM(CASE WHEN image_url IS NULL OR image_url = '' THEN 1 ELSE 0 END)"),
                ], "row_limit": 100}],
            },
        },
        {
            "slice_name": "Quality score distribution histogram",
            "viz_type": "histogram",
            "params": {"all_columns_x": "quality_score", "row_limit": 10000},
            "query_context": {
                "datasource": {"id": dataset_id, "type": "table"},
                "queries": [{"columns": ["quality_score"], "row_limit": 10000}],
            },
        },
        {
            "slice_name": "Artwork review table",
            "viz_type": "table",
            "params": {
                "all_columns": [
                    "artwork_id",
                    "artist_name",
                    "artwork_title",
                    "source_domain",
                    "quality_score",
                    "review_status",
                    "reviewed_at",
                ],
                "row_limit": 100,
                "order_desc": True,
                "orderby": [["reviewed_at", False]],
            },
            "query_context": {
                "datasource": {"id": dataset_id, "type": "table"},
                "queries": [{"columns": [
                    "artwork_id",
                    "artist_name",
                    "artwork_title",
                    "source_domain",
                    "quality_score",
                    "review_status",
                    "reviewed_at",
                ], "orderby": [["reviewed_at", False]], "row_limit": 100}],
            },
        },
    ]
    return charts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap Artio Superset dashboard")
    parser.add_argument(
        "--manual-only",
        action="store_true",
        help="Skip API chart creation and only print manual SQL setup references.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database_uri = os.getenv("ARTIO_DATABASE_URI", DEFAULT_ARTIO_DATABASE_URI)

    client = SupersetClient.from_env()
    print(f"Connecting to Superset at {client.base_url} as {client.username}")
    client.login()

    database = client.get_database_by_name(DATABASE_NAME)
    if database:
        database_id = database["id"]
        print(f"Database exists: {DATABASE_NAME} (id={database_id})")
    else:
        database_id = client.create_database(DATABASE_NAME, database_uri)
        print(f"Created database: {DATABASE_NAME} (id={database_id})")

    dataset = client.get_dataset(database_id=database_id, schema=DATASET_SCHEMA, table_name=DATASET_TABLE)
    if dataset:
        dataset_id = dataset["id"]
        print(f"Dataset exists: {DATASET_SCHEMA}.{DATASET_TABLE} (id={dataset_id})")
    else:
        dataset_id = client.create_dataset(database_id=database_id, schema=DATASET_SCHEMA, table_name=DATASET_TABLE)
        print(f"Created dataset: {DATASET_SCHEMA}.{DATASET_TABLE} (id={dataset_id})")

    dashboard = client.get_dashboard_by_title(DASHBOARD_TITLE)
    if dashboard:
        dashboard_id = dashboard["id"]
        print(f"Dashboard exists: {DASHBOARD_TITLE} (id={dashboard_id})")
    else:
        dashboard_id = client.create_dashboard(DASHBOARD_TITLE)
        print(f"Created dashboard: {DASHBOARD_TITLE} (id={dashboard_id})")

    if args.manual_only:
        print("Manual-only mode selected; skipping chart API creation.")
        print("Use superset/artio_dashboard_queries.sql for chart SQL and manual setup.")
        return 0

    chart_ids: list[int] = []
    failed_charts: list[str] = []

    for chart_def in chart_definitions(dataset_id):
        slice_name = chart_def["slice_name"]
        existing = client.get_chart_by_name(slice_name=slice_name, dataset_id=dataset_id)
        if existing:
            chart_id = existing["id"]
            print(f"Chart exists: {slice_name} (id={chart_id})")
            chart_ids.append(chart_id)
            continue

        try:
            chart_id = client.create_chart(
                dataset_id=dataset_id,
                slice_name=slice_name,
                viz_type=chart_def["viz_type"],
                params=chart_def["params"],
                query_context=chart_def["query_context"],
            )
            print(f"Created chart: {slice_name} (id={chart_id})")
            chart_ids.append(chart_id)
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: Failed to create chart '{slice_name}': {exc}")
            failed_charts.append(slice_name)

    if chart_ids:
        try:
            client.attach_charts_to_dashboard(dashboard_id, chart_ids)
            print(f"Attached {len(chart_ids)} chart(s) to dashboard id={dashboard_id}")
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: Failed to attach charts to dashboard: {exc}")

    if failed_charts:
        print("\nSome charts could not be created via API (often due to Superset version differences).")
        print("Use superset/artio_dashboard_queries.sql and create those charts manually in UI:")
        for name in failed_charts:
            print(f"- {name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
