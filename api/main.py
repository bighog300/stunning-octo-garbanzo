import os
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any
import logging

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


class ReviewActionPayload(BaseModel):
    reviewer: str | None = "artio_admin"
    notes: str | None = None
    rejection_reason: str | None = None
    public_visibility: bool = True


class ArtistBioEditPayload(BaseModel):
    edited_bio: str
    edited_by: str | None = "artio_admin"
    edit_notes: str | None = None
    source_domain: str = "art.co.za"


class DataQualityFlagPayload(BaseModel):
    entity_type: str
    entity_id: str | None = None
    artist_name: str | None = None
    issue_type: str = Field(min_length=1)
    notes: str | None = None
    created_by: str | None = "artio_admin"


class FlagResolvePayload(BaseModel):
    resolved_by: str | None = "artio_admin"
    resolution_notes: str | None = None


class FlagReopenPayload(BaseModel):
    reopened_by: str | None = "artio_admin"
    notes: str | None = None


class ArtistModerationPayload(BaseModel):
    is_hidden: bool = False
    canonical_artist_name: str | None = None
    reason: str | None = None
    updated_by: str | None = "artio_admin"


class EventModerationPayload(BaseModel):
    is_hidden: bool | None = None
    is_approved: bool | None = None
    canonical_event_title: str | None = None
    event_type: str | None = None
    moderation_reason: str | None = None
    moderator_notes: str | None = None


class BulkEventModerationPayload(BaseModel):
    event_ids: list[str] = Field(min_length=1)
    updates: EventModerationPayload


class GalleryModerationPayload(BaseModel):
    is_hidden: bool | None = None
    is_approved: bool | None = None
    canonical_gallery_name: str | None = None
    canonical_gallery_type: str | None = None
    canonical_address: str | None = None
    canonical_city: str | None = None
    canonical_country: str | None = None
    canonical_phone: str | None = None
    canonical_email: str | None = None
    canonical_website_url: str | None = None
    canonical_instagram_url: str | None = None
    canonical_facebook_url: str | None = None
    moderation_reason: str | None = None
    moderator_notes: str | None = None


class BulkGalleryModerationPayload(BaseModel):
    gallery_ids: list[str] = Field(min_length=1)
    updates: GalleryModerationPayload


class AutoApplySuggestionsPayload(BaseModel):
    limit: int = Field(default=500, ge=1, le=500)
    dry_run: bool = True
    queue: str = "needs_review"


app = FastAPI(title="Artio API", version="0.1.0")
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(psycopg.Error)
def psycopg_exception_handler(_request, exc: psycopg.Error):
    is_dev = os.getenv("ARTIO_ENV", "development").lower() in {"dev", "development", "local"}
    detail = str(exc) if is_dev else "Database error"
    return JSONResponse(status_code=500, content={"detail": detail, "error_type": exc.__class__.__name__})


def _db_conn_string() -> str:
    return (
        f"host={os.getenv('ARTIO_POSTGRES_HOST', 'postgres')} "
        f"port={os.getenv('ARTIO_POSTGRES_PORT', '5432')} "
        f"dbname={os.getenv('ARTIO_POSTGRES_DB', 'artio')} "
        f"user={os.getenv('ARTIO_POSTGRES_USER', 'artio')} "
        f"password={os.getenv('ARTIO_POSTGRES_PASSWORD', 'artio')}"
    )


@contextmanager
def get_conn() -> Any:
    with psycopg.connect(_db_conn_string(), row_factory=psycopg.rows.dict_row) as conn:
        yield conn


def _get_artwork_or_404(conn: psycopg.Connection, artwork_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM app.artwork_records WHERE artwork_id = %s", (artwork_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Artwork not found")
    return row


