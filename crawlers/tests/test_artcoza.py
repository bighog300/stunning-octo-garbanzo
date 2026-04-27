from pathlib import Path
import hashlib

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
            <a href="/watch-list/">watch list</a>
            <a href="/galleries/">galleries</a>
            <a href="/auctions/">auctions</a>
            <a href="/utility.php?id=abc">utility</a>
        </body></html>
        """,
    )

    links = spider._extract_artist_profile_links(response)

    assert links == ["https://www.art.co.za/hoseamatlou/"]
    assert spider.skipped_non_artist_links == 9


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
          <img src="/nickyliebenberg/work1.jpg" alt="Nicky Liebenberg Artwork" />
          <img src="/nickyliebenberg/work2.jpg" title="Artwork detail" />
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
            <img src="/jane-doe/images/sunset.jpg" alt="Sunset Over Cape Town" />
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
    assert item["source_url"] == "https://www.art.co.za/jane-doe/"
    assert item["image_url"] == "https://www.art.co.za/jane-doe/images/sunset.jpg"
    assert item["source_domain"] == "art.co.za"


def test_artist_bio_is_extracted_and_written_to_description_and_raw_payload() -> None:
    spider = ArtCoZaSpider(crawl_run_id="run-xyz")
    response = _html_response(
        "https://www.art.co.za/jane-doe/",
        """
        <html><body>
          <h1>Jane Doe</h1>
          <h2>About</h2>
          <p>Jane Doe is a Cape Town painter working in oil and charcoal.</p>
          <h2>Artist Statement</h2>
          <p>Her practice explores memory and migration through layered marks.</p>
          <h2>Recent Work</h2>
          <p>Recent Work</p>
          <img src="/jane-doe/work-a.jpg" alt="Work A" />
          <a href="/jane-doe/artworks/">View artworks</a>
        </body></html>
        """,
    )

    outputs = list(spider.parse_artist_profile(response))
    items = [obj for obj in outputs if not isinstance(obj, Request)]
    requests = [obj for obj in outputs if isinstance(obj, Request)]

    assert items
    assert "Cape Town painter" in items[0]["description"]
    assert "artist_bio" in items[0]["raw_payload"]
    assert "artist_statement" in items[0]["raw_payload"]
    assert "profile_text_blocks" in items[0]["raw_payload"]
    assert "Recent Work" not in items[0]["description"]

    section_response = _html_response(
        requests[0].url,
        """
        <html><body>
          <article>
            <img src="/jane-doe/work-b.jpg" alt="Work B" />
          </article>
        </body></html>
        """,
    )
    section_response.meta.update(requests[0].meta)

    section_items = [obj for obj in spider.parse_artwork_section(section_response) if not isinstance(obj, Request)]
    assert section_items
    assert "Cape Town painter" in section_items[0]["description"]
    assert section_items[0]["raw_payload"]["artist_profile_url"] == "https://www.art.co.za/jane-doe/"


def test_bad_artist_links_and_schemes_are_excluded() -> None:
    spider = ArtCoZaSpider(max_artists=10)
    response = _html_response(
        "https://www.art.co.za/artists/",
        """
        <html><body>
            <a href="/artist-good/">Good Artist</a>
            <a href="/training/">Art Training</a>
            <a href="/quiz/">Art Quiz</a>
            <a href="/weblinks/">Weblinks</a>
            <a href="/myartcoza/">My Artcoza</a>
            <a href="/index.php">Index</a>
            <a href="javascript:void(0)">Click</a>
            <a href="mailto:hello@example.com">Mail</a>
            <a href="tel:+27112223333">Call</a>
        </body></html>
        """,
    )

    links = spider._extract_artist_profile_links(response)
    assert links == ["https://www.art.co.za/artist-good/"]


def test_placeholder_and_invalid_records_are_skipped() -> None:
    spider = ArtCoZaSpider(crawl_run_id="run-xyz")
    response = _html_response(
        "https://www.art.co.za/jane-doe/",
        """
        <html><body>
          <h1>Recent Work | Featured Work | Art in South Africa | Jane Doe</h1>
          <article>
            <a href="javascript:void(0)">details</a>
            <img src="/artcoza.jpg" alt="placeholder" />
          </article>
          <article>
            <a href="/jane-doe/artwork/real-piece/">details</a>
            <img src="/images/top-facebook.png" alt="social" />
          </article>
          <article>
            <a href="/jane-doe/artwork/kept-piece/">details</a>
            <img src="/jane-doe/images/real-piece.jpg" alt="Golden Sunrise" />
          </article>
        </body></html>
        """,
    )

    outputs = list(spider.parse_artist_profile(response))
    items = [obj for obj in outputs if not isinstance(obj, Request)]

    assert len(items) == 1
    assert items[0]["source_url"] == "https://www.art.co.za/jane-doe/"
    assert items[0]["image_url"] == "https://www.art.co.za/jane-doe/images/real-piece.jpg"
    assert items[0]["artist_name"] == "Jane Doe"
    assert spider.skipped_placeholder_image >= 2


def test_invalid_artist_page_name_is_rejected() -> None:
    spider = ArtCoZaSpider(crawl_run_id="run-xyz")
    response = _html_response(
        "https://www.art.co.za/training/",
        """
        <html><body>
          <h1>Art Training</h1>
          <img src="/images/work1.jpg" alt="Some Art" />
        </body></html>
        """,
    )

    outputs = list(spider.parse_artist_profile(response))
    items = [obj for obj in outputs if not isinstance(obj, Request)]
    assert items == []
    assert spider.skipped_invalid_artist_page >= 1


def test_reserved_root_paths_are_excluded_from_artist_profiles() -> None:
    spider = ArtCoZaSpider(max_artists=10)
    response = _html_response(
        "https://www.art.co.za/artists/",
        """
        <html><body>
            <a href="/watch-list/">Watch List</a>
            <a href="/galleries/">Art Galleries</a>
            <a href="/auctions/">Art Auctions</a>
            <a href="/artist-good/">Good Artist</a>
        </body></html>
        """,
    )

    links = spider._extract_artist_profile_links(response)
    assert links == ["https://www.art.co.za/artist-good/"]


def test_follow_png_is_excluded_from_profile_items() -> None:
    spider = ArtCoZaSpider(crawl_run_id="run-xyz")
    response = _html_response(
        "https://www.art.co.za/jane-doe/",
        """
        <html><body>
          <h1>Jane Doe</h1>
          <img src="/jane-doe/follow.png" alt="Follow" />
          <img src="/jane-doe/actual-work.jpg" alt="Actual Work" />
        </body></html>
        """,
    )

    outputs = list(spider.parse_artist_profile(response))
    items = [obj for obj in outputs if not isinstance(obj, Request)]
    assert len(items) == 1
    assert items[0]["image_url"] == "https://www.art.co.za/jane-doe/actual-work.jpg"


def test_slug_scoped_image_required_for_profile_and_artwork_items() -> None:
    spider = ArtCoZaSpider(crawl_run_id="run-xyz")
    profile_response = _html_response(
        "https://www.art.co.za/ruhanjansevanvuuren/",
        """
        <html><body>
          <h1>Ruhan Janse Van Vuuren</h1>
          <img src="/images/not-scoped.jpg" alt="Nope" />
        </body></html>
        """,
    )

    profile_outputs = list(spider.parse_artist_profile(profile_response))
    profile_items = [obj for obj in profile_outputs if not isinstance(obj, Request)]
    assert profile_items == []

    section_response = _html_response(
        "https://www.art.co.za/ruhanjansevanvuuren/artworks/",
        """
        <html><body>
          <article>
            <a href="/ruhanjansevanvuuren/artwork/valid-piece/">details</a>
            <img src="/ruhanjansevanvuuren/ruhan_janse_van_vuuren_2024_52.jpg" alt="Valid Piece" />
          </article>
          <article>
            <a href="/ruhanjansevanvuuren/artwork/invalid-piece/">details</a>
            <img src="/galleries/listevent005.jpg" alt="Invalid Piece" />
          </article>
        </body></html>
        """,
    )
    section_response.meta["artist_name"] = "Ruhan Janse Van Vuuren"
    section_response.meta["artist_profile_url"] = "https://www.art.co.za/ruhanjansevanvuuren/"

    section_outputs = list(spider.parse_artwork_section(section_response))
    section_items = [obj for obj in section_outputs if not isinstance(obj, Request)]
    assert len(section_items) == 1
    assert (
        section_items[0]["image_url"]
        == "https://www.art.co.za/ruhanjansevanvuuren/ruhan_janse_van_vuuren_2024_52.jpg"
    )


def test_studio_image_is_excluded() -> None:
    spider = ArtCoZaSpider(crawl_run_id="run-xyz")
    response = _html_response(
        "https://www.art.co.za/jane-doe/",
        """
        <html><body>
          <h1>Jane Doe</h1>
          <img src="/jane-doe/studio.jpg" alt="Artist Photo" />
          <img src="/jane-doe/work-2024-01.jpg" alt="Blue Study" />
        </body></html>
        """,
    )

    outputs = list(spider.parse_artist_profile(response))
    items = [obj for obj in outputs if not isinstance(obj, Request)]
    assert len(items) == 1
    assert items[0]["image_url"] == "https://www.art.co.za/jane-doe/work-2024-01.jpg"


def test_cv_image_is_excluded() -> None:
    spider = ArtCoZaSpider(crawl_run_id="run-xyz")
    response = _html_response(
        "https://www.art.co.za/diane-victor/",
        """
        <html><body>
          <h1>Diane Victor</h1>
          <img src="/diane-victor/Diane_Victor_cv.jpg" alt="Diane Victor Cv" />
          <img src="/diane-victor/diane-victor-2023-18.jpg" alt="Smoke Figure" />
        </body></html>
        """,
    )

    outputs = list(spider.parse_artist_profile(response))
    items = [obj for obj in outputs if not isinstance(obj, Request)]
    assert len(items) == 1
    assert items[0]["image_url"] == "https://www.art.co.za/diane-victor/diane-victor-2023-18.jpg"


def test_front001_image_is_excluded() -> None:
    spider = ArtCoZaSpider(crawl_run_id="run-xyz")
    response = _html_response(
        "https://www.art.co.za/john-doe/",
        """
        <html><body>
          <h1>John Doe</h1>
          <img src="/john-doe/front001.jpg" alt="John Doe Profile" />
          <img src="/john-doe/john-doe-2019-07.jpg" alt="Red Horizon" />
        </body></html>
        """,
    )

    outputs = list(spider.parse_artist_profile(response))
    items = [obj for obj in outputs if not isinstance(obj, Request)]
    assert len(items) == 1
    assert items[0]["image_url"] == "https://www.art.co.za/john-doe/john-doe-2019-07.jpg"


def test_slug_scoped_images_are_kept_without_artworks_path_requirement() -> None:
    spider = ArtCoZaSpider(crawl_run_id="run-xyz")
    response = _html_response(
        "https://www.art.co.za/jane-doe/",
        """
        <html><body>
          <h1>Jane Doe</h1>
          <img src="/jane-doe/work-a.jpg" alt="Work A" />
          <img src="/jane-doe/artworks/work-b.jpg" alt="Work B" />
          <img src="/images/top-facebook.png" alt="social" />
        </body></html>
        """,
    )

    outputs = list(spider.parse_artist_profile(response))
    items = [obj for obj in outputs if not isinstance(obj, Request)]
    image_urls = sorted(item["image_url"] for item in items)
    assert image_urls == [
        "https://www.art.co.za/jane-doe/artworks/work-b.jpg",
        "https://www.art.co.za/jane-doe/work-a.jpg",
    ]
    assert spider.images_seen_per_artist["https://www.art.co.za/jane-doe/"] == 3
    assert spider.images_kept_per_artist["https://www.art.co.za/jane-doe/"] == 2
    assert spider.images_skipped_per_artist["https://www.art.co.za/jane-doe/"] == 1


def test_same_artist_different_images_have_unique_identity_fields() -> None:
    spider = ArtCoZaSpider(crawl_run_id="run-xyz")
    response = _html_response(
        "https://www.art.co.za/jane-doe/",
        """
        <html><body>
          <h1>Jane Doe</h1>
          <img src="/jane-doe/work-a.jpg" alt="Work A" />
          <img src="/jane-doe/work-b.jpg" alt="Work A" />
        </body></html>
        """,
    )

    outputs = list(spider.parse_artist_profile(response))
    items = [obj for obj in outputs if not isinstance(obj, Request)]

    assert len(items) == 2
    assert items[0]["source_record_id"] != items[1]["source_record_id"]
    assert items[0]["content_hash"] != items[1]["content_hash"]
    assert items[0]["source_record_id"] == "art.co.za:jane-doe:work-a.jpg"
    assert items[1]["source_record_id"] == "art.co.za:jane-doe:work-b.jpg"


def test_source_record_id_uses_sha1_when_image_filename_missing() -> None:
    spider = ArtCoZaSpider()
    image_url = "https://www.art.co.za/"

    source_record_id = spider._build_source_record_id("jane-doe", image_url)

    assert source_record_id == f"art.co.za:jane-doe:{hashlib.sha1(image_url.encode('utf-8')).hexdigest()}"
