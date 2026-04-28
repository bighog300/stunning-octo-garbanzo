\connect artio

CREATE TABLE IF NOT EXISTS raw.galleries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_domain TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_record_id TEXT,
    gallery_name TEXT,
    address TEXT,
    city TEXT,
    region TEXT,
    country TEXT,
    phone TEXT,
    email TEXT,
    website_url TEXT,
    instagram_url TEXT,
    facebook_url TEXT,
    contact_person TEXT,
    description TEXT,
    raw_payload JSONB,
    crawl_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS galleries_source_domain_source_record_id_key
    ON raw.galleries (source_domain, source_record_id)
    WHERE source_record_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS galleries_source_domain_source_url_null_record_id_key
    ON raw.galleries (source_domain, source_url)
    WHERE source_record_id IS NULL;
