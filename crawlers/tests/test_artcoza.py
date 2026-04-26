from artio_crawlers.spiders.artcoza import ArtCoZaSpider
from scrapy.http import Request, TextResponse


def _html_response(url: str, html: str) -> TextResponse:
    request = Request(url=url)
    return TextResponse(url=url, request=request, body=html.encode('utf-8'), encoding='utf-8')


def test_spider_imports_and_domain() -> None:
    spider = ArtCoZaSpider()

    assert spider.name == "artcoza_artworks"
    assert "art.co.za" in spider.allowed_domains


def test_artist_links_are_extracted_from_directory_html() -> None:
    spider = ArtCoZaSpider(max_artists=10)
    response = _html_response(
        "https://www.art.co.za/artists/",
        """
        <html><body>
          <a href="/artists/jane-doe/">Jane Doe</a>
          <a href="https://www.art.co.za/artists/john-smith/">John Smith</a>
          <a href="/artists/">Artists Index</a>
        </body></html>
        """,
    )

    requests = list(spider.parse(response))
    urls = [req.url for req in requests]

    assert "https://www.art.co.za/artists/jane-doe/" in urls
    assert "https://www.art.co.za/artists/john-smith/" in urls


def test_artwork_item_includes_artist_name_and_image_url() -> None:
    spider = ArtCoZaSpider(crawl_run_id="run-xyz")
    response = _html_response(
        "https://www.art.co.za/artists/jane-doe/artworks/",
        """
        <html><body>
          <article>
            <h2>Sunset Over Cape Town</h2>
            <a href="/artists/jane-doe/artworks/sunset-over-cape-town/">details</a>
            <img src="/images/sunset.jpg" alt="Sunset Over Cape Town" />
            <p>Oil on canvas.</p>
          </article>
        </body></html>
        """,
    )
    response.meta["artist_name"] = "Jane Doe"
    response.meta["artist_profile_url"] = "https://www.art.co.za/artists/jane-doe/"

    outputs = list(spider.parse_artwork_section(response))
    items = [obj for obj in outputs if not isinstance(obj, Request)]

    assert items
    item = items[0]
    assert item["artist_name"] == "Jane Doe"
    assert item["image_url"] == "https://www.art.co.za/images/sunset.jpg"
    assert item["source_domain"] == "art.co.za"
