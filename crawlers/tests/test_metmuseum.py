import json

from artio_crawlers.spiders.metmuseum import MetMuseumSpider
from scrapy.http import Request, TextResponse


def _json_response(url: str, payload: dict) -> TextResponse:
    request = Request(url=url)
    return TextResponse(
        url=url,
        request=request,
        body=json.dumps(payload).encode("utf-8"),
        encoding="utf-8",
    )


def test_parse_respects_max_records() -> None:
    spider = MetMuseumSpider(max_records=2)
    response = _json_response(
        "https://collectionapi.metmuseum.org/public/collection/v1/search?hasImages=true&q=painting",
        {"total": 3, "objectIDs": [101, 102, 103]},
    )

    requests = list(spider.parse(response))

    assert len(requests) == 2
    assert requests[0].url.endswith("/101")
    assert requests[1].url.endswith("/102")


def test_parse_artwork_maps_api_payload() -> None:
    spider = MetMuseumSpider(crawl_run_id="run-1")
    payload = {
        "objectID": 436535,
        "objectURL": "",
        "artistDisplayName": "Winslow Homer",
        "title": "Northeaster",
        "objectDate": "1895; reworked by 1901",
        "medium": "Oil on canvas",
        "dimensions": "34 1/2 x 50 1/4 in. (87.6 x 127.6 cm)",
        "department": "American Paintings and Sculpture",
        "primaryImage": "https://images.metmuseum.org/CRDImages/ap/original/DT1567.jpg",
        "primaryImageSmall": "https://images.metmuseum.org/CRDImages/ap/web-large/DT1567.jpg",
        "creditLine": "Bequest of George A. Hearn, 1910",
        "objectName": "Painting",
    }
    response = _json_response(
        "https://collectionapi.metmuseum.org/public/collection/v1/objects/436535",
        payload,
    )

    item = next(spider.parse_artwork(response))

    assert item["source_name"] == "The Metropolitan Museum of Art"
    assert item["source_domain"] == "metmuseum.org"
    assert item["source_url"].endswith("/436535")
    assert item["source_record_id"] == 436535
    assert item["artist_name"] == "Winslow Homer"
    assert item["artwork_title"] == "Northeaster"
    assert item["artwork_date_text"] == "1895; reworked by 1901"
    assert item["medium_text"] == "Oil on canvas"
    assert item["dimensions_text"] == "34 1/2 x 50 1/4 in. (87.6 x 127.6 cm)"
    assert item["price_text"] is None
    assert item["currency_text"] is None
    assert item["gallery_name"] is None
    assert item["institution_name"] == "The Metropolitan Museum of Art"
    assert item["department_name"] == "American Paintings and Sculpture"
    assert item["image_url"].startswith("https://images.metmuseum.org/")
    assert item["thumbnail_url"].startswith("https://images.metmuseum.org/")
    assert item["description"] == "Bequest of George A. Hearn, 1910"
    assert item["raw_payload"] == payload
    assert item["content_hash"]
    assert item["crawl_timestamp"]
    assert item["crawl_run_id"] == "run-1"


def test_start_requests_uses_sample_data_without_network_requests() -> None:
    spider = MetMuseumSpider(max_records=3, crawl_run_id="offline-run-1", use_sample_data=True)

    results = list(spider.start_requests())

    assert len(results) == 3
    assert all(not isinstance(result, Request) for result in results)

    first_item = results[0]
    second_item = results[1]
    assert first_item["source_domain"] == "metmuseum.org"
    assert first_item["source_url"] == "https://www.metmuseum.org/art/collection/search/sample-1"
    assert second_item["source_url"] == "https://www.metmuseum.org/art/collection/search/sample-2"
    assert first_item["source_record_id"] == "sample-1"
    assert second_item["source_record_id"] == "sample-2"
    assert first_item["artist_name"]
    assert first_item["artwork_title"]
    assert first_item["artwork_date_text"]
    assert first_item["medium_text"]
    assert first_item["dimensions_text"]
    assert first_item["image_url"].endswith("/sample-1.jpg")
    assert first_item["thumbnail_url"].endswith("/sample-1.jpg")
    assert first_item["description"]
    assert first_item["raw_payload"] == {"sample": True, "sample_id": "sample-1"}
    assert first_item["content_hash"]
    assert first_item["crawl_timestamp"]
    assert first_item["crawl_run_id"] == "offline-run-1"
