from datetime import datetime, timezone
import json

import scrapy

from artio_crawlers.items import ArtworkItem
from artio_crawlers.utils.hashing import content_hash


class MetMuseumSpider(scrapy.Spider):
    name = "metmuseum_artworks"
    allowed_domains = ["collectionapi.metmuseum.org", "metmuseum.org"]
    start_urls = [
        "https://collectionapi.metmuseum.org/public/collection/v1/search?hasImages=true&q=painting"
    ]

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
    }

    def __init__(self, max_records=25, max_pages=None, crawl_run_id=None, dry_run=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_records = int(max_records)
        self.max_pages = max_pages
        self.crawl_run_id = crawl_run_id
        self.dry_run = str(dry_run).lower() in {"true", "1", "yes"}
        self.records_seen = 0

    def parse(self, response):
        payload = json.loads(response.text)
        object_ids = payload.get("objectIDs") or []

        for object_id in object_ids:
            if self.records_seen >= self.max_records:
                break

            self.records_seen += 1
            yield scrapy.Request(
                url=(
                    "https://collectionapi.metmuseum.org/public/collection/v1/objects/"
                    f"{object_id}"
                ),
                callback=self.parse_artwork,
            )

    def parse_artwork(self, response):
        raw_payload = json.loads(response.text)

        object_id = raw_payload.get("objectID")
        object_api_url = (
            "https://collectionapi.metmuseum.org/public/collection/v1/objects/"
            f"{object_id}"
        )

        artist_name = raw_payload.get("artistDisplayName")
        title = raw_payload.get("title")
        object_date = raw_payload.get("objectDate")
        medium = raw_payload.get("medium")
        image_url = raw_payload.get("primaryImage")

        item = ArtworkItem()
        item["source_name"] = "The Metropolitan Museum of Art"
        item["source_domain"] = "metmuseum.org"
        item["source_url"] = raw_payload.get("objectURL") or object_api_url
        item["source_record_id"] = object_id
        item["artist_name"] = artist_name
        item["artwork_title"] = title
        item["artwork_date_text"] = object_date
        item["medium_text"] = medium
        item["dimensions_text"] = raw_payload.get("dimensions")
        item["price_text"] = None
        item["currency_text"] = None
        item["gallery_name"] = None
        item["institution_name"] = "The Metropolitan Museum of Art"
        item["department_name"] = raw_payload.get("department")
        item["image_url"] = image_url
        item["thumbnail_url"] = raw_payload.get("primaryImageSmall")
        item["description"] = raw_payload.get("creditLine") or raw_payload.get("objectName")
        item["raw_payload"] = raw_payload
        item["content_hash"] = content_hash(
            object_id,
            title,
            artist_name,
            object_date,
            medium,
            image_url,
        )
        item["crawl_timestamp"] = datetime.now(timezone.utc).isoformat()
        item["crawl_run_id"] = self.crawl_run_id

        yield item
