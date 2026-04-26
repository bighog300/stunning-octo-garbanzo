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

    SAMPLE_ARTWORKS = [
        {
            "artist_name": "Winslow Homer",
            "artwork_title": "Northeaster",
            "artwork_date_text": "1895; reworked by 1901",
            "medium_text": "Oil on canvas",
            "dimensions_text": "34 1/2 x 50 1/4 in. (87.6 x 127.6 cm)",
            "description": "Bequest of George A. Hearn, 1910",
        },
        {
            "artist_name": "John Singer Sargent",
            "artwork_title": "Madame X (Madame Pierre Gautreau)",
            "artwork_date_text": "1883–84",
            "medium_text": "Oil on canvas",
            "dimensions_text": "82 1/8 x 43 1/4 in. (208.6 x 109.9 cm)",
            "description": "Gift of Mrs. Charles Wrightsman, 1916",
        },
        {
            "artist_name": "Katsushika Hokusai",
            "artwork_title": "Under the Wave off Kanagawa (Kanagawa oki nami ura)",
            "artwork_date_text": "ca. 1830–32",
            "medium_text": "Polychrome woodblock print; ink and color on paper",
            "dimensions_text": "10 1/8 x 14 15/16 in. (25.7 x 37.9 cm)",
            "description": "From the series Thirty-six Views of Mount Fuji",
        },
        {
            "artist_name": "Vincent van Gogh",
            "artwork_title": "Wheat Field with Cypresses",
            "artwork_date_text": "1889",
            "medium_text": "Oil on canvas",
            "dimensions_text": "28 7/8 x 36 3/4 in. (73.2 x 93.4 cm)",
            "description": "Purchase, The Annenberg Foundation Gift, 1993",
        },
        {
            "artist_name": "Auguste Renoir",
            "artwork_title": "Two Young Girls at the Piano",
            "artwork_date_text": "1892",
            "medium_text": "Oil on canvas",
            "dimensions_text": "45 5/8 x 35 1/4 in. (116 x 90 cm)",
            "description": "Gift of Mr. and Mrs. Henry Ittleson Jr., 1948",
        },
    ]

    def __init__(
        self,
        max_records=25,
        max_pages=None,
        crawl_run_id=None,
        dry_run=False,
        use_sample_data=False,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.max_records = int(max_records)
        self.max_pages = max_pages
        self.crawl_run_id = crawl_run_id
        self.dry_run = str(dry_run).lower() in {"true", "1", "yes"}
        self.use_sample_data = str(use_sample_data).lower() in {"true", "1", "yes"}
        self.records_seen = 0

    def start_requests(self):
        if self.use_sample_data:
            yield scrapy.Request(
                url="https://example.com/",
                callback=self.parse_sample_data,
                dont_filter=True,
            )
            return

        yield from super().start_requests()

    def parse_sample_data(self, response):
        del response
        yield from self._iter_sample_items()

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

    def _iter_sample_items(self):
        for sample_index in range(1, self.max_records + 1):
            sample_id = f"sample-{sample_index}"
            sample_seed = self.SAMPLE_ARTWORKS[(sample_index - 1) % len(self.SAMPLE_ARTWORKS)]
            sample_url = f"https://www.metmuseum.org/art/collection/search/{sample_id}"
            image_url = f"https://images.metmuseum.org/CRDImages/sample/original/{sample_id}.jpg"
            thumbnail_url = f"https://images.metmuseum.org/CRDImages/sample/web-large/{sample_id}.jpg"
            raw_payload = {"sample": True, "sample_id": sample_id}

            item = ArtworkItem()
            item["source_name"] = "The Metropolitan Museum of Art"
            item["source_domain"] = "metmuseum.org"
            item["source_url"] = sample_url
            item["source_record_id"] = sample_id
            item["artist_name"] = sample_seed["artist_name"]
            item["artwork_title"] = sample_seed["artwork_title"]
            item["artwork_date_text"] = sample_seed["artwork_date_text"]
            item["medium_text"] = sample_seed["medium_text"]
            item["dimensions_text"] = sample_seed["dimensions_text"]
            item["price_text"] = None
            item["currency_text"] = None
            item["gallery_name"] = None
            item["institution_name"] = "The Metropolitan Museum of Art"
            item["department_name"] = "European Paintings"
            item["image_url"] = image_url
            item["thumbnail_url"] = thumbnail_url
            item["description"] = sample_seed["description"]
            item["raw_payload"] = raw_payload
            item["content_hash"] = content_hash(
                sample_id,
                sample_seed["artwork_title"],
                sample_seed["artist_name"],
                sample_seed["artwork_date_text"],
                sample_seed["medium_text"],
                image_url,
            )
            item["crawl_timestamp"] = datetime.now(timezone.utc).isoformat()
            item["crawl_run_id"] = self.crawl_run_id

            yield item
