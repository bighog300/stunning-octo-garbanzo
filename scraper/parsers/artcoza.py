from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from parsel import Selector

BIO_CONTAINER_SELECTORS = (
    "div.about",
    "div#about",
    "section.bio",
    "section#bio",
    "section.biography",
    "div.biography",
    "article.bio",
    "article.biography",
    "main .bio",
    "main .about",
)

JUNK_TOKENS = (
    "about the artist",
    "artworks ▼",
    "follow",
    "facebook",
    "instagram",
    "twitter",
    "menu",
    "navigation",
    "contact",
    "copyright",
    "all rights reserved",
)

PHONE_OR_EMAIL_RE = re.compile(
    r"(?:[\w.+-]+@[\w-]+\.[\w.-]+)|(?:\+?\d[\d\s().-]{7,}\d)",
    flags=re.IGNORECASE,
)

KNOWN_ARTIST_SLUG_OVERRIDES = {
    "hoseamatlou": "Hosea Matlou",
    "bastiaanvanstenis": "Bastiaan Van Stenis",
    "gunthervanderreis": "Gunther Van Der Reis",
    "collenmaswanganyi": "Collen Maswanganyi",
    "michelenigrini": "Michele Nigrini",
    "nickyliebenberg": "Nicky Liebenberg",
}

ARTIST_SECTION_LABELS = {
    "artist statement",
    "about the artist",
    "selected works",
    "latest work",
    "artworks",
    "paintings",
    "prints",
    "drawing",
    "sculpture",
    "african queens: restoring history",
}
ARTIST_CHROME_SNIPPETS = ("recent work", "featured work", "art in south africa")

HEADING_NAME_SELECTORS = (
    "h1::text",
    "h2::text",
    ".artist-name::text",
    ".entry-title::text",
)


def _normalize_whitespace(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split())


