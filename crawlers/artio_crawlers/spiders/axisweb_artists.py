from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import scrapy

from artio_crawlers.items import ArtistItem
from artio_crawlers.utils.hashing import content_hash


class AxiswebArtistsSpider(scrapy.Spider):
    name = "axisweb_artists"
    allowed_domains = ["axisweb.org", "www.axisweb.org", "algolia.net"]

    custom_settings = {
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 2,
        "AUTOTHROTTLE_MAX_DELAY": 20,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 0.5,
        "DOWNLOAD_DELAY": 2,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 2,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "RETRY_HTTP_CODES": [429, 500, 502, 503, 504],
        "RETRY_TIMES": 3,
        "ROBOTSTXT_OBEY": True,
    }

    ALGOLIA_APP_ID = "ZRWKGORU1W"
    ALGOLIA_API_KEY = "167e6b0a7408a25a86ce179218e38749"
    ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}.algolia.net/1/indexes/*/queries"
    ALGOLIA_INDEX_CANDIDATES = [
        "production_artists",
        "production_artist",
        "production_Algolia-Gallery",
        "production_gallery",
        "production_entries",
    ]

    TRACKING_QUERY_PREFIXES = ("utm_", "gclid", "fbclid", "mc_", "_hs")
    handle_httpstatus_list = [400, 403, 404]

    def __init__(self, crawl_run_id=None, max_pages=5, max_records=100, full_crawl=False, use_sample_data=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.crawl_run_id = crawl_run_id
        self.max_pages = int(max_pages) if int(max_pages) > 0 else 5
        self.max_records = int(max_records) if int(max_records) > 0 else 100
        self.full_crawl = str(full_crawl).lower() in {"true", "1", "yes"}
        self.use_sample_data = str(use_sample_data).lower() in {"true", "1", "yes"}
        self.records_emitted = 0
        self._algolia_index_used: str | None = None

    def start_requests(self):
        if self.use_sample_data:
            yield scrapy.Request(
                "data:text/plain,axisweb-sample",
                callback=self.parse_sample,
                dont_filter=True,
            )
            return

        for index_name in self.ALGOLIA_INDEX_CANDIDATES:
            yield self._algolia_request(index_name=index_name, page=0)

    def _algolia_request(self, index_name: str, page: int):
        hits_per_page = min(max(self.max_records, 1), 100)
        request_body = {
            "requests": [
                {
                    "indexName": index_name,
                    "params": urlencode({"page": page, "hitsPerPage": hits_per_page}),
                }
            ]
        }
        return scrapy.Request(
            self.ALGOLIA_URL,
            method="POST",
            body=json.dumps(request_body),
            headers={
                "X-Algolia-Application-Id": self.ALGOLIA_APP_ID,
                "X-Algolia-API-Key": self.ALGOLIA_API_KEY,
                "Content-Type": "application/json",
            },
            callback=self.parse_algolia,
            meta={
                "algolia_index": index_name,
                "algolia_page": page,
                "dont_obey_robotstxt": True,
            },
            dont_filter=True,
        )

    def parse_algolia(self, response: scrapy.http.Response):
        index_name = response.meta["algolia_index"]
        page = int(response.meta.get("algolia_page", 0))

        self._inc_stat(f"axisweb/algolia_status_{response.status}")

        if response.status == 404:
            self._inc_stat("axisweb/algolia_404")
            self.logger.warning("Algolia index request returned 404 for index=%s page=%s", index_name, page)
            return

        try:
            payload = response.json() if response.text else {}
        except ValueError:
            self.logger.warning("Non-JSON Algolia response for index=%s page=%s status=%s", index_name, page, response.status)
            return
        results = payload.get("results") or []
        result = results[0] if results else {}
        hits = result.get("hits") or []

        if not hits:
            if self._algolia_index_used is None and page == 0:
                self.logger.info("No hits for candidate index %s", index_name)
            self._inc_stat("axisweb/no_hits")
            return

        if self._algolia_index_used is None:
            self._algolia_index_used = index_name
            self._set_stat("axisweb/algolia_index_used", index_name)

        if index_name != self._algolia_index_used:
            return

        for hit in hits:
            if self._limit_reached():
                break
            item = self._item_from_hit(hit)
            if not item:
                continue
            self.records_emitted += 1
            self._inc_stat("axisweb/artists_scraped")
            yield item

        if self._limit_reached():
            return

        total_pages = int(result.get("nbPages") or 0)
        next_page = page + 1
        max_pages = total_pages if self.full_crawl else min(total_pages, self.max_pages)
        if next_page < max_pages:
            yield self._algolia_request(index_name=index_name, page=next_page)

    def _item_from_hit(self, hit: dict) -> ArtistItem | None:
        profile_url = self._extract_hit_url(hit)
        if not profile_url:
            return None

        source_id = str(hit.get("objectID") or hit.get("source_record_id") or profile_url)
        name = self._first_non_empty(
            self._clean(hit.get("title")),
            self._clean(hit.get("name")),
            self._clean(hit.get("artist_name")),
            self._slug_to_name(profile_url.rstrip("/").split("/")[-1]),
        )
        city = self._first_non_empty(
            self._clean(hit.get("city")),
            self._clean(hit.get("location")),
            self._clean((hit.get("address") or {}).get("city") if isinstance(hit.get("address"), dict) else None),
        )

        item = ArtistItem()
        item["crawl_run_id"] = self.crawl_run_id
        item["source_domain"] = "axisweb.org"
        item["source_url"] = profile_url
        item["source_record_id"] = source_id
        item["artist_name"] = name
        item["birth_year_text"] = None
        item["death_year_text"] = None
        item["nationality_text"] = None
        item["biography"] = self._clean(hit.get("biography") or hit.get("description") or hit.get("artist_statement"))
        item["image_url"] = self._canonicalize_url(hit.get("image") or hit.get("image_url") or "") or None
        item["raw_payload"] = hit
        item["content_hash"] = content_hash(profile_url, name, city, source_id)
        item["crawl_timestamp"] = datetime.now(UTC).isoformat()
        return item

    def _extract_hit_url(self, hit: dict) -> str | None:
        candidates = [
            hit.get("url"),
            hit.get("source_url"),
            hit.get("profile_url"),
            hit.get("permalink"),
            (hit.get("slug") and f"https://www.axisweb.org/artists/{hit.get('slug')}/"),
        ]
        for candidate in candidates:
            cleaned = self._clean(candidate)
            if not cleaned:
                continue
            parsed = urlparse(cleaned)
            if not parsed.scheme:
                cleaned = f"https://www.axisweb.org{cleaned if cleaned.startswith('/') else '/' + cleaned}"
            canonical = self._canonicalize_url(cleaned)
            parsed_canonical = urlparse(canonical)
            if parsed_canonical.netloc and "axisweb.org" not in parsed_canonical.netloc:
                continue
            if parsed_canonical.path in {"", "/"}:
                continue
            return canonical
        return None

    def _sample_items(self):
        sample_hits = [
            {"objectID": "sample-1", "title": "Sample Artist One", "url": "https://axisweb.org/p/sample-artist-one", "location": "Leeds"},
            {"objectID": "sample-2", "title": "Sample Artist Two", "url": "https://axisweb.org/p/sample-artist-two", "location": "Sheffield"},
            {"objectID": "sample-3", "name": "Sample Artist Three", "url": "https://axisweb.org/p/sample-artist-three", "location": "Bristol"},
            {"objectID": "sample-4", "artist_name": "Sample Artist Four", "url": "https://axisweb.org/p/sample-artist-four", "location": "Cardiff"},
            {"objectID": "sample-5", "title": "Sample Artist Five", "url": "https://axisweb.org/p/sample-artist-five", "location": "London"},
        ]
        for hit in sample_hits:
            item = self._item_from_hit(hit)
            if item:
                yield item

    def _canonicalize_url(self, url: str) -> str:
        if not url:
            return ""
        parsed = urlparse(url)
        path = re.sub(r"/+", "/", parsed.path or "/")
        clean_params = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower().startswith(self.TRACKING_QUERY_PREFIXES):
                continue
            clean_params.append((key, value))
        query = urlencode(sorted(clean_params))
        return urlunparse((parsed.scheme.lower() or "https", parsed.netloc.lower(), path, "", query, ""))

    def _slug_to_name(self, slug: str) -> str:
        return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = re.sub(r"\s+", " ", str(value)).strip()
        return cleaned or None

    @staticmethod
    def _first_non_empty(*values: str | None) -> str | None:
        for value in values:
            if value:
                return value
        return None

    def _limit_reached(self) -> bool:
        return not self.full_crawl and self.records_emitted >= self.max_records

    def _set_stat(self, key: str, value):
        crawler = getattr(self, "crawler", None)
        if crawler and crawler.stats:
            crawler.stats.set_value(key, value)

    def _inc_stat(self, key: str, count: int = 1):
        crawler = getattr(self, "crawler", None)
        if crawler and crawler.stats:
            crawler.stats.inc_value(key, count)

    def parse_sample(self, response: scrapy.http.Response):
        del response
        for item in self._sample_items():
            if self._limit_reached():
                break
            self.records_emitted += 1
            self._inc_stat("axisweb/artists_scraped")
            yield item