def _relation_columns(conn: psycopg.Connection, schema: str, relation: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            """,
            (schema, relation),
        )
        rows = cur.fetchall()
    return {row["column_name"] for row in rows}


def _relation_exists(conn: psycopg.Connection, schema: str, relation: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) AS relation_name", (f"{schema}.{relation}",))
        row = cur.fetchone()
    return bool(row and row["relation_name"])


def _serialize_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    return [_serialize_row(row) for row in rows]


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _serialize_row(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return {key: _json_safe(value) for key, value in row.items()}
    return {key: _json_safe(value) for key, value in dict(row).items()}


def _select_with_fallback(
    columns: set[str], preferred: list[tuple[str, str]]
) -> tuple[str, list[str]]:
    selected_parts: list[str] = []
    selected_aliases: list[str] = []
    for alias, fallback in preferred:
        if alias in columns:
            selected_parts.append(alias)
            selected_aliases.append(alias)
        elif fallback in columns:
            selected_parts.append(f"{fallback} AS {alias}")
            selected_aliases.append(alias)
    return ", ".join(selected_parts), selected_aliases


QUEUE_SUMMARY_KEYS = [
    "artworks_pending_review",
    "artists_missing_bio",
    "artists_short_bio",
    "artists_poor_bio",
    "artists_suspect_name",
    "artists_with_manual_bio",
    "artists_without_events",
    "broken_or_missing_images",
]

SUSPECT_NAME_PATTERNS = [
    "%selected works%",
    "%latest work%",
    "%artworks%",
    "%paintings%",
    "%prints%",
    "%about the artist%",
]

EVENT_RECORD_REQUIRED_COLUMNS = [
    "event_id",
    "event_title",
    "original_event_title",
    "canonical_event_title",
    "event_type",
    "original_event_type",
    "canonical_event_type",
    "source_domain",
    "source_url",
    "start_date",
    "end_date",
    "venue_name",
    "linked_artists",
    "is_hidden",
    "is_approved",
    "moderation_reason",
    "moderator_notes",
    "updated_at",
    "raw_payload",
    "crawl_timestamp",
]


def _queue_reason_sql(queue_name: str) -> str:
    mapping = {
        "artworks-pending-review": "'pending_review'",
        "artists-missing-bio": "'missing_bio'",
        "artists-short-bio": "'short_bio'",
        "artists-poor-bio": "'poor_bio_quality'",
        "artists-suspect-name": "'suspect_artist_name'",
        "artists-with-manual-bio": "'manual_bio_override'",
        "artists-without-events": "'missing_events'",
        "broken-or-missing-images": "'broken_or_missing_image'",
    }
    if queue_name not in mapping:
        raise HTTPException(status_code=404, detail="Unsupported queue name")
    return mapping[queue_name]


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, 500))


def validate_event_records_contract(conn: psycopg.Connection) -> list[str]:
    actual = _relation_columns(conn, "app", "event_records")
    return [column for column in EVENT_RECORD_REQUIRED_COLUMNS if column not in actual]


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


def _normalize_event_title(title: str | None) -> tuple[str | None, str | None]:
    if not title:
        return None, None
    normalized = _normalize_space(title.strip())
    reason_parts: list[str] = []
    if normalized != title:
        reason_parts.append("trimmed whitespace")

    deduped = normalized
    while "!!" in deduped or "??" in deduped or ".." in deduped:
        deduped = deduped.replace("!!", "!").replace("??", "?").replace("..", ".")
    if deduped != normalized:
        reason_parts.append("removed repeated punctuation")
    normalized = deduped

    letter_chars = [char for char in normalized if char.isalpha()]
    if letter_chars and all(char.isupper() for char in letter_chars):
        normalized = normalized.title()
        reason_parts.append("converted all-caps title to title case")

    reason = ", ".join(reason_parts) if reason_parts else None
    if normalized == title:
        return None, reason
    return normalized, reason


def _load_event_learned_rules(cur: psycopg.Cursor) -> list[dict[str, Any]]:
    if not _relation_exists(cur.connection, "app", "event_learned_rules"):
        return []
    cur.execute(
        """
        SELECT field_name, pattern, suggested_value, confidence, support_count,
               accepted_count, rejected_count, source_domain
        FROM app.event_learned_rules
        WHERE is_active = true
        ORDER BY confidence DESC, support_count DESC, updated_at DESC
        LIMIT 500
        """
    )
    return cur.fetchall() or []


def _suggest_event_type(
    event: dict[str, Any], learned_rules: list[dict[str, Any]] | None = None
) -> tuple[str | None, float | None, str | None]:
    event_type = (event.get("event_type") or "").strip().lower()
    if event_type:
        return None, None, None
    if (event.get("canonical_event_type") or "").strip():
        return None, None, None
    haystack = f"{event.get('event_title') or ''} {event.get('description') or ''}".lower()
    for rule in learned_rules or []:
        if rule.get("field_name") != "event_type":
            continue
        pattern = (rule.get("pattern") or "").strip().lower()
        if not pattern:
            continue
        if pattern in haystack and (rule.get("source_domain") in (None, "", event.get("source_domain"))):
            return (
                rule.get("suggested_value"),
                float(rule.get("confidence") or 0.5),
                f"learned rule match: {pattern}",
            )

    keyword_mapping = [
        ("workshop", ["workshop", "masterclass", "class", "course"], 0.95),
        ("exhibition", ["exhibition", "solo show", "group show", "retrospective"], 0.93),
        ("talk", ["artist talk", "lecture", "conversation", "panel"], 0.92),
        ("fair", ["art fair", "expo", "biennale"], 0.90),
        ("opening", ["opening", "vernissage", "launch"], 0.85),
    ]
    for suggestion, keywords, confidence in keyword_mapping:
        if any(keyword in haystack for keyword in keywords):
            return suggestion, confidence, f"keyword match for {suggestion}"
    return None, None, None


def _normalize_event_title_with_confidence(title: str | None) -> tuple[str | None, float | None, str | None]:
    if not title:
        return None, None, None
    original = title
    normalized = title.strip()
    if normalized != original:
        return normalized, 0.99, "trimmed whitespace"

    collapsed = _normalize_space(normalized)
    if collapsed != normalized:
        return collapsed, 0.99, "collapsed repeated spaces"

    deduped = collapsed
    while "!!" in deduped or "??" in deduped or ".." in deduped:
        deduped = deduped.replace("!!", "!").replace("??", "?").replace("..", ".")
    if deduped != collapsed:
        return deduped, 0.95, "removed repeated punctuation"

    letter_chars = [char for char in deduped if char.isalpha()]
    if letter_chars and all(char.isupper() for char in letter_chars):
        return deduped.title(), 0.90, "converted all-caps title to title case"

    return None, None, None


def _is_safe_title_change(current_title: str | None, suggested_title: str | None) -> bool:
    if not suggested_title:
        return False
    if not current_title:
        return True
    ratio = SequenceMatcher(None, current_title.strip().lower(), suggested_title.strip().lower()).ratio()
    return ratio >= 0.88


def _enrich_event_record(
    event: dict[str, Any], learned_rules: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    linked_artists = event.get("linked_artists") or []
    has_title = bool((event.get("event_title") or "").strip())
    has_start_date = bool(event.get("start_date"))
    has_venue = bool((event.get("venue_name") or "").strip())
    has_artists = isinstance(linked_artists, list) and len(linked_artists) > 0
    has_description = bool((event.get("description") or "").strip())
    has_source_url = bool((event.get("source_url") or "").strip())
    end_before_start = bool(
        event.get("start_date")
        and event.get("end_date")
        and event["end_date"] < event["start_date"]
    )
    quality_flags = []
    if not has_start_date:
        quality_flags.append("missing_date")
    if not has_venue:
        quality_flags.append("missing_venue")
    if not has_artists:
        quality_flags.append("missing_artists")
    if not has_description:
        quality_flags.append("missing_description")
    if not has_source_url:
        quality_flags.append("missing_source_url")
    if end_before_start:
        quality_flags.append("end_before_start")
    quality_score = int(has_title) + int(has_start_date) + int(has_venue) + int(has_artists) + int(has_description)

    suggested_title, title_confidence, title_reason = _normalize_event_title_with_confidence(
        event.get("canonical_event_title") or event.get("event_title")
    )
    suggested_type, type_confidence, type_reason = _suggest_event_type(event, learned_rules=learned_rules)
    suggestion_reason = "; ".join(part for part in [type_reason, title_reason] if part) or None

    return {
        **event,
        "quality_score": quality_score,
        "quality_flags": quality_flags,
        "missing_date": not has_start_date,
        "missing_venue": not has_venue,
        "missing_artists": not has_artists,
        "missing_description": not has_description,
        "missing_source_url": not has_source_url,
        "end_before_start": end_before_start,
        "suggested_event_type": suggested_type,
        "event_type_confidence": type_confidence,
        "event_type_suggestion_reason": type_reason,
        "suggested_event_title": suggested_title,
        "event_title_confidence": title_confidence,
        "event_title_suggestion_reason": title_reason,
        "suggestion_reason": suggestion_reason,
    }


def _merged_event_moderation_values(
    current: dict[str, Any], payload: EventModerationPayload
) -> tuple[bool, bool, str | None, str | None, str | None, str | None]:
    next_hidden = payload.is_hidden if payload.is_hidden is not None else current.get("is_hidden", False)
    next_approved = (
        payload.is_approved if payload.is_approved is not None else current.get("is_approved", False)
    )
    next_title = (
        payload.canonical_event_title
        if payload.canonical_event_title is not None
        else current.get("canonical_event_title")
    )
    next_type = payload.event_type if payload.event_type is not None else current.get("event_type")
    next_reason = (
        payload.moderation_reason
        if payload.moderation_reason is not None
        else current.get("moderation_reason")
    )
    next_notes = (
        payload.moderator_notes if payload.moderator_notes is not None else current.get("moderator_notes")
    )
    return next_hidden, next_approved, next_title, next_type, next_reason, next_notes


def _upsert_event_moderation(
    cur: psycopg.Cursor,
    event_id: str,
    payload: EventModerationPayload,
    *,
    actor: str = "admin_ui",
    action_override: str | None = None,
) -> dict[str, Any]:
    learned_rules = _load_event_learned_rules(cur)
    cur.execute(
        """
        SELECT event_id, event_title, description, source_domain, canonical_event_title, canonical_event_type, event_type
        FROM app.event_records
        WHERE event_id = %s::uuid
        LIMIT 1
        """,
        (event_id,),
    )
    event_record = cur.fetchone()
    if not event_record:
        raise HTTPException(status_code=404, detail=f"Event not found: {event_id}")
    enriched = _enrich_event_record(_serialize_row(event_record), learned_rules=learned_rules)

    cur.execute(
        """
        SELECT is_hidden, is_approved, canonical_event_title, event_type,
               moderation_reason, moderator_notes
        FROM app.event_moderation_overrides
        WHERE event_id = %s::uuid
        LIMIT 1
        """,
        (event_id,),
    )
    current = cur.fetchone() or {}
    next_hidden, next_approved, next_title, next_type, next_reason, next_notes = (
        _merged_event_moderation_values(current, payload)
    )

    cur.execute(
        """
        INSERT INTO app.event_moderation_overrides (
            event_id, is_hidden, is_approved, canonical_event_title, event_type,
            moderation_reason, moderator_notes, updated_at
        )
        VALUES (
            %s::uuid, %s, %s, NULLIF(%s, ''),
            NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''), now()
        )
        ON CONFLICT (event_id)
        DO UPDATE SET
            is_hidden = EXCLUDED.is_hidden,
            is_approved = EXCLUDED.is_approved,
            canonical_event_title = EXCLUDED.canonical_event_title,
            event_type = EXCLUDED.event_type,
            moderation_reason = EXCLUDED.moderation_reason,
            moderator_notes = EXCLUDED.moderator_notes,
            updated_at = now()
        RETURNING event_id, is_hidden, is_approved, canonical_event_title, event_type,
                  moderation_reason, moderator_notes, updated_at
        """,
        (
            event_id,
            next_hidden,
            next_approved,
            next_title,
            next_type,
            next_reason,
            next_notes,
        ),
    )
    row = cur.fetchone()
    _log_corrections_for_moderation(
        cur,
        event_id=event_id,
        previous=current,
        updated=row,
        enriched=enriched,
        actor=actor,
        action_override=action_override,
    )
    _update_learned_rules_from_moderation(cur, enriched=enriched, previous=current, updated=row)
    return _serialize_row(row)


def _enrich_gallery_record(gallery: dict[str, Any]) -> dict[str, Any]:
    linked_events = gallery.get("linked_events") or []
    if not isinstance(linked_events, list):
        linked_events = []
    has_address = bool((gallery.get("gallery_address") or "").strip())
    has_city = bool((gallery.get("city") or "").strip())
    has_country = bool((gallery.get("country") or "").strip())
    has_website = bool((gallery.get("website_url") or "").strip() or (gallery.get("source_url") or "").strip())
    has_phone = bool((gallery.get("phone") or "").strip())
    has_email = bool((gallery.get("email") or "").strip())
    has_social = bool((gallery.get("instagram_url") or "").strip() or (gallery.get("facebook_url") or "").strip())
    has_linked_events = len(linked_events) > 0
    quality_flags = []
    if not has_address:
        quality_flags.append("missing_address")
    if not has_city:
        quality_flags.append("missing_city")
    if not has_country:
        quality_flags.append("missing_country")
    if not has_website:
        quality_flags.append("missing_website")
    if not has_phone:
        quality_flags.append("missing_phone")
    if not has_email:
        quality_flags.append("missing_email")
    if not has_social:
        quality_flags.append("missing_social")
    if not has_linked_events:
        quality_flags.append("missing_linked_events")
    quality_score = (
        int(bool((gallery.get("gallery_name") or "").strip()))
        + int(has_address)
        + int(has_city)
        + int(has_country)
        + int(has_website)
        + int(has_phone)
        + int(has_email)
        + int(has_social)
        + int(has_linked_events)
    )
    return {
        **gallery,
        "quality_score": quality_score,
        "quality_flags": quality_flags,
        "missing_address": not has_address,
        "missing_city": not has_city,
        "missing_country": not has_country,
        "missing_website": not has_website,
        "missing_phone": not has_phone,
        "missing_email": not has_email,
        "missing_social": not has_social,
        "missing_linked_events": not has_linked_events,
    }


def _merged_gallery_moderation_values(
    current: dict[str, Any], payload: GalleryModerationPayload
) -> tuple[bool, bool, str | None, str | None, str | None, str | None, str | None, str | None, str | None, str | None, str | None, str | None, str | None, str | None]:
    next_hidden = payload.is_hidden if payload.is_hidden is not None else current.get("is_hidden", False)
    next_approved = payload.is_approved if payload.is_approved is not None else current.get("is_approved", False)
    next_name = (
        payload.canonical_gallery_name
        if payload.canonical_gallery_name is not None
        else current.get("canonical_gallery_name")
    )
    next_type = (
        payload.canonical_gallery_type
        if payload.canonical_gallery_type is not None
        else current.get("canonical_gallery_type")
    )
    next_address = (
        payload.canonical_address if payload.canonical_address is not None else current.get("canonical_address")
    )
    next_city = payload.canonical_city if payload.canonical_city is not None else current.get("canonical_city")
    next_country = (
        payload.canonical_country if payload.canonical_country is not None else current.get("canonical_country")
    )
    next_phone = payload.canonical_phone if payload.canonical_phone is not None else current.get("canonical_phone")
    next_email = payload.canonical_email if payload.canonical_email is not None else current.get("canonical_email")
    next_website_url = (
        payload.canonical_website_url
        if payload.canonical_website_url is not None
        else current.get("canonical_website_url")
    )
    next_instagram_url = (
        payload.canonical_instagram_url
        if payload.canonical_instagram_url is not None
        else current.get("canonical_instagram_url")
    )
    next_facebook_url = (
        payload.canonical_facebook_url
        if payload.canonical_facebook_url is not None
        else current.get("canonical_facebook_url")
    )
    next_reason = (
        payload.moderation_reason
        if payload.moderation_reason is not None
        else current.get("moderation_reason")
    )
    next_notes = payload.moderator_notes if payload.moderator_notes is not None else current.get("moderator_notes")
    return (
        next_hidden,
        next_approved,
        next_name,
        next_type,
        next_address,
        next_city,
        next_country,
        next_phone,
        next_email,
        next_website_url,
        next_instagram_url,
        next_facebook_url,
        next_reason,
        next_notes,
    )


def _upsert_gallery_moderation(cur: psycopg.Cursor, gallery_id: str, payload: GalleryModerationPayload) -> dict[str, Any]:
    cur.execute("SELECT gallery_id FROM app.gallery_records WHERE gallery_id = %s::uuid LIMIT 1", (gallery_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail=f"Gallery not found: {gallery_id}")
    cur.execute(
        """
        SELECT is_hidden, is_approved, canonical_gallery_name, canonical_gallery_type,
               canonical_address, canonical_city, canonical_country, canonical_phone, canonical_email,
               canonical_website_url, canonical_instagram_url, canonical_facebook_url,
               moderation_reason, moderator_notes
        FROM app.gallery_moderation_overrides
        WHERE gallery_id = %s::uuid
        LIMIT 1
        """,
        (gallery_id,),
    )
    current = cur.fetchone() or {}
    merged = _merged_gallery_moderation_values(current, payload)
    cur.execute(
        """
        INSERT INTO app.gallery_moderation_overrides (
            gallery_id, is_hidden, is_approved, canonical_gallery_name, canonical_gallery_type,
            canonical_address, canonical_city, canonical_country, canonical_phone, canonical_email,
            canonical_website_url, canonical_instagram_url, canonical_facebook_url,
            moderation_reason, moderator_notes, updated_at
        )
        VALUES (
            %s::uuid, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''),
            NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''),
            NULLIF(%s, ''), NULLIF(%s, ''), now()
        )
        ON CONFLICT (gallery_id)
        DO UPDATE SET
            is_hidden = EXCLUDED.is_hidden,
            is_approved = EXCLUDED.is_approved,
            canonical_gallery_name = EXCLUDED.canonical_gallery_name,
            canonical_gallery_type = EXCLUDED.canonical_gallery_type,
            canonical_address = EXCLUDED.canonical_address,
            canonical_city = EXCLUDED.canonical_city,
            canonical_country = EXCLUDED.canonical_country,
            canonical_phone = EXCLUDED.canonical_phone,
            canonical_email = EXCLUDED.canonical_email,
            canonical_website_url = EXCLUDED.canonical_website_url,
            canonical_instagram_url = EXCLUDED.canonical_instagram_url,
            canonical_facebook_url = EXCLUDED.canonical_facebook_url,
            moderation_reason = EXCLUDED.moderation_reason,
            moderator_notes = EXCLUDED.moderator_notes,
            updated_at = now()
        RETURNING gallery_id, is_hidden, is_approved, canonical_gallery_name, canonical_gallery_type,
                  canonical_address, canonical_city, canonical_country, canonical_phone, canonical_email,
                  canonical_website_url, canonical_instagram_url, canonical_facebook_url,
                  moderation_reason, moderator_notes, updated_at
        """,
        (gallery_id, *merged),
    )
    return _serialize_row(cur.fetchone())


def _determine_correction_action(
    *,
    old_value: str | None,
    new_value: str | None,
    suggested_value: str | None,
    previous_moderation_reason: str | None = None,
    action_override: str | None = None,
) -> str:
    if action_override:
        return action_override
    old_clean = (old_value or "").strip() or None
    new_clean = (new_value or "").strip() or None
    suggested_clean = (suggested_value or "").strip() or None
    if (previous_moderation_reason or "").startswith("auto_applied"):
        return "reverted" if new_clean is None else "rejected"
    if new_clean is None and old_clean:
        return "reverted"
    if suggested_clean and new_clean == suggested_clean:
        return "accepted"
    if suggested_clean and new_clean is None:
        return "rejected"
    if suggested_clean and new_clean != suggested_clean:
        return "manually_edited"
    return "manually_edited"


def _log_corrections_for_moderation(
    cur: psycopg.Cursor,
    *,
    event_id: str,
    previous: dict[str, Any],
    updated: dict[str, Any],
    enriched: dict[str, Any],
    actor: str,
    action_override: str | None = None,
) -> None:
    if not _relation_exists(cur.connection, "app", "event_moderation_corrections"):
        return
    field_specs = [
        ("canonical_event_type", "event_type", "suggested_event_type", "event_type_confidence", "event_type_suggestion_reason"),
        ("canonical_event_title", "canonical_event_title", "suggested_event_title", "event_title_confidence", "event_title_suggestion_reason"),
    ]
    for _field_name, updated_key, suggested_key, confidence_key, reason_key in field_specs:
        old_value = previous.get(updated_key)
        new_value = updated.get(updated_key)
        if (old_value or None) == (new_value or None):
            continue
        suggested_value = enriched.get(suggested_key)
        action = _determine_correction_action(
            old_value=old_value,
            new_value=new_value,
            suggested_value=suggested_value,
            previous_moderation_reason=previous.get("moderation_reason"),
            action_override=action_override,
        )
        cur.execute(
            """
            INSERT INTO app.event_moderation_corrections (
                event_id, field_name, original_value, suggested_value, final_value,
                suggestion_confidence, suggestion_reason, action, source_domain, event_title, event_type,
                created_by
            )
            VALUES (
                %s::uuid, %s, NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''),
                %s, NULLIF(%s, ''), %s, NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, '')
            )
            """,
            (
                event_id,
                updated_key,
                old_value,
                suggested_value,
                new_value,
                enriched.get(confidence_key),
                enriched.get(reason_key),
                action,
                enriched.get("source_domain"),
                enriched.get("event_title"),
                enriched.get("event_type"),
                actor,
            ),
        )


def _update_learned_rules_from_moderation(
    cur: psycopg.Cursor, *, enriched: dict[str, Any], previous: dict[str, Any], updated: dict[str, Any]
) -> None:
    if not _relation_exists(cur.connection, "app", "event_learned_rules"):
        return
    source_domain = enriched.get("source_domain")
    haystack = f"{enriched.get('event_title') or ''} {enriched.get('description') or ''}".strip().lower()
    title_pattern = (enriched.get("event_title") or "").strip().lower()
    for field_name, key, suggested_key, pattern in (
        ("event_type", "event_type", "suggested_event_type", haystack),
        ("event_title", "canonical_event_title", "suggested_event_title", title_pattern),
    ):
        old_value = previous.get(key)
        new_value = updated.get(key)
        suggested_value = enriched.get(suggested_key)
        if (old_value or None) == (new_value or None):
            continue
        if not pattern or not suggested_value:
            continue
        accepted = 1 if (new_value or "").strip() == (suggested_value or "").strip() else 0
        rejected = 1 - accepted
        cur.execute(
            """
            INSERT INTO app.event_learned_rules (
                field_name, pattern, suggested_value, support_count, accepted_count, rejected_count,
                confidence, source_domain, updated_at
            )
            VALUES (
                %s, %s, %s, 1, %s, %s, (%s + 2.0) / (1 + 4.0), NULLIF(%s, ''), now()
            )
            ON CONFLICT (field_name, pattern, suggested_value, source_domain)
            DO UPDATE SET
                support_count = app.event_learned_rules.support_count + 1,
                accepted_count = app.event_learned_rules.accepted_count + EXCLUDED.accepted_count,
                rejected_count = app.event_learned_rules.rejected_count + EXCLUDED.rejected_count,
                confidence = (
                    (app.event_learned_rules.accepted_count + EXCLUDED.accepted_count + 2.0)
                    / (app.event_learned_rules.support_count + 1 + 4.0)
                ),
                updated_at = now()
            """,
            (field_name, pattern, suggested_value, accepted, rejected, accepted, source_domain),
        )


def _queue_status_filter(status: str) -> str:
    allowed = {"open", "resolved", "all"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="status must be open|resolved|all")
    return status


@app.get("/health")
def health() -> dict[str, str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    return {"status": "ok"}


@app.get("/api/moderation/queues")
def moderation_queue_summary() -> dict[str, int]:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      COUNT(*) FILTER (WHERE COALESCE(review_status, 'pending') = 'pending') AS artworks_pending_review,
                      COUNT(*) FILTER (WHERE image_url IS NULL OR btrim(image_url) = '') AS broken_or_missing_images
                    FROM app.artwork_records
                    """
                )
                artwork_counts = cur.fetchone() or {}

                cur.execute(
                    """
                    SELECT
                      COUNT(*) FILTER (WHERE artist_bio IS NULL OR btrim(artist_bio) = '') AS artists_missing_bio,
                      COUNT(*) FILTER (
                        WHERE artist_bio IS NOT NULL
                          AND btrim(artist_bio) <> ''
                          AND length(btrim(artist_bio)) < 120
                      ) AS artists_short_bio,
                      COUNT(*) FILTER (
                        WHERE COALESCE(bio_quality_score, 100) < 60
                      ) AS artists_poor_bio,
                      COUNT(*) FILTER (
                        WHERE artist_name ILIKE %s
                           OR artist_name ILIKE %s
                           OR artist_name ILIKE %s
                           OR artist_name ILIKE %s
                           OR artist_name ILIKE %s
                           OR artist_name ILIKE %s
                      ) AS artists_suspect_name,
                      COUNT(*) FILTER (WHERE edited_artist_bio IS NOT NULL) AS artists_with_manual_bio
                    FROM app.artist_profiles
                    """,
                    tuple(SUSPECT_NAME_PATTERNS),
                )
                artist_counts = cur.fetchone() or {}

                artists_without_events = 0
                if _relation_exists(conn, "app", "artist_event_links"):
                    cur.execute(
                        """
                        SELECT COUNT(*) AS artists_without_events
                        FROM app.artist_profiles ap
                        WHERE NOT EXISTS (
                          SELECT 1
                          FROM app.artist_event_links ael
                          WHERE ael.artist_name = ap.artist_name
                        )
                        """
                    )
                    row = cur.fetchone() or {}
                    artists_without_events = row.get("artists_without_events", 0) or 0
        return {
            "artworks_pending_review": artwork_counts.get("artworks_pending_review", 0) or 0,
            "artists_missing_bio": artist_counts.get("artists_missing_bio", 0) or 0,
            "artists_short_bio": artist_counts.get("artists_short_bio", 0) or 0,
            "artists_poor_bio": artist_counts.get("artists_poor_bio", 0) or 0,
            "artists_suspect_name": artist_counts.get("artists_suspect_name", 0) or 0,
            "artists_with_manual_bio": artist_counts.get("artists_with_manual_bio", 0) or 0,
            "artists_without_events": artists_without_events,
            "broken_or_missing_images": artwork_counts.get("broken_or_missing_images", 0) or 0,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch moderation queue summary")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/moderation/queue/{queue_name}")