def _clean_block(value: str | None) -> str:
    cleaned = _normalize_whitespace(value)
    cleaned = re.sub(r"\s*Artworks\s*[▼»]+\s*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = PHONE_OR_EMAIL_RE.sub(" ", cleaned)
    return _normalize_whitespace(cleaned)


def _is_likely_junk(value: str) -> bool:
    lowered = value.lower()
    if len(lowered) < 40:
        return True
    return any(token in lowered for token in JUNK_TOKENS)


def _section_text(selector: Selector) -> str:
    return _clean_block(" ".join(selector.xpath(".//text()[normalize-space()]").getall()))


def _slug_from_url(url: str | None) -> str | None:
    if not url:
        return None
    path = urlparse(url).path.strip("/")
    if not path:
        return None
    return path.split("/")[0].strip().lower() or None


def artist_name_from_slug(url: str) -> str | None:
    slug = _slug_from_url(url)
    if not slug:
        return None
    if slug in KNOWN_ARTIST_SLUG_OVERRIDES:
        return KNOWN_ARTIST_SLUG_OVERRIDES[slug]
    if "-" in slug or "_" in slug:
        return slug.replace("-", " ").replace("_", " ").title()
    return None


def clean_artist_title(title: str) -> str | None:
    cleaned = _normalize_whitespace(title)
    if not cleaned:
        return None
    cleaned = re.sub(r"\bArt\.co\.za\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSouth African Artists\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bArtist Statement\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bAbout\b", " ", cleaned, flags=re.IGNORECASE)
    parts = [part.strip() for part in re.split(r"[|\-]", cleaned) if part.strip()]
    if not parts:
        return None
    for part in parts:
        if not _is_artist_label_candidate(part):
            return part
    return parts[0]


def _is_artist_label_candidate(candidate: str) -> bool:
    lowered = _normalize_whitespace(candidate).lower()
    if not lowered:
        return True
    if lowered in ARTIST_SECTION_LABELS:
        return True
    if "about " in lowered and len(lowered.split()) <= 6:
        return True
    if any(snippet in lowered for snippet in ARTIST_CHROME_SNIPPETS):
        return True
    if ":" in candidate and len(candidate.split()) > 2:
        return True
    return False


def extract_artist_name(html: str, url: str | None = None) -> str | None:
    sel = Selector(text=html)
    fallback_candidate: str | None = None

    for css in HEADING_NAME_SELECTORS:
        value = _normalize_whitespace(sel.css(css).get())
        if not value:
            continue
        if _is_artist_label_candidate(value):
            fallback_candidate = fallback_candidate or value
            continue
        return value

    page_title = clean_artist_title(sel.css("title::text").get() or "")
    if page_title and not _is_artist_label_candidate(page_title):
        return page_title

    slug_name = artist_name_from_slug(url or "")
    if slug_name:
        return slug_name

    if fallback_candidate and not _is_artist_label_candidate(fallback_candidate):
        return fallback_candidate
    return None


def extract_artist_bio(html: str) -> str:
    return extract_artist_profile_context(html).get("bio", "") or ""


def extract_artist_profile_context(html: str) -> dict[str, Any]:
    sel = Selector(text=html)

    candidate_blocks: list[str] = []
    fallback_used = False

    for css in BIO_CONTAINER_SELECTORS:
        for node in sel.css(css):
            text = _section_text(node)
            if text and not _is_likely_junk(text):
                candidate_blocks.append(text)

    # heading-based sections across layout variants
    for heading in sel.xpath("//h1|//h2|//h3|//h4"):
        heading_text = _normalize_whitespace(" ".join(heading.xpath(".//text()").getall())).lower()
        if not any(token in heading_text for token in ("about", "biography", "artist statement", "bio")):
            continue
        parts: list[str] = []
        for sibling in heading.xpath("following-sibling::*[position()<=6]"):
            if sibling.root.tag in {"h1", "h2", "h3", "h4"}:
                break
            segment = _section_text(sibling)
            if segment:
                parts.append(segment)
        merged = _clean_block(" ".join(parts))
        if merged and not _is_likely_junk(merged):
            candidate_blocks.append(merged)

    deduped = list(dict.fromkeys(candidate_blocks))

    if not deduped:
        fallback_used = True
        broad_blocks: list[str] = []
        for node in sel.xpath(
            "//main//*[self::p or self::div or self::section] | //article//*[self::p or self::div] | //body//p | //body//div"
        ):
            segment = _section_text(node)
            if len(segment) > 80 and "artwork" not in segment.lower():
                broad_blocks.append(segment)
        deduped = list(dict.fromkeys(broad_blocks))

    selected_blocks = deduped[:3]
    best = "\n\n".join(selected_blocks)
    if best and all(_is_likely_junk(block) for block in selected_blocks):
        best = ""

    return {
        "bio": best,
        "fallback_used": fallback_used,
        "candidate_count": len(deduped),
    }


def extract_artworks(html: str) -> list[dict[str, Any]]:
    sel = Selector(text=html)
    artworks: list[dict[str, Any]] = []

    nodes = sel.xpath("//article | //figure | //li | //div[contains(@class, 'art')]")
    for node in nodes:
        image_src = node.xpath(".//img/@src | .//img/@data-src").get()
        if not image_src:
            continue

        title = _normalize_whitespace(
            node.xpath(
                ".//figcaption//text() | .//h1//text() | .//h2//text() | .//h3//text() | .//img/@alt | .//img/@title"
            ).get()
        )
        if not title:
            image_name = urlparse(image_src).path.rsplit("/", 1)[-1]
            title = re.sub(r"\.[a-z0-9]+$", "", image_name, flags=re.IGNORECASE).replace("-", " ").strip().title()

        if not title or any(token in title.lower() for token in ("logo", "facebook", "instagram", "follow")):
            continue

        link = node.xpath(".//a/@href").get()
        artworks.append(
            {
                "title": title,
                "image_src": image_src,
                "detail_href": link,
            }
        )

    return artworks


def extract_events(html: str) -> list[dict[str, Any]]:
    sel = Selector(text=html)
    events: list[dict[str, Any]] = []

    event_nodes = sel.xpath(
        "//*[contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'event')]"
        " | //section[contains(translate(@id, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'event')]"
    )

    for node in event_nodes:
        text = _section_text(node)
        if not text or len(text) < 20:
            continue
        title = _normalize_whitespace(node.xpath(".//h1/text() | .//h2/text() | .//h3/text() | .//strong/text()").get())
        date_text = _normalize_whitespace(node.xpath(".//*[contains(@class,'date')]//text()").get())
        events.append({"title": title, "date_text": date_text, "description": text})

    return events
