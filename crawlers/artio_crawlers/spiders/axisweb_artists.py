from __future__ import annotations

from datetime import UTC, datetime
from html import unescape
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
    ALGOLIA_URL_TEMPLATE = "https://{app_id}.algolia.net/1/indexes/*/queries"
    ALGOLIA_URL = ALGOLIA_URL_TEMPLATE.format(app_id=ALGOLIA_APP_ID)
    ARTIST_GALLERY_URL = "https://axisweb.org/artist-gallery"
    DIRECTORY_URL = "https://axisweb.org/directory-of-artists"
    ALGOLIA_INDEX_CANDIDATES = [
        "production_artists",
        "production_artist",
        "production_Algolia-Gallery",
        "production_gallery",
        "production_entries",
    ]

    TRACKING_QUERY_PREFIXES = ("utm_", "gclid", "fbclid", "mc_", "_hs")
    SAFE_SECTION_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
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
        self._algolia_pending = 0
        self._algolia_hits_found = False
        self._directory_fallback_started = False

    def start_requests(self):
        if self.use_sample_data:
            yield scrapy.Request(
                "data:text/plain,axisweb-sample",
                callback=self.parse_sample,
                dont_filter=True,
            )
            return

        yield scrapy.Request(self.ARTIST_GALLERY_URL, callback=self.parse_artist_gallery, dont_filter=True)

    def parse_artist_gallery(self, response: scrapy.http.Response):
        discovered = self._discover_search_config(response)
        app_id = discovered.get("app_id") or self.ALGOLIA_APP_ID
        api_key = discovered.get("api_key") or self.ALGOLIA_API_KEY
        index_candidates = self._build_index_candidates(discovered)

        if not index_candidates:
            self.logger.warning("No Algolia index candidates discovered from artist-gallery page.")
            yield from self._start_directory_fallback()
            return

        self._algolia_pending = len(index_candidates)
        for index_name in index_candidates:
            yield self._algolia_request(index_name=index_name, page=0, app_id=app_id, api_key=api_key)

    def _algolia_request(self, index_name: str, page: int, app_id: str | None = None, api_key: str | None = None):
        app_id = app_id or self.ALGOLIA_APP_ID
        api_key = api_key or self.ALGOLIA_API_KEY
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
            self.ALGOLIA_URL_TEMPLATE.format(app_id=app_id),
            method="POST",
            body=json.dumps(request_body),
            headers={
                "X-Algolia-Application-Id": app_id,
                "X-Algolia-API-Key": api_key,
                "Content-Type": "application/json",
            },
            callback=self.parse_algolia,
            meta={
                "algolia_index": index_name,
                "algolia_page": page,
                "algolia_app_id": app_id,
                "algolia_api_key": api_key,
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
            if page == 0:
                yield from self._mark_algolia_candidate_done(index_name)
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
            if page == 0:
                yield from self._mark_algolia_candidate_done(index_name)
            return

        self._algolia_hits_found = True

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
            yield self._algolia_request(
                index_name=index_name,
                page=next_page,
                app_id=response.meta.get("algolia_app_id"),
                api_key=response.meta.get("algolia_api_key"),
            )

    def _mark_algolia_candidate_done(self, index_name: str):
        del index_name
        if self._algolia_hits_found or self._directory_fallback_started:
            return
        if self._algolia_pending > 0:
            self._algolia_pending -= 1
        if self._algolia_pending == 0:
            self._directory_fallback_started = True
            return list(self._start_directory_fallback())
        return []

    def _start_directory_fallback(self):
        self._inc_stat("axisweb/directory_fallback_used")
        self.logger.info("Falling back to directory-of-artists crawl for Axisweb live ingestion")
        yield scrapy.Request(self.DIRECTORY_URL, callback=self.parse_directory, dont_filter=True)

    def parse_directory(self, response: scrapy.http.Response):
        entries = response.css("main a[href], [class*='directory'] a[href], [id*='directory'] a[href], a[href]")
        links_found = 0
        seen: set[str] = set()
        for anchor in entries:
            if self._limit_reached():
                break
            href = self._clean(anchor.attrib.get("href"))
            if not href:
                continue
            if not self._is_directory_profile_link(href):
                continue
            source_url = self._canonicalize_url(response.urljoin(href))
            if source_url in seen:
                continue
            seen.add(source_url)
            links_found += 1
            artist_name = self._clean(" ".join(anchor.css("::text").getall()))
            if not artist_name:
                artist_name = self._slug_to_name(urlparse(source_url).path.rstrip("/").split("/")[-1])
            if not artist_name:
                continue
            letter_group = self._nearest_letter_group(anchor)
            source_record_id = urlparse(source_url).path.rstrip("/").split("/")[-1] or content_hash(source_url)

            item = ArtistItem()
            item["crawl_run_id"] = self.crawl_run_id
            item["source_domain"] = "axisweb.org"
            item["source_url"] = source_url
            item["source_record_id"] = source_record_id
            item["artist_name"] = artist_name
            item["raw_payload"] = {
                "source": "directory-of-artists",
                "letter_group": letter_group,
                "href": href,
                "name": artist_name,
            }
            item["content_hash"] = content_hash(source_url, artist_name, source_record_id)
            item["crawl_timestamp"] = datetime.now(UTC).isoformat()
            self.records_emitted += 1
            self._inc_stat("axisweb/artists_scraped")
            yield item
        self._set_stat("axisweb/directory_links_found", links_found)
        if links_found == 0:
            self._inc_stat("axisweb/directory_no_links")
            self.logger.warning("axisweb/directory_no_links: no artist profile links found in directory fallback")

    def _discover_search_config(self, response: scrapy.http.Response) -> dict:
        html = response.text or ""
        def _attr(name: str):
            m = re.search(rf'data-{name}=["\']([^"\']+)["\']', html, re.IGNORECASE)
            return m.group(1).strip() if m else None
        config = {
            "app_id": _attr("search-app"),
            "api_key": _attr("search-key"),
            "prefix": _attr("search-prefix"),
            "sections": [],
            "indexes": [],
        }
        section_attr = _attr("config")
        if section_attr:
            config["sections"] = self._extract_sections(section_attr)
        config["indexes"] = self._extract_index_names(html)
        return config

    def _build_index_candidates(self, discovered: dict) -> list[str]:
        candidates: list[str] = []
        sections = discovered.get("sections") or []
        prefix = self._clean(discovered.get("prefix") or "")
        for idx in discovered.get("indexes") or []:
            if self._is_safe_candidate(idx) and idx not in candidates:
                candidates.append(idx)
            elif idx and not self._is_safe_candidate(idx):
                self.logger.warning("Skipping invalid Algolia index candidate: %s", idx)
        if prefix and sections:
            ordered_sections = sorted(sections, key=lambda section: 0 if section.lower() == "artists" else 1)
            for section in ordered_sections:
                for separator in ("_", "-", ""):
                    candidate = f"{prefix}{separator}{section}" if separator else f"{prefix}{section}"
                    if self._is_safe_candidate(candidate) and candidate not in candidates:
                        candidates.append(candidate)
                    elif not self._is_safe_candidate(candidate):
                        self.logger.warning("Skipping invalid Algolia index candidate: %s", candidate)
            if "artists" in [s.lower() for s in sections] and "artists" not in candidates:
                candidates.append("artists")
        for fallback in self.ALGOLIA_INDEX_CANDIDATES:
            if self._is_safe_candidate(fallback) and fallback not in candidates:
                candidates.append(fallback)
        return sorted(candidates, key=lambda value: (0 if "artist" in value.lower() else 1, value))

    def _extract_sections(self, section_attr: str) -> list[str]:
        decoded = unescape(section_attr)
        parsed_sections: list[str] = []
        try:
            parsed = json.loads(decoded)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            sections = parsed.get("sections")
            if isinstance(sections, list):
                parsed_sections = [self._clean(str(section)) for section in sections if self._clean(str(section))]
        elif isinstance(parsed, list):
            parsed_sections = [self._clean(str(section)) for section in parsed if self._clean(str(section))]
        if not parsed_sections:
            parsed_sections = [part.strip() for part in re.split(r"[,\s]+", decoded) if part.strip()]

        clean_sections: list[str] = []
        for section in parsed_sections:
            if section and self.SAFE_SECTION_PATTERN.fullmatch(section) and section not in clean_sections:
                clean_sections.append(section)
            elif section:
                self.logger.warning("Skipping invalid section value from data-config: %s", section)
        return clean_sections

    def _is_safe_candidate(self, candidate: str | None) -> bool:
        return bool(candidate and self.SAFE_SECTION_PATTERN.fullmatch(candidate))

    def _is_directory_profile_link(self, href: str) -> bool:
        parsed = urlparse(href.strip())
        if parsed.netloc and "axisweb.org" not in parsed.netloc:
            return False
        path = (parsed.path or "").lower()
        if not path or path in {"/", "/directory-of-artists"}:
            return False
        return bool(re.search(r"^/(p|artist|artists)/[^/]+/?$", path))

    def _extract_index_names(self, text: str) -> list[str]:
        patterns = [
            r'"indexName"\s*:\s*"([^"]+)"',
            r'indexName\s*[=:]\s*["\']([^"\']+)["\']',
            r'"index"\s*:\s*"([^"]+)"',
            r'indexes?/([A-Za-z0-9_\-]+)',
        ]
        names: list[str] = []
        for pattern in patterns:
            for match in re.findall(pattern, text, flags=re.IGNORECASE):
                cleaned = self._clean(match)
                if cleaned and cleaned not in names:
                    names.append(cleaned)
        return names

    def _nearest_letter_group(self, anchor) -> str | None:
        letter = anchor.xpath("preceding::*[self::h1 or self::h2 or self::h3 or self::h4][1]/text()").get()
        cleaned = self._clean(letter)
        return cleaned[:1].upper() if cleaned else None

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
