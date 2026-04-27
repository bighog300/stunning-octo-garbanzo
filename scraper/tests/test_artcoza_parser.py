from pathlib import Path

from scraper.parsers.artcoza import (
    extract_artist_bio,
    extract_artist_name,
    extract_artist_profile_context,
    extract_artworks,
    extract_events,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "artcoza"


def _fixture(name: str) -> str:
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return f.read()


def test_good_bio_extracts_clean_text() -> None:
    html = _fixture("good_bio.html")
    bio = extract_artist_bio(html)

    assert "contemporary South African painter" in bio
    assert "About the Artist" not in bio
    assert "Artworks ▼" not in bio


def test_noisy_bio_navigation_removed() -> None:
    html = _fixture("noisy_bio.html")
    bio = extract_artist_bio(html)

    assert "mixed-media artist" in bio
    assert "Facebook" not in bio
    assert "sam@example.com" not in bio
    assert "+27 11 222 3333" not in bio


def test_no_bio_returns_empty() -> None:
    html = _fixture("no_bio.html")

    assert extract_artist_bio(html) == ""


def test_multiple_sections_prefers_descriptive_block() -> None:
    html = _fixture("multiple_sections.html")
    bio = extract_artist_bio(html)

    assert "Johannesburg-based painter and printmaker" in bio
    assert "Artworks ▼" not in bio


def test_artworks_count_matches_expected() -> None:
    html_good = _fixture("good_bio.html")
    html_no_bio = _fixture("no_bio.html")

    assert len(extract_artworks(html_good)) == 2
    assert len(extract_artworks(html_no_bio)) == 2


def test_events_are_extracted() -> None:
    html = _fixture("artist_with_events.html")
    events = extract_events(html)

    assert len(events) >= 2
    assert any("Tidal Forms" in (event["title"] or "") for event in events)


def test_regression_expectations_on_all_bio_fixtures() -> None:
    fixture_expectations = {
        "good_bio.html": ["Cape Town", "memory, migration"],
        "noisy_bio.html": ["Pretoria", "urban rhythms"],
        "multiple_sections.html": ["Johannesburg", "botanical archives"],
    }

    for fixture_name, expected_phrases in fixture_expectations.items():
        html = _fixture(fixture_name)
        bio = extract_artist_bio(html)

        for phrase in expected_phrases:
            assert phrase in bio

        assert "About the Artist" not in bio
        assert "Artworks ▼" not in bio
        assert "@" not in bio


def test_name_extraction_works() -> None:
    html = _fixture("good_bio.html")
    name = extract_artist_name(html)

    assert name == "Jane Doe"


def test_profile_context_reports_fallback() -> None:
    html = _fixture("no_bio.html")
    ctx = extract_artist_profile_context(html)

    assert ctx["fallback_used"] is True
    assert ctx["bio"] == ""
