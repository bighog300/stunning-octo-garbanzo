#!/usr/bin/env python3
"""Bootstrap Artist Profile Superset assets via REST API.

Creates (idempotently where possible):
- Database connection for Artio Postgres
- Dataset for app.artist_profiles
- Virtual dataset artwork_gallery
- Dashboard: Artist Profile
- Charts used by the dashboard
- Native filter on artist_name
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_SUPERSET_URL = "http://superset:8088"
DEFAULT_SUPERSET_USERNAME = "admin"
DEFAULT_SUPERSET_PASSWORD = "admin"
DEFAULT_ARTIO_DATABASE_URI = "postgresql://postgres:postgres@postgres:5432/artio"
DATABASE_NAME = "Artio Postgres"
DASHBOARD_TITLE = "Artist Profile"

ARTIST_PROFILE_SCHEMA = "app"
ARTIST_PROFILE_TABLE = "artist_profiles"

ARTWORK_GALLERY_SCHEMA = "app"
ARTWORK_GALLERY_TABLE = "artwork_gallery"
ARTWORK_GALLERY_SQL = """
select
  artist_name,
  artwork_title,
  image_url,
  concat('<img src="', image_url, '" width="120"/>') as thumbnail,
  source_url,
  quality_score,
  review_status
from app.artwork_records
where source_domain='art.co.za'
""".strip()


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
            "q": json.dumps(
                {
                    "filters": [{"col": "database_name", "opr": "eq", "value": database_name}],
                    "page": 0,
                    "page_size": 1,
                }
            )
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
            "q": json.dumps(
                {
                    "filters": [{"col": "table_name", "opr": "eq", "value": table_name}],
                    "page": 0,
                    "page_size": 100,
                }
            )
        }
        data = self._request("GET", "/api/v1/dataset/", params=query)
        result = data.get("result", [])

        for dataset in result:
            if dataset.get("table_name") != table_name:
                continue
            if dataset.get("schema") != schema:
                continue
            db = dataset.get("database")
            db_id = db.get("id") if isinstance(db, dict) else dataset.get("database_id")
            if db_id in (None, database_id):
                return dataset
        return None

    def create_dataset(self, database_id: int, schema: str, table_name: str, sql: str | None = None) -> int:
        payload: dict[str, Any] = {
            "database": database_id,
            "schema": schema,
            "table_name": table_name,
        }
        if sql is not None:
            payload["sql"] = sql
        data = self._request("POST", "/api/v1/dataset/", expected_status=(201,), json=payload)
        return data["id"]

    def get_chart_by_name(self, slice_name: str, dataset_id: int) -> dict[str, Any] | None:
        query = {
            "q": json.dumps(
                {
                    "filters": [
                        {"col": "slice_name", "opr": "eq", "value": slice_name},
                        {"col": "datasource_id", "opr": "eq", "value": dataset_id},
                        {"col": "datasource_type", "opr": "eq", "value": "table"},
                    ],
                    "page": 0,
                    "page_size": 1,
                }
            )
        }
        data = self._request("GET", "/api/v1/chart/", params=query)
        result = data.get("result", [])
        return result[0] if result else None

    def create_chart(
        self,
        dataset_id: int,
        slice_name: str,
        viz_type: str,
        params: dict[str, Any],
        query_context: dict[str, Any],
    ) -> int:
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

    def get_dashboard_by_title(self, title: str) -> dict[str, Any] | None:
        query = {
            "q": json.dumps(
                {
                    "filters": [{"col": "dashboard_title", "opr": "eq", "value": title}],
                    "page": 0,
                    "page_size": 1,
                }
            )
        }
        data = self._request("GET", "/api/v1/dashboard/", params=query)
        result = data.get("result", [])
        return result[0] if result else None

    def get_dashboard(self, dashboard_id: int) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/dashboard/{dashboard_id}").get("result", {})

    def create_dashboard(self, title: str) -> int:
        data = self._request(
            "POST",
            "/api/v1/dashboard/",
            expected_status=(201,),
            json={"dashboard_title": title, "published": True},
        )
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

    def update_dashboard_native_filter(self, dashboard_id: int, dataset_id: int) -> None:
        dashboard = self.get_dashboard(dashboard_id)
        json_metadata_raw = dashboard.get("json_metadata") or "{}"
        if isinstance(json_metadata_raw, str):
            json_metadata = json.loads(json_metadata_raw)
        else:
            json_metadata = json_metadata_raw

        native_filters = json_metadata.get("native_filter_configuration", [])
        already_exists = False
        for native_filter in native_filters:
            if native_filter.get("name") == "Artist Name":
                native_filter["targets"] = [{"datasetId": dataset_id, "column": {"name": "artist_name"}}]
                already_exists = True
                break

        if not already_exists:
            native_filters.append(
                {
                    "id": f"NATIVE_FILTER-{uuid.uuid4().hex[:10]}",
                    "name": "Artist Name",
                    "filterType": "filter_select",
                    "targets": [{"datasetId": dataset_id, "column": {"name": "artist_name"}}],
                    "controlValues": {"enableEmptyFilter": True, "multiSelect": False, "searchAllOptions": True},
                    "defaultDataMask": {"filterState": {"value": None}, "ownState": {}},
                    "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
                }
            )

        json_metadata["native_filter_configuration"] = native_filters
        self._request(
            "PUT",
            f"/api/v1/dashboard/{dashboard_id}",
            expected_status=(200,),
            json={"json_metadata": json.dumps(json_metadata)},
        )


def metric(label: str, expression: str) -> dict[str, Any]:
    return {"expressionType": "SQL", "label": label, "sqlExpression": expression}


def table_chart_definition(slice_name: str, dataset_id: int, columns: list[str], *, enable_html: bool = False) -> dict[str, Any]:
    params: dict[str, Any] = {"all_columns": columns, "row_limit": 100}
    if enable_html:
        params["allow_render_html"] = True
        params["table_cell_html"] = True

    return {
        "slice_name": slice_name,
        "dataset_id": dataset_id,
        "viz_type": "table",
        "params": params,
        "query_context": {
            "datasource": {"id": dataset_id, "type": "table"},
            "queries": [{"columns": columns, "row_limit": 100}],
        },
    }


def kpi_chart_definition(slice_name: str, dataset_id: int) -> dict[str, Any]:
    artwork_metric = metric("artwork_count", "COUNT(*)")
    return {
        "slice_name": slice_name,
        "dataset_id": dataset_id,
        "viz_type": "big_number_total",
        "params": {"metric": artwork_metric},
        "query_context": {
            "datasource": {"id": dataset_id, "type": "table"},
            "queries": [{"metrics": [artwork_metric], "row_limit": 1}],
        },
    }


def ensure_dataset(client: SupersetClient, database_id: int, schema: str, table_name: str, sql: str | None = None) -> int:
    existing = client.get_dataset(database_id=database_id, schema=schema, table_name=table_name)
    if existing:
        dataset_id = existing["id"]
        print(f"Dataset exists: {schema}.{table_name} (id={dataset_id})")
        return dataset_id

    dataset_id = client.create_dataset(database_id=database_id, schema=schema, table_name=table_name, sql=sql)
    kind = "virtual dataset" if sql else "dataset"
    print(f"Created {kind}: {schema}.{table_name} (id={dataset_id})")
    return dataset_id


def ensure_chart(client: SupersetClient, chart_def: dict[str, Any]) -> int:
    existing = client.get_chart_by_name(slice_name=chart_def["slice_name"], dataset_id=chart_def["dataset_id"])
    if existing:
        chart_id = existing["id"]
        print(f"Chart exists: {chart_def['slice_name']} (id={chart_id})")
        return chart_id

    chart_id = client.create_chart(
        dataset_id=chart_def["dataset_id"],
        slice_name=chart_def["slice_name"],
        viz_type=chart_def["viz_type"],
        params=chart_def["params"],
        query_context=chart_def["query_context"],
    )
    print(f"Created chart: {chart_def['slice_name']} (id={chart_id})")
    return chart_id


def main() -> int:
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

    artist_profiles_dataset_id = ensure_dataset(
        client,
        database_id=database_id,
        schema=ARTIST_PROFILE_SCHEMA,
        table_name=ARTIST_PROFILE_TABLE,
    )
    artwork_gallery_dataset_id = ensure_dataset(
        client,
        database_id=database_id,
        schema=ARTWORK_GALLERY_SCHEMA,
        table_name=ARTWORK_GALLERY_TABLE,
        sql=ARTWORK_GALLERY_SQL,
    )

    dashboard = client.get_dashboard_by_title(DASHBOARD_TITLE)
    if dashboard:
        dashboard_id = dashboard["id"]
        print(f"Dashboard exists: {DASHBOARD_TITLE} (id={dashboard_id})")
    else:
        dashboard_id = client.create_dashboard(DASHBOARD_TITLE)
        print(f"Created dashboard: {DASHBOARD_TITLE} (id={dashboard_id})")

    chart_definitions = [
        table_chart_definition(
            slice_name="Artist Bio table",
            dataset_id=artist_profiles_dataset_id,
            columns=["artist_name", "artwork_count", "profile_url", "artist_bio"],
        ),
        table_chart_definition(
            slice_name="Artist Artwork Gallery table",
            dataset_id=artwork_gallery_dataset_id,
            columns=["thumbnail", "artwork_title", "image_url", "source_url", "quality_score", "review_status"],
            enable_html=True,
        ),
        kpi_chart_definition(
            slice_name="Artist Artwork Count KPI",
            dataset_id=artwork_gallery_dataset_id,
        ),
    ]

    chart_ids = [ensure_chart(client, chart_def) for chart_def in chart_definitions]
    client.attach_charts_to_dashboard(dashboard_id, chart_ids)
    print(f"Attached {len(chart_ids)} chart(s) to dashboard id={dashboard_id}")

    client.update_dashboard_native_filter(dashboard_id=dashboard_id, dataset_id=artwork_gallery_dataset_id)
    print("Ensured native filter 'artist_name' exists on dashboard")

    return 0


if __name__ == "__main__":
    sys.exit(main())
