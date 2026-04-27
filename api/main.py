import os
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any
import logging

import psycopg
from fastapi import FastAPI, HTTPException, Query
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


app = FastAPI(title="Artio API", version="0.1.0")
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    moderation_status: str = Query(default="all"),
    event_type: str | None = None,
    source_domain: str | None = None,
    missing_date: bool = False,
    missing_venue: bool = False,
    search: str | None = None,
    include_hidden: bool = True,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 500))
    where_clauses: list[str] = []
    params: list[Any] = []

    allowed_statuses = {"all", "unmoderated", "approved", "hidden"}
    if moderation_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Invalid moderation_status")

    if moderation_status == "unmoderated":
        where_clauses.append("moderation_override_exists = false")
    elif moderation_status == "approved":
        where_clauses.append("is_approved = true")
    elif moderation_status == "hidden":
        where_clauses.append("is_hidden = true")

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

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT event_id, event_title, original_event_title, canonical_event_title,
                       event_type, original_event_type, linked_artists, venue_name, city, country,
                       start_date, end_date, source_name, source_domain, source_url, crawl_timestamp,
                       is_hidden, is_approved, moderation_override_exists, moderation_reason, updated_at
                FROM app.event_records
                {where_sql}
                ORDER BY crawl_timestamp DESC NULLS LAST, created_at DESC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            rows = cur.fetchall()
    return _serialize_rows(rows)


@app.get("/api/admin/events/{event_id}")
def get_admin_event(event_id: str) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
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
    return {"event": _serialize_row(event_row), "linked_artists": _serialize_rows(linked_artists)}


@app.patch("/api/admin/events/{event_id}/moderation")
def patch_admin_event_moderation(event_id: str, payload: EventModerationPayload) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM app.event_records WHERE event_id = %s::uuid LIMIT 1",
                (event_id,),
            )
            exists = cur.fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="Event not found")

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

            next_hidden = (
                payload.is_hidden if payload.is_hidden is not None else current.get("is_hidden", False)
            )
            next_approved = (
                payload.is_approved
                if payload.is_approved is not None
                else current.get("is_approved", False)
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
                payload.moderator_notes
                if payload.moderator_notes is not None
                else current.get("moderator_notes")
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
        conn.commit()
    return {"status": "updated", "event_moderation": _serialize_row(row)}


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
