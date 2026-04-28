from contextlib import contextmanager

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

        if "FROM app.gallery_records" in sql and "ORDER BY crawl_timestamp" in sql:
            self._rows = self.conn.list_rows
            return

        if "FROM app.gallery_records" in sql and "WHERE gallery_id = %s::uuid" in sql and "SELECT gallery_id FROM" not in sql:
            gallery_id = params[0]
            if gallery_id == "missing-gallery-id":
                self._row = None
                return
            self._row = {
                "gallery_id": gallery_id,
                "gallery_name": "Main Hall Gallery",
                "gallery_address": None,
                "city": "Cape Town",
                "country": "South Africa",
                "source_domain": "example.com",
                "source_url": "https://example.com/events/1",
                "linked_events": [{"event_id": "11111111-1111-1111-1111-111111111111", "event_title": "Open Studio"}],
                "linked_artists": [{"artist_name": "Alice"}],
                "is_hidden": False,
                "is_approved": False,
            }
            return

        if "SELECT gallery_id FROM app.gallery_records" in sql:
            gallery_id = params[0]
            self._row = None if gallery_id == "missing-gallery-id" else {"gallery_id": gallery_id}
            return

        if "FROM app.gallery_moderation_overrides" in sql:
            self._row = {
                "is_hidden": False,
                "is_approved": False,
                "canonical_gallery_name": None,
                "canonical_gallery_type": None,
                "canonical_address": None,
                "canonical_city": None,
                "canonical_country": None,
                "moderation_reason": None,
                "moderator_notes": None,
            }
            return

        if "INSERT INTO app.gallery_moderation_overrides" in sql:
            self._row = {
                "gallery_id": params[0],
                "is_hidden": params[1],
                "is_approved": params[2],
                "canonical_gallery_name": params[3],
                "canonical_gallery_type": params[4],
                "canonical_address": params[5],
                "canonical_city": params[6],
                "canonical_country": params[7],
                "moderation_reason": params[8],
                "moderator_notes": params[9],
                "updated_at": "2026-04-27T00:00:00Z",
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
        self.list_rows = [{
            "gallery_id": "33333333-3333-3333-3333-333333333333",
            "gallery_name": "Main Hall Gallery",
            "gallery_address": None,
            "city": "Cape Town",
            "country": "South Africa",
            "source_domain": "example.com",
            "source_url": "https://example.com/events/1",
            "linked_events": [{"event_id": "11111111-1111-1111-1111-111111111111", "event_title": "Open Studio"}],
            "linked_artists": [{"artist_name": "Alice"}],
            "is_hidden": False,
            "is_approved": False,
            "quality_score": 4,
            "quality_flags": ["missing_address"],
            "missing_address": True,
            "missing_city": False,
            "missing_country": False,
            "missing_website": False,
            "missing_linked_events": False,
            "crawl_timestamp": "2026-04-27T00:00:00Z",
        }]

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True


@contextmanager
def fake_get_conn():
    yield FakeConn()


def test_list_admin_galleries(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    rows = main.list_admin_galleries(limit=20, queue="all")
    assert rows[0]["missing_address"] is True
    assert "missing_address" in rows[0]["quality_flags"]


def test_get_admin_gallery(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    payload = main.get_admin_gallery("33333333-3333-3333-3333-333333333333")
    assert payload["gallery"]["gallery_name"] == "Main Hall Gallery"


def test_patch_admin_gallery_moderation(monkeypatch):
    holder = FakeConn()

    @contextmanager
    def _conn():
        yield holder

    monkeypatch.setattr(main, "get_conn", _conn)
    payload = main.GalleryModerationPayload(canonical_gallery_name="Main Hall", is_approved=True)
    response = main.patch_admin_gallery_moderation("33333333-3333-3333-3333-333333333333", payload)
    assert response["status"] == "updated"
    assert holder.committed is True


def test_patch_admin_galleries_bulk_moderation_collects_failures(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    payload = main.BulkGalleryModerationPayload(
        gallery_ids=["33333333-3333-3333-3333-333333333333", "missing-gallery-id"],
        updates=main.GalleryModerationPayload(is_hidden=True),
    )
    result = main.patch_admin_galleries_bulk_moderation(payload)
    assert result["updated"] == 1
    assert result["failed"][0]["gallery_id"] == "missing-gallery-id"
