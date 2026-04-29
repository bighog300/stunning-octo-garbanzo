\connect artio

CREATE TABLE IF NOT EXISTS raw.sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name TEXT NOT NULL,
    source_domain TEXT NOT NULL UNIQUE,
    base_url TEXT,
    source_type TEXT,
    risk_level TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS raw.crawl_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES raw.sources(id),
    source_name TEXT,
    spider_name TEXT NOT NULL,
    run_status TEXT NOT NULL DEFAULT 'started',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    records_found INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    error_message TEXT,
    airflow_dag_id TEXT,
    airflow_task_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.artworks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES raw.sources(id),
    crawl_run_id UUID REFERENCES raw.crawl_runs(id),
    source_name TEXT,
    source_domain TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_record_id TEXT,
    artist_name TEXT,
    artwork_title TEXT,
    artwork_date_text TEXT,
    medium_text TEXT,
    dimensions_text TEXT,
    price_text TEXT,
    currency_text TEXT,
    gallery_name TEXT,
    institution_name TEXT,
    department_name TEXT,
    image_url TEXT,
    thumbnail_url TEXT,
    description TEXT,
    raw_payload JSONB,
    content_hash TEXT,
    crawl_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS artworks_source_domain_source_record_id_key
    ON raw.artworks (source_domain, source_record_id)
    WHERE source_record_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS artworks_source_domain_source_url_null_record_id_key
    ON raw.artworks (source_domain, source_url)
    WHERE source_record_id IS NULL;

CREATE TABLE IF NOT EXISTS raw.artists (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES raw.sources(id),
    crawl_run_id UUID REFERENCES raw.crawl_runs(id),
    source_url TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    source_record_id TEXT,
    artist_name TEXT NOT NULL,
    birth_year_text TEXT,
    death_year_text TEXT,
    nationality_text TEXT,
    biography TEXT,
    image_url TEXT,
    raw_payload JSONB,
    content_hash TEXT,
    crawl_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS artists_source_domain_source_record_id_key
    ON raw.artists (source_domain, source_record_id)
    WHERE source_record_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS artists_source_domain_source_url_null_record_id_key
    ON raw.artists (source_domain, source_url)
    WHERE source_record_id IS NULL;

CREATE TABLE IF NOT EXISTS raw.crawl_errors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    crawl_run_id UUID REFERENCES raw.crawl_runs(id),
    source_id UUID REFERENCES raw.sources(id),
    spider_name TEXT,
    source_url TEXT,
    error_type TEXT NOT NULL,
    error_message TEXT,
    http_status INTEGER,
    retry_count INTEGER DEFAULT 0,
    raw_context JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO raw.sources (source_name, source_domain, base_url, source_type, risk_level)
VALUES ('The Metropolitan Museum of Art', 'metmuseum.org', 'https://www.metmuseum.org', 'museum', 'low')
ON CONFLICT (source_domain) DO NOTHING;
