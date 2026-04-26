from datetime import datetime, timezone
import json
import scrapy

from artio_crawlers.items import ArtworkItem
from artio_crawlers.utils.hashing import content_hash


class MetMuseumSpider(scrapy.Spider):
    name = "metmuseum_artworks"
    allowed_domains = ["metmuseum.org"]
    start_urls = ["https://www.metmuseum.org/art/collection/search"]

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
    }

    def __init__(self, max_records=25, max_pages=3, crawl_run_id=None, dry_run=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_records = int(max_records)
        self.max_pages = int(max_pages)
        self.crawl_run_id = crawl_run_id
        self.dry_run = str(dry_run).lower() in {"true", "1", "yes"}
        self.records_seen = 0
        self.pages_seen = 0

    def parse(self, response):
        self.pages_seen += 1

        detail_links = response.css("a[href*='/art/collection/search/']::attr(href)").getall()
        seen = set()

        for href in detail_links:
            if self.records_seen >= self.max_records:
                return

            url = response.urljoin(href)
            if url in seen:
                continue
            seen.add(url)

            self.records_seen += 1
            yield scrapy.Request(url, callback=self.parse_artwork)

        if self.pages_seen < self.max_pages and self.records_seen < self.max_records:
            next_page = response.css("a[rel='next']::attr(href), a.next::attr(href)").get()
            if next_page:
                yield response.follow(next_page, callback=self.parse)

    def parse_artwork(self, response):
        title = response.css("h1::text").get()
        artist = response.css("[data-testid='artist-name']::text, .artist-name::text").get()

        # Fallbacks for generic page text.
        if title:
            title = title.strip()
        if artist:
            artist = artist.strip()

        meta_description = response.css("meta[name='description']::attr(content)").get()
        canonical = response.css("link[rel='canonical']::attr(href)").get()
        source_url = response.urljoin(canonical) if canonical else response.url

        image_url = response.css("meta[property='og:image']::attr(content)").get()

        raw_payload = {
            "title": title,
            "artist": artist,
            "meta_description": meta_description,
            "source_url": source_url,
        }

        item = ArtworkItem()
        item["crawl_run_id"] = self.crawl_run_id
        item["source_name"] = "The Metropolitan Museum of Art"
        item["source_domain"] = "metmuseum.org"
        item["source_url"] = source_url
        item["source_record_id"] = source_url.rstrip("/").split("/")[-1]
        item["artist_name"] = artist
        item["artwork_title"] = title
        item["artwork_date_text"] = None
        item["medium_text"] = None
        item["dimensions_text"] = None
        item["price_text"] = None
        item["currency_text"] = None
        item["gallery_name"] = None
        item["institution_name"] = "The Metropolitan Museum of Art"
        item["department_name"] = None
        item["image_url"] = image_url
        item["thumbnail_url"] = image_url
        item["description"] = meta_description
        item["raw_payload"] = raw_payload
        item["content_hash"] = content_hash(source_url, artist, title, image_url, meta_description)
        item["crawl_timestamp"] = datetime.now(timezone.utc).isoformat()

        yield item
