import os
from contextlib import contextmanager
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


class ReviewActionPayload(BaseModel):
    reviewer: str | None = "artio_admin"
    notes: str | None = None
    rejection_reason: str | None = None
    public_visibility: bool = True


app = FastAPI(title="Artio API", version="0.1.0")

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


@app.get("/api/artworks/{artwork_id}")
def get_artwork(artwork_id: str) -> dict[str, Any]:
    with get_conn() as conn:
        return _get_artwork_or_404(conn, artwork_id)


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
