from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import scrapy

from artio_crawlers.items import ArtworkItem, GalleryItem
from artio_crawlers.utils.hashing import content_hash


class ArtUkArtworksSpider(scrapy.Spider):
    name = "artuk_artworks"
    allowed_domains = ["artuk.org", "www.artuk.org"]

    custom_settings = {
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 3,
        "AUTOTHROTTLE_MAX_DELAY": 30,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 0.5,
        "DOWNLOAD_DELAY": 3,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 2,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "RETRY_HTTP_CODES": [429, 500, 502, 503, 504, 522, 524, 408],
        "RETRY_TIMES": 4,
        "ROBOTSTXT_OBEY": True,
    }

    TRACKING_QUERY_PREFIXES = ("utm_", "gclid", "fbclid", "mc_", "_hs")
    ARTWORK_PATH_RE = re.compile(r"^/(discover/artworks|artwork)/[^?#]+", re.IGNORECASE)
    ARTIST_PATH_RE = re.compile(r"^/discover/artists/[^?#]+", re.IGNORECASE)
    COLLECTION_PATH_RE = re.compile(r"^/visit/venues/[^?#]+", re.IGNORECASE)
    LISTING_PATH_HINTS = (
        "/discover/artworks",
        "/discover/artists",
        "/visit/venues",
        "/search",
    )
    DISALLOWED_PATH_HINTS = (
        "/log-in",
        "/login",
        "/account",
        "/shop",
        "/cart",
        "/donate",
        "/support-us",
        "/stories",
        "/story/",
        "/editorial",
    )

    SAMPLE_ITEMS = [
        {
            "source_url": "https://artuk.org/discover/artworks/sample-landscape-1",
            "source_record_id": "artuk:artwork:sample-landscape-1",
            "artwork_title": "Sample Landscape",
            "artist_name": "Sample Artist",
            "artist_source_url": "https://artuk.org/discover/artists/sample-artist",
            "artwork_date_text": "c. 1955",
            "medium_text": "Oil on canvas",
            "dimensions_text": "60 x 80 cm",
            "gallery_name": "Sample Museum",
            "collection_source_url": "https://artuk.org/visit/venues/sample-museum",
            "image_url": "https://media.artuk.org/sample-1.jpg",
            "description": "Sample artwork record for dry, scoped pipeline testing.",
        },
        {
            "source_url": "https://artuk.org/discover/artworks/sample-portrait-2",
            "source_record_id": "artuk:artwork:sample-portrait-2",
            "artwork_title": "Sample Portrait",
            "artist_name": "Another Artist",
            "artist_source_url": "https://artuk.org/discover/artists/another-artist",
            "artwork_date_text": "1972",
            "medium_text": "Acrylic on panel",
            "dimensions_text": "40 x 35 cm",
            "gallery_name": "Sample Collection",
            "collection_source_url": "https://artuk.org/visit/venues/sample-collection",
            "image_url": "https://media.artuk.org/sample-2.jpg",
            "description": "Secondary sample record.",
        },
    ]

    def __init__(
        self,
        crawl_run_id=None,
        max_pages=5,
        max_records=100,
        full_crawl=False,
        use_sample_data=False,
        search_query="",
        artist_slug=None,
        collection_slug=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.crawl_run_id = crawl_run_id
        self.max_pages = int(max_pages) if int(max_pages) > 0 else 5
        self.max_records = int(max_records) if int(max_records) > 0 else 100
        self.full_crawl = str(full_crawl).lower() in {"true", "1", "yes"}
        self.use_sample_data = str(use_sample_data).lower() in {"true", "1", "yes"}
        self.search_query = (search_query or "").strip()
        self.artist_slug = (artist_slug or "").strip(" /") or None
        self.collection_slug = (collection_slug or "").strip(" /") or None

        self._seen_listing_urls: set[str] = set()
        self._queued_listing_urls: set[str] = set()
        self._seen_artwork_urls: set[str] = set()
        self._emitted_artwork_keys: set[str] = set()
        self._emitted_collection_keys: set[str] = set()
        self._records_emitted = 0

    def start_requests(self):
        if self.use_sample_data:
            yield scrapy.Request("https://example.com/", callback=self.parse_sample_data, dont_filter=True)
            return

        for url in self._start_listing_urls():
            canonical = self._canonicalize_url(url)
            self._queued_listing_urls.add(canonical)
            yield scrapy.Request(canonical, callback=self.parse)

    def parse_sample_data(self, response: scrapy.http.Response):
        del response
        for idx in range(self.max_records):
            sample = self.SAMPLE_ITEMS[idx % len(self.SAMPLE_ITEMS)]
            record_id = sample["source_record_id"]
            item = ArtworkItem()
            item["crawl_run_id"] = self.crawl_run_id
            item["source_name"] = "Art UK"
            item["source_domain"] = "artuk.org"
            item["source_url"] = sample["source_url"]
            item["source_record_id"] = record_id
            item["artist_name"] = sample["artist_name"]
            item["artwork_title"] = sample["artwork_title"]
            item["artwork_date_text"] = sample["artwork_date_text"]
            item["medium_text"] = sample["medium_text"]
            item["dimensions_text"] = sample["dimensions_text"]
            item["price_text"] = None
            item["currency_text"] = None
            item["gallery_name"] = sample["gallery_name"]
            item["institution_name"] = sample["gallery_name"]
            item["department_name"] = None
            item["image_url"] = sample["image_url"]
            item["thumbnail_url"] = sample["image_url"]
            item["description"] = sample["description"]
            item["raw_payload"] = {
                "sample": True,
                "artist_source_url": sample["artist_source_url"],
                "collection_source_url": sample["collection_source_url"],
            }
            item["content_hash"] = content_hash(record_id, sample["artwork_title"], sample["artist_name"], sample["image_url"])
            item["crawl_timestamp"] = datetime.now(UTC).isoformat()
            yield item

    def parse(self, response: scrapy.http.Response):
        listing_url = self._canonicalize_url(response.url)
        if listing_url in self._seen_listing_urls:
            return

        page_number = self._page_number(listing_url)
        if not self.full_crawl and page_number > self.max_pages:
            return

        self._seen_listing_urls.add(listing_url)

        artwork_links = self._extract_artwork_links(response)
        new_artwork_links = [url for url in artwork_links if url not in self._seen_artwork_urls]

        if not artwork_links or not new_artwork_links:
            return

        for url in new_artwork_links:
            if self._limit_reached():
                return
            self._seen_artwork_urls.add(url)
            yield response.follow(url, callback=self.parse_artwork)

        if self._limit_reached():
            return

        if not self.full_crawl and page_number >= self.max_pages:
            return

        for next_url in self._extract_pagination_links(response):
            if next_url in self._seen_listing_urls or next_url in self._queued_listing_urls:
                continue
            self._queued_listing_urls.add(next_url)
            yield response.follow(next_url, callback=self.parse)

    def parse_artwork(self, response: scrapy.http.Response):
        if self._limit_reached():
            return

        canonical_url = self._canonicalize_url(response.url)
        if not self._is_artwork_detail_url(canonical_url):
            return

        json_ld_blocks = self._json_ld(response)
        artwork_data = self._first_json_ld_type(json_ld_blocks, {"VisualArtwork", "CreativeWork", "Product"})
        artist_data = self._first_json_ld_type(json_ld_blocks, {"Person"})
        place_data = self._first_json_ld_type(json_ld_blocks, {"Place", "Organization", "Museum"})

        title = self._first_non_empty(
            self._clean(self._json_value(artwork_data, "name")),
            self._clean(response.css("h1::text").get()),
            self._clean(response.css("meta[property='og:title']::attr(content)").get()),
        )
        artist_name = self._first_non_empty(
            self._clean(self._extract_artist_name_from_json_ld(artwork_data)),
            self._clean(response.css("a[href*='/discover/artists/']::text").get()),
            self._clean(response.css("[itemprop='creator']::text").get()),
        )

        artist_source_url = self._first_non_empty(
            self._absolute_json_url(response, self._extract_artist_url_from_json_ld(artwork_data)),
            self._extract_first_matching_link(response, self._is_artist_detail_url),
        )

        collection_source_url = self._first_non_empty(
            self._absolute_json_url(response, self._extract_collection_url_from_json_ld(artwork_data)),
            self._extract_first_matching_link(response, self._is_collection_detail_url),
        )

        collection_name = self._first_non_empty(
            self._clean(self._extract_collection_name_from_json_ld(artwork_data)),
            self._clean(self._json_value(place_data, "name")),
            self._clean(response.css("a[href*='/visit/venues/']::text").get()),
        )

        date_text = self._first_non_empty(
            self._clean(self._json_value(artwork_data, "dateCreated")),
            self._extract_labeled_text(response, ("Date", "Date displayed")),
        )

        medium = self._first_non_empty(
            self._clean(self._json_value(artwork_data, "artMedium")),
            self._extract_labeled_text(response, ("Medium", "Materials")),
        )
        dimensions = self._first_non_empty(
            self._clean(self._json_value(artwork_data, "size")),
            self._extract_labeled_text(response, ("Dimensions", "Size")),
        )
        description = self._first_non_empty(
            self._clean(self._json_value(artwork_data, "description")),
            self._clean(response.css("meta[name='description']::attr(content)").get()),
        )

        image_url = self._first_non_empty(
            self._absolute_json_url(response, self._json_value(artwork_data, "image")),
            self._absolute_json_url(response, response.css("meta[property='og:image']::attr(content)").get()),
            self._extract_primary_image(response),
        )

        record_slug = self._slug_from_url(canonical_url) or self._stable_id(canonical_url)
        source_record_id = f"artuk:artwork:{record_slug}"
        if source_record_id in self._emitted_artwork_keys:
            return
        self._emitted_artwork_keys.add(source_record_id)

        raw_payload = {
            "artist_source_url": artist_source_url,
            "collection_source_url": collection_source_url,
            "artist_structured": artist_data,
            "collection_structured": place_data,
            "json_ld_types": sorted(self._json_ld_types(json_ld_blocks)),
            "detail_page_links": self._detail_links_snapshot(response),
            "raw_title": self._clean(response.css("title::text").get()),
            # TODO: add first-class ArtistItem ingestion once raw artists pipeline exists.
            "artist_metadata": {
                "artist_name": artist_name,
                "birth_year": self._parse_artist_year(artist_data, "birthDate"),
                "death_year": self._parse_artist_year(artist_data, "deathDate"),
                "nationality": self._clean(self._json_value(artist_data, "nationality")),
                "artist_source_record_id": self._artist_source_record_id(artist_source_url),
            },
        }

        item = ArtworkItem()
        item["crawl_run_id"] = self.crawl_run_id
        item["source_name"] = "Art UK"
        item["source_domain"] = "artuk.org"
        item["source_url"] = canonical_url
        item["source_record_id"] = source_record_id
        item["artist_name"] = artist_name
        item["artwork_title"] = title
        item["artwork_date_text"] = date_text
        item["medium_text"] = medium
        item["dimensions_text"] = dimensions
        item["price_text"] = None
        item["currency_text"] = None
        item["gallery_name"] = collection_name
        item["institution_name"] = collection_name
        item["department_name"] = None
        item["image_url"] = image_url
        item["thumbnail_url"] = image_url
        item["description"] = description
        item["raw_payload"] = raw_payload
        item["content_hash"] = content_hash(source_record_id, title, artist_name, date_text, medium, image_url)
        item["crawl_timestamp"] = datetime.now(UTC).isoformat()

        self._records_emitted += 1
        yield item

        gallery_item = self._build_gallery_item(response, collection_name, collection_source_url, place_data)
        if gallery_item is not None:
            yield gallery_item

    def _build_gallery_item(self, response: scrapy.http.Response, collection_name: str | None, collection_source_url: str | None, place_data: dict | None) -> GalleryItem | None:
        if not collection_name:
            return None

        gallery_key = self._collection_source_record_id(collection_source_url or response.url)
        if gallery_key in self._emitted_collection_keys:
            return None
        self._emitted_collection_keys.add(gallery_key)

        address = self._first_non_empty(
            self._json_address(place_data),
            self._extract_labeled_text(response, ("Address", "Collection address")),
        )
        city = self._first_non_empty(
            self._json_address_component(place_data, "addressLocality"),
            self._extract_labeled_text(response, ("City",)),
        )
        country = self._first_non_empty(
            self._json_address_component(place_data, "addressCountry"),
            self._extract_labeled_text(response, ("Country",)),
            "United Kingdom",
        )
        website_url = self._first_non_empty(
            self._absolute_json_url(response, self._json_value(place_data, "url")),
            self._extract_onsite_website_url(response),
        )

        item = GalleryItem()
        item["crawl_run_id"] = self.crawl_run_id
        item["source_domain"] = "artuk.org"
        item["source_url"] = collection_source_url or response.url
        item["source_record_id"] = gallery_key
        item["gallery_name"] = collection_name
        item["address"] = address
        item["city"] = city
        item["region"] = None
        item["country"] = country
        item["phone"] = None
        item["email"] = None
        item["website_url"] = website_url
        item["instagram_url"] = None
        item["facebook_url"] = None
        item["contact_person"] = None
        item["description"] = self._clean(self._json_value(place_data, "description"))
        item["raw_payload"] = {
            "collection_source_url": collection_source_url,
            "place_structured": place_data,
        }
        item["crawl_timestamp"] = datetime.now(UTC).isoformat()
        return item

    def _start_listing_urls(self) -> list[str]:
        base = "https://artuk.org"
        urls: list[str] = []
        if self.artist_slug:
            urls.append(f"{base}/discover/artists/{self.artist_slug}")
        elif self.collection_slug:
            urls.append(f"{base}/visit/venues/{self.collection_slug}")
        elif self.search_query:
            encoded = urlencode({"q": self.search_query})
            urls.append(f"{base}/search/artworks?{encoded}")
        else:
            urls.append(f"{base}/discover/artworks")
        return urls

    def _extract_artwork_links(self, response: scrapy.http.Response) -> list[str]:
        links: list[str] = []
        for href in response.css("a::attr(href)").getall():
            absolute = self._canonicalize_url(response.urljoin(href))
            if self._is_artwork_detail_url(absolute):
                links.append(absolute)
        return list(dict.fromkeys(links))

    def _extract_pagination_links(self, response: scrapy.http.Response) -> list[str]:
        links: list[str] = []
        for href in response.css("a[rel='next']::attr(href), a.next::attr(href), a[aria-label*='Next']::attr(href)").getall():
            absolute = self._canonicalize_url(response.urljoin(href))
            if self._should_follow_listing_url(absolute, current_url=self._canonicalize_url(response.url)):
                links.append(absolute)

        current_page = self._page_number(response.url)
        auto_next = self._with_page(response.url, current_page + 1)
        if auto_next and self._should_follow_listing_url(auto_next, current_url=self._canonicalize_url(response.url)):
            links.append(auto_next)

        return list(dict.fromkeys(links))

    def _should_follow_listing_url(self, url: str, current_url: str) -> bool:
        parsed = urlparse(url)
        if not parsed.netloc.endswith("artuk.org"):
            return False
        if any(hint in parsed.path for hint in self.DISALLOWED_PATH_HINTS):
            return False
        if not any(hint in parsed.path for hint in self.LISTING_PATH_HINTS):
            return False

        current_path = urlparse(current_url).path
        if self.search_query:
            return parsed.path.startswith("/search")
        if self.artist_slug:
            return parsed.path.startswith(f"/discover/artists/{self.artist_slug}")
        if self.collection_slug:
            return parsed.path.startswith(f"/visit/venues/{self.collection_slug}")
        return parsed.path.startswith(current_path.rstrip("/")) or parsed.path.startswith("/discover/artworks")

    def _extract_first_matching_link(self, response: scrapy.http.Response, predicate) -> str | None:
        for href in response.css("a::attr(href)").getall():
            absolute = self._canonicalize_url(response.urljoin(href))
            if predicate(absolute):
                return absolute
        return None

    def _extract_labeled_text(self, response: scrapy.http.Response, labels: tuple[str, ...]) -> str | None:
        lowered = {label.lower() for label in labels}
        for row in response.css("dt, th, li, p, div"):
            text = self._clean(" ".join(row.css("::text").getall()))
            if not text:
                continue
            for label in lowered:
                if text.lower().startswith(f"{label}:"):
                    return self._clean(text.split(":", 1)[-1])
        return None

    def _extract_primary_image(self, response: scrapy.http.Response) -> str | None:
        for src in response.css("main img::attr(src), article img::attr(src), img::attr(src)").getall():
            absolute = self._absolute_json_url(response, src)
            if absolute and "logo" not in absolute and "icon" not in absolute:
                return absolute
        return None

    def _extract_onsite_website_url(self, response: scrapy.http.Response) -> str | None:
        for href in response.css("a::attr(href)").getall():
            absolute = response.urljoin(href)
            parsed = urlparse(absolute)
            if not parsed.scheme.startswith("http"):
                continue
            if parsed.netloc.endswith("artuk.org"):
                continue
            if any(token in absolute.lower() for token in ("facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com")):
                continue
            return absolute
        return None

    def _json_ld(self, response: scrapy.http.Response) -> list[dict]:
        blocks: list[dict] = []
        for raw in response.css("script[type='application/ld+json']::text").getall():
            raw = (raw or "").strip()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            blocks.extend(self._flatten_json_ld(parsed))
        return blocks

    def _flatten_json_ld(self, obj):
        if isinstance(obj, list):
            result = []
            for item in obj:
                result.extend(self._flatten_json_ld(item))
            return result
        if isinstance(obj, dict):
            if isinstance(obj.get("@graph"), list):
                return self._flatten_json_ld(obj["@graph"])
            return [obj]
        return []

    def _first_json_ld_type(self, blocks: list[dict], accepted_types: set[str]) -> dict | None:
        for block in blocks:
            value = block.get("@type")
            types = value if isinstance(value, list) else [value]
            normalized_types = {str(t) for t in types if t}
            if normalized_types.intersection(accepted_types):
                return block
        return None

    def _json_ld_types(self, blocks: list[dict]) -> set[str]:
        result: set[str] = set()
        for block in blocks:
            block_type = block.get("@type")
            if isinstance(block_type, list):
                result.update(str(v) for v in block_type if v)
            elif block_type:
                result.add(str(block_type))
        return result

    def _json_value(self, payload: dict | None, key: str):
        if not payload:
            return None
        value = payload.get(key)
        if isinstance(value, dict):
            return value.get("url") or value.get("name")
        return value

    def _extract_artist_name_from_json_ld(self, artwork_data: dict | None) -> str | None:
        creator = (artwork_data or {}).get("creator")
        if isinstance(creator, dict):
            return self._clean(creator.get("name"))
        if isinstance(creator, list):
            for entry in creator:
                if isinstance(entry, dict) and entry.get("name"):
                    return self._clean(entry.get("name"))
        if isinstance(creator, str):
            return self._clean(creator)
        return None

    def _extract_artist_url_from_json_ld(self, artwork_data: dict | None) -> str | None:
        creator = (artwork_data or {}).get("creator")
        if isinstance(creator, dict):
            return creator.get("url")
        if isinstance(creator, list):
            for entry in creator:
                if isinstance(entry, dict) and entry.get("url"):
                    return entry.get("url")
        return None

    def _extract_collection_name_from_json_ld(self, artwork_data: dict | None) -> str | None:
        location = (artwork_data or {}).get("locationCreated") or (artwork_data or {}).get("location")
        if isinstance(location, dict):
            return self._clean(location.get("name"))
        return None

    def _extract_collection_url_from_json_ld(self, artwork_data: dict | None) -> str | None:
        location = (artwork_data or {}).get("locationCreated") or (artwork_data or {}).get("location")
        if isinstance(location, dict):
            return location.get("url")
        return None

    def _json_address(self, place_data: dict | None) -> str | None:
        addr = (place_data or {}).get("address")
        if isinstance(addr, str):
            return self._clean(addr)
        if not isinstance(addr, dict):
            return None
        ordered = [
            addr.get("streetAddress"),
            addr.get("addressLocality"),
            addr.get("addressRegion"),
            addr.get("postalCode"),
            addr.get("addressCountry"),
        ]
        return self._clean(", ".join(part.strip() for part in ordered if isinstance(part, str) and part.strip()))

    def _json_address_component(self, place_data: dict | None, key: str) -> str | None:
        addr = (place_data or {}).get("address")
        if isinstance(addr, dict):
            return self._clean(addr.get(key))
        return None

    def _artist_source_record_id(self, artist_url: str | None) -> str | None:
        if not artist_url:
            return None
        slug = self._slug_from_url(artist_url)
        if not slug:
            return None
        return f"artuk:artist:{slug}"

    def _collection_source_record_id(self, collection_url: str) -> str:
        slug = self._slug_from_url(collection_url) or self._stable_id(collection_url)
        return f"artuk:collection:{slug}"

    def _detail_links_snapshot(self, response: scrapy.http.Response) -> dict:
        return {
            "artist_links": [
                self._canonicalize_url(response.urljoin(href))
                for href in response.css("a[href*='/discover/artists/']::attr(href)").getall()
            ],
            "collection_links": [
                self._canonicalize_url(response.urljoin(href))
                for href in response.css("a[href*='/visit/venues/']::attr(href)").getall()
            ],
        }

    def _canonicalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        query_pairs = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            lowered = key.lower()
            if any(lowered.startswith(prefix) for prefix in self.TRACKING_QUERY_PREFIXES):
                continue
            if lowered in {"ref", "source", "campaign"}:
                continue
            query_pairs.append((key, value))
        query = urlencode(query_pairs, doseq=True)
        normalized_path = parsed.path.rstrip("/") or "/"
        canonical = parsed._replace(
            scheme=(parsed.scheme or "https"),
            netloc=parsed.netloc.lower().replace("www.", ""),
            path=normalized_path,
            query=query,
            fragment="",
        )
        return urlunparse(canonical)

    def _slug_from_url(self, url: str) -> str | None:
        path = urlparse(url).path.strip("/")
        if not path:
            return None
        return path.split("/")[-1]

    def _stable_id(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:120]

    def _is_artwork_detail_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if not parsed.netloc.endswith("artuk.org"):
            return False
        if any(disallowed in parsed.path for disallowed in self.DISALLOWED_PATH_HINTS):
            return False
        return bool(self.ARTWORK_PATH_RE.match(parsed.path))

    def _is_artist_detail_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc.endswith("artuk.org") and bool(self.ARTIST_PATH_RE.match(parsed.path))

    def _is_collection_detail_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc.endswith("artuk.org") and bool(self.COLLECTION_PATH_RE.match(parsed.path))

    def _with_page(self, url: str, page_number: int) -> str | None:
        if page_number < 2:
            return None
        parsed = urlparse(self._canonicalize_url(url))
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params["page"] = str(page_number)
        return urlunparse(parsed._replace(query=urlencode(params)))

    def _page_number(self, url: str) -> int:
        parsed = urlparse(url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        try:
            return int(params.get("page", "1"))
        except ValueError:
            return 1

    def _limit_reached(self) -> bool:
        return (not self.full_crawl) and self._records_emitted >= self.max_records

    def _parse_artist_year(self, artist_data: dict | None, key: str) -> int | None:
        value = self._json_value(artist_data, key)
        if not value:
            return None
        match = re.search(r"(1[5-9]\d{2}|20\d{2})", str(value))
        return int(match.group(1)) if match else None

    def _absolute_json_url(self, response: scrapy.http.Response, value) -> str | None:
        if isinstance(value, list):
            for candidate in value:
                normalized = self._absolute_json_url(response, candidate)
                if normalized:
                    return normalized
            return None
        if not isinstance(value, str) or not value.strip():
            return None
        return self._canonicalize_url(response.urljoin(value.strip()))

    def _clean(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = re.sub(r"\s+", " ", value).strip()
        if not cleaned:
            return None
        cleaned = re.sub(r"\s*\|\s*Art UK$", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned or None

    def _first_non_empty(self, *values):
        for value in values:
            cleaned = self._clean(value) if isinstance(value, str) else value
            if isinstance(cleaned, str) and cleaned:
                return cleaned
            if cleaned is not None and not isinstance(cleaned, str):
                return cleaned
        return None