def moderation_queue_records(
    queue_name: str,
    limit: int = Query(default=100, ge=1),
    offset: int = Query(default=0, ge=0),
    status: str = "open",
) -> list[dict[str, Any]]:
    safe_limit = _safe_limit(limit)
    queue_status = _queue_status_filter(status)
    issue_reason = _queue_reason_sql(queue_name)

    artist_queue_where = {
        "artists-missing-bio": "artist_bio IS NULL OR btrim(artist_bio) = ''",
        "artists-short-bio": (
            "artist_bio IS NOT NULL AND btrim(artist_bio) <> '' AND length(btrim(artist_bio)) < 120"
        ),
        "artists-poor-bio": "COALESCE(bio_quality_score, 100) < 60",
        "artists-suspect-name": (
            "artist_name ILIKE %s OR artist_name ILIKE %s OR artist_name ILIKE %s "
            "OR artist_name ILIKE %s OR artist_name ILIKE %s OR artist_name ILIKE %s"
        ),
        "artists-with-manual-bio": "edited_artist_bio IS NOT NULL",
    }

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if queue_name in artist_queue_where:
                    params: list[Any] = []
                    if queue_name == "artists-suspect-name":
                        params.extend(SUSPECT_NAME_PATTERNS)
                    status_filter_sql = ""
                    if queue_status == "resolved":
                        status_filter_sql = (
                            "AND EXISTS (SELECT 1 FROM app.data_quality_flags dqr "
                            "WHERE dqr.entity_type = 'artist' AND dqr.artist_name = ap.artist_name "
                            "AND dqr.issue_type = "
                            + issue_reason
                            + " AND dqr.status = 'resolved')"
                        )
                    elif queue_status == "open":
                        status_filter_sql = (
                            "AND NOT EXISTS (SELECT 1 FROM app.data_quality_flags dqo "
                            "WHERE dqo.entity_type = 'artist' AND dqo.artist_name = ap.artist_name "
                            "AND dqo.issue_type = "
                            + issue_reason
                            + " AND dqo.status = 'resolved')"
                        )
                    params.extend([safe_limit, offset])
                    cur.execute(
                        f"""
                        SELECT ap.artist_name, ap.source_domain, ap.profile_url, ap.artist_bio, ap.original_artist_bio,
                               ap.cleaned_artist_bio, ap.bio_quality_score, ap.bio_quality_flags,
                               ap.edited_artist_bio AS edited_bio, ap.bio_edited_by AS edited_by,
                               ap.bio_last_edited_at AS edited_at, ap.artwork_count, ap.last_seen,
                               COALESCE(dq.open_flags_count, 0) AS open_flags_count,
                               COALESCE(amo.is_hidden, false) AS is_hidden,
                               amo.canonical_artist_name,
                               {issue_reason} AS issue_reason
                        FROM app.artist_profiles ap
                        LEFT JOIN (
                          SELECT artist_name, issue_type, COUNT(*) AS open_flags_count
                          FROM app.data_quality_flags
                          WHERE status = 'open'
                          GROUP BY artist_name, issue_type
                        ) dq ON dq.artist_name = ap.artist_name AND dq.issue_type = {issue_reason}
                        LEFT JOIN app.artist_moderation_overrides amo
                          ON amo.artist_name = ap.artist_name AND amo.source_domain = ap.source_domain
                        WHERE {artist_queue_where[queue_name]}
                        {status_filter_sql}
                        ORDER BY last_seen DESC NULLS LAST, artist_name ASC
                        LIMIT %s OFFSET %s
                        """,
                        tuple(params),
                    )
                    return _serialize_rows(cur.fetchall())

                if queue_name == "artists-without-events":
                    if not _relation_exists(conn, "app", "artist_event_links"):
                        return []
                    status_filter_sql = ""
                    if queue_status == "resolved":
                        status_filter_sql = (
                            "AND EXISTS (SELECT 1 FROM app.data_quality_flags dqr "
                            "WHERE dqr.entity_type = 'artist' AND dqr.artist_name = ap.artist_name "
                            "AND dqr.issue_type = "
                            + issue_reason
                            + " AND dqr.status = 'resolved')"
                        )
                    elif queue_status == "open":
                        status_filter_sql = (
                            "AND NOT EXISTS (SELECT 1 FROM app.data_quality_flags dqo "
                            "WHERE dqo.entity_type = 'artist' AND dqo.artist_name = ap.artist_name "
                            "AND dqo.issue_type = "
                            + issue_reason
                            + " AND dqo.status = 'resolved')"
                        )
                    cur.execute(
                        f"""
                        SELECT ap.artist_name, ap.source_domain, ap.profile_url, ap.artist_bio,
                               ap.original_artist_bio, ap.edited_artist_bio AS edited_bio,
                               ap.cleaned_artist_bio, ap.bio_quality_score, ap.bio_quality_flags,
                               ap.bio_edited_by AS edited_by, ap.bio_last_edited_at AS edited_at,
                               ap.artwork_count, ap.last_seen,
                               COALESCE(dq.open_flags_count, 0) AS open_flags_count,
                               COALESCE(amo.is_hidden, false) AS is_hidden,
                               amo.canonical_artist_name,
                               {issue_reason} AS issue_reason
                        FROM app.artist_profiles ap
                        LEFT JOIN (
                          SELECT artist_name, issue_type, COUNT(*) AS open_flags_count
                          FROM app.data_quality_flags
                          WHERE status = 'open'
                          GROUP BY artist_name, issue_type
                        ) dq ON dq.artist_name = ap.artist_name AND dq.issue_type = {issue_reason}
                        LEFT JOIN app.artist_moderation_overrides amo
                          ON amo.artist_name = ap.artist_name AND amo.source_domain = ap.source_domain
                        WHERE NOT EXISTS (
                          SELECT 1
                          FROM app.artist_event_links ael
                          WHERE ael.artist_name = ap.artist_name
                        )
                        {status_filter_sql}
                        ORDER BY ap.last_seen DESC NULLS LAST, ap.artist_name ASC
                        LIMIT %s OFFSET %s
                        """,
                        (safe_limit, offset),
                    )
                    return _serialize_rows(cur.fetchall())

                if queue_name == "artworks-pending-review":
                    where_sql = "COALESCE(ar.review_status, 'pending') = 'pending'"
                    if queue_status == "resolved":
                        where_sql = "COALESCE(ar.review_status, 'pending') <> 'pending'"
                    cur.execute(
                        f"""
                        SELECT ar.artwork_id, ar.artwork_title, ar.artist_name, ar.image_url, ar.source_url,
                               ar.review_status, ar.public_visibility, ar.quality_score,
                               rr.rejection_reason,
                               {issue_reason} AS issue_reason
                        FROM app.artwork_records ar
                        LEFT JOIN LATERAL (
                          SELECT rejection_reason
                          FROM app.rejected_artworks r
                          WHERE r.artwork_id = ar.artwork_id::uuid
                          ORDER BY r.rejected_at DESC
                          LIMIT 1
                        ) rr ON true
                        WHERE {where_sql}
                        ORDER BY ar.created_at DESC
                        LIMIT %s OFFSET %s
                        """,
                        (safe_limit, offset),
                    )
                    return _serialize_rows(cur.fetchall())

                if queue_name == "broken-or-missing-images":
                    review_sql = ""
                    if queue_status == "open":
                        review_sql = "AND COALESCE(ar.review_status, 'pending') = 'pending'"
                    elif queue_status == "resolved":
                        review_sql = "AND COALESCE(ar.review_status, 'pending') <> 'pending'"
                    cur.execute(
                        f"""
                        SELECT ar.artwork_id, ar.artwork_title, ar.artist_name, ar.image_url, ar.source_url,
                               ar.review_status, ar.public_visibility, ar.quality_score,
                               rr.rejection_reason,
                               {issue_reason} AS issue_reason
                        FROM app.artwork_records ar
                        LEFT JOIN LATERAL (
                          SELECT rejection_reason
                          FROM app.rejected_artworks r
                          WHERE r.artwork_id = ar.artwork_id::uuid
                          ORDER BY r.rejected_at DESC
                          LIMIT 1
                        ) rr ON true
                        WHERE (ar.image_url IS NULL OR btrim(ar.image_url) = '')
                        {review_sql}
                        ORDER BY ar.created_at DESC
                        LIMIT %s OFFSET %s
                        """,
                        (safe_limit, offset),
                    )
                    return _serialize_rows(cur.fetchall())

        raise HTTPException(status_code=404, detail="Unsupported queue name")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch moderation queue records for %s", queue_name)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/moderation/flags")
