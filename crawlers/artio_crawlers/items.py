import scrapy


class ArtworkItem(scrapy.Item):
    source_name = scrapy.Field()
    source_domain = scrapy.Field()
    source_url = scrapy.Field()
    source_record_id = scrapy.Field()

    artist_name = scrapy.Field()
    artwork_title = scrapy.Field()
    artwork_date_text = scrapy.Field()
    medium_text = scrapy.Field()
    dimensions_text = scrapy.Field()
    price_text = scrapy.Field()
    currency_text = scrapy.Field()

    gallery_name = scrapy.Field()
    institution_name = scrapy.Field()
    department_name = scrapy.Field()

    image_url = scrapy.Field()
    thumbnail_url = scrapy.Field()
    description = scrapy.Field()

    raw_payload = scrapy.Field()
    content_hash = scrapy.Field()
    crawl_timestamp = scrapy.Field()
    crawl_run_id = scrapy.Field()
