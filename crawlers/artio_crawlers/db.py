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


def upsert_event(conn, item: dict) -> str:
    has_source_record_id = bool(item.get("source_record_id"))
    conflict_target = (
        "(source_domain, source_record_id) WHERE source_record_id IS NOT NULL"
        if has_source_record_id
        else "(source_domain, source_url) WHERE source_record_id IS NULL"
    )
    with conn.cursor() as cur:
        cur.execute(
            f'''
            INSERT INTO raw.events (
                crawl_run_id,
                source_name,
                source_domain,
                source_url,
                source_record_id,
                event_type,
                event_title,
                venue_name,
                venue_address,
                city,
                country,
                start_date,
                end_date,
                opening_datetime,
                description,
                image_url,
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
                %(event_type)s,
                %(event_title)s,
                %(venue_name)s,
                %(venue_address)s,
                %(city)s,
                %(country)s,
                %(start_date)s,
                %(end_date)s,
                %(opening_datetime)s,
                %(description)s,
                %(image_url)s,
                %(raw_payload)s,
                %(content_hash)s,
                %(crawl_timestamp)s
            )
            ON CONFLICT {conflict_target}
            DO UPDATE SET
                source_name = EXCLUDED.source_name,
                event_type = EXCLUDED.event_type,
                event_title = EXCLUDED.event_title,
                venue_name = EXCLUDED.venue_name,
                venue_address = EXCLUDED.venue_address,
                city = EXCLUDED.city,
                country = EXCLUDED.country,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                opening_datetime = EXCLUDED.opening_datetime,
                description = EXCLUDED.description,
                image_url = EXCLUDED.image_url,
                raw_payload = EXCLUDED.raw_payload,
                content_hash = EXCLUDED.content_hash,
                crawl_timestamp = EXCLUDED.crawl_timestamp,
                updated_at = now()
            RETURNING id
            ''',
            {**item, "raw_payload": Json(item.get("raw_payload") or {})},
        )
        event_id = str(cur.fetchone()[0])
    conn.commit()
    return event_id


def delete_event_children(conn, event_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM raw.event_artists WHERE event_id = %s", (event_id,))
        cur.execute("DELETE FROM raw.event_images WHERE event_id = %s", (event_id,))
    conn.commit()


def insert_event_artist(conn, item: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw.event_artists (
                event_id,
                artist_name,
                artist_name_normalized,
                artist_profile_url,
                match_type
            )
            VALUES (%(event_id)s, %(artist_name)s, %(artist_name_normalized)s, %(artist_profile_url)s, %(match_type)s)
            """,
            item,
        )
    conn.commit()


def insert_event_image(conn, item: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw.event_images (
                event_id,
                image_url,
                image_caption,
                image_type,
                content_hash
            )
            VALUES (%(event_id)s, %(image_url)s, %(image_caption)s, %(image_type)s, %(content_hash)s)
            """,
            item,
        )
    conn.commit()


def upsert_gallery(conn, item: dict) -> None:
    has_source_record_id = bool(item.get("source_record_id"))
    conflict_target = (
        "(source_domain, source_record_id) WHERE source_record_id IS NOT NULL"
        if has_source_record_id
        else "(source_domain, source_url) WHERE source_record_id IS NULL"
    )
    with conn.cursor() as cur:
        cur.execute(
            f'''
            INSERT INTO raw.galleries (
                source_domain,
                source_url,
                source_record_id,
                gallery_name,
                address,
                city,
                region,
                country,
                phone,
                email,
                website_url,
                instagram_url,
                facebook_url,
                contact_person,
                description,
                raw_payload,
                crawl_timestamp
            )
            VALUES (
                %(source_domain)s,
                %(source_url)s,
                %(source_record_id)s,
                %(gallery_name)s,
                %(address)s,
                %(city)s,
                %(region)s,
                %(country)s,
                %(phone)s,
                %(email)s,
                %(website_url)s,
                %(instagram_url)s,
                %(facebook_url)s,
                %(contact_person)s,
                %(description)s,
                %(raw_payload)s,
                %(crawl_timestamp)s
            )
            ON CONFLICT {conflict_target}
            DO UPDATE SET
                gallery_name = EXCLUDED.gallery_name,
                address = EXCLUDED.address,
                city = EXCLUDED.city,
                region = EXCLUDED.region,
                country = EXCLUDED.country,
                phone = EXCLUDED.phone,
                email = EXCLUDED.email,
                website_url = EXCLUDED.website_url,
                instagram_url = EXCLUDED.instagram_url,
                facebook_url = EXCLUDED.facebook_url,
                contact_person = EXCLUDED.contact_person,
                description = EXCLUDED.description,
                raw_payload = EXCLUDED.raw_payload,
                crawl_timestamp = EXCLUDED.crawl_timestamp
            ''',
            {**item, "raw_payload": Json(item.get("raw_payload") or {})},
        )
    conn.commit()


def upsert_artist(conn, item: dict) -> None:
    has_source_record_id = bool(item.get("source_record_id"))
    conflict_target = (
        "(source_domain, source_record_id) WHERE source_record_id IS NOT NULL"
        if has_source_record_id
        else "(source_domain, source_url) WHERE source_record_id IS NULL"
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'raw' AND table_name = 'artists'
            """
        )
        available_columns = {row[0] for row in cur.fetchall()}

        ordered_columns = [
            "crawl_run_id",
            "source_name",
            "source_domain",
            "source_url",
            "source_record_id",
            "artist_name",
            "birth_year_text",
            "death_year_text",
            "nationality_text",
            "biography",
            "image_url",
            "raw_payload",
            "content_hash",
            "crawl_timestamp",
        ]
        insert_columns = [column for column in ordered_columns if column in available_columns]
        update_columns = [
            column
            for column in (
                "source_name",
                "artist_name",
                "birth_year_text",
                "death_year_text",
                "nationality_text",
                "biography",
                "image_url",
                "raw_payload",
                "content_hash",
                "crawl_timestamp",
            )
            if column in insert_columns
        ]

        insert_sql = ",\n                ".join(insert_columns)
        values_sql = ",\n                ".join(f"%({column})s" for column in insert_columns)
        update_sql = ",\n                ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
        if "updated_at" in available_columns:
            update_sql = f"{update_sql},\n                updated_at = now()"

        cur.execute(
            f"""
            INSERT INTO raw.artists (
                {insert_sql}
            )
            VALUES (
                {values_sql}
            )
            ON CONFLICT {conflict_target}
            DO UPDATE SET
                {update_sql}
            """,
            {**item, "raw_payload": Json(item.get("raw_payload") or {})},
        )
    conn.commit()