def create_data_quality_flag(payload: DataQualityFlagPayload) -> dict[str, Any]:
    allowed_entity_types = {"artist", "artwork", "event"}
    if payload.entity_type not in allowed_entity_types:
        raise HTTPException(status_code=400, detail="entity_type must be one of artist/artwork/event")
    if not payload.issue_type.strip():
        raise HTTPException(status_code=400, detail="issue_type cannot be blank")
    if not (payload.entity_id or payload.artist_name):
        raise HTTPException(status_code=400, detail="Provide at least one of entity_id or artist_name")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO app.data_quality_flags (
                      entity_type, entity_id, artist_name, issue_type, notes, created_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, entity_type, entity_id, artist_name, issue_type, notes,
                              status, created_by, created_at, resolved_by, resolved_at, resolution_notes
                    """,
                    (
                        payload.entity_type,
                        payload.entity_id,
                        payload.artist_name,
                        payload.issue_type.strip(),
                        payload.notes,
                        payload.created_by,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return {"status": "created", "flag": _serialize_row(row)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create data quality flag")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/moderation/flags")
def list_data_quality_flags(
    status: str = Query(default="open"),
    entity_type: str | None = None,
    artist_name: str | None = None,
    issue_type: str | None = None,
    limit: int = Query(default=100, ge=1),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    safe_limit = _safe_limit(limit)
    where_clauses: list[str] = []
    params: list[Any] = []
    if status != "all":
        if status not in {"open", "resolved"}:
            raise HTTPException(status_code=400, detail="status must be open|resolved|all")
        where_clauses.append("status = %s")
        params.append(status)
    if entity_type:
        where_clauses.append("entity_type = %s")
        params.append(entity_type)
    if artist_name:
        where_clauses.append("artist_name ILIKE %s")
        params.append(f"%{artist_name}%")
    if issue_type:
        where_clauses.append("issue_type = %s")
        params.append(issue_type)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params.extend([safe_limit, offset])

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, entity_type, entity_id, artist_name, issue_type, notes, status,
                       created_by, created_at, resolved_by, resolved_at, resolution_notes
                FROM app.data_quality_flags
                {where_sql}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            rows = cur.fetchall()
    return _serialize_rows(rows)


@app.post("/api/moderation/flags/{flag_id}/resolve")
def resolve_data_quality_flag(flag_id: str, payload: FlagResolvePayload) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE app.data_quality_flags
                SET status = 'resolved',
                    resolved_at = now(),
                    resolved_by = %s,
                    resolution_notes = %s
                WHERE id = %s::uuid
                RETURNING id, entity_type, entity_id, artist_name, issue_type, notes, status,
                          created_by, created_at, resolved_by, resolved_at, resolution_notes
                """,
                (payload.resolved_by, payload.resolution_notes, flag_id),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Flag not found")
        conn.commit()
    return {"status": "resolved", "flag": _serialize_row(row)}


@app.post("/api/moderation/flags/{flag_id}/reopen")
def reopen_data_quality_flag(flag_id: str, payload: FlagReopenPayload) -> dict[str, Any]:
    reopen_note = payload.notes.strip() if payload.notes else None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE app.data_quality_flags
                SET status = 'open',
                    resolved_at = NULL,
                    resolved_by = NULL,
                    resolution_notes = %s
                WHERE id = %s::uuid
                RETURNING id, entity_type, entity_id, artist_name, issue_type, notes, status,
                          created_by, created_at, resolved_by, resolved_at, resolution_notes
                """,
                (reopen_note, flag_id),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Flag not found")
        conn.commit()
    return {"status": "open", "flag": _serialize_row(row)}


@app.get("/api/artworks")
def list_artworks(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT artwork_id, artwork_title, artist_name, image_url, source_name, source_url,
                       medium_text, year_start, year_end, quality_score, review_status
                FROM app.artwork_records
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall()
    return rows


@app.get("/api/artists")
def list_artists(
    limit: int = Query(default=100, ge=1),
    offset: int = Query(default=0, ge=0),
    search: str | None = None,
    source_domain: str | None = None,
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 500))
    where_clauses: list[str] = []
    params: list[Any] = []

    if search:
        where_clauses.append("ap.artist_name ILIKE %s")
        params.append(f"%{search}%")
    if source_domain:
        where_clauses.append("ap.source_domain = %s")
        params.append(source_domain)
    if not include_hidden:
        where_clauses.append("COALESCE(amo.is_hidden, false) = false")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params.extend([safe_limit, offset])

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT ap.artist_name, ap.source_domain, ap.profile_url, ap.original_artist_bio,
                           ap.edited_artist_bio, ap.cleaned_artist_bio, ap.bio_quality_score,
                           ap.bio_quality_flags, ap.artist_bio, ap.bio_edited_by, ap.bio_edit_notes,
                           ap.bio_last_edited_at, ap.artwork_count, ap.last_seen,
                           COALESCE(amo.is_hidden, false) AS is_hidden,
                           amo.canonical_artist_name,
                           amo.reason AS moderation_reason,
                           amo.updated_by AS moderation_updated_by,
                           amo.updated_at AS moderation_updated_at
                    FROM app.artist_profiles ap
                    LEFT JOIN app.artist_moderation_overrides amo
                      ON amo.artist_name = ap.artist_name AND amo.source_domain = ap.source_domain
                    {where_sql}
                    ORDER BY ap.artist_name ASC
                    LIMIT %s OFFSET %s
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        return _serialize_rows(rows)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to list artists")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/admin/events")
def list_admin_events(
    limit: int = Query(default=100, ge=1),
    offset: int = Query(default=0, ge=0),
    moderation_status: str | None = Query(default=None),
    queue: str = Query(default="needs_review"),
    event_type: str | None = None,
    source_domain: str | None = None,
    missing_date: bool = False,
    missing_venue: bool = False,
    search: str | None = None,
    include_hidden: bool = True,
) -> list[dict[str, Any]]:
    if not isinstance(offset, int):
        offset = 0
    if not isinstance(moderation_status, str):
        moderation_status = None
    if not isinstance(queue, str):
        queue = "needs_review"
    safe_limit = max(1, min(limit, 500))
    where_clauses: list[str] = []
    params: list[Any] = []

    status_to_queue = {
        "all": "all",
        "unmoderated": "needs_review",
        "approved": "approved",
        "hidden": "hidden",
    }
    if moderation_status:
        if moderation_status not in status_to_queue:
            raise HTTPException(status_code=400, detail="Invalid moderation_status")
        queue = status_to_queue[moderation_status]

    allowed_queues = {"needs_review", "low_quality", "recent", "approved", "hidden", "edited", "all"}
    if queue not in allowed_queues:
        raise HTTPException(status_code=400, detail="Invalid queue")

    if queue == "needs_review":
        where_clauses.append("COALESCE(is_hidden, false) = false")
        where_clauses.append("COALESCE(is_approved, false) = false")
    elif queue == "approved":
        where_clauses.append("COALESCE(is_approved, false) = true")
    elif queue == "hidden":
        where_clauses.append("COALESCE(is_hidden, false) = true")
    elif queue == "edited":
        where_clauses.append("COALESCE(moderation_override_exists, false) = true")
    elif queue == "recent":
        where_clauses.append("crawl_timestamp >= NOW() - INTERVAL '7 days'")
    elif queue == "low_quality":
        where_clauses.append(
            """
            (
                (CASE WHEN COALESCE(NULLIF(btrim(event_title), ''), NULLIF(btrim(original_event_title), '')) IS NULL THEN 0 ELSE 1 END)
              + (CASE WHEN start_date IS NULL THEN 0 ELSE 1 END)
              + (CASE WHEN COALESCE(NULLIF(btrim(venue_name), ''), '') = '' THEN 0 ELSE 1 END)
              + (CASE WHEN linked_artists IS NULL OR cardinality(linked_artists) = 0 THEN 0 ELSE 1 END)
              + (CASE WHEN COALESCE(NULLIF(btrim(description), ''), '') = '' THEN 0 ELSE 1 END)
            ) <= 2
            """
        )

    if not include_hidden:
        where_clauses.append("is_hidden = false")
    if event_type:
        where_clauses.append("event_type = %s")
        params.append(event_type)
    if source_domain:
        where_clauses.append("source_domain = %s")
        params.append(source_domain)
    if missing_date:
        where_clauses.append("start_date IS NULL AND end_date IS NULL")
    if missing_venue:
        where_clauses.append("(venue_name IS NULL OR btrim(venue_name) = '')")
    if search:
        where_clauses.append(
            "(event_title ILIKE %s OR canonical_event_title ILIKE %s OR source_url ILIKE %s)"
        )
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params.extend([safe_limit, offset])

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                learned_rules = _load_event_learned_rules(cur)
                cur.execute(
                    f"""
                    SELECT event_id, event_title, original_event_title, canonical_event_title,
                           event_type, original_event_type, canonical_event_type,
                           linked_artists, venue_name, city, country,
                           start_date, end_date, description, source_name, source_domain, source_url, crawl_timestamp,
                           is_hidden, is_approved, moderation_override_exists, moderation_reason, updated_at
                    FROM app.event_records
                    {where_sql}
                    ORDER BY crawl_timestamp DESC NULLS LAST, created_at DESC NULLS LAST
                    LIMIT %s OFFSET %s
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        return [_enrich_event_record(row, learned_rules=learned_rules) for row in _serialize_rows(rows)]
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to list admin events")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/admin/events/{event_id}")
def get_admin_event(event_id: str) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            learned_rules = _load_event_learned_rules(cur)
            cur.execute(
                """
                SELECT event_id, source_name, source_domain, source_url, source_record_id,
                       event_type, original_event_type, canonical_event_type,
                       event_title, original_event_title,
                       canonical_event_title, venue_name, venue_address, city, country,
                       start_date, end_date, opening_datetime, description, image_url,
                       raw_payload, linked_artists, artist_count, is_hidden, is_approved,
                       moderation_override_exists, moderation_reason, moderator_notes,
                       updated_at, crawl_timestamp, created_at
                FROM app.event_records
                WHERE event_id = %s::uuid
                LIMIT 1
                """,
                (event_id,),
            )
            event_row = cur.fetchone()
            if not event_row:
                raise HTTPException(status_code=404, detail="Event not found")

            cur.execute(
                """
                SELECT artist_activity_id, artist_name, artist_name_normalized, artist_profile_url,
                       match_type, event_type, event_title, city, country, start_date, end_date,
                       source_domain, source_url, crawl_timestamp
                FROM app.artist_event_links
                WHERE event_id = %s::uuid
                ORDER BY artist_name ASC NULLS LAST
                """,
                (event_id,),
            )
            linked_artists = cur.fetchall()
            cur.execute(
                """
                SELECT gallery_id, COALESCE(canonical_gallery_name, gallery_name) AS gallery_name
                FROM app.gallery_records gr
                WHERE EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(COALESCE(gr.linked_events, '[]'::jsonb)) AS ev
                    WHERE ev->>'event_id' = %s
                )
                ORDER BY crawl_timestamp DESC NULLS LAST
                LIMIT 1
                """,
                (event_id,),
            )
            linked_gallery = cur.fetchone()
    return {
        "event": _enrich_event_record(_serialize_row(event_row), learned_rules=learned_rules),
        "linked_artists": _serialize_rows(linked_artists),
        "linked_gallery": _serialize_row(linked_gallery) if linked_gallery else None,
    }


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _smoothed_confidence(accepted_count: int, support_count: int) -> float:
    return (accepted_count + 2) / (support_count + 4)


