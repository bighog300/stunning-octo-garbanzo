import json

from artio_crawlers.spiders.axisweb_artists import AxiswebArtistsSpider
from scrapy.http import Request, TextResponse


def _json_response(url: str, payload: dict, meta: dict | None = None) -> TextResponse:
    request = Request(url=url, meta=meta or {})
    return TextResponse(url=url, request=request, body=json.dumps(payload).encode("utf-8"), encoding="utf-8")


def _html_response(url: str, html: str) -> TextResponse:
    return TextResponse(url=url, request=Request(url=url), body=html.encode("utf-8"), encoding="utf-8")


def test_sample_mode_start_requests_yields_requests_only():
    spider = AxiswebArtistsSpider(use_sample_data=True, max_records=5)
    outputs = list(spider.start_requests())
    assert len(outputs) == 1
    assert isinstance(outputs[0], Request)
    assert outputs[0].dont_filter is True


def test_parse_sample_yields_artist_items_without_network():
    spider = AxiswebArtistsSpider(use_sample_data=True, max_records=5)
    response = TextResponse(url="data:text/plain,axisweb-sample", request=Request(url="data:text/plain,axisweb-sample"))
    outputs = list(spider.parse_sample(response))
    assert len(outputs) >= 5
    item = outputs[0]
    assert item["source_domain"] == "axisweb.org"
    assert item["artist_name"].startswith("Sample Artist")
    assert item["source_url"].startswith("https://axisweb.org/p/")
    assert item["source_record_id"]
    assert isinstance(item["raw_payload"], dict)


def test_algolia_candidates_are_discovered_from_html_config():
    spider = AxiswebArtistsSpider(use_sample_data=False)
    html = '<div data-search-app="APP123" data-search-key="KEY123" data-search-prefix="production" data-config="artists,gallery"></div><script>const cfg={indexName:"production_artists_v2"};</script>'
    response = _html_response(spider.ARTIST_GALLERY_URL, html)

    outputs = list(spider.parse_artist_gallery(response))

    assert outputs
    assert all(isinstance(r, Request) for r in outputs)
    urls = [r.url for r in outputs]
    assert all("algolia.net/1/indexes/*/queries" in url for url in urls)
    assert all(r.headers.get("X-Algolia-Application-Id") == b"APP123" for r in outputs)
    bodies = [json.loads(r.body.decode("utf-8")) for r in outputs]
    index_names = [b["requests"][0]["indexName"] for b in bodies]
    assert "production_artists_v2" in index_names
    assert "production_artists" in index_names


def test_data_config_html_escaped_json_parses_clean_sections_and_filters_bad_candidates():
    spider = AxiswebArtistsSpider(use_sample_data=False)
    html = (
        '<div data-search-prefix="production" '
        'data-config="{&quot;sections&quot;:[&quot;artists&quot;,&quot;artwork&quot;,&quot;initiative&quot;,&quot;bad section&quot;]}"></div>'
    )
    response = _html_response(spider.ARTIST_GALLERY_URL, html)

    discovered = spider._discover_search_config(response)
    candidates = spider._build_index_candidates(discovered)

    assert discovered["sections"] == ["artists", "artwork", "initiative"]
    assert "production_artists" in candidates
    assert "production_artwork" in candidates
    assert "production_&quot;artwork&quot;" not in candidates
    assert all('"' not in candidate and "{" not in candidate for candidate in candidates)


def test_algolia_404_triggers_directory_fallback_request():
    spider = AxiswebArtistsSpider(max_records=10)
    spider._algolia_pending = 1
    response = TextResponse(
        url=spider.ALGOLIA_URL,
        request=Request(url=spider.ALGOLIA_URL, meta={"algolia_index": "missing", "algolia_page": 0}),
        status=404,
        body=b"",
    )

    outputs = list(spider.parse_algolia(response))

    assert len(outputs) == 1
    assert isinstance(outputs[0], Request)
    assert outputs[0].url == spider.DIRECTORY_URL


def test_directory_of_artists_parsing_yields_artist_items_with_required_fields():
    spider = AxiswebArtistsSpider(max_records=10)
    html = """
    <h2>A</h2>
    <a href="/artists/jane-doe/">Jane Doe</a>
    <a href="https://axisweb.org/artists/john-smith/">John Smith</a>
    """
    response = _html_response(spider.DIRECTORY_URL, html)

    outputs = list(spider.parse_directory(response))

    assert len(outputs) == 2
    for item in outputs:
        assert item["source_domain"] == "axisweb.org"
        assert item["source_url"].startswith("https://")
        assert item["source_record_id"]
        assert item["artist_name"]
        assert isinstance(item["raw_payload"], dict)
        assert item["raw_payload"]["source"] == "directory-of-artists"


def test_max_records_is_respected_for_directory_fallback():
    spider = AxiswebArtistsSpider(max_records=1)
    html = '<a href="/artists/one/">One</a><a href="/artists/two/">Two</a>'
    response = _html_response(spider.DIRECTORY_URL, html)

    outputs = list(spider.parse_directory(response))

    assert len(outputs) == 1
    assert outputs[0]["source_record_id"] == "one"


def test_directory_fallback_accepts_profile_like_links_and_increments_stats():
    spider = AxiswebArtistsSpider(max_records=10)
    html = """
    <main>
      <a href="/p/jane-doe">Jane Doe</a>
      <a href="/artist/john-smith">John Smith</a>
      <a href="/directory-of-artists">Directory</a>
      <a href="https://example.com/p/not-axis">Not Axis</a>
    </main>
    """
    response = _html_response(spider.DIRECTORY_URL, html)

    outputs = list(spider.parse_directory(response))

    assert len(outputs) == 2
    assert all(item["artist_name"] for item in outputs)
    assert all(item["raw_payload"]["source"] == "directory-of-artists" for item in outputs)


def test_directory_fallback_accepts_membership_redirect_links_and_extracts_ids():
    spider = AxiswebArtistsSpider(max_records=10)
    html = """
    <main>
      <a href="https://axisweb.org/membership/redirect?id=208">Artist Name</a>
      <a href="/membership/redirect?id=832">Another Artist</a>
      <a href="/membership/redirect?id=bad">Bad Id</a>
      <a href="/membership/redirect?id=999">   </a>
    </main>
    """
    response = _html_response(spider.DIRECTORY_URL, html)

    outputs = list(spider.parse_directory(response))

    assert len(outputs) == 2
    assert outputs[0]["source_record_id"] == "membership-208"
    assert outputs[1]["source_record_id"] == "membership-832"
    assert outputs[0]["source_url"] == "https://axisweb.org/membership/redirect?id=208"
    assert outputs[1]["source_url"] == "https://axisweb.org/membership/redirect?id=832"
    assert outputs[0]["artist_name"] == "Artist Name"
    assert outputs[1]["artist_name"] == "Another Artist"
    assert outputs[0]["raw_payload"]["href"] == "https://axisweb.org/membership/redirect?id=208"
    assert outputs[0]["raw_payload"]["text"] == "Artist Name"
    assert outputs[0]["raw_payload"]["membership_id"] == "208"
    assert outputs[1]["raw_payload"]["membership_id"] == "832"


def test_directory_fallback_membership_links_respect_max_records():
    spider = AxiswebArtistsSpider(max_records=1)
    html = """
    <a href="/membership/redirect?id=208">Artist Name</a>
    <a href="/membership/redirect?id=832">Another Artist</a>
    """
    response = _html_response(spider.DIRECTORY_URL, html)

    outputs = list(spider.parse_directory(response))

    assert len(outputs) == 1
    assert outputs[0]["source_record_id"] == "membership-208"
