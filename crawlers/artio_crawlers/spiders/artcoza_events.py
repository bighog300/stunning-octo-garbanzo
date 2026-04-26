from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import re
from urllib.parse import parse_qs, urlparse

import scrapy

from artio_crawlers.items import EventArtistItem, EventImageItem, EventItem
from artio_crawlers.utils.hashing import content_hash


class ArtCoZaEventsSpider(scrapy.Spider):
    name = "artcoza_events"
    allowed_domains = ["art.co.za", "www.art.co.za"]
    start_urls = [
        "https://www.art.co.za/exhibitions/",
        "https://www.art.co.za/exhibitions/running.php",
        "https://www.art.co.za/galleries/opening.php",
        "https://www.art.co.za/galleries/running.php",
        "https://www.art.co.za/training/",
        "https://www.art.co.za/news/",
    ]

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 1.5,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
    }

    MONTH_PATTERN = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

    def __init__(self, max_records=100, crawl_run_id=None, dry_run=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_records = int(max_records) if int(max_records) > 0 else 100
        self.crawl_run_id = crawl_run_id
        self.dry_run = str(dry_run).lower() in {"true", "1", "yes"}
        self._records_emitted = 0
        self._seen_event_urls: set[str] = set()

    def parse(self, response: scrapy.http.Response):
        if self._limit_reached():
            return

        listing_cards = response.css("article, .event, .listing, .news-item, .training-item, .exhibition")
        for card in listing_cards:
            detail_href = card.css("a::attr(href)").get()
            detail_url = response.urljoin(detail_href) if detail_href else None
            if not detail_url:
                continue
            if detail_url in self._seen_event_urls:
                continue
            self._seen_event_urls.add(detail_url)
            listing_data = self._extract_listing_card_data(response, card)
            yield response.follow(detail_url, callback=self.parse_detail, meta={"listing": listing_data})

        fallback_links = self._extract_candidate_event_links(response)
        for detail_url in fallback_links:
            if self._limit_reached():
                break
            if detail_url in self._seen_event_urls:
                continue
            self._seen_event_urls.add(detail_url)
            yield response.follow(detail_url, callback=self.parse_detail, meta={"listing": {}})

        next_page = response.css("a.next::attr(href), a[rel='next']::attr(href)").get()
        if next_page and not self._limit_reached():
            yield response.follow(next_page, callback=self.parse)

    def parse_detail(self, response: scrapy.http.Response):
        if self._limit_reached():
            return

        listing_data = response.meta.get("listing") or {}

        title = self._first_non_empty(
            response.css("h1::text, h2::text, title::text").get(),
            listing_data.get("event_title"),
        )
        description_blocks = self._text_blocks(response)
        description = self._first_non_empty(
            "\n".join(description_blocks[:8]).strip(),
            listing_data.get("description"),
        )
        event_type = self._classify_event_type(response.url, title, description)

        venue_name = self._extract_venue_name(response, title)
        venue_address = self._extract_value_after_label(response, ["venue", "address"]) or listing_data.get("venue_address")
        city = self._extract_city(response, venue_address)

        start_date, end_date, opening_dt = self._extract_dates(response, description)

        image_url = self._first_non_empty(
            response.css("meta[property='og:image']::attr(content), article img::attr(src), .content img::attr(src), img::attr(src)").get(),
            listing_data.get("image_url"),
        )
        if image_url:
            image_url = response.urljoin(image_url)

        artists = self._extract_artist_candidates(response, description)
        source_record_id = self._build_source_record_id(response.url, event_type, title)

        payload = {
            "listing": listing_data,
            "detail_text_blocks": description_blocks,
            "detail_links": [response.urljoin(h) for h in response.css("a::attr(href)").getall() if h],
            "artists_raw": artists,
        }

        event_item = EventItem()
        event_item["crawl_run_id"] = self.crawl_run_id
        event_item["source_name"] = "Art.co.za"
        event_item["source_domain"] = "art.co.za"
        event_item["source_url"] = response.url
        event_item["source_record_id"] = source_record_id
        event_item["event_type"] = event_type
        event_item["event_title"] = title
        event_item["venue_name"] = venue_name
        event_item["venue_address"] = venue_address
        event_item["city"] = city
        event_item["country"] = "South Africa"
        event_item["start_date"] = start_date
        event_item["end_date"] = end_date
        event_item["opening_datetime"] = opening_dt
        event_item["description"] = description
        event_item["image_url"] = image_url
        event_item["raw_payload"] = payload
        event_item["content_hash"] = content_hash(response.url, title, description, start_date, end_date, image_url)
        event_item["crawl_timestamp"] = datetime.now(UTC).isoformat()
        yield event_item

        for artist in artists:
            name = artist.get("name")
            if not name:
                continue
            artist_item = EventArtistItem()
            artist_item["event_source_record_id"] = source_record_id
            artist_item["event_source_url"] = response.url
            artist_item["artist_name"] = name
            artist_item["artist_name_normalized"] = self._normalize_artist_name(name)
            artist_item["artist_profile_url"] = artist.get("profile_url")
            artist_item["match_type"] = "parsed"
            yield artist_item

        if image_url:
            image_item = EventImageItem()
            image_item["event_source_record_id"] = source_record_id
            image_item["event_source_url"] = response.url
            image_item["image_url"] = image_url
            image_item["image_caption"] = response.css("figcaption::text").get()
            image_item["image_type"] = "primary"
            image_item["content_hash"] = content_hash(response.url, image_url, title)
            yield image_item

        self._records_emitted += 1

    def _extract_candidate_event_links(self, response: scrapy.http.Response) -> list[str]:
        links = []
        for href in response.css("a::attr(href)").getall():
            url = response.urljoin(href)
            if not url.startswith("http"):
                continue
            if "art.co.za" not in url:
                continue
            if url.rstrip("/") == response.url.rstrip("/"):
                continue
            path = urlparse(url).path.lower()
            if any(token in path for token in ["exhibitions", "galleries", "training", "news", "opening", "running"]):
                links.append(url)
        return list(dict.fromkeys(links))

    def _extract_listing_card_data(self, response: scrapy.http.Response, card: scrapy.selector.Selector) -> dict:
        title = self._first_non_empty(card.css("h1::text, h2::text, h3::text, a::text").get())
        description = self._first_non_empty(" ".join(t.strip() for t in card.css("p::text, .description::text").getall() if t.strip()))
        image = card.css("img::attr(src)").get()
        if image:
            image = response.urljoin(image)
        return {
            "event_title": title,
            "description": description,
            "image_url": image,
        }

    def _extract_artist_candidates(self, response: scrapy.http.Response, description: str | None) -> list[dict[str, str | None]]:
        artists: dict[str, dict[str, str | None]] = {}

        for anchor in response.css("a[href]"):
            href = anchor.attrib.get("href")
            if not href:
                continue
            absolute = response.urljoin(href)
            text = self._clean_text(anchor.css("::text").get())
            if not text:
                continue
            if self._is_artist_profile_url(absolute):
                artists[text] = {"name": text, "profile_url": absolute}

        text_sources = [description or ""] + response.css("p::text, li::text").getall()
        for raw_text in text_sources:
            for name in self._split_artist_names(raw_text):
                artists.setdefault(name, {"name": name, "profile_url": None})

        return list(artists.values())

    def _extract_dates(self, response: scrapy.http.Response, description: str | None) -> tuple[datetime.date | None, datetime.date | None, datetime | None]:
        text = " ".join(self._text_blocks(response))
        if description:
            text = f"{text} {description}"

        range_match = re.search(
            rf"(\d{{1,2}}\s+{self.MONTH_PATTERN}\s+\d{{4}})\s*(?:-|to|until)\s*(\d{{1,2}}\s+{self.MONTH_PATTERN}\s+\d{{4}})",
            text,
            flags=re.IGNORECASE,
        )
        if range_match:
            start = self._parse_date(range_match.group(1))
            end = self._parse_date(range_match.group(2))
            return start, end, None

        single_match = re.search(rf"(\d{{1,2}}\s+{self.MONTH_PATTERN}\s+\d{{4}})", text, flags=re.IGNORECASE)
        start = self._parse_date(single_match.group(1)) if single_match else None

        opening_match = re.search(
            rf"opening[^\d]*(\d{{1,2}}\s+{self.MONTH_PATTERN}\s+\d{{4}})(?:[^\d]*(\d{{1,2}}[:.]\d{{2}}\s*(?:am|pm)?))?",
            text,
            flags=re.IGNORECASE,
        )
        opening_dt = None
        if opening_match:
            date_part = opening_match.group(1)
            time_part = opening_match.group(2)
            opening_dt = self._parse_datetime(date_part, time_part)

        return start, start, opening_dt

    @staticmethod
    def _parse_date(value: str | None):
        if not value:
            return None
        for fmt in ("%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
        return None

    @classmethod
    def _parse_datetime(cls, date_part: str | None, time_part: str | None):
        parsed_date = cls._parse_date(date_part)
        if not parsed_date:
            return None
        if not time_part:
            return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC)

        cleaned_time = time_part.replace(".", ":").strip().lower()
        for fmt in ("%I:%M %p", "%H:%M"):
            try:
                parsed_time = datetime.strptime(cleaned_time, fmt)
                return datetime(
                    parsed_date.year,
                    parsed_date.month,
                    parsed_date.day,
                    parsed_time.hour,
                    parsed_time.minute,
                    tzinfo=UTC,
                )
            except ValueError:
                continue
        return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC)

    def _extract_venue_name(self, response: scrapy.http.Response, title: str | None) -> str | None:
        venue = self._extract_value_after_label(response, ["venue", "gallery"]) or response.css(".venue::text").get()
        return self._clean_text(venue) or self._clean_text(title)

    def _extract_value_after_label(self, response: scrapy.http.Response, labels: list[str]) -> str | None:
        text_blocks = self._text_blocks(response)
        for block in text_blocks:
            lower_block = block.lower()
            for label in labels:
                token = f"{label}:"
                if token in lower_block:
                    after = block[lower_block.find(token) + len(token) :].strip(" -")
                    if after:
                        return after
        return None

    def _extract_city(self, response: scrapy.http.Response, venue_address: str | None) -> str | None:
        text = " ".join(self._text_blocks(response))
        for city in ["Cape Town", "Johannesburg", "Pretoria", "Durban", "Stellenbosch", "Port Elizabeth"]:
            if city.lower() in text.lower() or (venue_address and city.lower() in venue_address.lower()):
                return city
        return None

    @classmethod
    def _classify_event_type(cls, url: str, title: str | None, description: str | None) -> str:
        lower_url = url.lower()
        text = f"{title or ''} {description or ''}".lower()

        if "opening.php" in lower_url:
            return "opening"
        if "training" in lower_url:
            if "workshop" in text or "class" in text:
                return "workshop"
            return "training"
        if "news" in lower_url:
            return "news"
        if "running.php" in lower_url or "/exhibitions" in lower_url:
            if "workshop" in text or "class" in text:
                return "workshop"
            return "exhibition"
        if "workshop" in text or "class" in text:
            return "workshop"
        return "event"

    @staticmethod
    def _normalize_artist_name(name: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
        return re.sub(r"\s+", " ", normalized)

    def _split_artist_names(self, text: str | None) -> list[str]:
        if not text:
            return []
        normalized_text = re.sub(r"\s+", " ", text).strip()
        if not normalized_text:
            return []
        if not any(token in normalized_text.lower() for token in ["artist", "featuring", "with", "participants", "by"]):
            return []

        candidate = re.split(r"artists?:|featuring|participants?:|with|by", normalized_text, flags=re.IGNORECASE)
        target = candidate[-1] if candidate else normalized_text
        names = re.split(r",|;| and | & ", target)

        cleaned = []
        for name in names:
            name = self._clean_text(name)
            if not name:
                continue
            if len(name) < 3:
                continue
            if any(char.isdigit() for char in name):
                continue
            if name.lower() in {"opening", "running", "news", "training", "class", "workshop"}:
                continue
            cleaned.append(name)
        return cleaned

    @staticmethod
    def _is_artist_profile_url(url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc not in {"art.co.za", "www.art.co.za"}:
            return False
        path = parsed.path.strip("/")
        if not path or "/" in path:
            return False
        return not path.endswith(".php")

    def _build_source_record_id(self, source_url: str, event_type: str, title: str | None) -> str:
        parsed = urlparse(source_url)
        query = parse_qs(parsed.query)
        nom_value = (query.get("nom") or [None])[0]
        slug = parsed.path.strip("/").split("/")[-1] if parsed.path.strip("/") else None
        slug = slug.replace(".php", "") if slug else None
        title_slug = self._slugify(title) if title else None
        fallback_hash = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:16]
        stable = nom_value or slug or title_slug or fallback_hash
        return f"art.co.za:event:{event_type}:{stable}"

    @staticmethod
    def _slugify(text: str | None) -> str | None:
        if not text:
            return None
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        return slug or None

    @staticmethod
    def _first_non_empty(*values):
        for value in values:
            cleaned = ArtCoZaEventsSpider._clean_text(value)
            if cleaned:
                return cleaned
        return None

    @staticmethod
    def _clean_text(value: str | None) -> str | None:
        if value is None:
            return None
        collapsed = re.sub(r"\s+", " ", value).strip()
        return collapsed or None

    def _text_blocks(self, response: scrapy.http.Response) -> list[str]:
        raw = response.css("h1::text, h2::text, h3::text, p::text, li::text, .content::text").getall()
        blocks = [self._clean_text(text) for text in raw]
        return [block for block in blocks if block]

    def _limit_reached(self) -> bool:
        return self.max_records > 0 and self._records_emitted >= self.max_records
