from artio_crawlers.spiders.artcoza_events import ArtCoZaEventsSpider
from scrapy.http import Request, TextResponse


def _html_response(url: str, html: str) -> TextResponse:
    request = Request(url=url)
    return TextResponse(url=url, request=request, body=html.encode("utf-8"), encoding="utf-8")


def test_event_listing_extraction_follows_detail_links() -> None:
    spider = ArtCoZaEventsSpider(max_records=5)
    response = _html_response(
        "https://www.art.co.za/exhibitions/",
        """
        <html><body>
            <article class="listing">
                <h2>Group Exhibition</h2>
                <a href="/exhibitions/running.php?nom=abc123">View</a>
                <p>Artists: Jane Doe and John Smith</p>
            </article>
        </body></html>
        """,
    )

    requests = list(spider.parse(response))

    assert len(requests) == 1
    assert requests[0].url == "https://www.art.co.za/exhibitions/running.php?nom=abc123"


def test_event_detail_extraction_emits_event_artist_and_image_items() -> None:
    spider = ArtCoZaEventsSpider(max_records=5, crawl_run_id="run-123")
    response = _html_response(
        "https://www.art.co.za/exhibitions/running.php?nom=abc123",
        """
        <html><head><title>Summer Show</title><meta property="og:image" content="/images/show.jpg"></head>
        <body>
            <h1>Summer Show</h1>
            <p>Venue: Example Gallery</p>
            <p>Address: 1 Main Rd, Cape Town</p>
            <p>Running: 01 January 2026 to 15 January 2026</p>
            <p>Artists: Jane Doe and John Smith</p>
            <p>A curated exhibition of painting.</p>
            <a href="/jane-doe/">Jane Doe</a>
        </body></html>
        """,
    )

    items = list(spider.parse_detail(response))

    event_items = [item for item in items if "event_title" in item]
    artist_items = [item for item in items if "artist_name_normalized" in item]
    image_items = [item for item in items if "image_type" in item]

    assert len(event_items) == 1
    assert event_items[0]["event_type"] == "exhibition"
    assert event_items[0]["event_title"] == "Summer Show"
    assert str(event_items[0]["start_date"]) == "2026-01-01"
    assert str(event_items[0]["end_date"]) == "2026-01-15"
    assert event_items[0]["city"] == "Cape Town"

    names = {item["artist_name"] for item in artist_items}
    assert "Jane Doe" in names
    assert "John Smith" in names
    assert any(item["artist_profile_url"] == "https://www.art.co.za/jane-doe/" for item in artist_items)

    assert len(image_items) == 1
    assert image_items[0]["image_url"] == "https://www.art.co.za/images/show.jpg"


def test_artist_name_parsing_and_normalization() -> None:
    spider = ArtCoZaEventsSpider()

    names = spider._split_artist_names("Featuring artists: Jane Doe, John Smith & Mia Van Wyk")

    assert names == ["Jane Doe", "John Smith", "Mia Van Wyk"]
    assert spider._normalize_artist_name("Mia Van-Wyk") == "mia van wyk"


def test_date_parsing_supports_opening_datetime() -> None:
    spider = ArtCoZaEventsSpider()
    response = _html_response(
        "https://www.art.co.za/galleries/opening.php?nom=show-1",
        """
        <html><body>
          <p>Opening: 05 March 2026 18:30</p>
        </body></html>
        """,
    )

    start_date, end_date, opening_dt = spider._extract_dates(response, "")

    assert str(start_date) == "2026-03-05"
    assert str(end_date) == "2026-03-05"
    assert opening_dt is not None
    assert opening_dt.hour == 18
    assert opening_dt.minute == 30


def test_source_record_id_stability_uses_nom_then_slug_then_hash() -> None:
    spider = ArtCoZaEventsSpider()

    with_nom = spider._build_source_record_id(
        "https://www.art.co.za/exhibitions/running.php?nom=abc123", "exhibition", "Ignored"
    )
    with_slug = spider._build_source_record_id(
        "https://www.art.co.za/news/fresh-update/", "news", "Fresh Update"
    )

    assert with_nom == "art.co.za:event:exhibition:abc123"
    assert with_slug == "art.co.za:event:news:fresh-update"


def test_url_normalization_and_filtering_rejects_html_fragments() -> None:
    spider = ArtCoZaEventsSpider()
    response = _html_response("https://www.art.co.za/exhibitions/", "<html><body></body></html>")

    assert spider._normalize_and_validate_url(response, " /exhibitions/%3Crunning.php%3E ") is None
    assert spider._normalize_and_validate_url(response, "mailto:info@art.co.za") is None
    assert spider._normalize_and_validate_url(response, "/exhibitions/running.php?nom=abc123") == (
        "https://www.art.co.za/exhibitions/running.php?nom=abc123"
    )


def test_irrelevant_pages_do_not_follow_links() -> None:
    spider = ArtCoZaEventsSpider(max_records=5)
    response = _html_response(
        "https://www.art.co.za/exhibitions/",
        """
        <html><body>
            <p>This page has no useful context.</p>
            <a href="/exhibitions/running.php?nom=abc123">Should not follow</a>
        </body></html>
        """,
    )

    requests = list(spider.parse(response))
    assert requests == []
