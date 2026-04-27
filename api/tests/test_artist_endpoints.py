from contextlib import contextmanager
from datetime import datetime, timezone

import api.main as main
from starlette.routing import Match


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        sql = " ".join(query.split())
        self.conn.queries.append((sql, params))

        if "FROM app.artist_profiles" in sql and "WHERE artist_name = %s" not in sql:
            self._rows = [
                {
                    "artist_name": "Gregory Kerr",
                    "source_domain": "art.co.za",
                    "profile_url": "https://example.com/gregory-kerr",
                    "artist_bio": "bio",
                    "artwork_count": 10,
                    "last_seen": "2026-04-27T00:00:00Z",
                }
            ]
            return

        if "FROM app.artist_profiles" in sql and "WHERE artist_name = %s" in sql:
            name = params[0]
            self._row = (
                {
                    "artist_name": name,
                    "source_domain": "art.co.za",
                    "profile_url": "https://example.com/artist",
                    "artist_bio": "bio",
                    "artwork_count": 1,
                    "last_seen": "2026-04-27T00:00:00Z",
                }
                if name == "Gregory Kerr"
                else None
            )
            return

        if "information_schema.columns" in sql:
            table_name = params[1]
            if table_name == "artwork_records":
                self._rows = [
                    {"column_name": "artwork_id"},
                    {"column_name": "artwork_title"},
                    {"column_name": "image_url"},
                    {"column_name": "year_start"},
                    {"column_name": "source_url"},
                ]
            else:
                self._rows = [
                    {"column_name": "event_id"},
                    {"column_name": "event_title"},
                    {"column_name": "start_date"},
                    {"column_name": "source_url"},
                ]
            return

        if "to_regclass" in sql:
            self._row = {"relation_name": "app.artist_event_links"}
            return

        if "FROM app.artwork_records" in sql:
            self._rows = [
                {
                    "artwork_id": "id-1",
                    "artwork_title": "Artwork",
                    "image_url": "https://example.com/image.jpg",
                    "year_start": 2020,
                    "source_url": "https://example.com/a",
                }
            ]
            return

        if "FROM app.artist_event_links" in sql:
            self._rows = [
                {
                    "event_id": "e-1",
                    "event_title": "Exhibition",
                    "start_date": "2026-01-01",
                    "source_url": "https://example.com/e",
                }
            ]
            return

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row


class FakeConn:
    def __init__(self):
        self.queries = []

    def cursor(self):
        return FakeCursor(self)


@contextmanager
def fake_get_conn():
    conn = FakeConn()
    yield conn


def test_list_artists_returns_200(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    response = main.list_artists(limit=100, offset=0)
    assert isinstance(response, list)
    assert response[0]["artist_name"] == "Gregory Kerr"


def test_list_artists_with_limit_returns_200(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    response = main.list_artists(limit=5)
    assert len(response) == 1


def test_artworks_route_still_returns_data(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    response = main.list_artworks(limit=5, offset=0)
    assert isinstance(response, list)
    assert response[0]["artwork_id"] == "id-1"


def test_artist_detail_not_found_returns_404(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    try:
        main.get_artist_profile("Unknown Artist")
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 404


def test_list_artists_serializes_datetime_values(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    dt = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)

    class DictLikeRow:
        def __iter__(self):
            return iter({"artist_name": "A", "last_seen": dt}.items())

    serialized = main._serialize_rows([{"artist_name": "A", "last_seen": dt}, DictLikeRow()])
    assert serialized[0]["last_seen"] == "2026-04-27T12:00:00+00:00"
    assert serialized[1]["last_seen"] == "2026-04-27T12:00:00+00:00"


def test_artist_profile_route_returns_404_for_unknown_artist(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    from fastapi import HTTPException

    try:
        main.get_artist_profile("Unknown Artist")
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Artist not found"


def test_route_order_keeps_static_before_dynamic_routes():
    route_paths = [route.path for route in main.app.routes]
    assert route_paths.index("/api/artists") < route_paths.index("/api/artists/{artist_name}")


def test_route_resolution_uses_list_artists_handler_for_static_path():
    scope = {"type": "http", "method": "GET", "path": "/api/artists"}
    for route in main.app.router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            assert getattr(route, "name", None) == "list_artists"
            return
    assert False, "No route matched /api/artists"
