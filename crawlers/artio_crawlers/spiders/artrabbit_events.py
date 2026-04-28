from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import scrapy

from artio_crawlers.items import EventItem, GalleryItem
from artio_crawlers.utils.hashing import content_hash


class ArtRabbitEventsSpider(scrapy.Spider):
    name = "art_rabbit_events"
    allowed_domains = ["artrabbit.com"]

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
    }

    DATE_RANGE_PATTERN = re.compile(
        r"(?P<start>\d{1,2}\s+[A-Za-z]+\s+\d{4})\s*(?:-|to|–)\s*(?P<end>\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        re.IGNORECASE,
    )
    SINGLE_DATE_PATTERN = re.compile(r"\b(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b")
    OPENING_PATTERN = re.compile(
        r"(?:opening|starts?)\s*[:\-]?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4}(?:\s+\d{1,2}:\d{2})?)",
        re.IGNORECASE,
    )

    EVENT_TYPE_KEYWORDS = {
        "exhibition": ["exhibition", "exhibitions", "student show"],
        "art fair": ["art fair", "art-fairs", "fair"],
        "biennial": ["biennial"],
        "talk": ["talk", "conference", "screening"],
        "workshop": ["workshop", "art tour"],
        "event": ["event", "events"],
    }

    SOCIAL_HOSTS = {
        "instagram.com": "instagram_url",
        "www.instagram.com": "instagram_url",
        "facebook.com": "facebook_url",
        "www.facebook.com": "facebook_url",
    }

    FOOTER_HINTS = {"footer", "site-footer", "global-footer", "bottom-links"}

    def __init__(
        self,
        crawl_run_id=None,
        city="london",
        country="united-kingdom",
        max_pages=5,
        max_records=200,
        full_crawl=False,
        use_sample_data=False,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.crawl_run_id = crawl_run_id
        self.city = city
        self.country = country
        self.max_pages = int(max_pages) if int(max_pages) > 0 else 5
        self.max_records = int(max_records) if int(max_records) > 0 else 200
        self.full_crawl = str(full_crawl).lower() in {"true", "1", "yes"}
        self.use_sample_data = str(use_sample_data).lower() in {"true", "1", "yes"}

        base = f"https://www.artrabbit.com"
        self.start_urls = [
            f"{base}/all-listings/{self.country}/{self.city}",
            f"{base}/exhibitions/{self.country}/{self.city}",
            f"{base}/talks/{self.country}/{self.city}/upcoming",
            f"{base}/workshops/{self.country}/{self.city}/upcoming",
            f"{base}/art-fairs/{self.country}/{self.city}",
        ]

        self._seen_event_urls: set[str] = set()
        self._listing_pages_seen: set[str] = set()
        self._pages_crawled = 0
        self._records_emitted = 0

    def parse(self, response: scrapy.http.Response):
        page_url = self._canonical_page_url(response.url)
        if page_url in self._listing_pages_seen:
            return

        if self._pages_crawled >= self.max_pages and not self.full_crawl:
            return

        self._listing_pages_seen.add(page_url)
        self._pages_crawled += 1

        event_links = self._extract_event_links(response)
        for url in event_links:
            if self._limit_reached():
                break
            if url in self._seen_event_urls:
                continue
            self._seen_event_urls.add(url)
            yield response.follow(url, callback=self.parse_detail)

        if self._limit_reached():
            return

        next_link = response.css("a[rel='next']::attr(href), a.next::attr(href)").get()
        if next_link:
            yield response.follow(next_link, callback=self.parse)

        parsed = urlparse(response.url)
        query = parse_qs(parsed.query)
        current_page = int((query.get("page") or ["1"])[0])
        if self.full_crawl or self._pages_crawled < self.max_pages:
            next_page = current_page + 1
            query["page"] = [str(next_page)]
            auto_next = parsed._replace(query=urlencode({k: v[0] for k, v in query.items()})).geturl()
            if self._canonical_page_url(auto_next) not in self._listing_pages_seen:
                yield response.follow(auto_next, callback=self.parse)

    def parse_detail(self, response: scrapy.http.Response):
        if self._limit_reached():
            return

        title = self._clean(response.css("h1::text, meta[property='og:title']::attr(content), title::text").get())
        page_text = "\n".join(self._text_blocks(response))
        event_type = self._extract_event_type(response, page_text)
        start_date, end_date, opening_dt = self._extract_dates(response, page_text)

        venue_block = response.css("[class*='venue'], [class*='location'], [data-testid*='venue']")
        venue_text = " ".join(t.strip() for t in venue_block.css("::text").getall() if t.strip())
        venue_name = self._first_non_empty(
            self._clean(response.css("[itemprop='name']::text").get()),
            self._clean(venue_block.css("h2::text, h3::text, strong::text, a::text").get()),
            self._extract_after_label(page_text, ["Venue", "Gallery"]),
        )
        venue_address = self._first_non_empty(
            self._clean(response.css("[itemprop='streetAddress']::text").get()),
            self._extract_after_label(page_text, ["Address"]),
            self._extract_address_like_line(page_text),
        )

        city = self._first_non_empty(
            self._clean(response.css("[itemprop='addressLocality']::text").get()),
            self._extract_after_label(page_text, ["City"]),
            self.city.replace("-", " ").title(),
        )
        country = self._first_non_empty(
            self._clean(response.css("[itemprop='addressCountry']::text").get()),
            self._extract_after_label(page_text, ["Country"]),
            self.country.replace("-", " ").title(),
        )

        description = self._first_non_empty(
            self._clean(response.css("meta[name='description']::attr(content)").get()),
            "\n".join(self._text_blocks(response.css("article, main, [class*='description']"))[:8]),
            page_text[:2000],
        )
        image_url = response.css("meta[property='og:image']::attr(content), article img::attr(src), img::attr(src)").get()
        image_url = response.urljoin(image_url) if image_url else None

        source_record_id = self._event_source_record_id(response.url)
        raw_payload = {
            "event_category_text": self._clean(response.css("[class*='category']::text").get()),
            "venue_block_text": venue_text,
            "detail_links": [response.urljoin(h) for h in response.css("a::attr(href)").getall() if h],
        }

        event_item = EventItem()
        event_item["crawl_run_id"] = self.crawl_run_id
        event_item["source_name"] = "ArtRabbit"
        event_item["source_domain"] = "artrabbit.com"
        event_item["source_url"] = response.url
        event_item["source_record_id"] = source_record_id
        event_item["event_type"] = event_type
        event_item["event_title"] = title
        event_item["venue_name"] = venue_name
        event_item["venue_address"] = venue_address
        event_item["city"] = city
        event_item["country"] = country
        event_item["start_date"] = start_date
        event_item["end_date"] = end_date
        event_item["opening_datetime"] = opening_dt
        event_item["description"] = description
        event_item["image_url"] = image_url
        event_item["raw_payload"] = raw_payload
        event_item["content_hash"] = content_hash(response.url, title, event_type, start_date, end_date, venue_name)
        event_item["crawl_timestamp"] = datetime.now(UTC).isoformat()
        yield event_item

        gallery_item = self._build_gallery_item(response, venue_name, venue_address, city, country, description, venue_text)
        if gallery_item is not None:
            yield gallery_item

        self._records_emitted += 1

    def _extract_event_links(self, response: scrapy.http.Response) -> list[str]:
        links: list[str] = []
        for href in response.css("a::attr(href)").getall():
            if not href:
                continue
            absolute = response.urljoin(href.strip())
            parsed = urlparse(absolute)
            if not parsed.netloc.endswith("artrabbit.com"):
                continue
            if "/events/" not in parsed.path.lower():
                continue
            links.append(parsed._replace(fragment="").geturl().rstrip("/"))
        return list(dict.fromkeys(links))

    def _build_gallery_item(
        self,
        response: scrapy.http.Response,
        venue_name: str | None,
        venue_address: str | None,
        city: str | None,
        country: str | None,
        description: str | None,
        venue_text: str,
    ) -> GalleryItem | None:
        if not venue_name:
            return None

        social_links = self._extract_social_links_near_venue(response)
        website_url = self._extract_venue_website(response)

        key = self._slugify("-".join(filter(None, [venue_name, city or "", country or ""])))
        gallery_item = GalleryItem()
        gallery_item["crawl_run_id"] = self.crawl_run_id
        gallery_item["source_domain"] = "artrabbit.com"
        gallery_item["source_url"] = website_url or response.url
        gallery_item["source_record_id"] = f"artrabbit:gallery:{key}"
        gallery_item["gallery_name"] = venue_name
        gallery_item["address"] = venue_address
        gallery_item["city"] = city
        gallery_item["region"] = None
        gallery_item["country"] = country
        gallery_item["phone"] = None
        gallery_item["email"] = None
        gallery_item["website_url"] = website_url
        gallery_item["instagram_url"] = social_links.get("instagram_url")
        gallery_item["facebook_url"] = social_links.get("facebook_url")
        gallery_item["contact_person"] = None
        gallery_item["description"] = description
        gallery_item["raw_payload"] = {
            "event_source_url": response.url,
            "venue_block_text": venue_text,
        }
        gallery_item["crawl_timestamp"] = datetime.now(UTC).isoformat()
        return gallery_item

    def _extract_venue_website(self, response: scrapy.http.Response) -> str | None:
        scopes = response.css("[class*='venue'], [class*='location'], [data-testid*='venue'], article, main")
        for href in scopes.css("a::attr(href)").getall():
            if not href:
                continue
            url = response.urljoin(href)
            parsed = urlparse(url)
            host = parsed.netloc.lower()
            if not host:
                continue
            if host.endswith("artrabbit.com"):
                continue
            if any(s in host for s in ["instagram.com", "facebook.com", "twitter.com", "linkedin.com", "pinterest.com"]):
                continue
            return url
        return None

    def _extract_social_links_near_venue(self, response: scrapy.http.Response) -> dict[str, str]:
        socials: dict[str, str] = {}
        scope_selectors = [
            "[class*='venue'] a::attr(href)",
            "[class*='location'] a::attr(href)",
            "[data-testid*='venue'] a::attr(href)",
            "article a::attr(href)",
            "main a::attr(href)",
        ]
        for selector in scope_selectors:
            for href in response.css(selector).getall():
                if not href:
                    continue
                url = response.urljoin(href)
                lower_url = url.lower()
                if any(hint in lower_url for hint in self.FOOTER_HINTS):
                    continue
                host = urlparse(url).netloc.lower()
                field = self.SOCIAL_HOSTS.get(host)
                if not field:
                    continue
                if self._link_looks_like_footer(href):
                    continue
                socials.setdefault(field, url)
        return socials

    def _link_looks_like_footer(self, href: str) -> bool:
        lowered = href.lower()
        return any(hint in lowered for hint in self.FOOTER_HINTS)

    def _extract_event_type(self, response: scrapy.http.Response, page_text: str) -> str:
        candidates = " ".join(
            filter(
                None,
                [
                    response.url.lower(),
                    page_text.lower(),
                    self._clean(response.css("meta[property='og:type']::attr(content)").get()),
                    self._clean(response.css("[class*='category']::text").get()),
                ],
            )
        )
        for event_type, keywords in self.EVENT_TYPE_KEYWORDS.items():
            if any(keyword in candidates for keyword in keywords):
                return event_type
        return "event"

    def _extract_dates(self, response: scrapy.http.Response, page_text: str):
        text = " ".join(filter(None, [page_text, " ".join(response.css("time::text").getall())]))

        match = self.DATE_RANGE_PATTERN.search(text)
        if match:
            start = self._parse_date(match.group("start"))
            end = self._parse_date(match.group("end"))
            return start, end, self._parse_opening_dt(text)

        single = self.SINGLE_DATE_PATTERN.search(text)
        if single:
            day = self._parse_date(single.group(1))
            return day, day, self._parse_opening_dt(text)

        return None, None, self._parse_opening_dt(text)

    def _parse_opening_dt(self, text: str):
        match = self.OPENING_PATTERN.search(text)
        if not match:
            return None
        raw = match.group(1)
        for fmt in ["%d %B %Y %H:%M", "%d %b %Y %H:%M", "%d %B %Y", "%d %b %Y"]:
            try:
                dt = datetime.strptime(raw, fmt)
                return dt.replace(tzinfo=UTC)
            except ValueError:
                continue
        return None

    def _parse_date(self, raw: str):
        for fmt in ["%d %B %Y", "%d %b %Y"]:
            try:
                return datetime.strptime(raw.strip(), fmt).date()
            except ValueError:
                continue
        return None

    def _event_source_record_id(self, url: str) -> str:
        slug = urlparse(url).path.strip("/").split("/")[-1]
        slug = self._slugify(slug)
        if not slug:
            slug = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        return f"artrabbit:event:{slug}"

    def _canonical_page_url(self, url: str) -> str:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        page_value = query.get("page", ["1"])[0]
        normalized_query = urlencode({"page": page_value}) if page_value and page_value != "1" else ""
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", normalized_query, ""))

    def _extract_after_label(self, text: str, labels: list[str]) -> str | None:
        for label in labels:
            match = re.search(rf"{label}\s*:\s*([^\n|]+)", text, flags=re.IGNORECASE)
            if match:
                return self._clean(match.group(1))
        return None

    def _extract_address_like_line(self, text: str) -> str | None:
        for line in text.splitlines():
            clean_line = self._clean(line)
            if not clean_line:
                continue
            if any(token in clean_line.lower() for token in ["street", "road", "rd", "ave", "avenue", "lane"]):
                return clean_line
        return None

    def _text_blocks(self, selector) -> list[str]:
        blocks: list[str] = []
        for value in selector.css("p::text, li::text, div::text, span::text").getall():
            cleaned = self._clean(value)
            if cleaned:
                blocks.append(cleaned)
        return blocks

    def _clean(self, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned or None

    def _first_non_empty(self, *values: str | None) -> str | None:
        for value in values:
            cleaned = self._clean(value)
            if cleaned:
                return cleaned
        return None

    def _slugify(self, value: str) -> str:
        lowered = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
        return re.sub(r"-{2,}", "-", lowered)

    def _limit_reached(self) -> bool:
        return (not self.full_crawl) and self._records_emitted >= self.max_records