@app.post("/api/admin/events/auto-apply-suggestions")
def auto_apply_event_suggestions(payload: AutoApplySuggestionsPayload) -> dict[str, Any]:
    auto_enabled = _env_bool("EVENT_AUTO_APPLY_ENABLED", False)
    type_threshold = _env_float("EVENT_TYPE_AUTO_APPLY_THRESHOLD", 0.93)
    title_threshold = _env_float("EVENT_TITLE_AUTO_APPLY_THRESHOLD", 0.96)
    queue = payload.queue if payload.queue in {"needs_review", "all"} else "needs_review"

    with get_conn() as conn:
        with conn.cursor() as cur:
            learned_rules = _load_event_learned_rules(cur)
            where = [
                "COALESCE(is_approved, false) = false",
                "COALESCE(is_hidden, false) = false",
            ]
            if queue == "needs_review":
                where.append("COALESCE(moderation_override_exists, false) = false")
            where_sql = " AND ".join(where)
            cur.execute(
                f"""
                SELECT event_id, event_title, description, source_domain, event_type, canonical_event_title,
                       canonical_event_type, is_hidden, is_approved
                FROM app.event_records
                WHERE {where_sql}
                ORDER BY crawl_timestamp DESC NULLS LAST, created_at DESC NULLS LAST
                LIMIT %s
                """,
                (payload.limit,),
            )
            base_rows = [_serialize_row(row) for row in (cur.fetchall() or [])]

            eligible = 0
            would_update = 0
            updated = 0
            examples: list[dict[str, Any]] = []
            for row in base_rows:
                enriched = _enrich_event_record(row, learned_rules=learned_rules)
                updates: dict[str, Any] = {}
                if (
                    not enriched.get("event_type")
                    and enriched.get("suggested_event_type")
                    and float(enriched.get("event_type_confidence") or 0) >= type_threshold
                ):
                    updates["event_type"] = enriched["suggested_event_type"]
                if (
                    not (enriched.get("canonical_event_title") or "").strip()
                    and enriched.get("suggested_event_title")
                    and float(enriched.get("event_title_confidence") or 0) >= title_threshold
                    and _is_safe_title_change(enriched.get("event_title"), enriched.get("suggested_event_title"))
                ):
                    updates["canonical_event_title"] = enriched["suggested_event_title"]
                if not updates:
                    continue
                eligible += 1
                would_update += 1
                if len(examples) < 10:
                    examples.append(
                        {
                            "event_id": enriched["event_id"],
                            "event_title": enriched.get("event_title"),
                            "updates": updates,
                        }
                    )
                if payload.dry_run:
                    continue
                if not auto_enabled:
                    continue
                moderation_reason = "auto_applied: high_confidence_suggestion"
                _upsert_event_moderation(
                    cur,
                    enriched["event_id"],
                    EventModerationPayload(**updates, moderation_reason=moderation_reason),
                    actor="auto_apply",
                    action_override="auto_applied",
                )
                updated += 1
        conn.commit()

    return {
        "dry_run": payload.dry_run,
        "eligible": eligible,
        "would_update": would_update,
        "updated": updated,
        "examples": examples,
    }


