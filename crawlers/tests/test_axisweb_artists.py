import json

from artio_crawlers.spiders.axisweb_artists import AxiswebArtistsSpider
from scrapy.http import Request, TextResponse


def _json_response(url: str, payload: dict, meta: dict | None = None) -> TextResponse:
    request = Request(url=url, meta=meta or {})
    return TextResponse(url=url, request=request, body=json.dumps(payload).encode("utf-8"), encoding="utf-8")


def test_sample_mode_yields_artist_item_without_network():
    spider = AxiswebArtistsSpider(use_sample_data=True, max_records=5)

    outputs = list(spider.start_requests())

    assert len(outputs) == 1
    item = outputs[0]
    assert item["source_domain"] == "axisweb.org"
    assert item["source_name"] == "axisweb"
    assert item["artist_name"] == "Sample Axisweb Artist"


def test_algolia_response_parsing_yields_artist_item():
    spider = AxiswebArtistsSpider(max_records=5)
    response = _json_response(
        spider.ALGOLIA_URL,
        {
            "results": [
                {
                    "nbPages": 1,
                    "hits": [
                        {
                            "objectID": "artist-123",
                            "title": "Jane Doe",
                            "url": "https://www.axisweb.org/artists/jane-doe/",
                            "location": "Leeds",
                        }
                    ],
                }
            ]
        },
        meta={"algolia_index": "production_artists", "algolia_page": 0},
    )

    outputs = list(spider.parse_algolia(response))

    assert len(outputs) == 1
    item = outputs[0]
    assert item["source_record_id"] == "artist-123"
    assert item["artist_name"] == "Jane Doe"
    assert item["raw_payload"]["city"] == "Leeds"


def test_max_records_is_respected_when_parsing_algolia_hits():
    spider = AxiswebArtistsSpider(max_records=1)
    response = _json_response(
        spider.ALGOLIA_URL,
        {
            "results": [
                {
                    "nbPages": 1,
                    "hits": [
                        {"objectID": "artist-1", "name": "One", "url": "https://www.axisweb.org/artists/one/"},
                        {"objectID": "artist-2", "name": "Two", "url": "https://www.axisweb.org/artists/two/"},
                    ],
                }
            ]
        },
        meta={"algolia_index": "production_artists", "algolia_page": 0},
    )

    outputs = list(spider.parse_algolia(response))

    assert len(outputs) == 1
    assert outputs[0]["source_record_id"] == "artist-1"


def test_no_static_html_dependency_for_artist_extraction():
    spider = AxiswebArtistsSpider(max_records=5)
    response = _json_response(
        spider.ALGOLIA_URL,
        {
            "results": [{"nbPages": 1, "hits": [{"objectID": "artist-9", "slug": "slug-only"}]}]
        },
        meta={"algolia_index": "production_artists", "algolia_page": 0},
    )

    outputs = list(spider.parse_algolia(response))

    assert len(outputs) == 1
    assert outputs[0]["source_url"] == "https://www.axisweb.org/artists/slug-only/"
