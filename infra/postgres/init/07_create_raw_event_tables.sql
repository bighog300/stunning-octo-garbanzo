\connect artio

CREATE TABLE IF NOT EXISTS raw.events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    crawl_run_id UUID REFERENCES raw.crawl_runs(id),
    source_name TEXT,
    source_domain TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_record_id TEXT,
    event_type TEXT,
    event_title TEXT,
    venue_name TEXT,
    venue_address TEXT,
    city TEXT,
    country TEXT,
    start_date DATE,
    end_date DATE,
    opening_datetime TIMESTAMPTZ,
    description TEXT,
    image_url TEXT,
    raw_payload JSONB,
    content_hash TEXT,
    crawl_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS events_source_domain_source_record_id_key
    ON raw.events (source_domain, source_record_id)
    WHERE source_record_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS events_source_domain_source_url_null_record_id_key
    ON raw.events (source_domain, source_url)
    WHERE source_record_id IS NULL;

CREATE TABLE IF NOT EXISTS raw.event_artists (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES raw.events(id),
    artist_name TEXT,
    artist_name_normalized TEXT,
    artist_profile_url TEXT,
    match_type TEXT
);

CREATE TABLE IF NOT EXISTS raw.event_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES raw.events(id),
    image_url TEXT,
    image_caption TEXT,
    image_type TEXT,
    content_hash TEXT
);
