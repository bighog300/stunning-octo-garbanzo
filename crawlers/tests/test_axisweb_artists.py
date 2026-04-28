from artio_crawlers.spiders.axisweb_artists import AxiswebArtistsSpider
from scrapy.http import Request, TextResponse


def _html_response(url: str, body: str) -> TextResponse:
    request = Request(url=url)
    return TextResponse(url=url, request=request, body=body.encode("utf-8"), encoding="utf-8")


def test_listing_extracts_artist_links_only():
    spider = AxiswebArtistsSpider(max_pages=2, max_records=25)
    response = _html_response(
        "https://www.axisweb.org/artists/",
        """
        <html><body>
            <a href="/artists/jane-doe/">Jane</a>
            <a href="/artists/john-smith?utm_source=test">John</a>
            <a href="/news/new-opportunity">News</a>
            <a href="https://external.example/artist">External</a>
            <a href="/jobs/curator">Jobs</a>
        </body></html>
        """,
    )

    links = spider._extract_artist_links(response)

    assert links == [
        "https://www.axisweb.org/artists/jane-doe/",
        "https://www.axisweb.org/artists/john-smith",
    ]


def test_profile_extraction_returns_expected_artist_fields():
    spider = AxiswebArtistsSpider(crawl_run_id="run-1", max_records=10)
    response = _html_response(
        "https://www.axisweb.org/artists/jane-doe/",
        """
        <html><head>
            <meta property="og:image" content="https://www.axisweb.org/media/jane.jpg" />
        </head><body>
            <h1>Jane Doe</h1>
            <div class="bio"><p>  Jane Doe is a UK artist focused on memory. </p></div>
            <div class="discipline">Painting</div>
            <div class="discipline">Printmaking</div>
            <div class="location">Leeds, UK</div>
            <a href="https://janedoe.studio">Official site</a>
            <a href="https://instagram.com/janedoe">Instagram</a>
            <a href="https://www.axisweb.org/projects/project-1/">Project</a>
        </body></html>
        """,
    )

    outputs = list(spider.parse_artist(response))

    assert len(outputs) == 1
    item = outputs[0]
    assert item["source_domain"] == "axisweb.org"
    assert item["source_record_id"] == "axisweb:artist:jane-doe"
    assert item["artist_name"] == "Jane Doe"
    assert "memory" in item["biography"]
    assert item["raw_payload"]["disciplines"] == ["Painting", "Printmaking"]
    assert item["raw_payload"]["location"] == "Leeds, UK"
    assert item["raw_payload"]["website_url"] == "https://janedoe.studio/"
    assert item["raw_payload"]["social_links"]["instagram_url"] == "https://instagram.com/janedoe"


def test_pagination_stops_when_no_new_artist_links():
    spider = AxiswebArtistsSpider(max_pages=3, max_records=25)
    response = _html_response(
        "https://www.axisweb.org/artists/?page=1",
        """
        <html><body>
            <a href="/artists/jane-doe/">Jane</a>
            <a rel="next" href="/artists/?page=2">Next</a>
        </body></html>
        """,
    )

    first_pass = list(spider.parse(response))
    assert len(first_pass) == 2

    spider.seen_artist_urls.add("https://www.axisweb.org/artists/jane-doe/")
    second = _html_response(
        "https://www.axisweb.org/artists/?page=2",
        """
        <html><body>
            <a href="/artists/jane-doe/">Jane</a>
            <a rel="next" href="/artists/?page=3">Next</a>
        </body></html>
        """,
    )

    second_pass = list(spider.parse(second))
    assert second_pass == []


def test_no_non_artist_pages_followed_by_parser():
    spider = AxiswebArtistsSpider(max_pages=2, max_records=25)
    response = _html_response(
        "https://www.axisweb.org/artists/",
        """
        <html><body>
            <a href="/artists/jane-doe/">Jane</a>
            <a href="/artists/?page=2">Next</a>
            <a href="/news/something">News</a>
            <a href="/opportunities/open-call">Open Call</a>
            <a href="/events/foo">Event</a>
        </body></html>
        """,
    )

    outputs = list(spider.parse(response))
    followed = [o.url for o in outputs]

    assert "https://www.axisweb.org/artists/jane-doe/" in followed
    assert "https://www.axisweb.org/artists/?page=2" in followed
    assert all("/news/" not in u for u in followed)
    assert all("/opportunities/" not in u for u in followed)
    assert all("/events/" not in u for u in followed)
