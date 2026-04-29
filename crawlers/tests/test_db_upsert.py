from artio_crawlers.db import upsert_artist, upsert_artwork, upsert_event


class _CursorCtx:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, dict]] = []
        self._fetchall_result = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None) -> None:
        if "information_schema.columns" in query:
            self._fetchall_result = [
                ("source_domain",),
                ("source_url",),
                ("source_record_id",),
                ("artist_name",),
                ("raw_payload",),
                ("crawl_timestamp",),
            ]
        self.execute_calls.append((query, params))

    def fetchone(self):
        return ["00000000-0000-0000-0000-000000000001"]

    def fetchall(self):
        return self._fetchall_result


class _ConnStub:
    def __init__(self) -> None:
        self.cursor_ctx = _CursorCtx()
        self.commit_calls = 0

    def cursor(self):
        return self.cursor_ctx

    def commit(self) -> None:
        self.commit_calls += 1


def _base_item() -> dict:
    return {
        "crawl_run_id": "run-id",
        "source_name": "Art.co.za",
        "source_domain": "art.co.za",
        "source_url": "https://www.art.co.za/example-artist/",
        "source_record_id": "art.co.za:example-artist:piece.jpg",
        "artist_name": "Example Artist",
        "artwork_title": "Piece",
        "artwork_date_text": None,
        "medium_text": None,
        "dimensions_text": None,
        "price_text": None,
        "currency_text": None,
        "gallery_name": None,
        "institution_name": None,
        "department_name": None,
        "image_url": "https://www.art.co.za/example-artist/piece.jpg",
        "thumbnail_url": "https://www.art.co.za/example-artist/piece.jpg",
        "description": None,
        "raw_payload": {},
        "content_hash": "hash",
        "crawl_timestamp": "2026-01-01T00:00:00+00:00",
    }


def test_upsert_artwork_uses_record_id_conflict_target_when_record_id_present() -> None:
    conn = _ConnStub()
    item = _base_item()

    upsert_artwork(conn, item)

    assert conn.commit_calls == 1
    query, _ = conn.cursor_ctx.execute_calls[0]
    assert "ON CONFLICT (source_domain, source_record_id) WHERE source_record_id IS NOT NULL" in query


def test_upsert_artwork_falls_back_to_source_url_conflict_target_when_record_id_missing() -> None:
    conn = _ConnStub()
    item = _base_item()
    item["source_record_id"] = None

    upsert_artwork(conn, item)

    assert conn.commit_calls == 1
    query, _ = conn.cursor_ctx.execute_calls[0]
    assert "ON CONFLICT (source_domain, source_url) WHERE source_record_id IS NULL" in query


def _base_event_item() -> dict:
    return {
        "crawl_run_id": "run-id",
        "source_name": "Art.co.za",
        "source_domain": "art.co.za",
        "source_url": "https://www.art.co.za/exhibitions/running.php?nom=sample",
        "source_record_id": "art.co.za:event:exhibition:sample",
        "event_type": "exhibition",
        "event_title": "Sample Exhibition",
        "venue_name": "Sample Gallery",
        "venue_address": "1 Sample Street",
        "city": "Cape Town",
        "country": "South Africa",
        "start_date": "2026-01-01",
        "end_date": "2026-01-15",
        "opening_datetime": None,
        "description": "Sample description",
        "image_url": "https://www.art.co.za/sample.jpg",
        "raw_payload": {},
        "content_hash": "hash",
        "crawl_timestamp": "2026-01-01T00:00:00+00:00",
    }


def test_upsert_event_uses_record_id_conflict_target_when_record_id_present() -> None:
    conn = _ConnStub()
    item = _base_event_item()

    event_id = upsert_event(conn, item)

    assert conn.commit_calls == 1
    assert event_id == "00000000-0000-0000-0000-000000000001"
    query, _ = conn.cursor_ctx.execute_calls[0]
    assert "ON CONFLICT (source_domain, source_record_id) WHERE source_record_id IS NOT NULL" in query


def test_upsert_event_falls_back_to_source_url_conflict_target_when_record_id_missing() -> None:
    conn = _ConnStub()
    item = _base_event_item()
    item["source_record_id"] = None

    upsert_event(conn, item)

    assert conn.commit_calls == 1
    query, _ = conn.cursor_ctx.execute_calls[0]
    assert "ON CONFLICT (source_domain, source_url) WHERE source_record_id IS NULL" in query


def test_upsert_artist_sql_does_not_require_source_name_column() -> None:
    conn = _ConnStub()
    item = {
        "source_domain": "axisweb.org",
        "source_url": "https://www.axisweb.org/artists/jane-doe/",
        "source_record_id": "artist-123",
        "artist_name": "Jane Doe",
        "raw_payload": {"objectID": "artist-123"},
        "crawl_timestamp": "2026-01-01T00:00:00+00:00",
    }

    upsert_artist(conn, item)

    assert conn.commit_calls == 1
    query, _ = conn.cursor_ctx.execute_calls[-1]
    assert "source_name" not in query
    assert "artist_name" in query
