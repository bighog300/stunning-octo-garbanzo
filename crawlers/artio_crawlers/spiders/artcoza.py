from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import PurePosixPath
import re
from urllib.parse import urlparse

import scrapy

from artio_crawlers.items import ArtworkItem
from artio_crawlers.utils.hashing import content_hash
from scraper.parsers.artcoza import (
    extract_artist_bio,
    extract_artist_name,
    extract_artist_profile_context,
    extract_artworks,
    extract_events,
)


class ArtCoZaSpider(scrapy.Spider):
    name = "artcoza_artworks"
    allowed_domains = ["art.co.za", "www.art.co.za"]
    start_urls = ["https://www.art.co.za/artists/"]

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 1.5,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
    }

    NON_ARTIST_ROOT_PATHS = {
        "index.php",
        "watch-list",
        "galleries",
        "auctions",
        "weblinks",
        "quiz",
        "myartcoza",
        "contact",
        "gallery",
        "advertise",
        "about",
        "articles",
        "news",
        "exhibitions",
        "events",
        "artists",
        "training",
    }

    ARTIST_NAME_BLACKLIST = {
        "art training",
        "art quiz",
        "recent work",
        "featured work",
        "art in south africa",
    }
    ARTIST_NAME_PREFIX_BLACKLIST = (
        "art.co.za",
        "art galleries",
        "art auctions",
        "watch list",
    )

    ARTIST_NAME_CHROME_TOKENS = (
        "recent work",
        "featured work",
        "art in south africa",
        "| art.co.za",
        "- art.co.za",
    )

    EXCLUDED_IMAGE_TOKENS = (
        "follow.png",
        "artcoza.jpg",
        "top-facebook.png",
        "facebook",
        "instagram",
        "twitter",
        "logo",
        "icon",
        "banner",
        "header",
        "footer",
        "nav",
    )
    EXCLUDED_NON_ARTWORK_TOKENS = (
        "artist photo",
        "artist_photo",
        "studio",
        "cv",
        "biography",
        "bio",
        "portrait",
        "profile",
        "front001",
        "frontpage",
        "front-page",
    )
    PROFILE_SECTION_KEYWORDS = ("about", "biography", "artist statement", "profile", "cv")
    PROFILE_TEXT_JUNK_TOKENS = (
        "recent work",
        "featured work",
        "art in south africa",
        "copyright",
        "all rights reserved",
        "share",
        "facebook",
        "instagram",
        "twitter",
    )
    PROFILE_CONTAINER_HINTS = (
        "main",
        "content",
        "profile",
        "artist",
        "about",
        "bio",
        "biography",
        "statement",
        "cv",
    )
    JUNK_CONTAINER_HINTS = (
        "nav",
        "menu",
        "footer",
        "sidebar",
        "social",
        "share",
        "cookie",
        "newsletter",
        "breadcrumb",
    )

    def __init__(
        self,
        max_artists=25,
        max_records=100,
        full_crawl=False,
        crawl_run_id=None,
        dry_run=False,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.full_crawl = str(full_crawl).lower() in {"true", "1", "yes"}

        user_max_artists = int(max_artists)
        user_max_records = int(max_records)

        if self.full_crawl:
            self.max_artists = 0 if user_max_artists == 0 else user_max_artists
            self.max_records = 0 if user_max_records == 0 else user_max_records
        else:
            self.max_artists = user_max_artists or 25
            self.max_records = user_max_records or 100

        self.crawl_run_id = crawl_run_id
        self.dry_run = str(dry_run).lower() in {"true", "1", "yes"}

        self.artists_seen = 0
        self.records_seen = 0
        self._visited_artist_urls: set[str] = set()
        self._visited_artwork_pages: set[str] = set()
        self._emitted_record_keys: set[str] = set()

        self.candidate_artist_links_found = 0
        self.filtered_artist_profile_links = 0
        self.skipped_non_artist_links = 0
        self.records_per_artist: dict[str, int] = {}
        self.skipped_invalid_source_url = 0
        self.skipped_placeholder_image = 0
        self.skipped_invalid_artist_page = 0
        self.emitted_records = 0
        self.images_seen_per_artist: dict[str, int] = {}
        self.images_kept_per_artist: dict[str, int] = {}
        self.images_skipped_per_artist: dict[str, int] = {}
        self.artists_with_bio = 0
        self.artists_without_bio = 0
        self.scraper_debug = os.getenv("ARTIO_SCRAPER_DEBUG", "0").strip() in {"1", "true", "yes"}

    def parse(self, response: scrapy.http.Response):
        artist_links = self._extract_artist_profile_links(response)
        self.logger.info(
            "Artist directory stats: candidates=%d filtered=%d skipped=%d",
            self.candidate_artist_links_found,
            self.filtered_artist_profile_links,
            self.skipped_non_artist_links,
        )

        for href in artist_links:
            if self._artist_limit_reached():
                break

            artist_url = response.urljoin(href)
            if artist_url in self._visited_artist_urls:
                continue

            self._visited_artist_urls.add(artist_url)
            self.artists_seen += 1
            yield response.follow(artist_url, callback=self.parse_artist_profile)

        next_page = response.css("a.next::attr(href), a[rel='next']::attr(href)").get()
        if next_page and not self._artist_limit_reached():
            yield response.follow(next_page, callback=self.parse)

    def parse_artist_profile(self, response: scrapy.http.Response):
        if not self._is_valid_artcoza_http_url(response.url) or not self._is_artist_profile_url(response.url):
            self.skipped_invalid_artist_page += 1
            self.logger.info("Skipped invalid artist page: %s", response.url)
            return

        artist_slug = self._artist_slug_from_url(response.url)
        if not artist_slug:
            self.skipped_invalid_artist_page += 1
            self.logger.info("Skipped invalid artist slug: %s", response.url)
            return

        artist_name = self._extract_artist_name(response)
        if not self._is_valid_artist_name(artist_name):
            self.skipped_invalid_artist_page += 1
            self.logger.info("Skipped invalid artist page name: url=%s artist_name=%s", response.url, artist_name)
            return

        if not self._has_slug_scoped_artwork_image(response, artist_slug):
            self.skipped_invalid_artist_page += 1
            self.logger.info("Skipped artist page without slug-scoped artwork image: %s", response.url)
            return

        artist_profile_url = response.url
        profile_context = self._extract_artist_profile_context(response, artist_name, artist_profile_url)
        if profile_context.get("artist_bio"):
            self.artists_with_bio += 1
        else:
            self.artists_without_bio += 1
        per_artist_count = 0

        for item in self._extract_profile_artwork_items(response, artist_name, artist_profile_url, profile_context):
            if self._record_limit_reached():
                break
            self.records_seen += 1
            per_artist_count += 1
            yield item

        section_links = self._extract_artwork_section_links(response)
        for href in section_links:
            if self._record_limit_reached():
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
                    "profile_context": profile_context,
                },
            )

        self.records_per_artist[artist_profile_url] = self.records_per_artist.get(artist_profile_url, 0) + per_artist_count
        self._log_artist_image_stats_delta(
            artist_profile_url,
            context="artist_profile",
            seen_before=0,
            kept_before=0,
            skipped_before=0,
        )
        self.logger.info(
            "Artist processed: url=%s name=%s records=%d artist_bio_len=%d profile_text_blocks=%d",
            artist_profile_url,
            artist_name,
            self.records_per_artist[artist_profile_url],
            len(profile_context.get("artist_bio") or ""),
            len(profile_context.get("profile_text_blocks") or []),
        )

    def parse_artwork_section(self, response: scrapy.http.Response):
        artist_name = response.meta.get("artist_name")
        artist_profile_url = response.meta.get("artist_profile_url")
        profile_context = response.meta.get("profile_context") or {}
        artist_key = artist_profile_url or response.url
        seen_before = self.images_seen_per_artist.get(artist_key, 0)
        kept_before = self.images_kept_per_artist.get(artist_key, 0)
        skipped_before = self.images_skipped_per_artist.get(artist_key, 0)

        for item in self._extract_artwork_items(response, artist_name, artist_profile_url, profile_context):
            if self._record_limit_reached():
                break
            self.records_seen += 1
            self.records_per_artist[artist_key] = self.records_per_artist.get(artist_key, 0) + 1
            yield item
        self._log_artist_image_stats_delta(
            artist_key,
            context="artwork_section",
            seen_before=seen_before,
            kept_before=kept_before,
            skipped_before=skipped_before,
        )

        if self._record_limit_reached():
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
            if self._record_limit_reached():
                break
            detail_url = response.urljoin(href)
            if detail_url in self._visited_artwork_pages:
                continue
            self._visited_artwork_pages.add(detail_url)
            yield response.follow(detail_url, callback=self.parse_artwork_section, meta=response.meta)

    def _extract_artist_profile_links(self, response: scrapy.http.Response) -> list[str]:
        candidates = response.xpath("//a[@href]/@href").getall()
        self.candidate_artist_links_found += len(candidates)

        out: list[str] = []
        for href in candidates:
            absolute = response.urljoin(href)
            if self._is_artist_profile_url(absolute):
                out.append(absolute)
            else:
                self.skipped_non_artist_links += 1

        deduped_links = list(dict.fromkeys(out))
        self.filtered_artist_profile_links += len(deduped_links)
        return deduped_links

    def _is_artist_profile_url(self, url: str) -> bool:
        if not self._is_valid_artcoza_http_url(url):
            return False

        parsed = urlparse(url)
        if parsed.query or parsed.fragment:
            return False

        path = parsed.path.strip("/")
        if not path:
            return False

        lower_path = path.lower()
        if lower_path.endswith(".php"):
            return False

        segments = [s for s in lower_path.split("/") if s]
        if len(segments) != 1:
            return False

        slug = segments[0]
        if slug in self.NON_ARTIST_ROOT_PATHS:
            return False

        # avoid hidden utility/file-like links
        suffix = PurePosixPath(slug).suffix
        if suffix and suffix != ".coza":
            return False

        if slug.startswith("index"):
            return False

        return True

    def _extract_artist_name(self, response: scrapy.http.Response) -> str | None:
        parsed_name = self._clean_artist_name(extract_artist_name(response.text, url=response.url))
        return parsed_name if self._is_valid_artist_name(parsed_name) else None

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
        profile_context: dict | None = None,
    ):
        nodes = response.xpath("//article | //li | //figure | //div[contains(@class, 'art')]")
        artist_slug = self._artist_slug_from_url(artist_profile_url or response.url)
        artist_key = artist_profile_url or response.url
        for node in nodes:
            image_src = node.xpath(".//img/@src").get() or node.xpath(".//img/@data-src").get()
            if not image_src:
                continue
            self._track_artist_image_seen(artist_key)
            image_url = response.urljoin(image_src)
            if not self._is_valid_image_url(image_url):
                self.skipped_placeholder_image += 1
                self._track_artist_image_skipped(artist_key)
                self.logger.debug("Skipped placeholder image: %s", image_url)
                continue
            if artist_slug and not self._is_slug_scoped_image_url(image_url, artist_slug):
                self.skipped_placeholder_image += 1
                self._track_artist_image_skipped(artist_key)
                self.logger.debug("Skipped non-artist image path: artist_slug=%s image=%s", artist_slug, image_url)
                continue

            image_alt = node.xpath(".//img/@alt").get()
            image_title = node.xpath(".//img/@title").get()
            caption = self._first_text(node, [".//figcaption//text()", ".//*[contains(@class,'caption')]//text()"])

            source_href = node.xpath(".//a[1]/@href").get()
            source_url = artist_profile_url or response.url
            if not self._is_valid_artcoza_http_url(source_url):
                self.skipped_invalid_source_url += 1
                self._track_artist_image_skipped(artist_key)
                self.logger.debug("Skipped invalid source_url: %s", source_url)
                continue

            if not self._is_valid_artist_name(artist_name):
                self.skipped_invalid_artist_page += 1
                self._track_artist_image_skipped(artist_key)
                continue

            title = self._infer_title(image_url, image_alt, image_title, caption, node)
            if not title:
                self._track_artist_image_skipped(artist_key)
                continue
            title = title.strip()
            if not title:
                self._track_artist_image_skipped(artist_key)
                continue
            if self._is_non_artwork_image(image_url, title):
                self.skipped_placeholder_image += 1
                self._track_artist_image_skipped(artist_key)
                self.logger.debug("Skipped non-artwork image/title: image=%s title=%s", image_url, title)
                continue

            dedupe_key = f"{source_url}|{image_url}|{title}"
            if dedupe_key in self._emitted_record_keys:
                self._track_artist_image_skipped(artist_key)
                continue
            self._emitted_record_keys.add(dedupe_key)

            raw_payload = {
                "artist_profile_url": artist_profile_url,
                "source_href": source_href,
                "image_src": image_src,
                "image_alt": image_alt,
                "image_title": image_title,
                "caption": caption,
                "artist_bio": (profile_context or {}).get("artist_bio"),
                "artist_statement": (profile_context or {}).get("artist_statement"),
                "profile_text_blocks": (profile_context or {}).get("profile_text_blocks", []),
            }

            item = ArtworkItem()
            item["source_name"] = "Art.co.za"
            item["source_domain"] = "art.co.za"
            item["source_url"] = source_url
            item["source_record_id"] = self._build_source_record_id(artist_slug, image_url)
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
            item["description"] = (profile_context or {}).get("artist_bio") or caption
            item["raw_payload"] = raw_payload
            item["content_hash"] = content_hash("art.co.za", artist_slug, artist_name, image_url, title)
            item["crawl_timestamp"] = datetime.now(timezone.utc).isoformat()
            item["crawl_run_id"] = self.crawl_run_id
            self.emitted_records += 1
            self._track_artist_image_kept(artist_key)
            yield item

    def _extract_profile_artwork_items(
        self,
        response: scrapy.http.Response,
        artist_name: str | None,
        artist_profile_url: str | None,
        profile_context: dict | None = None,
    ):
        image_nodes = response.xpath("//img")
        artist_slug = self._artist_slug_from_url(artist_profile_url or response.url)
        artist_key = artist_profile_url or response.url
        for node in image_nodes:
            image_src = node.xpath("./@src").get() or node.xpath("./@data-src").get()
            if not image_src:
                continue
            self._track_artist_image_seen(artist_key)
            image_url = response.urljoin(image_src)
            if not self._is_valid_image_url(image_url):
                self.skipped_placeholder_image += 1
                self._track_artist_image_skipped(artist_key)
                self.logger.debug("Skipped placeholder image: %s", image_url)
                continue
            if artist_slug and not self._is_slug_scoped_image_url(image_url, artist_slug):
                self.skipped_placeholder_image += 1
                self._track_artist_image_skipped(artist_key)
                self.logger.debug("Skipped non-artist image path: artist_slug=%s image=%s", artist_slug, image_url)
                continue

            image_alt = node.xpath("./@alt").get()
            image_title = node.xpath("./@title").get()
            caption = self._first_text(
                node,
                [
                    "./ancestor::figure[1]//figcaption//text()",
                    "./ancestor::*[contains(@class,'art')][1]//*[contains(@class,'caption')]//text()",
                ],
            )
            title = self._infer_title(image_url, image_alt, image_title, caption)
            if not title:
                self._track_artist_image_skipped(artist_key)
                continue
            if self._is_non_artwork_image(image_url, title):
                self.skipped_placeholder_image += 1
                self._track_artist_image_skipped(artist_key)
                self.logger.debug("Skipped non-artwork image/title: image=%s title=%s", image_url, title)
                continue

            source_url = artist_profile_url or response.url
            if not self._is_valid_artcoza_http_url(source_url):
                self.skipped_invalid_source_url += 1
                self._track_artist_image_skipped(artist_key)
                self.logger.debug("Skipped invalid source_url: %s", source_url)
                continue

            if not self._is_valid_artist_name(artist_name):
                self.skipped_invalid_artist_page += 1
                self._track_artist_image_skipped(artist_key)
                continue
            dedupe_key = f"{source_url}|{image_url}|{title}"
            if dedupe_key in self._emitted_record_keys:
                self._track_artist_image_skipped(artist_key)
                continue
            self._emitted_record_keys.add(dedupe_key)

            raw_payload = {
                "artist_profile_url": artist_profile_url,
                "image_src": image_src,
                "image_alt": image_alt,
                "image_title": image_title,
                "caption": caption,
                "artist_bio": (profile_context or {}).get("artist_bio"),
                "artist_statement": (profile_context or {}).get("artist_statement"),
                "profile_text_blocks": (profile_context or {}).get("profile_text_blocks", []),
            }

            item = ArtworkItem()
            item["source_name"] = "Art.co.za"
            item["source_domain"] = "art.co.za"
            item["source_url"] = source_url
            item["source_record_id"] = self._build_source_record_id(artist_slug, image_url)
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
            item["description"] = (profile_context or {}).get("artist_bio") or caption
            item["raw_payload"] = raw_payload
            item["content_hash"] = content_hash("art.co.za", artist_slug, artist_name, image_url, title)
            item["crawl_timestamp"] = datetime.now(timezone.utc).isoformat()
            item["crawl_run_id"] = self.crawl_run_id
            self.emitted_records += 1
            self._track_artist_image_kept(artist_key)
            yield item

    def _extract_artist_profile_context(
        self,
        response: scrapy.http.Response,
        artist_name: str | None,
        artist_profile_url: str | None,
    ) -> dict:
        profile_context = extract_artist_profile_context(response.text)
        artist_bio = extract_artist_bio(response.text) or None
        artworks_snapshot = extract_artworks(response.text)
        events_snapshot = extract_events(response.text)
        context = {
            "artist_profile_url": artist_profile_url,
            "artist_bio": artist_bio,
            "artist_statement": None,
            "profile_text_blocks": [artist_bio] if artist_bio else [],
            "parsed_artworks_snapshot": artworks_snapshot,
            "parsed_events_snapshot": events_snapshot,
            "fallback_used": bool(profile_context.get("fallback_used")),
        }
        if self.scraper_debug:
            self.logger.info(
                "ARTIO_SCRAPER_DEBUG profile extraction: url=%s bio_len=%d fallback_used=%s candidate_count=%s events=%d artworks=%d",
                response.url,
                len(artist_bio or ""),
                context["fallback_used"],
                profile_context.get("candidate_count"),
                len(events_snapshot),
                len(artworks_snapshot),
            )
            if not artist_bio:
                self.logger.warning("ARTIO_SCRAPER_DEBUG extraction failure: missing bio for url=%s", response.url)
        return context

    def closed(self, reason: str):
        self.logger.info(
            "Crawl summary: reason=%s artists_visited=%d artwork_records=%d emitted=%d candidates=%d filtered=%d skipped=%d skipped_invalid_source_url=%d skipped_placeholder_image=%d skipped_invalid_artist_page=%d artists_with_bio=%d artists_without_bio=%d",
            reason,
            self.artists_seen,
            self.records_seen,
            self.emitted_records,
            self.candidate_artist_links_found,
            self.filtered_artist_profile_links,
            self.skipped_non_artist_links,
            self.skipped_invalid_source_url,
            self.skipped_placeholder_image,
            self.skipped_invalid_artist_page,
            self.artists_with_bio,
            self.artists_without_bio,
        )

    @staticmethod
    def _is_valid_artcoza_http_url(url: str | None) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and parsed.netloc in {"art.co.za", "www.art.co.za"}

    def _is_valid_image_url(self, image_url: str | None) -> bool:
        if not self._is_valid_artcoza_http_url(image_url):
            return False
        path = urlparse(image_url).path.lower()
        if not path:
            return False
        return not any(token in path for token in self.EXCLUDED_IMAGE_TOKENS)

    @classmethod
    def _clean_artist_name(cls, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = " ".join(value.split())
        lowered = cleaned.lower()
        for token in cls.ARTIST_NAME_CHROME_TOKENS:
            idx = lowered.find(token)
            if idx >= 0:
                cleaned = cleaned[:idx].strip(" |-–—")
                lowered = cleaned.lower()
        return cleaned.strip() or None

    def _is_valid_artist_name(self, artist_name: str | None) -> bool:
        cleaned = self._clean_artist_name(artist_name)
        if not cleaned:
            return False
        lowered = cleaned.lower()
        if lowered in self.ARTIST_NAME_BLACKLIST:
            return False
        if any(lowered.startswith(prefix) for prefix in self.ARTIST_NAME_PREFIX_BLACKLIST):
            return False
        if "recent work" in lowered or "featured work" in lowered:
            return False
        return True

    @staticmethod
    def _artist_slug_from_url(url: str | None) -> str | None:
        if not url:
            return None
        path = urlparse(url).path.strip("/")
        if not path:
            return None
        return path.split("/")[0].lower()

    @staticmethod
    def _build_source_record_id(artist_slug: str | None, image_url: str) -> str:
        normalized_slug = (artist_slug or "unknown-artist").strip().lower()
        image_filename = PurePosixPath(urlparse(image_url).path).name
        image_identifier = image_filename or hashlib.sha1(image_url.encode("utf-8")).hexdigest()
        return f"art.co.za:{normalized_slug}:{image_identifier}"

    def _is_slug_scoped_image_url(self, image_url: str | None, artist_slug: str) -> bool:
        if not image_url or not artist_slug:
            return False
        image_path = urlparse(image_url).path.lower()
        slug = artist_slug.strip("/").lower()
        return f"/{slug}/" in image_path

    def _has_slug_scoped_artwork_image(self, response: scrapy.http.Response, artist_slug: str) -> bool:
        image_sources = response.xpath("//img/@src | //img/@data-src").getall()
        for image_src in image_sources:
            image_url = response.urljoin(image_src)
            if (
                self._is_valid_image_url(image_url)
                and self._is_slug_scoped_image_url(image_url, artist_slug)
                and not self._is_non_artwork_image(image_url, None)
            ):
                return True
        return False

    @staticmethod
    def _normalize_token_text(value: str | None) -> str:
        if not value:
            return ""
        return re.sub(r"[\W_]+", " ", value.lower()).strip()

    @staticmethod
    def _normalize_whitespace(value: str | None) -> str:
        if not value:
            return ""
        return " ".join(value.split())

    def _clean_profile_text(self, value: str | None) -> str | None:
        cleaned = self._normalize_whitespace(value)
        if not cleaned:
            return None
        return cleaned.strip()

    def _is_junk_profile_text_block(self, value: str | None) -> bool:
        normalized = self._normalize_token_text(value)
        if not normalized or len(normalized) < 20:
            return True
        return any(self._normalize_token_text(token) in normalized for token in self.PROFILE_TEXT_JUNK_TOKENS)

    def _profile_container_xpath(self) -> str:
        hints = " or ".join(
            [
                f"contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{hint}')"
                f" or contains(translate(@id, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{hint}')"
                for hint in self.PROFILE_CONTAINER_HINTS
            ]
        )
        junk_hints = " or ".join(
            [
                f"contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{hint}')"
                f" or contains(translate(@id, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{hint}')"
                for hint in self.JUNK_CONTAINER_HINTS
            ]
        )
        valid_predicate = f"not({junk_hints}) and not(ancestor::nav) and not(ancestor::footer) and not(ancestor::aside)"
        return (
            f"//main[{valid_predicate}]"
            f" | //article[{valid_predicate}]"
            f" | //section[({hints}) and {valid_predicate}]"
            f" | //div[({hints}) and {valid_predicate}]"
            f" | //td[({hints}) and {valid_predicate}]"
        )

    def _is_probably_junk_container_text(self, value: str) -> bool:
        lowered = value.lower()
        if any(hint in lowered for hint in self.JUNK_CONTAINER_HINTS):
            return True
        if "follow" in lowered and "facebook" in lowered:
            return True
        return False

    def _contains_non_artwork_token(self, value: str | None) -> bool:
        normalized = self._normalize_token_text(value)
        if not normalized:
            return False
        return any(self._normalize_token_text(token) in normalized for token in self.EXCLUDED_NON_ARTWORK_TOKENS)

    def _is_non_artwork_image(self, image_url: str | None, inferred_title: str | None) -> bool:
        if not image_url:
            return True
        path = urlparse(image_url).path
        filename = PurePosixPath(path).name
        return self._contains_non_artwork_token(filename) or self._contains_non_artwork_token(inferred_title)

    def _track_artist_image_seen(self, artist_key: str) -> None:
        self.images_seen_per_artist[artist_key] = self.images_seen_per_artist.get(artist_key, 0) + 1

    def _track_artist_image_kept(self, artist_key: str) -> None:
        self.images_kept_per_artist[artist_key] = self.images_kept_per_artist.get(artist_key, 0) + 1

    def _track_artist_image_skipped(self, artist_key: str) -> None:
        self.images_skipped_per_artist[artist_key] = self.images_skipped_per_artist.get(artist_key, 0) + 1

    def _log_artist_image_stats_delta(
        self,
        artist_key: str,
        context: str,
        seen_before: int,
        kept_before: int,
        skipped_before: int,
    ) -> None:
        seen_after = self.images_seen_per_artist.get(artist_key, 0)
        kept_after = self.images_kept_per_artist.get(artist_key, 0)
        skipped_after = self.images_skipped_per_artist.get(artist_key, 0)
        self.logger.info(
            "Image filtering stats: context=%s artist=%s seen=%d kept=%d skipped=%d delta_seen=%d delta_kept=%d delta_skipped=%d",
            context,
            artist_key,
            seen_after,
            kept_after,
            skipped_after,
            seen_after - seen_before,
            kept_after - kept_before,
            skipped_after - skipped_before,
        )

    @staticmethod
    def _first_text(node, xpaths: list[str]) -> str | None:
        for xp in xpaths:
            value = node.xpath(xp).get()
            if value and value.strip():
                return " ".join(value.split())
        return None

    def _artist_limit_reached(self) -> bool:
        return self.max_artists > 0 and self.artists_seen >= self.max_artists

    def _record_limit_reached(self) -> bool:
        return self.max_records > 0 and self.records_seen >= self.max_records

    @staticmethod
    def _infer_title(
        image_url: str,
        image_alt: str | None,
        image_title: str | None,
        caption: str | None,
        node=None,
    ) -> str | None:
        candidates = [image_alt, image_title, caption]
        if node is not None:
            candidates.extend(
                [
                    node.xpath(".//h1/text()").get(),
                    node.xpath(".//h2/text()").get(),
                    node.xpath(".//h3/text()").get(),
                    node.xpath(".//a[contains(@class, 'title')]/text()").get(),
                ]
            )
        for value in candidates:
            if value and value.strip():
                return " ".join(value.split())

        image_name = PurePosixPath(urlparse(image_url).path).stem
        if image_name:
            return image_name.replace("-", " ").replace("_", " ").strip().title()
        return None