@app.patch("/api/admin/events/{event_id}/moderation")
def patch_admin_event_moderation(event_id: str, payload: EventModerationPayload) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            row = _upsert_event_moderation(cur, event_id, payload)
        conn.commit()
    return {"status": "updated", "event_moderation": row}


@app.patch("/api/admin/events/bulk-moderation")
def patch_admin_events_bulk_moderation(payload: BulkEventModerationPayload) -> dict[str, Any]:
    if not payload.event_ids:
        raise HTTPException(status_code=400, detail="event_ids must be non-empty")
    if len(payload.event_ids) > 500:
        raise HTTPException(status_code=400, detail="event_ids exceeds max size of 500")

    with get_conn() as conn:
        updated = 0
        failed: list[dict[str, str]] = []
        with conn.cursor() as cur:
            for event_id in payload.event_ids:
                try:
                    _upsert_event_moderation(cur, event_id, payload.updates)
                    updated += 1
                except HTTPException as exc:
                    failed.append({"event_id": event_id, "detail": str(exc.detail)})
        conn.commit()
    return {"updated": updated, "failed": failed}


@app.get("/api/admin/galleries")
def list_admin_galleries(
    limit: int = Query(default=100, ge=1),
    offset: int = Query(default=0, ge=0),
    queue: str = Query(default="needs_review"),
    search: str | None = None,
    source_domain: str | None = None,
    missing_address: bool = False,
    missing_city: bool = False,
    missing_country: bool = False,
    missing_email: bool = False,
    missing_phone: bool = False,
    missing_website: bool = False,
    missing_social: bool = False,
    possible_duplicate: bool = False,
    gallery_record_type: str | None = None,
    include_hidden: bool = True,
) -> list[dict[str, Any]]:
    safe_limit = _safe_limit(limit)
    where_clauses: list[str] = []
    params: list[Any] = []
    allowed_queues = {"needs_review", "low_quality", "recent", "approved", "hidden", "edited", "all"}
    if queue not in allowed_queues:
        raise HTTPException(status_code=400, detail="Invalid queue")
    if queue == "needs_review":
        where_clauses.extend(["COALESCE(is_hidden, false) = false", "COALESCE(is_approved, false) = false"])
    elif queue == "approved":
        where_clauses.append("COALESCE(is_approved, false) = true")
    elif queue == "hidden":
        where_clauses.append("COALESCE(is_hidden, false) = true")
    elif queue == "edited":
        where_clauses.append("updated_at IS NOT NULL")
    elif queue == "recent":
        where_clauses.append("crawl_timestamp >= NOW() - INTERVAL '7 days'")
    elif queue == "low_quality":
        where_clauses.append("COALESCE(quality_score, 0) <= 3")
    if not include_hidden:
        where_clauses.append("COALESCE(is_hidden, false) = false")
    if source_domain:
        where_clauses.append("source_domain = %s")
        params.append(source_domain)
    if missing_address:
        where_clauses.append("missing_address = true")
    if missing_city:
        where_clauses.append("missing_city = true")
    if missing_country:
        where_clauses.append("missing_country = true")
    if missing_email:
        where_clauses.append("missing_email = true")
    if missing_phone:
        where_clauses.append("missing_phone = true")
    if missing_website:
        where_clauses.append("missing_website = true")
    if missing_social:
        where_clauses.append("missing_social = true")
    if possible_duplicate:
        where_clauses.append("gallery_name ILIKE '%gallery%'")
    if gallery_record_type in {"scraped", "inferred_from_event"}:
        where_clauses.append("gallery_record_type = %s")
        params.append(gallery_record_type)
    if search:
        where_clauses.append("(gallery_name ILIKE %s OR canonical_gallery_name ILIKE %s OR source_url ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params.extend([safe_limit, offset])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT gallery_id, gallery_name, normalized_gallery_name, gallery_address, city, country,
                       source_domain, source_url, gallery_record_type, phone, email, website_url, instagram_url, facebook_url,
                       linked_events, linked_artists, linked_artworks, is_hidden, is_approved,
                       canonical_gallery_name, canonical_gallery_type, canonical_address, canonical_city,
                       canonical_country, canonical_phone, canonical_email, canonical_website_url,
                       canonical_instagram_url, canonical_facebook_url, moderation_reason, moderator_notes, updated_at,
                       quality_score, quality_flags, missing_address, missing_city, missing_country,
                       missing_website, missing_email, missing_phone, missing_social, missing_linked_events, crawl_timestamp
                FROM app.gallery_records
                {where_sql}
                ORDER BY crawl_timestamp DESC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            rows = cur.fetchall()
    return [_enrich_gallery_record(_serialize_row(row)) for row in rows]


@app.get("/api/admin/galleries/{gallery_id}")
def get_admin_gallery(gallery_id: str) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT gallery_id, gallery_name, normalized_gallery_name, gallery_address, city, country,
                       source_domain, source_url, gallery_record_type, phone, email, website_url, instagram_url, facebook_url,
                       linked_events, linked_artists, linked_artworks, is_hidden, is_approved,
                       canonical_gallery_name, canonical_gallery_type, canonical_address, canonical_city,
                       canonical_country, canonical_phone, canonical_email, canonical_website_url,
                       canonical_instagram_url, canonical_facebook_url, moderation_reason, moderator_notes, updated_at,
                       quality_score, quality_flags, missing_address, missing_city, missing_country,
                       missing_website, missing_email, missing_phone, missing_social, missing_linked_events, raw_payload, crawl_timestamp
                FROM app.gallery_records
                WHERE gallery_id = %s::uuid
                LIMIT 1
                """,
                (gallery_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Gallery not found")
    return {"gallery": _enrich_gallery_record(_serialize_row(row))}


@app.patch("/api/admin/galleries/{gallery_id}/moderation")
def patch_admin_gallery_moderation(gallery_id: str, payload: GalleryModerationPayload) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            row = _upsert_gallery_moderation(cur, gallery_id, payload)
        conn.commit()
    return {"status": "updated", "gallery_moderation": row}


@app.patch("/api/admin/galleries/bulk-moderation")
def patch_admin_galleries_bulk_moderation(payload: BulkGalleryModerationPayload) -> dict[str, Any]:
    if len(payload.gallery_ids) > 500:
        raise HTTPException(status_code=400, detail="gallery_ids exceeds max size of 500")
    with get_conn() as conn:
        updated = 0
        failed: list[dict[str, str]] = []
        with conn.cursor() as cur:
            for gallery_id in payload.gallery_ids:
                try:
                    _upsert_gallery_moderation(cur, gallery_id, payload.updates)
                    updated += 1
                except HTTPException as exc:
                    failed.append({"gallery_id": gallery_id, "detail": str(exc.detail)})
        conn.commit()
    return {"updated": updated, "failed": failed}


@app.get("/api/admin/moderation/metrics")
def get_admin_moderation_metrics() -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE COALESCE(is_approved, false) = true)::int AS approved,
                    COUNT(*) FILTER (WHERE COALESCE(is_hidden, false) = true)::int AS hidden,
                    COUNT(*) FILTER (WHERE COALESCE(is_approved, false) = false AND COALESCE(is_hidden, false) = false)::int AS unmoderated,
                    COUNT(*) FILTER (WHERE start_date IS NULL)::int AS missing_date,
                    COUNT(*) FILTER (WHERE COALESCE(NULLIF(btrim(venue_name), ''), '') = '')::int AS missing_venue,
                    COUNT(*) FILTER (
                        WHERE (
                            (CASE WHEN COALESCE(NULLIF(btrim(event_title), ''), NULLIF(btrim(original_event_title), '')) IS NULL THEN 0 ELSE 1 END)
                          + (CASE WHEN start_date IS NULL THEN 0 ELSE 1 END)
                          + (CASE WHEN COALESCE(NULLIF(btrim(venue_name), ''), '') = '' THEN 0 ELSE 1 END)
                          + (CASE WHEN linked_artists IS NULL OR cardinality(linked_artists) = 0 THEN 0 ELSE 1 END)
                          + (CASE WHEN COALESCE(NULLIF(btrim(description), ''), '') = '' THEN 0 ELSE 1 END)
                        ) <= 2
                    )::int AS low_quality,
                    COUNT(*) FILTER (WHERE crawl_timestamp >= NOW() - INTERVAL '7 days')::int AS recently_crawled
                FROM app.event_records
                """
            )
            event_metrics = _serialize_row(cur.fetchone())
            cur.execute(
                """
                SELECT
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE COALESCE(is_approved, false) = true)::int AS approved,
                    COUNT(*) FILTER (WHERE COALESCE(is_hidden, false) = true)::int AS hidden,
                    COUNT(*) FILTER (WHERE COALESCE(is_approved, false) = false AND COALESCE(is_hidden, false) = false)::int AS unmoderated,
                    COUNT(*) FILTER (WHERE missing_address = true)::int AS missing_address,
                    COUNT(*) FILTER (WHERE missing_city = true)::int AS missing_city,
                    COUNT(*) FILTER (WHERE missing_country = true)::int AS missing_country,
                    COUNT(*) FILTER (WHERE missing_email = true)::int AS missing_email,
                    COUNT(*) FILTER (WHERE missing_phone = true)::int AS missing_phone,
                    COUNT(*) FILTER (WHERE missing_social = true)::int AS missing_social,
                    COUNT(*) FILTER (WHERE COALESCE(quality_score, 0) <= 3)::int AS low_quality,
                    COUNT(*) FILTER (WHERE crawl_timestamp >= NOW() - INTERVAL '7 days')::int AS recently_crawled
                FROM app.gallery_records
                """
            )
            gallery_metrics = _serialize_row(cur.fetchone())
    return {"events": event_metrics, "galleries": gallery_metrics}


