from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import scrapy

from artio_crawlers.items import ArtworkItem
from artio_crawlers.utils.hashing import content_hash


class ArtCoZaSpider(scrapy.Spider):
    name = "artcoza_artworks"
    allowed_domains = ["art.co.za", "www.art.co.za"]
    start_urls = ["https://www.art.co.za/artists/"]

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 1.5,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
    }

    def __init__(
        self,
        max_artists=25,
        max_records=100,
        crawl_run_id=None,
        dry_run=False,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.max_artists = int(max_artists)
        self.max_records = int(max_records)
        self.crawl_run_id = crawl_run_id
        self.dry_run = str(dry_run).lower() in {"true", "1", "yes"}

        self.artists_seen = 0
        self.records_seen = 0
        self._visited_artist_urls: set[str] = set()
        self._visited_artwork_pages: set[str] = set()
        self._emitted_record_keys: set[str] = set()

    def parse(self, response: scrapy.http.Response):
        artist_links = self._extract_artist_profile_links(response)
        self.logger.info("Found %d artist links on %s", len(artist_links), response.url)
        self.logger.info(
            "First 5 artist URLs: %s",
            [response.urljoin(link) for link in artist_links[:5]],
        )
        for href in artist_links:
            if self.artists_seen >= self.max_artists:
                break

            artist_url = response.urljoin(href)
            if artist_url in self._visited_artist_urls:
                continue

            self._visited_artist_urls.add(artist_url)
            self.artists_seen += 1
            yield response.follow(artist_url, callback=self.parse_artist_profile)

        next_page = response.css("a.next::attr(href), a[rel='next']::attr(href)").get()
        if next_page and self.artists_seen < self.max_artists:
            yield response.follow(next_page, callback=self.parse)

    def parse_artist_profile(self, response: scrapy.http.Response):
        artist_name = self._extract_artist_name(response)
        artist_profile_url = response.url
        found_profile_records = 0

        for item in self._extract_profile_artwork_items(response, artist_name, artist_profile_url):
            if self.records_seen >= self.max_records:
                break
            self.records_seen += 1
            found_profile_records += 1
            yield item

        section_links = self._extract_artwork_section_links(response)
        for href in section_links:
            if self.records_seen >= self.max_records:
                break
            section_url = response.urljoin(href)
            if section_url in self._visited_artwork_pages:
                continue
            self._visited_artwork_pages.add(section_url)
            yield response.follow(
                section_url,
                callback=self.parse_artwork_section,
                meta={
                    "artist_name": artist_name,
                    "artist_profile_url": artist_profile_url,
                },
            )

        if found_profile_records == 0:
            self.logger.info("No artwork records found on profile page: %s", response.url)

    def parse_artwork_section(self, response: scrapy.http.Response):
        artist_name = response.meta.get("artist_name")
        artist_profile_url = response.meta.get("artist_profile_url")

        for item in self._extract_artwork_items(response, artist_name, artist_profile_url):
            if self.records_seen >= self.max_records:
                break
            self.records_seen += 1
            yield item

        if self.records_seen >= self.max_records:
            return

        next_page = response.css("a.next::attr(href), a[rel='next']::attr(href)").get()
        if next_page:
            next_url = response.urljoin(next_page)
            if next_url not in self._visited_artwork_pages:
                self._visited_artwork_pages.add(next_url)
                yield response.follow(next_url, callback=self.parse_artwork_section, meta=response.meta)

        detail_links = response.xpath(
            "//a[contains(@href, '/artworks/') or contains(@class, 'artwork')]/@href"
        ).getall()
        for href in detail_links:
            if self.records_seen >= self.max_records:
                break
            detail_url = response.urljoin(href)
            if detail_url in self._visited_artwork_pages:
                continue
            self._visited_artwork_pages.add(detail_url)
            yield response.follow(detail_url, callback=self.parse_artwork_section, meta=response.meta)

    def _extract_artist_profile_links(self, response: scrapy.http.Response) -> list[str]:
        candidates = response.xpath("//a[@href]/@href").getall()
        excluded_root_paths = {
            "artists",
            "exhibitions",
            "training",
            "auctions",
            "galleries",
            "websites",
            "art-quiz",
            "art-videos",
            "watch-list",
            "blog",
            "my",
        }
        out: list[str] = []
        for href in candidates:
            absolute = response.urljoin(href)
            parsed = urlparse(absolute)
            if parsed.netloc not in {"art.co.za", "www.art.co.za"}:
                continue
            path = parsed.path.rstrip("/")
            if not path or path == "/artists":
                continue
            segments = [segment for segment in path.split("/") if segment]
            if not segments:
                continue
            if segments[0] == "artists":
                if len(segments) == 1:
                    continue
                if len(segments) == 2 and len(segments[1]) == 1:
                    continue
            elif len(segments) == 1:
                if segments[0] in excluded_root_paths:
                    continue
            else:
                continue
            out.append(href)
        return list(dict.fromkeys(out))

    def _extract_artist_name(self, response: scrapy.http.Response) -> str | None:
        for selector in ["h1::text", "h2::text", ".artist-name::text", "title::text"]:
            value = response.css(selector).get()
            if value and value.strip():
                return value.strip()
        return None

    def _extract_artwork_section_links(self, response: scrapy.http.Response) -> list[str]:
        section_links = response.xpath(
            "//h1[contains(translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'artworks')]"
            "/following::a[1]/@href"
            " | //h2[contains(translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'artworks')]"
            "/following::a/@href"
            " | //h3[contains(translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'artworks')]"
            "/following::a/@href"
        ).getall()

        if not section_links:
            section_links = response.xpath(
                "//a[contains(@href, '/artworks/') or contains(translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'artworks')]/@href"
            ).getall()

        return list(dict.fromkeys(section_links))

    def _extract_artwork_items(
        self,
        response: scrapy.http.Response,
        artist_name: str | None,
        artist_profile_url: str | None,
    ):
        nodes = response.xpath("//article | //li | //div[contains(@class, 'art')]")
        for node in nodes:
            title = self._first_text(
                node,
                [
                    ".//h1/text()",
                    ".//h2/text()",
                    ".//h3/text()",
                    ".//a[contains(@class, 'title')]/text()",
                    ".//img/@alt",
                ],
            )
            image_url = node.xpath(".//img/@src").get() or node.xpath(".//img/@data-src").get()
            if image_url:
                image_url = response.urljoin(image_url)
            source_url = node.xpath(".//a[1]/@href").get()
            source_url = response.urljoin(source_url) if source_url else response.url

            if not title and not image_url:
                continue

            dedupe_key = f"{source_url}|{image_url or title or ''}"
            if dedupe_key in self._emitted_record_keys:
                continue
            self._emitted_record_keys.add(dedupe_key)

            raw_payload = {
                "artist_profile_url": artist_profile_url,
                "source_page": response.url,
                "title": title,
                "image_url": image_url,
            }

            item = ArtworkItem()
            item["source_name"] = "Art.co.za"
            item["source_domain"] = "art.co.za"
            item["source_url"] = source_url
            item["source_record_id"] = content_hash(source_url, image_url or title)[:24]
            item["artist_name"] = artist_name
            item["artwork_title"] = title
            item["artwork_date_text"] = self._first_text(node, [".//*[contains(@class,'date')]/text()"])
            item["medium_text"] = self._first_text(node, [".//*[contains(@class,'medium')]/text()"])
            item["dimensions_text"] = self._first_text(node, [".//*[contains(@class,'dimension')]/text()"])
            item["price_text"] = None
            item["currency_text"] = None
            item["gallery_name"] = None
            item["institution_name"] = None
            item["department_name"] = None
            item["image_url"] = image_url
            item["thumbnail_url"] = image_url
            item["description"] = self._first_text(node, [".//p/text()", ".//*[contains(@class,'description')]/text()"])
            item["raw_payload"] = raw_payload
            item["content_hash"] = content_hash(source_url, image_url or title)
            item["crawl_timestamp"] = datetime.now(timezone.utc).isoformat()
            item["crawl_run_id"] = self.crawl_run_id
            yield item

    def _extract_profile_artwork_items(
        self,
        response: scrapy.http.Response,
        artist_name: str | None,
        artist_profile_url: str | None,
    ):
        image_nodes = response.xpath(
            "//img[contains(translate(@alt, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'artwork')]"
            " | //img[contains(translate(@title, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'artwork')]"
            " | //a[contains(@href, '/uploads/')]/img"
        )
        for node in image_nodes:
            image_url = node.xpath("./@src").get() or node.xpath("./@data-src").get()
            if not image_url:
                continue
            image_url = response.urljoin(image_url)
            title = self._first_text(node, ["./@alt", "./@title"]) or "Artwork"
            source_url = response.url

            dedupe_key = f"{source_url}|{image_url}"
            if dedupe_key in self._emitted_record_keys:
                continue
            self._emitted_record_keys.add(dedupe_key)

            raw_payload = {
                "artist_profile_url": artist_profile_url,
                "source_page": response.url,
                "title": title,
                "image_url": image_url,
            }

            item = ArtworkItem()
            item["source_name"] = "Art.co.za"
            item["source_domain"] = "art.co.za"
            item["source_url"] = source_url
            item["source_record_id"] = content_hash(source_url, image_url)[:24]
            item["artist_name"] = artist_name
            item["artwork_title"] = title
            item["artwork_date_text"] = None
            item["medium_text"] = None
            item["dimensions_text"] = None
            item["price_text"] = None
            item["currency_text"] = None
            item["gallery_name"] = None
            item["institution_name"] = None
            item["department_name"] = None
            item["image_url"] = image_url
            item["thumbnail_url"] = image_url
            item["description"] = None
            item["raw_payload"] = raw_payload
            item["content_hash"] = content_hash(source_url, image_url)
            item["crawl_timestamp"] = datetime.now(timezone.utc).isoformat()
            item["crawl_run_id"] = self.crawl_run_id
            yield item

    @staticmethod
    def _first_text(node, xpaths: list[str]) -> str | None:
        for xp in xpaths:
            value = node.xpath(xp).get()
            if value and value.strip():
                return " ".join(value.split())
        return None
