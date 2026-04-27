from contextlib import contextmanager

from fastapi import HTTPException

import api.main as main


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

        if "SELECT to_regclass" in sql:
            self._row = {"relation_name": "app.artist_event_links"}
            return

        if "FROM app.artwork_records" in sql and "FILTER" in sql:
            self._row = {
                "artworks_pending_review": 7,
                "broken_or_missing_images": 2,
            }
            return

        if "FROM app.artist_profiles" in sql and "FILTER" in sql:
            self._row = {
                "artists_missing_bio": 3,
                "artists_short_bio": 4,
                "artists_poor_bio": 2,
                "artists_suspect_name": 1,
                "artists_with_manual_bio": 5,
            }
            return

        if "COUNT(*) AS artists_without_events" in sql:
            self._row = {"artists_without_events": 6}
            return

        if "FROM app.artist_profiles" in sql and "issue_reason" in sql:
            self._rows = [
                {
                    "artist_name": "Latest Work",
                    "source_domain": "art.co.za",
                    "profile_url": "https://example.com/artist",
                    "artist_bio": "short",
                    "cleaned_artist_bio": "short",
                    "bio_quality_score": 40,
                    "bio_quality_flags": ["too_short"],
                    "original_artist_bio": "",
                    "edited_bio": None,
                    "edited_by": None,
                    "edited_at": None,
                    "artwork_count": 1,
                    "last_seen": "2026-04-27T00:00:00Z",
                    "issue_reason": "suspect_artist_name",
                }
            ]
            return

        if "FROM app.artwork_records" in sql and "issue_reason" in sql:
            self._rows = [
                {
                    "artwork_id": "a-1",
                    "artwork_title": "Untitled",
                    "artist_name": "Gregory Kerr",
                    "image_url": "",
                    "source_url": "https://example.com/artwork",
                    "review_status": "pending",
                    "public_visibility": True,
                    "quality_score": 0.8,
                    "issue_reason": "pending_review",
                }
            ]
            return

        if "CREATE TABLE IF NOT EXISTS app.data_quality_flags" in sql:
            return

        if "INSERT INTO app.data_quality_flags" in sql:
            self._row = {
                "id": "11111111-1111-1111-1111-111111111111",
                "entity_type": params[0],
                "entity_id": params[1],
                "artist_name": params[2],
                "issue_type": params[3],
                "notes": params[4],
                "status": "open",
                "created_by": params[5],
                "created_at": "2026-04-27T00:00:00Z",
                "resolved_at": None,
            }
            return

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row


class FakeConn:
    def __init__(self):
        self.queries = []
        self.committed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True


@contextmanager
def fake_get_conn():
    yield FakeConn()


def test_queue_summary_endpoint_returns_expected_keys(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    summary = main.moderation_queue_summary()

    expected_keys = {
        "artworks_pending_review",
        "artists_missing_bio",
        "artists_short_bio",
        "artists_poor_bio",
        "artists_suspect_name",
        "artists_with_manual_bio",
        "artists_without_events",
        "broken_or_missing_images",
    }
    assert set(summary.keys()) == expected_keys


def test_invalid_queue_name_returns_404(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    try:
        main.moderation_queue_records("not-a-real-queue", limit=100, offset=0)
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 404


def test_queue_endpoint_clamps_limit(monkeypatch):
    captured = {}

    @contextmanager
    def tracking_conn():
        conn = FakeConn()
        original_cursor = conn.cursor

        def cursor_with_tracking():
            cur = original_cursor()
            original_execute = cur.execute

            def wrapped_execute(query, params=None):
                if "LIMIT %s OFFSET %s" in " ".join(query.split()) and params:
                    captured["params"] = params
                return original_execute(query, params)

            cur.execute = wrapped_execute
            return cur

        conn.cursor = cursor_with_tracking
        yield conn

    monkeypatch.setattr(main, "get_conn", tracking_conn)
    main.moderation_queue_records("artists-suspect-name", limit=1000)
    assert captured["params"][-2] == 500


def test_flag_creation_rejects_invalid_payload():
    payload = main.DataQualityFlagPayload(
        entity_type="artist",
        entity_id=None,
        artist_name=None,
        issue_type="missing_bio",
        notes="x",
        created_by="admin",
    )
    try:
        main.create_data_quality_flag(payload)
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400


def test_flag_creation_succeeds(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    payload = main.DataQualityFlagPayload(
        entity_type="artist",
        entity_id=None,
        artist_name="Latest Work",
        issue_type="suspect_artist_name",
        notes="Looks like navigation text.",
        created_by="craig",
    )

    response = main.create_data_quality_flag(payload)
    assert response["status"] == "created"
    assert response["flag"]["artist_name"] == "Latest Work"
