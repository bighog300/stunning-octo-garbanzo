from artio_crawlers.spiders.artrabbit_events import ArtRabbitEventsSpider
from scrapy.http import Request, TextResponse


def _html_response(url: str, html: str) -> TextResponse:
    request = Request(url=url)
    return TextResponse(url=url, request=request, body=html.encode("utf-8"), encoding="utf-8")


def test_listing_extracts_event_links() -> None:
    spider = ArtRabbitEventsSpider(max_pages=1, max_records=5)
    response = _html_response(
        "https://www.artrabbit.com/all-listings/united-kingdom/london",
        """
        <html><body>
          <a href="/events/future-memory">Future Memory</a>
          <a href="/events/future-memory">Duplicate</a>
          <a href="/galleries/something">Ignore</a>
        </body></html>
        """,
    )

    requests = [item for item in spider.parse(response) if hasattr(item, "url")]

    assert len(requests) == 1
    assert requests[0].url == "https://www.artrabbit.com/events/future-memory"


def test_detail_extracts_event_core_fields() -> None:
    spider = ArtRabbitEventsSpider(crawl_run_id="run-1")
    response = _html_response(
        "https://www.artrabbit.com/events/future-memory",
        """
        <html>
            <head>
                <meta property="og:image" content="/images/future-memory.jpg" />
            </head>
            <body>
              <main>
                <h1>Future Memory</h1>
                <div class="category">Exhibitions</div>
                <p>12 April 2026 - 18 May 2026</p>
                <section class="venue-details">
                  <h2>Example Gallery</h2>
                  <p>Address: 10 Example Street, London</p>
                  <p>City: London</p>
                  <p>Country: United Kingdom</p>
                  <a href="https://examplegallery.com">Website</a>
                </section>
              </main>
            </body>
        </html>
        """,
    )

    outputs = list(spider.parse_detail(response))
    event_items = [item for item in outputs if "event_title" in item]

    assert len(event_items) == 1
    event = event_items[0]
    assert event["event_title"] == "Future Memory"
    assert event["event_type"] == "exhibition"
    assert str(event["start_date"]) == "2026-04-12"
    assert str(event["end_date"]) == "2026-05-18"
    assert event["venue_name"] == "Example Gallery"
    assert event["venue_address"] == "10 Example Street, London"


def test_detail_emits_gallery_with_address_and_website() -> None:
    spider = ArtRabbitEventsSpider(crawl_run_id="run-1")
    response = _html_response(
        "https://www.artrabbit.com/events/future-memory",
        """
        <html><body>
          <main>
            <h1>Future Memory</h1>
            <section class="venue">
              <h2>Example Gallery</h2>
              <p>Address: 10 Example Street, London</p>
              <p>City: London</p>
              <p>Country: United Kingdom</p>
              <a href="https://examplegallery.com">Website</a>
            </section>
          </main>
        </body></html>
        """,
    )

    outputs = list(spider.parse_detail(response))
    gallery_items = [item for item in outputs if "gallery_name" in item]

    assert len(gallery_items) == 1
    gallery = gallery_items[0]
    assert gallery["gallery_name"] == "Example Gallery"
    assert gallery["address"] == "10 Example Street, London"
    assert gallery["website_url"] == "https://examplegallery.com"


def test_footer_social_links_are_ignored() -> None:
    spider = ArtRabbitEventsSpider()
    response = _html_response(
        "https://www.artrabbit.com/events/future-memory",
        """
        <html><body>
          <main>
            <h1>Future Memory</h1>
            <section class="venue-details">
              <h2>Example Gallery</h2>
              <a href="https://www.instagram.com/examplegallery/">Instagram</a>
              <a href="https://www.facebook.com/examplegallery/">Facebook</a>
            </section>
          </main>
          <footer class="site-footer">
            <a href="https://www.instagram.com/artrabbit/">Footer Instagram</a>
            <a href="https://www.facebook.com/artrabbit/">Footer Facebook</a>
          </footer>
        </body></html>
        """,
    )

    outputs = list(spider.parse_detail(response))
    gallery = [item for item in outputs if "gallery_name" in item][0]

    assert gallery["instagram_url"] == "https://www.instagram.com/examplegallery/"
    assert gallery["facebook_url"] == "https://www.facebook.com/examplegallery/"
