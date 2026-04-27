from pathlib import Path

from artio_cli.audit_artcoza_extraction import (
    _parse_records_content,
    build_artist_name_backfill_plan,
    build_changed_records,
    build_matched_metrics,
    build_suspect_artist_names,
    match_records,
)


def _record(**overrides):
    base = {
        "source_record_id": "",
        "source_url": "",
        "image_url": "",
        "artist_name": "Artist",
        "artwork_title": "Work",
        "description": "desc",
        "medium_text": "oil",
        "dimensions_text": "10 x 10",
        "price_text": "100",
        "raw_payload": {"artist_bio": "bio"},
    }
    base.update(overrides)
    return base


def test_parse_json_array_input():
    records = _parse_records_content('[{"artwork_title":"A"},{"skip":1}]')
    assert len(records) == 1
    assert records[0]["artwork_title"] == "A"


def test_parse_jsonl_input(tmp_path: Path):
    path = tmp_path / "recrawl.jsonl"
    path.write_text('{"artwork_title":"A"}\n{"skip":1}\n', encoding="utf-8")

    parsed = _parse_records_content(path.read_text(encoding="utf-8"))
    assert len(parsed) == 1
    assert parsed[0]["artwork_title"] == "A"


def test_matching_by_source_record_id():
    baseline = [_record(source_record_id="r1", artwork_title="B")]
    recrawl = [_record(source_record_id="r1", artwork_title="C")]

    matched, baseline_only, recrawl_only = match_records(baseline, recrawl)
    assert len(matched) == 1
    assert baseline_only == []
    assert recrawl_only == []


def test_fallback_matching_without_source_record_id():
    baseline = [
        _record(source_url="https://a/1", image_url="https://img/1", source_record_id=""),
        _record(source_url="https://a/2", artwork_title="Same", source_record_id="", image_url=""),
    ]
    recrawl = [
        _record(source_url="https://a/1", image_url="https://img/1", source_record_id="", artwork_title="X"),
        _record(source_url="https://a/2", artwork_title="same", source_record_id="", image_url=""),
    ]

    matched, baseline_only, recrawl_only = match_records(baseline, recrawl)
    assert len(matched) == 2
    assert baseline_only == []
    assert recrawl_only == []


def test_matched_only_metrics_counts_and_quality():
    baseline = [
        _record(source_record_id="1", description="", medium_text=""),
        _record(source_record_id="2"),
    ]
    recrawl = [
        _record(source_record_id="2", description="", medium_text="", dimensions_text="", price_text="", raw_payload={"artist_bio": ""}),
        _record(source_record_id="3"),
    ]

    matched, baseline_only, recrawl_only = match_records(baseline, recrawl)
    metrics = build_matched_metrics(baseline, recrawl, matched, baseline_only, recrawl_only)

    assert metrics.baseline_records_total == 2
    assert metrics.recrawl_records_total == 2
    assert metrics.matched_records_total == 1
    assert metrics.baseline_only_records_total == 1
    assert metrics.recrawl_only_records_total == 1
    assert metrics.matched_quality_delta < 0


def test_changed_record_sorting_improvements_then_regressions():
    matched_pairs = [
        (_record(source_record_id="a", description="", medium_text=""), _record(source_record_id="a")),
        (_record(source_record_id="b"), _record(source_record_id="b", description="", medium_text="", dimensions_text="", price_text="", raw_payload={"artist_bio": ""})),
        (_record(source_record_id="c", description="", medium_text=""), _record(source_record_id="c", description="", medium_text="")),
    ]

    changed = build_changed_records(matched_pairs, show_changes=10)
    ids = [row["source_record_id"] for row in changed]
    assert ids[0] == "a"
    assert ids[-1] == "b"


def test_suspect_artist_names_flags_expected_patterns():
    suspects = build_suspect_artist_names(
        [
            _record(artist_name="Artist Statement", source_url="https://www.art.co.za/marriannabooyens/"),
            _record(artist_name="Hoseamatlou", source_url="https://www.art.co.za/hoseamatlou/"),
            _record(artist_name="Summer Expo: New Voices", source_url="https://www.art.co.za/chantalcoetzee/"),
            _record(artist_name="A" * 61, source_url="https://www.art.co.za/valid-artist/"),
        ]
    )

    reasons = {row["reason"] for row in suspects}
    assert "section_label_denylist" in reasons
    assert "single_token_with_known_slug_override" in reasons
    assert "contains_colon_exhibition_like" in reasons
    assert "name_too_long" in reasons


def test_changed_records_marks_artist_name_changed_when_quality_same():
    matched_pairs = [
        (
            _record(source_record_id="1", artist_name="Wrong Label"),
            _record(source_record_id="1", artist_name="Correct Artist"),
        )
    ]

    changed = build_changed_records(matched_pairs, show_changes=10)
    assert len(changed) == 1
    assert changed[0]["artist_name_changed"] is True
    assert changed[0]["quality_delta"] == 0


def test_artist_name_backfill_plan_is_source_record_id_guarded():
    matched_pairs = [
        (_record(source_record_id="1", artist_name="Old"), _record(source_record_id="1", artist_name="New")),
        (_record(source_record_id="", artist_name="Old 2"), _record(source_record_id="2", artist_name="New 2")),
        (_record(source_record_id="3", artist_name="Old 3"), _record(source_record_id="4", artist_name="New 3")),
        (_record(source_record_id="5", artist_name="Old 5"), _record(source_record_id="5", artist_name="")),
    ]

    metrics, updates = build_artist_name_backfill_plan(matched_pairs, show_updates=10)

    assert metrics.changed_artist_name_count == 4
    assert metrics.update_candidate_count == 1
    assert metrics.skipped_missing_source_record_id_count == 1
    assert metrics.skipped_source_record_id_mismatch_count == 1
    assert metrics.skipped_empty_after_name_count == 1
    assert updates == [{"source_record_id": "1", "artist_name_before": "Old", "artist_name_after": "New"}]
