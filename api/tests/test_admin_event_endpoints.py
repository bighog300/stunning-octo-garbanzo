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

        if "FROM app.event_records" in sql and "ORDER BY crawl_timestamp" in sql:
            self._rows = [
                {
                    "event_id": "11111111-1111-1111-1111-111111111111",
                    "event_title": "Studio Talk",
                    "original_event_title": "Studio Talk",
                    "canonical_event_title": None,
                    "event_type": "talk",
                    "linked_artists": ["Alice"],
                    "venue_name": "Main Hall",
                    "city": "Cape Town",
                    "start_date": "2026-04-10",
                    "end_date": "2026-04-12",
                    "source_domain": "example.com",
                    "source_name": "Example",
                    "source_url": "https://example.com/events/1",
                    "crawl_timestamp": "2026-04-27T00:00:00Z",
                    "is_hidden": False,
                    "is_approved": False,
                    "moderation_override_exists": False,
                }
            ]
            return

        if "FROM app.event_records" in sql and "WHERE event_id = %s::uuid" in sql:
            self._row = {
                "event_id": params[0],
                "event_title": "Studio Talk",
                "original_event_title": "Studio Talk",
                "canonical_event_title": None,
                "raw_payload": {"raw": True},
                "is_hidden": False,
                "is_approved": False,
            }
            return

        if "FROM app.artist_event_links" in sql:
            self._rows = [
                {
                    "artist_activity_id": "aaa",
                    "artist_name": "Alice",
                    "artist_profile_url": "https://example.com/artists/alice",
                }
            ]
            return

        if "SELECT 1 FROM app.event_records" in sql:
            self._row = {"?column?": 1}
            return

        if "FROM app.event_moderation_overrides" in sql:
            self._row = {
                "is_hidden": False,
                "is_approved": False,
                "canonical_event_title": None,
                "event_type": None,
                "moderation_reason": None,
                "moderator_notes": None,
            }
            return

        if "INSERT INTO app.event_moderation_overrides" in sql:
            self._row = {
                "event_id": params[0],
                "is_hidden": params[1],
                "is_approved": params[2],
                "canonical_event_title": params[3],
                "event_type": params[4],
                "moderation_reason": params[5],
                "moderator_notes": params[6],
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

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True


@contextmanager
def fake_get_conn():
    yield FakeConn()


def test_list_admin_events(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    rows = main.list_admin_events(limit=20, moderation_status="all")
    assert rows[0]["event_title"] == "Studio Talk"
    assert rows[0]["original_event_title"] == "Studio Talk"


def test_get_admin_event(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    payload = main.get_admin_event("11111111-1111-1111-1111-111111111111")
    assert payload["event"]["event_title"] == "Studio Talk"
    assert payload["event"]["original_event_title"] == "Studio Talk"
    assert payload["linked_artists"][0]["artist_name"] == "Alice"


def test_patch_admin_event_moderation(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    payload = main.EventModerationPayload(
        is_hidden=True,
        is_approved=True,
        canonical_event_title="Canonical Studio Talk",
        event_type="talk",
        moderation_reason="Looks valid",
        moderator_notes="Keep visible in search",
    )
    response = main.patch_admin_event_moderation(
        "11111111-1111-1111-1111-111111111111",
        payload,
    )
    assert response["status"] == "updated"
    assert response["event_moderation"]["is_hidden"] is True
