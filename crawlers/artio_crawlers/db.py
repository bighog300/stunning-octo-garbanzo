import os
import psycopg2
from psycopg2.extras import Json


def get_connection():
    return psycopg2.connect(
        host=os.getenv("ARTIO_POSTGRES_HOST", "postgres"),
        port=os.getenv("ARTIO_POSTGRES_PORT", "5432"),
        dbname=os.getenv("ARTIO_POSTGRES_DB", "artio"),
        user=os.getenv("ARTIO_POSTGRES_USER", "artio"),
        password=os.getenv("ARTIO_POSTGRES_PASSWORD", "artio"),
    )


def upsert_artwork(conn, item: dict) -> None:
    has_source_record_id = bool(item.get("source_record_id"))
    conflict_target = (
        "(source_domain, source_record_id) WHERE source_record_id IS NOT NULL"
        if has_source_record_id
        else "(source_domain, source_url) WHERE source_record_id IS NULL"
    )
    with conn.cursor() as cur:
        cur.execute(
            f'''
            INSERT INTO raw.artworks (
                crawl_run_id,
                source_name,
                source_domain,
                source_url,
                source_record_id,
                artist_name,
                artwork_title,
                artwork_date_text,
                medium_text,
                dimensions_text,
                price_text,
                currency_text,
                gallery_name,
                institution_name,
                department_name,
                image_url,
                thumbnail_url,
                description,
                raw_payload,
                content_hash,
                crawl_timestamp
            )
            VALUES (
                %(crawl_run_id)s,
                %(source_name)s,
                %(source_domain)s,
                %(source_url)s,
                %(source_record_id)s,
                %(artist_name)s,
                %(artwork_title)s,
                %(artwork_date_text)s,
                %(medium_text)s,
                %(dimensions_text)s,
                %(price_text)s,
                %(currency_text)s,
                %(gallery_name)s,
                %(institution_name)s,
                %(department_name)s,
                %(image_url)s,
                %(thumbnail_url)s,
                %(description)s,
                %(raw_payload)s,
                %(content_hash)s,
                %(crawl_timestamp)s
            )
            ON CONFLICT {conflict_target}
            DO UPDATE SET
                artist_name = EXCLUDED.artist_name,
                artwork_title = EXCLUDED.artwork_title,
                artwork_date_text = EXCLUDED.artwork_date_text,
                medium_text = EXCLUDED.medium_text,
                dimensions_text = EXCLUDED.dimensions_text,
                image_url = EXCLUDED.image_url,
                thumbnail_url = EXCLUDED.thumbnail_url,
                description = EXCLUDED.description,
                raw_payload = EXCLUDED.raw_payload,
                content_hash = EXCLUDED.content_hash,
                crawl_timestamp = EXCLUDED.crawl_timestamp,
                updated_at = now()
            ''',
            {**item, "raw_payload": Json(item.get("raw_payload") or {})},
        )
    conn.commit()
