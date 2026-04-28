from itemadapter import ItemAdapter
from artio_crawlers.db import (
    delete_event_children,
    get_connection,
    insert_event_artist,
    insert_event_image,
    upsert_gallery,
    upsert_artwork,
    upsert_event,
)


class PostgresArtworkPipeline:
    def open_spider(self, spider):
        self.conn = get_connection()
        self._event_id_map: dict[tuple[str | None, str | None], str] = {}
        self._event_children_reset: set[str] = set()

    def close_spider(self, spider):
        self.conn.close()

    def process_item(self, item, spider):
        data = dict(ItemAdapter(item))
        if getattr(spider, "dry_run", False):
            spider.logger.info("Dry run item: %s", data)
            return item

        if "artwork_title" in data:
            if not data.get("source_url") or not data.get("source_domain"):
                raise ValueError("source_url and source_domain are required for ArtworkItem")
            upsert_artwork(self.conn, data)
            return item

        if "event_title" in data:
            if not data.get("source_url") or not data.get("source_domain"):
                raise ValueError("source_url and source_domain are required for EventItem")
            event_id = upsert_event(self.conn, data)
            event_key = (data.get("source_record_id"), data.get("source_url"))
            self._event_id_map[event_key] = event_id
            if event_id not in self._event_children_reset:
                delete_event_children(self.conn, event_id)
                self._event_children_reset.add(event_id)
            return item

        if "artist_name_normalized" in data:
            event_key = (data.get("event_source_record_id"), data.get("event_source_url"))
            event_id = data.get("event_id") or self._event_id_map.get(event_key)
            if not event_id:
                raise ValueError("event_id or resolvable event source identity is required for EventArtistItem")
            insert_event_artist(
                self.conn,
                {
                    "event_id": event_id,
                    "artist_name": data.get("artist_name"),
                    "artist_name_normalized": data.get("artist_name_normalized"),
                    "artist_profile_url": data.get("artist_profile_url"),
                    "match_type": data.get("match_type"),
                },
            )
            return item

        if "image_type" in data:
            event_key = (data.get("event_source_record_id"), data.get("event_source_url"))
            event_id = data.get("event_id") or self._event_id_map.get(event_key)
            if not event_id:
                raise ValueError("event_id or resolvable event source identity is required for EventImageItem")
            insert_event_image(
                self.conn,
                {
                    "event_id": event_id,
                    "image_url": data.get("image_url"),
                    "image_caption": data.get("image_caption"),
                    "image_type": data.get("image_type"),
                    "content_hash": data.get("content_hash"),
                },
            )
            return item

        if "gallery_name" in data or "contact_person" in data or "website_url" in data or "instagram_url" in data:
            if not data.get("source_url") or not data.get("source_domain"):
                raise ValueError("source_url and source_domain are required for GalleryItem")
            upsert_gallery(self.conn, data)
            return item

        raise ValueError("Unknown item type for database pipeline")
        return item
