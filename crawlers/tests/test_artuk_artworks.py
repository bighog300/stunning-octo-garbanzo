from artio_crawlers.spiders.artuk_artworks import ArtUkArtworksSpider
from scrapy.http import Request, TextResponse
from unittest.mock import Mock


def _html_response(url: str, body: str, status: int = 200) -> TextResponse:
    request = Request(url=url)
    return TextResponse(url=url, request=request, body=body.encode("utf-8"), encoding="utf-8", status=status)


class _DummyStats:
    def __init__(self):
        self._values = {}

    def get_value(self, key):
        return self._values.get(key)

    def set_value(self, key, value):
        self._values[key] = value


class _DummyCrawler:
    def __init__(self):
        self.stats = _DummyStats()
        self.engine = Mock()


def test_listing_parser_extracts_artwork_links_only():
    spider = ArtUkArtworksSpider(max_pages=2, max_records=25)
    response = _html_response(
        "https://artuk.org/discover/artworks",
        """
        <html><body>
            <a href="/discover/artworks/first-work">Artwork 1</a>
            <a href="/discover/artworks/second-work?utm_source=test">Artwork 2</a>
            <a href="/discover/artists/test-artist">Artist</a>
            <a href="/visit/venues/test-gallery">Venue</a>
            <a href="https://external.example/work">External</a>
            <a href="/shop">Shop</a>
        </body></html>
        """,
    )

    links = spider._extract_artwork_links(response)

    assert links == [
        "https://artuk.org/discover/artworks/first-work",
        "https://artuk.org/discover/artworks/second-work",
    ]


def test_pagination_stops_on_duplicate_or_no_new_links():
    spider = ArtUkArtworksSpider(max_pages=2, max_records=25)
    response = _html_response(
        "https://artuk.org/discover/artworks?page=1",
        """
        <html><body>
            <a href="/discover/artworks/only-work">Artwork</a>
            <a rel="next" href="/discover/artworks?page=2">Next</a>
        </body></html>
        """,
    )

    first_pass = list(spider.parse(response))
    assert len(first_pass) == 2

    spider._seen_artwork_urls.add("https://artuk.org/discover/artworks/only-work")
    second_response = _html_response(
        "https://artuk.org/discover/artworks?page=2",
        """
        <html><body>
            <a href="/discover/artworks/only-work">Artwork</a>
            <a rel="next" href="/discover/artworks?page=3">Next</a>
        </body></html>
        """,
    )
    second_pass = list(spider.parse(second_response))

    assert second_pass == []


def test_artwork_detail_parser_extracts_expected_fields_and_artist_link():
    spider = ArtUkArtworksSpider(crawl_run_id="run-1", max_records=10)
    response = _html_response(
        "https://artuk.org/discover/artworks/example-artwork",
        """
        <html><head>
          <meta property="og:image" content="https://media.artuk.org/images/example.jpg" />
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "VisualArtwork",
            "name": "Example Artwork",
            "dateCreated": "1964",
            "artMedium": "Oil on board",
            "size": "51 x 42 cm",
            "description": "Example description",
            "creator": {
              "@type": "Person",
              "name": "Jane Doe",
              "url": "/discover/artists/jane-doe"
            },
            "locationCreated": {
              "@type": "Place",
              "name": "Example Gallery",
              "url": "/visit/venues/example-gallery"
            }
          }
          </script>
        </head>
        <body>
          <a href="/discover/artists/jane-doe">Jane Doe</a>
          <a href="/visit/venues/example-gallery">Example Gallery</a>
        </body></html>
        """,
    )

    outputs = list(spider.parse_artwork(response))

    assert len(outputs) == 2
    artwork = outputs[0]
    assert artwork["source_domain"] == "artuk.org"
    assert artwork["source_record_id"] == "artuk:artwork:example-artwork"
    assert artwork["artwork_title"] == "Example Artwork"
    assert artwork["artist_name"] == "Jane Doe"
    assert artwork["artwork_date_text"] == "1964"
    assert artwork["medium_text"] == "Oil on board"
    assert artwork["dimensions_text"] == "51 x 42 cm"
    assert artwork["gallery_name"] == "Example Gallery"
    assert artwork["raw_payload"]["artist_source_url"] == "https://artuk.org/discover/artists/jane-doe"


def test_collection_gallery_item_emitted_when_collection_exists():
    spider = ArtUkArtworksSpider(crawl_run_id="run-2", max_records=10)
    response = _html_response(
        "https://artuk.org/discover/artworks/example-two",
        """
        <html><head>
          <script type="application/ld+json">
          {
            "@type": "VisualArtwork",
            "name": "Example 2",
            "creator": {"@type": "Person", "name": "John Doe"},
            "locationCreated": {"@type": "Place", "name": "Collection House", "url": "/visit/venues/collection-house"}
          }
          </script>
          <script type="application/ld+json">
          {
            "@type": "Place",
            "name": "Collection House",
            "address": {
              "streetAddress": "1 Main St",
              "addressLocality": "Leeds",
              "addressCountry": "United Kingdom"
            },
            "url": "https://collection-house.example.org"
          }
          </script>
        </head><body></body></html>
        """,
    )

    outputs = list(spider.parse_artwork(response))
    gallery = outputs[1]

    assert gallery["source_record_id"] == "artuk:collection:collection-house"
    assert gallery["gallery_name"] == "Collection House"
    assert gallery["city"] == "Leeds"
    assert gallery["country"] == "United Kingdom"


def test_footer_social_navigation_links_ignored_for_websites():
    spider = ArtUkArtworksSpider()
    response = _html_response(
        "https://artuk.org/discover/artworks/example-three",
        """
        <html><body>
            <footer>
              <a href="https://facebook.com/artuk">Facebook</a>
              <a href="https://instagram.com/artukdotorg">Instagram</a>
            </footer>
            <a href="https://example-gallery.org">Official website</a>
        </body></html>
        """,
    )

    website = spider._extract_onsite_website_url(response)

    assert website == "https://example-gallery.org"


def test_robots_403_closes_spider_and_sets_blocked_stat():
    spider = ArtUkArtworksSpider(max_pages=2, max_records=25)
    crawler = _DummyCrawler()
    spider._crawler = crawler

    response = _html_response("https://artuk.org/robots.txt", "User-agent: *", status=403)

    output = list(spider.parse_robots_check(response))

    assert output == []
    assert crawler.stats.get_value("artuk/source_blocked") == 1
    crawler.engine.close_spider.assert_called_once_with(spider, "artuk_source_blocked_403")
