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

        if "FROM app.data_quality_flags" in sql and "ORDER BY created_at DESC" in sql:
            self._rows = [
                {
                    "id": "f-1",
                    "entity_type": "artist",
                    "artist_name": "Latest Work",
                    "issue_type": "suspect_artist_name",
                    "status": "open",
                }
            ]
            return

        if "UPDATE app.data_quality_flags" in sql and "SET status = 'resolved'" in sql:
            if params[2] == "missing":
                self._row = None
            else:
                self._row = {"id": params[2], "status": "resolved", "resolution_notes": params[1]}
            return

        if "UPDATE app.data_quality_flags" in sql and "SET status = 'open'" in sql:
            if params[1] == "missing":
                self._row = None
            else:
                self._row = {"id": params[1], "status": "open", "resolution_notes": params[0]}
            return

        if "WITH artist_candidates AS" in sql and "FROM app.artist_profiles" in sql:
            self._row = {"source_domain": "art.co.za"}
            return

        if "INSERT INTO app.artist_moderation_overrides" in sql:
            self._row = {
                "artist_name": params[0],
                "source_domain": params[1],
                "is_hidden": params[2],
            }
            return

        if "FROM app.artist_profiles ap" in sql and "LEFT JOIN app.artist_moderation_overrides" in sql:
            all_rows = [
                {"artist_name": "Visible Artist", "is_hidden": False},
                {"artist_name": "Latest Work", "is_hidden": True},
            ]
            include_hidden = "COALESCE(amo.is_hidden, false) = false" not in sql
            rows = all_rows if include_hidden else [row for row in all_rows if not row["is_hidden"]]
            if params and any(isinstance(param, str) and "Latest Work" in param for param in params):
                rows = [row for row in rows if row["artist_name"] == "Latest Work"]
            self._rows = rows

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


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


def test_list_flags(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    rows = main.list_data_quality_flags(status="open", limit=100, offset=0)
    assert rows[0]["status"] == "open"


def test_resolve_and_reopen_flag(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    resolved = main.resolve_data_quality_flag(
        "flag-1", main.FlagResolvePayload(resolved_by="craig", resolution_notes="fixed")
    )
    reopened = main.reopen_data_quality_flag(
        "flag-1", main.FlagReopenPayload(reopened_by="craig", notes="still broken")
    )
    assert resolved["flag"]["status"] == "resolved"
    assert reopened["flag"]["status"] == "open"


def test_invalid_flag_id_returns_404(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    try:
        main.resolve_data_quality_flag("missing", main.FlagResolvePayload())
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 404


def test_artist_moderation_override_upsert(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    response = main.update_artist_moderation(
        "Latest Work",
        main.ArtistModerationPayload(
            is_hidden=True,
            reason="Navigation label",
            updated_by="craig",
        ),
    )
    assert response["status"] == "updated"
    assert response["artist_moderation"]["is_hidden"] is True


def test_hidden_artist_default_excluded_and_include_hidden(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    visible = main.list_artists(limit=100, offset=0, include_hidden=False)
    with_hidden = main.list_artists(limit=100, offset=0, include_hidden=True)
    assert len(visible) == 1
    assert len(with_hidden) == 2


def test_hidden_artist_search_behavior(monkeypatch):
    monkeypatch.setattr(main, "get_conn", fake_get_conn)
    hidden_excluded = main.list_artists(
        limit=100, offset=0, search="Latest Work", include_hidden=False
    )
    hidden_included = main.list_artists(
        limit=100, offset=0, search="Latest Work", include_hidden=True
    )
    assert hidden_excluded == []
    assert len(hidden_included) == 1
    assert hidden_included[0]["artist_name"] == "Latest Work"
    assert hidden_included[0]["is_hidden"] is True


def test_canonical_filtered_artist_can_still_be_moderated(monkeypatch):
    class CanonicalFilteredCursor(FakeCursor):
        def execute(self, query, params=None):
            sql = " ".join(query.split())
            self.conn.queries.append((sql, params))

            if "WITH artist_candidates AS" in sql and "FROM app.artist_profiles" in sql:
                # Artist is no longer present in app.artist_profiles, but still exists in
                # app.artwork_records.original_artist_name after canonical filtering.
                self._row = {"source_domain": "art.co.za"}
                return

            if "INSERT INTO app.artist_moderation_overrides" in sql:
                self._row = {
                    "artist_name": params[0],
                    "source_domain": params[1],
                    "is_hidden": params[2],
                    "canonical_artist_name": params[3],
                    "reason": params[4],
                    "updated_by": params[5],
                }
                return

    class CanonicalFilteredConn(FakeConn):
        def cursor(self):
            return CanonicalFilteredCursor(self)

    @contextmanager
    def canonical_filtered_conn():
        yield CanonicalFilteredConn()

    monkeypatch.setattr(main, "get_conn", canonical_filtered_conn)
    response = main.update_artist_moderation(
        "Latest Work",
        main.ArtistModerationPayload(
            is_hidden=True,
            canonical_artist_name="Gregory Kerr",
            reason="Navigation label",
            updated_by="moderator",
        ),
    )

    assert response["status"] == "updated"
    assert response["artist_moderation"]["artist_name"] == "Latest Work"
    assert response["artist_moderation"]["source_domain"] == "art.co.za"
    assert response["artist_moderation"]["is_hidden"] is True
