from __future__ import annotations

from datetime import UTC, datetime
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import scrapy

from artio_crawlers.items import ArtistItem
from artio_crawlers.utils.hashing import content_hash


class AxiswebArtistsSpider(scrapy.Spider):
    name = "axisweb_artists"
    allowed_domains = ["axisweb.org", "www.axisweb.org"]

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

    TRACKING_QUERY_PREFIXES = ("utm_", "gclid", "fbclid", "mc_", "_hs")
    LISTING_PATH_RE = re.compile(r"^/artists/?$", re.IGNORECASE)
    PROFILE_PATH_RE = re.compile(r"^/artists/[^/]+/?$", re.IGNORECASE)
    DISALLOWED_PATH_HINTS = (
        "/login",
        "/log-in",
        "/signup",
        "/sign-up",
        "/jobs",
        "/opportunities",
        "/news",
        "/blog",
        "/editorial",
        "/events",
    )
    PLATFORM_HOST_HINTS = ("axisweb.org", "www.axisweb.org")

    def __init__(
        self,
        crawl_run_id=None,
        max_pages=5,
        max_records=100,
        full_crawl=False,
        use_sample_data=False,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.crawl_run_id = crawl_run_id
        self.max_pages = int(max_pages) if int(max_pages) > 0 else 5
        self.max_records = int(max_records) if int(max_records) > 0 else 100
        self.full_crawl = str(full_crawl).lower() in {"true", "1", "yes"}
        self.use_sample_data = str(use_sample_data).lower() in {"true", "1", "yes"}

        self.start_urls = ["https://www.axisweb.org/artists/"]
        self.seen_listing_urls: set[str] = set()
        self.queued_listing_urls: set[str] = set()
        self.seen_artist_urls: set[str] = set()
        self.records_emitted = 0

    def start_requests(self):
        for url in self.start_urls:
            canonical = self._canonicalize_url(url)
            self.queued_listing_urls.add(canonical)
            yield scrapy.Request(canonical, callback=self.parse)

    def parse(self, response: scrapy.http.Response):
        listing_url = self._canonicalize_url(response.url)
        if listing_url in self.seen_listing_urls:
            return

        page_num = self._page_number(listing_url)
        if not self.full_crawl and page_num > self.max_pages:
            return

        self.seen_listing_urls.add(listing_url)

        artist_links = self._extract_artist_links(response)
        new_artist_links = [url for url in artist_links if url not in self.seen_artist_urls]

        if not new_artist_links:
            return

        for artist_url in new_artist_links:
            if self._limit_reached():
                return
            self.seen_artist_urls.add(artist_url)
            yield response.follow(artist_url, callback=self.parse_artist)

        if self._limit_reached():
            return

        if not self.full_crawl and page_num >= self.max_pages:
            return

        for next_url in self._extract_pagination_links(response):
            if next_url in self.seen_listing_urls or next_url in self.queued_listing_urls:
                continue
            self.queued_listing_urls.add(next_url)
            yield response.follow(next_url, callback=self.parse)

    def parse_artist(self, response: scrapy.http.Response):
        if self._limit_reached():
            return

        canonical_url = self._canonicalize_url(response.url)
        if not self._is_artist_profile_url(canonical_url):
            return

        slug = canonical_url.rstrip("/").split("/")[-1]
        artist_name = self._first_non_empty(
            self._clean(response.css("h1::text").get()),
            self._clean(response.css("meta[property='og:title']::attr(content)").get()),
            self._slug_to_name(slug),
        )
        biography = self._extract_biography(response)
        disciplines = self._extract_disciplines(response)
        location = self._extract_location(response)
        website_url = self._extract_artist_website(response)
        social_links = self._extract_social_links(response)
        image_url = self._extract_profile_image(response)
        portfolio_links = self._extract_portfolio_links(response)

        item = ArtistItem()
        item["crawl_run_id"] = self.crawl_run_id
        item["source_name"] = "Axisweb"
        item["source_domain"] = "axisweb.org"
        item["source_url"] = canonical_url
        item["source_record_id"] = f"axisweb:artist:{slug}"
        item["artist_name"] = artist_name
        item["birth_year_text"] = None
        item["death_year_text"] = None
        item["nationality_text"] = None
        item["biography"] = biography
        item["image_url"] = image_url
        item["raw_payload"] = {
            "artist_statement": biography,
            "disciplines": disciplines,
            "media": disciplines,
            "location": location,
            "website_url": website_url,
            "social_links": social_links,
            "portfolio_project_links": portfolio_links,
        }
        item["content_hash"] = content_hash(canonical_url, artist_name, biography, image_url)
        item["crawl_timestamp"] = datetime.now(UTC).isoformat()

        self.records_emitted += 1
        yield item

    def _extract_artist_links(self, response: scrapy.http.Response) -> list[str]:
        links: list[str] = []
        for href in response.css("a::attr(href)").getall():
            normalized = self._normalize_candidate_url(response, href)
            if not normalized or not self._is_artist_profile_url(normalized):
                continue
            if self._is_disallowed_url(normalized):
                continue
            links.append(normalized)
        return list(dict.fromkeys(links))

    def _extract_pagination_links(self, response: scrapy.http.Response) -> list[str]:
        links: list[str] = []
        for href in response.css("a[rel='next']::attr(href), a.next::attr(href), a::attr(href)").getall():
            normalized = self._normalize_candidate_url(response, href)
            if not normalized:
                continue
            if self._is_listing_page_url(normalized):
                links.append(normalized)
        return list(dict.fromkeys(links))

    def _extract_biography(self, response: scrapy.http.Response) -> str | None:
        selectors = [
            "[class*='bio']::text",
            "[class*='bio'] *::text",
            "[class*='statement']::text",
            "[class*='statement'] *::text",
            "[data-testid*='bio']::text",
            "main p::text",
        ]
        text_parts: list[str] = []
        for selector in selectors:
            text_parts.extend(self._clean(x) for x in response.css(selector).getall())
        text_parts = [x for x in text_parts if x]
        joined = "\n".join(dict.fromkeys(text_parts))
        return joined[:6000] or None

    def _extract_disciplines(self, response: scrapy.http.Response) -> list[str]:
        values = []
        selectors = [
            "[class*='discipline']::text",
            "[class*='medium']::text",
            "[data-testid*='discipline']::text",
        ]
        for selector in selectors:
            for text in response.css(selector).getall():
                cleaned = self._clean(text)
                if cleaned and len(cleaned) <= 80:
                    values.append(cleaned)
        return list(dict.fromkeys(values))

    def _extract_location(self, response: scrapy.http.Response) -> str | None:
        return self._first_non_empty(
            self._clean(response.css("[class*='location']::text").get()),
            self._clean(response.css("[itemprop='addressLocality']::text").get()),
            self._clean(response.css("[class*='region']::text").get()),
        )

    def _extract_artist_website(self, response: scrapy.http.Response) -> str | None:
        for href in response.css("a::attr(href)").getall():
            normalized = self._normalize_candidate_url(response, href)
            if not normalized:
                continue
            host = (urlparse(normalized).hostname or "").lower()
            if any(h in host for h in self.PLATFORM_HOST_HINTS):
                continue
            if any(s in host for s in ("instagram.com", "x.com", "twitter.com", "facebook.com")):
                continue
            if self._looks_like_content_noise(normalized):
                continue
            return normalized
        return None

    def _extract_social_links(self, response: scrapy.http.Response) -> dict[str, str]:
        social: dict[str, str] = {}
        for href in response.css("a::attr(href)").getall():
            normalized = self._normalize_candidate_url(response, href)
            if not normalized:
                continue
            host = (urlparse(normalized).hostname or "").lower()
            if "instagram.com" in host:
                social["instagram_url"] = normalized
            elif "twitter.com" in host or "x.com" in host:
                social["twitter_url"] = normalized
        return social

    def _extract_profile_image(self, response: scrapy.http.Response) -> str | None:
        image = self._first_non_empty(
            response.css("meta[property='og:image']::attr(content)").get(),
            response.css("main img::attr(src), article img::attr(src)").get(),
        )
        if not image:
            return None
        return self._canonicalize_url(response.urljoin(image))

    def _extract_portfolio_links(self, response: scrapy.http.Response) -> list[str]:
        links = []
        for href in response.css("a::attr(href)").getall():
            normalized = self._normalize_candidate_url(response, href)
            if not normalized:
                continue
            if normalized == self._canonicalize_url(response.url):
                continue
            if self._is_listing_page_url(normalized):
                continue
            if self._is_artist_profile_url(normalized):
                continue
            if self._is_disallowed_url(normalized):
                continue
            if self._looks_like_content_noise(normalized):
                continue
            links.append(normalized)
        return list(dict.fromkeys(links))[:20]

    def _is_listing_page_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if not self._is_axisweb_host(parsed.hostname):
            return False
        if not self.LISTING_PATH_RE.match(parsed.path.rstrip("/") or "/"):
            return False
        return "page=" in parsed.query or parsed.query == ""

    def _is_artist_profile_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if not self._is_axisweb_host(parsed.hostname):
            return False
        if not self.PROFILE_PATH_RE.match(parsed.path):
            return False
        if parsed.path.rstrip("/").lower() == "/artists":
            return False
        return not self._is_disallowed_url(url)

    def _is_axisweb_host(self, hostname: str | None) -> bool:
        host = (hostname or "").lower()
        return host in self.PLATFORM_HOST_HINTS

    def _is_disallowed_url(self, url: str) -> bool:
        lowered = url.lower()
        return any(hint in lowered for hint in self.DISALLOWED_PATH_HINTS)

    def _looks_like_content_noise(self, url: str) -> bool:
        lowered = url.lower()
        return any(marker in lowered for marker in ("/privacy", "/terms", "/cookie", "/about", "/contact"))

    def _normalize_candidate_url(self, response: scrapy.http.Response, href: str | None) -> str | None:
        if not href:
            return None
        href = href.strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            return None
        return self._canonicalize_url(response.urljoin(href))

    def _canonicalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        path = re.sub(r"/+", "/", parsed.path or "/")
        clean_params = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            key_lower = key.lower()
            if key_lower.startswith(self.TRACKING_QUERY_PREFIXES):
                continue
            clean_params.append((key, value))
        query = urlencode(sorted(clean_params))
        return urlunparse((parsed.scheme.lower() or "https", parsed.netloc.lower(), path, "", query, ""))

    def _page_number(self, url: str) -> int:
        parsed = urlparse(url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        value = params.get("page")
        if not value:
            return 1
        try:
            return int(value)
        except ValueError:
            return 1

    def _slug_to_name(self, slug: str) -> str:
        return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned or None

    @staticmethod
    def _first_non_empty(*values: str | None) -> str | None:
        for value in values:
            if value:
                return value
        return None

    def _limit_reached(self) -> bool:
        return not self.full_crawl and self.records_emitted >= self.max_records
