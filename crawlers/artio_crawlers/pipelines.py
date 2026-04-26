from itemadapter import ItemAdapter
from artio_crawlers.db import get_connection, upsert_artwork


class PostgresArtworkPipeline:
    def open_spider(self, spider):
        self.conn = get_connection()

    def close_spider(self, spider):
        self.conn.close()

    def process_item(self, item, spider):
        data = dict(ItemAdapter(item))
        if getattr(spider, "dry_run", False):
            spider.logger.info("Dry run item: %s", data)
            return item

        if not data.get("source_url") or not data.get("source_domain"):
            raise ValueError("source_url and source_domain are required")

        upsert_artwork(self.conn, data)
        return item
