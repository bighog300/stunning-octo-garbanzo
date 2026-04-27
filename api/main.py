import os
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any
import logging

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


class ReviewActionPayload(BaseModel):
    reviewer: str | None = "artio_admin"
    notes: str | None = None
    rejection_reason: str | None = None
    public_visibility: bool = True


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


@app.get("/health")
def health() -> dict[str, str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    return {"status": "ok"}


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
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 500))
    where_clauses: list[str] = []
    params: list[Any] = []

    if search:
        where_clauses.append("artist_name ILIKE %s")
        params.append(f"%{search}%")
    if source_domain:
        where_clauses.append("source_domain = %s")
        params.append(source_domain)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params.extend([safe_limit, offset])

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT artist_name, source_domain, profile_url, artist_bio, artwork_count, last_seen
                    FROM app.artist_profiles
                    {where_sql}
                    ORDER BY artist_name ASC
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
                    SELECT artist_name, source_domain, profile_url, artist_bio, artwork_count, last_seen
                    FROM app.artist_profiles
                    WHERE artist_name = %s
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
