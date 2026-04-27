from __future__ import annotations

import json
from pathlib import Path

from artio_cli import audit_artcoza_extraction as cli


def test_build_stats_counts_quality_fields() -> None:
    records = [
        {
            "artist_name": "Artist A",
            "artwork_title": "Work 1",
            "description": "Strong biography text",
            "medium_text": "Oil",
            "dimensions_text": "10 x 10 cm",
            "price_text": "R 1000",
            "raw_payload": {"artist_bio": "Bio", "artist_statement": "Statement"},
        },
        {
            "artist_name": "Artist B",
            "artwork_title": "Work 2",
            "description": "",
            "medium_text": "",
            "dimensions_text": None,
            "price_text": None,
            "raw_payload": {},
        },
    ]

    stats = cli.build_stats("after", records)

    assert stats.records_total == 2
    assert stats.unique_artists == 2
    assert stats.with_description == 1
    assert stats.with_artist_bio == 1
    assert stats.with_artist_statement == 1
    assert stats.with_medium == 1
    assert stats.with_dimensions == 1
    assert stats.with_price == 1
    assert stats.quality_score > 0


def test_load_records_from_jsonl_filters_non_artworks(tmp_path: Path) -> None:
    path = tmp_path / "crawl.jsonl"
    rows = [
        {"artwork_title": "A", "artist_name": "X", "raw_payload": {}},
        {"event_title": "Not artwork"},
        {"artwork_title": "B", "artist_name": "Y", "raw_payload": {"artist_bio": "bio"}},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    records = cli.load_records_from_jsonl(path)

    assert len(records) == 2
    assert {record["artwork_title"] for record in records} == {"A", "B"}
