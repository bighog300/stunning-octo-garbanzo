\connect artio

CREATE UNIQUE INDEX IF NOT EXISTS artists_source_domain_source_record_id_key
    ON raw.artists (source_domain, source_record_id)
    WHERE source_record_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS artists_source_domain_source_url_null_record_id_key
    ON raw.artists (source_domain, source_url)
    WHERE source_record_id IS NULL;
