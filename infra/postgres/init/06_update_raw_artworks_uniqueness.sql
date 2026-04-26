\connect artio

ALTER TABLE raw.artworks
    DROP CONSTRAINT IF EXISTS artworks_source_domain_source_url_key;

DROP INDEX IF EXISTS raw.artworks_source_domain_source_url_key;

CREATE UNIQUE INDEX IF NOT EXISTS artworks_source_domain_source_record_id_key
    ON raw.artworks (source_domain, source_record_id)
    WHERE source_record_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS artworks_source_domain_source_url_null_record_id_key
    ON raw.artworks (source_domain, source_url)
    WHERE source_record_id IS NULL;
