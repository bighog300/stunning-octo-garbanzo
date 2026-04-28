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


class ArtistItem(scrapy.Item):
    crawl_run_id = scrapy.Field()
    source_name = scrapy.Field()
    source_domain = scrapy.Field()
    source_url = scrapy.Field()
    source_record_id = scrapy.Field()

    artist_name = scrapy.Field()
    birth_year_text = scrapy.Field()
    death_year_text = scrapy.Field()
    nationality_text = scrapy.Field()
    biography = scrapy.Field()
    image_url = scrapy.Field()

    raw_payload = scrapy.Field()
    content_hash = scrapy.Field()
    crawl_timestamp = scrapy.Field()


class EventItem(scrapy.Item):
    crawl_run_id = scrapy.Field()
    source_name = scrapy.Field()
    source_domain = scrapy.Field()
    source_url = scrapy.Field()
    source_record_id = scrapy.Field()

    event_type = scrapy.Field()
    event_title = scrapy.Field()
    venue_name = scrapy.Field()
    venue_address = scrapy.Field()
    city = scrapy.Field()
    country = scrapy.Field()
    start_date = scrapy.Field()
    end_date = scrapy.Field()
    opening_datetime = scrapy.Field()
    description = scrapy.Field()
    image_url = scrapy.Field()

    raw_payload = scrapy.Field()
    content_hash = scrapy.Field()
    crawl_timestamp = scrapy.Field()


class EventArtistItem(scrapy.Item):
    event_source_record_id = scrapy.Field()
    event_source_url = scrapy.Field()
    event_id = scrapy.Field()
    artist_name = scrapy.Field()
    artist_name_normalized = scrapy.Field()
    artist_profile_url = scrapy.Field()
    match_type = scrapy.Field()


class EventImageItem(scrapy.Item):
    event_source_record_id = scrapy.Field()
    event_source_url = scrapy.Field()
    event_id = scrapy.Field()
    image_url = scrapy.Field()
    image_caption = scrapy.Field()
    image_type = scrapy.Field()
    content_hash = scrapy.Field()


class GalleryItem(scrapy.Item):
    crawl_run_id = scrapy.Field()
    source_domain = scrapy.Field()
    source_url = scrapy.Field()
    source_record_id = scrapy.Field()
    gallery_name = scrapy.Field()
    address = scrapy.Field()
    city = scrapy.Field()
    region = scrapy.Field()
    country = scrapy.Field()
    phone = scrapy.Field()
    email = scrapy.Field()
    website_url = scrapy.Field()
    instagram_url = scrapy.Field()
    facebook_url = scrapy.Field()
    contact_person = scrapy.Field()
    description = scrapy.Field()
    raw_payload = scrapy.Field()
    crawl_timestamp = scrapy.Field()
