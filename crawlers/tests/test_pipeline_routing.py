from __future__ import annotations

from types import SimpleNamespace

import pytest

from artio_crawlers.items import ArtistItem, ArtworkItem
from artio_crawlers.pipelines import PostgresArtworkPipeline


def _pipeline() -> PostgresArtworkPipeline:
    pipeline = PostgresArtworkPipeline()
    pipeline.conn = object()
    pipeline._event_id_map = {}
    pipeline._event_children_reset = set()
    return pipeline


def test_artist_item_without_biography_routes_to_upsert_artist(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = _pipeline()
    called = {"artist": 0}

    def fake_upsert_artist(conn, data):
        called["artist"] += 1
        assert data["artist_name"] == "Jane Doe"

    monkeypatch.setattr("artio_crawlers.pipelines.upsert_artist", fake_upsert_artist)

    item = ArtistItem(
        artist_name="Jane Doe",
        source_domain="axisweb.org",
        source_url="https://axisweb.org/artists/jane-doe/",
        source_record_id="jane-doe",
        raw_payload={"name": "Jane Doe"},
        content_hash="abc",
        crawl_timestamp="2026-04-29T00:00:00Z",
    )

    pipeline.process_item(item, SimpleNamespace(dry_run=False, logger=None))
    assert called["artist"] == 1


def test_unknown_dict_still_raises_value_error() -> None:
    pipeline = _pipeline()

    with pytest.raises(ValueError, match="Unknown item type"):
        pipeline.process_item({"foo": "bar"}, SimpleNamespace(dry_run=False, logger=None))


def test_artwork_item_with_artist_name_and_title_routes_to_upsert_artwork(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _pipeline()
    called = {"artwork": 0, "artist": 0}

    monkeypatch.setattr(
        "artio_crawlers.pipelines.upsert_artwork",
        lambda conn, data: called.__setitem__("artwork", called["artwork"] + 1),
    )
    monkeypatch.setattr(
        "artio_crawlers.pipelines.upsert_artist",
        lambda conn, data: called.__setitem__("artist", called["artist"] + 1),
    )

    item = ArtworkItem(
        artist_name="Jane Doe",
        artwork_title="Untitled",
        source_domain="example.org",
        source_url="https://example.org/artwork/1",
    )

    pipeline.process_item(item, SimpleNamespace(dry_run=False, logger=None))
    assert called["artwork"] == 1
    assert called["artist"] == 0


def test_axisweb_directory_fallback_artist_item_routes_to_upsert_artist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _pipeline()
    called = {"artist": 0}

    monkeypatch.setattr(
        "artio_crawlers.pipelines.upsert_artist",
        lambda conn, data: called.__setitem__("artist", called["artist"] + 1),
    )

    item = ArtistItem(
        artist_name="Directory Artist",
        source_domain="axisweb.org",
        source_url="https://axisweb.org/membership/redirect?id=208",
        source_record_id="208",
        raw_payload={"href": "https://axisweb.org/membership/redirect?id=208"},
        content_hash="hash",
        crawl_timestamp="2026-04-29T00:00:00Z",
    )

    pipeline.process_item(item, SimpleNamespace(dry_run=False, logger=None))
    assert called["artist"] == 1
