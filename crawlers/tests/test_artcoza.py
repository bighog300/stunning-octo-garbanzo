from pathlib import Path

from artio_crawlers.spiders.artcoza import ArtCoZaSpider
from scrapy.http import Request, TextResponse


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _html_response(url: str, html: str) -> TextResponse:
    request = Request(url=url)
    return TextResponse(url=url, request=request, body=html.encode("utf-8"), encoding="utf-8")


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def test_spider_imports_and_domain() -> None:
    spider = ArtCoZaSpider()

    assert spider.name == "artcoza_artworks"
    assert "art.co.za" in spider.allowed_domains


def test_artist_links_are_extracted_from_directory_html() -> None:
    spider = ArtCoZaSpider(max_artists=10)
    response = _html_response(
        "https://www.art.co.za/artists/",
        _fixture("artcoza_artists_directory.html"),
    )

    links = spider._extract_artist_profile_links(response)

    assert "https://www.art.co.za/nickyliebenberg/" in links
    assert "https://www.art.co.za/mia-van-wyk/" in links
    assert "https://www.art.co.za/artists/A/" not in links


def test_non_artist_links_are_excluded() -> None:
    spider = ArtCoZaSpider(max_artists=10)
    response = _html_response(
        "https://www.art.co.za/artists/",
        """
        <html><body>
            <a href="/hoseamatlou/">Artist</a>
            <a href="/index.php">index</a>
            <a href="/weblinks/">weblinks</a>
            <a href="/artists/">artists</a>
            <a href="/contact/">contact</a>
            <a href="/news/">news</a>
            <a href="/utility.php?id=abc">utility</a>
        </body></html>
        """,
    )

    links = spider._extract_artist_profile_links(response)

    assert links == ["https://www.art.co.za/hoseamatlou/"]
    assert spider.skipped_non_artist_links == 6


def test_parse_respects_max_artists() -> None:
    spider = ArtCoZaSpider(max_artists=1)
    response = _html_response(
        "https://www.art.co.za/artists/",
        _fixture("artcoza_artists_directory.html"),
    )

    requests = list(spider.parse(response))
    assert len(requests) == 1


def test_full_crawl_true_disables_artist_cap() -> None:
    spider = ArtCoZaSpider(max_artists=0, full_crawl=True)
    response = _html_response(
        "https://www.art.co.za/artists/",
        _fixture("artcoza_artists_directory.html"),
    )

    requests = list(spider.parse(response))
    urls = [req.url for req in requests]

    assert len(urls) == 2
    assert "https://www.art.co.za/nickyliebenberg/" in urls
    assert "https://www.art.co.za/mia-van-wyk/" in urls


def test_profile_page_extracts_visible_artwork_images() -> None:
    spider = ArtCoZaSpider(crawl_run_id="run-xyz")
    response = _html_response(
        "https://www.art.co.za/nickyliebenberg/",
        """
        <html><body>
          <h1>Nicky Liebenberg</h1>
          <img src="/images/logo.png" alt="Site Logo" />
          <img src="/images/work1.jpg" alt="Nicky Liebenberg Artwork" />
          <img src="/images/work2.jpg" title="Artwork detail" />
        </body></html>
        """,
    )

    outputs = list(spider.parse_artist_profile(response))
    items = [obj for obj in outputs if not isinstance(obj, Request)]

    assert len(items) == 2
    assert items[0]["artist_name"] == "Nicky Liebenberg"
    assert items[0]["source_domain"] == "art.co.za"


def test_artwork_item_includes_artist_name_source_url_and_image_url() -> None:
    spider = ArtCoZaSpider(crawl_run_id="run-xyz")
    response = _html_response(
        "https://www.art.co.za/jane-doe/",
        """
        <html><body>
          <article>
            <h2>Sunset Over Cape Town</h2>
            <a href="/jane-doe/artwork/sunset-over-cape-town/">details</a>
            <img src="/images/sunset.jpg" alt="Sunset Over Cape Town" />
            <figcaption>Oil on canvas.</figcaption>
          </article>
        </body></html>
        """,
    )
    response.meta["artist_name"] = "Jane Doe"
    response.meta["artist_profile_url"] = "https://www.art.co.za/jane-doe/"

    outputs = list(spider.parse_artwork_section(response))
    items = [obj for obj in outputs if not isinstance(obj, Request)]

    assert items
    item = items[0]
    assert item["artist_name"] == "Jane Doe"
    assert item["source_url"] == "https://www.art.co.za/jane-doe/artwork/sunset-over-cape-town/"
    assert item["image_url"] == "https://www.art.co.za/images/sunset.jpg"
    assert item["source_domain"] == "art.co.za"
