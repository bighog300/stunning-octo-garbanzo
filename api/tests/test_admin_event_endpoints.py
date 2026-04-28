from contextlib import contextmanager

import api.main as main


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []
        self._row = None

    @property
    def connection(self):
        return self.conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        sql = " ".join(query.split())
        self.conn.queries.append((sql, params))

        if "SELECT to_regclass" in sql:
            relation = params[0]
            self._row = {"relation_name": relation if relation.endswith(("event_learned_rules", "event_moderation_corrections")) else None}
            return

        if "FROM app.event_learned_rules" in sql:
            self._rows = self.conn.learned_rules
            return

        if "FROM app.event_records" in sql and "ORDER BY crawl_timestamp" in sql:
            self._rows = self.conn.list_rows
            return

        if "FROM app.event_records" in sql and "WHERE event_id = %s::uuid" in sql and "SELECT 1" not in sql:
            event_id = params[0]
            if event_id == "missing-event-id":
                self._row = None
                return
            self._row = {
                "event_id": event_id,
                "event_title": "WORKSHOP  NIGHT!!",
                "canonical_event_title": None,
                "canonical_event_type": None,
                "event_type": None,
                "description": "artist workshop and panel",
                "source_domain": "example.com",
                "is_hidden": False,
                "is_approved": False,
                "raw_payload": {"raw": True},
            }
            return

        if "FROM information_schema.columns" in sql:
            self._rows = [{"column_name": name} for name in main.EVENT_RECORD_REQUIRED_COLUMNS]
            return

        if "FROM app.artist_event_links" in sql:
            self._rows = [{"artist_activity_id": "aaa", "artist_name": "Alice"}]
            return

        if "COUNT(*)::int AS total" in sql and "FROM app.event_records" in sql:
            self._row = {
                "total": 10,
                "approved": 3,
                "hidden": 1,
                "unmoderated": 6,
                "missing_date": 2,
                "missing_venue": 2,
                "low_quality": 4,
                "recently_crawled": 5,
            }
            return

        if "FROM app.event_moderation_overrides" in sql:
            self._row = {
                "is_hidden": False,
                "is_approved": False,
                "canonical_event_title": None,
                "event_type": None,
                "moderation_reason": self.conn.previous_reason,
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

        if "INSERT INTO app.event_moderation_corrections" in sql:
            self.conn.corrections += 1
            return

        if "INSERT INTO app.event_learned_rules" in sql:
            self.conn.learned_updates += 1
            return

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row


class FakeConn:
    def __init__(self):
        self.queries = []
        self.committed = False
        self.corrections = 0
        self.learned_updates = 0
        self.previous_reason = None
        self.learned_rules = []
        self.list_rows = [{
            "event_id": "11111111-1111-1111-1111-111111111111",
            "event_title": "WORKSHOP  NIGHT!!",
            "original_event_title": "WORKSHOP  NIGHT!!",
            "canonical_event_title": None,
            "event_type": None,
            "original_event_type": None,
            "canonical_event_type": None,
            "linked_artists": ["Alice"],
            "venue_name": "Main Hall",
            "city": "Cape Town",
            "start_date": "2026-04-10",
            "end_date": "2026-04-12",
            "source_domain": "example.com",
            "source_name": "Example",
            "source_url": "https://example.com/events/1",
            "description": "Artist workshop and panel",
            "crawl_timestamp": "2026-04-27T00:00:00Z",
            "is_hidden": False,
            "is_approved": False,
            "moderation_override_exists": False,
        }]

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True


@contextmanager
def fake_get_conn():
    yield FakeConn()


def test_type_confidence_static_rules():
    suggestion = main._suggest_event_type({"event_title": "Masterclass with artist", "description": ""}, learned_rules=[])
    assert suggestion[0] == "workshop"
    assert suggestion[1] == 0.95


def test_title_cleanup_confidence_rules():
    value, confidence, reason = main._normalize_event_title_with_confidence("  HELLO  ")
    assert value == "HELLO"
    assert confidence == 0.99
    assert "trimmed" in reason


def test_list_admin_events(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    rows = main.list_admin_events(limit=20, moderation_status="all")
    assert rows[0]["event_type_confidence"] == 0.95
    assert rows[0]["event_title_confidence"] == 0.99


def test_patch_admin_event_moderation_logs_corrections(monkeypatch):
    holder = FakeConn()

    @contextmanager
    def _conn():
        yield holder

    monkeypatch.setattr(main, "get_conn", _conn)
    payload = main.EventModerationPayload(canonical_event_title="Workshop Night", event_type="workshop")
    response = main.patch_admin_event_moderation("11111111-1111-1111-1111-111111111111", payload)
    assert response["status"] == "updated"
    assert holder.corrections >= 1


def test_patch_admin_events_bulk_moderation_logs_corrections(monkeypatch):
    holder = FakeConn()

    @contextmanager
    def _conn():
        yield holder

    monkeypatch.setattr(main, "get_conn", _conn)
    payload = main.BulkEventModerationPayload(
        event_ids=["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"],
        updates=main.EventModerationPayload(event_type="workshop"),
    )
    response = main.patch_admin_events_bulk_moderation(payload)
    assert response["updated"] == 2
    assert holder.corrections >= 1


def test_patch_admin_events_bulk_moderation_collects_failures(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    payload = main.BulkEventModerationPayload(
        event_ids=["11111111-1111-1111-1111-111111111111", "missing-event-id"],
        updates=main.EventModerationPayload(is_hidden=False, is_approved=False, event_type="talk"),
    )
    response = main.patch_admin_events_bulk_moderation(payload)
    assert response["updated"] == 1
    assert response["failed"][0]["event_id"] == "missing-event-id"


def test_bulk_moderation_has_max_limit(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    payload = main.BulkEventModerationPayload(event_ids=[f"id-{i}" for i in range(501)], updates=main.EventModerationPayload(is_hidden=True))
    try:
        main.patch_admin_events_bulk_moderation(payload)
        assert False
    except main.HTTPException as exc:
        assert exc.status_code == 400


def test_auto_apply_dry_run_does_not_write(monkeypatch):
    holder = FakeConn()

    @contextmanager
    def _conn():
        yield holder

    monkeypatch.setattr(main, "get_conn", _conn)
    monkeypatch.setattr(main, "_env_bool", lambda *_args, **_kwargs: True)
    result = main.auto_apply_event_suggestions(main.AutoApplySuggestionsPayload(dry_run=True, limit=10))
    assert result["dry_run"] is True
    assert result["would_update"] >= 1
    assert holder.corrections == 0


def test_auto_apply_writes_overrides_and_corrections(monkeypatch):
    holder = FakeConn()

    @contextmanager
    def _conn():
        yield holder

    monkeypatch.setattr(main, "get_conn", _conn)
    monkeypatch.setattr(main, "_env_bool", lambda *_args, **_kwargs: True)
    result = main.auto_apply_event_suggestions(main.AutoApplySuggestionsPayload(dry_run=False, limit=10))
    assert result["updated"] >= 1
    assert holder.corrections >= 1


def test_auto_apply_skips_approved_hidden(monkeypatch):
    holder = FakeConn()
    holder.list_rows = []

    @contextmanager
    def _conn():
        yield holder

    monkeypatch.setattr(main, "get_conn", _conn)
    monkeypatch.setattr(main, "_env_bool", lambda *_args, **_kwargs: True)
    result = main.auto_apply_event_suggestions(main.AutoApplySuggestionsPayload(dry_run=False, limit=10))
    assert result["eligible"] == 0


def test_learned_rule_confidence_update_helper():
    assert main._smoothed_confidence(accepted_count=3, support_count=5) == (3 + 2) / (5 + 4)


def test_validate_event_records_contract(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    with main.get_conn() as conn:
        missing = main.validate_event_records_contract(conn)
    assert missing == []


def test_admin_moderation_metrics(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    payload = main.get_admin_moderation_metrics()
    assert payload["events"]["total"] == 10