@app.get("/api/review-queue")
def review_queue(limit: int = 100) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT artwork_id, artwork_title, artist_name, image_url, source_name, source_url,
                       medium_text, year_start, year_end, quality_score, review_status
                FROM app.artwork_records
                WHERE COALESCE(review_status, 'pending') = 'pending'
                ORDER BY quality_score DESC NULLS LAST, created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    return rows


@app.get("/api/artworks/{artwork_id}")
def get_artwork(artwork_id: str) -> dict[str, Any]:
    with get_conn() as conn:
        return _get_artwork_or_404(conn, artwork_id)


@app.get("/api/artists/{artist_name}")
def get_artist_profile(artist_name: str) -> dict[str, Any]:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ap.artist_name, ap.source_domain, ap.profile_url, ap.original_artist_bio,
                           ap.edited_artist_bio, ap.cleaned_artist_bio, ap.bio_quality_score,
                           ap.bio_quality_flags, ap.artist_bio, ap.bio_edited_by, ap.bio_edit_notes,
                           ap.bio_last_edited_at, ap.artwork_count, ap.last_seen,
                           COALESCE(amo.is_hidden, false) AS is_hidden,
                           amo.canonical_artist_name,
                           amo.reason AS moderation_reason,
                           amo.updated_by AS moderation_updated_by,
                           amo.updated_at AS moderation_updated_at
                    FROM app.artist_profiles ap
                    LEFT JOIN app.artist_moderation_overrides amo
                      ON amo.artist_name = ap.artist_name AND amo.source_domain = ap.source_domain
                    WHERE ap.artist_name = %s
                    LIMIT 1
                    """,
                    (artist_name,),
                )
                artist = cur.fetchone()

            if not artist:
                raise HTTPException(status_code=404, detail="Artist not found")

            artwork_columns = _relation_columns(conn, "app", "artwork_records")
            artwork_select, _ = _select_with_fallback(
                artwork_columns,
                [
                    ("artwork_id", "id"),
                    ("artwork_title", "title"),
                    ("image_url", "image_url"),
                    ("thumbnail_url", "thumbnail_url"),
                    ("medium_text", "medium_text"),
                    ("year_start", "year_start"),
                    ("year_end", "year_end"),
                    ("source_url", "source_url"),
                    ("review_status", "review_status"),
                    ("public_visibility", "public_visibility"),
                ],
            )
            artworks: list[dict[str, Any]] = []
            if artwork_select:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT {artwork_select}
                        FROM app.artwork_records
                        WHERE artist_name = %s
                        ORDER BY artwork_title ASC NULLS LAST
                        """,
                        (artist_name,),
                    )
                    artworks = _serialize_rows(cur.fetchall())

            events: list[dict[str, Any]] = []
            if _relation_exists(conn, "app", "artist_event_links"):
                event_columns = _relation_columns(conn, "app", "artist_event_links")
                event_select, _ = _select_with_fallback(
                    event_columns,
                    [
                        ("event_id", "id"),
                        ("event_title", "title"),
                        ("event_type", "event_type"),
                        ("venue_name", "venue_name"),
                        ("city", "city"),
                        ("country", "country"),
                        ("start_date", "start_date"),
                        ("end_date", "end_date"),
                        ("source_url", "source_url"),
                    ],
                )
                order_parts = [c for c in ("start_date", "end_date") if c in event_columns]
                order_sql = (
                    " ORDER BY " + ", ".join(f"{col} DESC NULLS LAST" for col in order_parts)
                    if order_parts
                    else ""
                )
                if event_select:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            SELECT {event_select}
                            FROM app.artist_event_links
                            WHERE artist_name = %s
                            {order_sql}
                            """,
                            (artist_name,),
                        )
                        events = _serialize_rows(cur.fetchall())

        return {
            "artist": _serialize_row(artist),
            "artworks": artworks,
            "events": events,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch artist profile for %s", artist_name)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/artists/{artist_name}/moderation")
def update_artist_moderation(artist_name: str, payload: ArtistModerationPayload) -> dict[str, Any]:
    try:
        canonical_artist_name = (
            payload.canonical_artist_name.strip() if payload.canonical_artist_name else None
        )
        canonical_artist_name = canonical_artist_name or None
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH artist_candidates AS (
                        SELECT
                            source_domain,
                            last_seen
                        FROM app.artist_profiles
                        WHERE artist_name = %s

                        UNION ALL

                        SELECT
                            COALESCE(source_domain, 'art.co.za') AS source_domain,
                            MAX(crawl_timestamp) AS last_seen
                        FROM app.artwork_records
                        WHERE original_artist_name = %s
                        GROUP BY COALESCE(source_domain, 'art.co.za')

                        UNION ALL

                        SELECT
                            COALESCE(source_domain, 'art.co.za') AS source_domain,
                            MAX(crawl_timestamp) AS last_seen
                        FROM raw.artworks
                        WHERE artist_name = %s
                        GROUP BY COALESCE(source_domain, 'art.co.za')
                    )
                    SELECT source_domain
                    FROM artist_candidates
                    ORDER BY last_seen DESC NULLS LAST, source_domain ASC
                    LIMIT 1
                    """,
                    (artist_name, artist_name, artist_name),
                )
                artist_row = cur.fetchone()
                if not artist_row:
                    raise HTTPException(status_code=404, detail="Artist not found")
                source_domain = artist_row["source_domain"] or "art.co.za"

                cur.execute(
                    """
                    INSERT INTO app.artist_moderation_overrides (
                      artist_name, source_domain, is_hidden, canonical_artist_name, reason, updated_by, updated_at
                    )
                    VALUES (%s, %s, %s, NULLIF(%s, ''), %s, %s, now())
                    ON CONFLICT (artist_name, source_domain)
                    DO UPDATE SET
                      is_hidden = EXCLUDED.is_hidden,
                      canonical_artist_name = EXCLUDED.canonical_artist_name,
                      reason = EXCLUDED.reason,
                      updated_by = EXCLUDED.updated_by,
                      updated_at = now()
                    RETURNING id, artist_name, source_domain, is_hidden, canonical_artist_name,
                              reason, updated_by, updated_at
                    """,
                    (
                        artist_name,
                        source_domain,
                        payload.is_hidden,
                        canonical_artist_name,
                        payload.reason,
                        payload.updated_by,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return {"status": "updated", "artist_moderation": _serialize_row(row)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update artist moderation for %s", artist_name)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/artists/{artist_name}/bio")
def save_artist_bio_edit(artist_name: str, payload: ArtistBioEditPayload) -> dict[str, Any]:
    if not payload.edited_bio.strip():
        raise HTTPException(status_code=400, detail="edited_bio cannot be empty")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM app.artist_profiles
                    WHERE artist_name = %s
                      AND source_domain = %s
                    LIMIT 1
                    """,
                    (artist_name, payload.source_domain),
                )
                artist = cur.fetchone()
                if not artist:
                    raise HTTPException(status_code=404, detail="Artist not found")

                cur.execute(
                    """
                    INSERT INTO app.artist_profile_edits (
                        artist_name,
                        source_domain,
                        edited_bio,
                        edited_by,
                        edit_notes
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, created_at
                    """,
                    (
                        artist_name,
                        payload.source_domain,
                        payload.edited_bio.strip(),
                        payload.edited_by,
                        payload.edit_notes,
                    ),
                )
                edit_row = _serialize_row(cur.fetchone())
            conn.commit()
        return {"status": "saved", "edit": edit_row}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to save artist bio edit for %s", artist_name)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/artworks/{artwork_id}/approve")
def approve_artwork(artwork_id: str, payload: ReviewActionPayload) -> dict[str, str]:
    with get_conn() as conn:
        _get_artwork_or_404(conn, artwork_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.review_queue (artwork_id, review_status, reviewed_by, review_notes, reviewed_at)
                VALUES (%s::uuid, 'approved', %s, %s, now())
                """,
                (artwork_id, payload.reviewer, payload.notes),
            )
            cur.execute(
                """
                INSERT INTO app.approved_artworks (artwork_id, approved_by, approved_at, public_visibility, notes)
                VALUES (%s::uuid, %s, now(), %s, %s)
                """,
                (artwork_id, payload.reviewer, payload.public_visibility, payload.notes),
            )
            cur.execute("DELETE FROM app.rejected_artworks WHERE artwork_id = %s::uuid", (artwork_id,))
        conn.commit()
    return {"status": "approved"}


@app.post("/api/artworks/{artwork_id}/reject")
def reject_artwork(artwork_id: str, payload: ReviewActionPayload) -> dict[str, str]:
    rejection_reason = payload.rejection_reason or "Rejected by reviewer"
    with get_conn() as conn:
        _get_artwork_or_404(conn, artwork_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.review_queue (artwork_id, review_status, reviewed_by, review_notes, reviewed_at)
                VALUES (%s::uuid, 'rejected', %s, %s, now())
                """,
                (artwork_id, payload.reviewer, payload.notes),
            )
            cur.execute(
                """
                INSERT INTO app.rejected_artworks (artwork_id, rejection_reason, rejected_by, rejected_at, notes)
                VALUES (%s::uuid, %s, %s, now(), %s)
                """,
                (artwork_id, rejection_reason, payload.reviewer, payload.notes),
            )
            cur.execute("DELETE FROM app.approved_artworks WHERE artwork_id = %s::uuid", (artwork_id,))
        conn.commit()
    return {"status": "rejected"}
