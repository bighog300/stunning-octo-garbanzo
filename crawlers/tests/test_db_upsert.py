from artio_crawlers.db import upsert_artwork


class _CursorCtx:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params) -> None:
        self.execute_calls.append((query, params))


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
