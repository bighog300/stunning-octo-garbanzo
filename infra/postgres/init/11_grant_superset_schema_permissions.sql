\connect artio

CREATE SCHEMA IF NOT EXISTS superset;

GRANT USAGE, CREATE ON SCHEMA superset TO artio;
GRANT SELECT ON ALL TABLES IN SCHEMA superset TO artio;
ALTER DEFAULT PRIVILEGES IN SCHEMA superset GRANT SELECT ON TABLES TO artio;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.views
        WHERE table_schema = 'superset'
          AND table_name = 'gallery_quality_summary'
    ) THEN
        EXECUTE 'ALTER VIEW superset.gallery_quality_summary OWNER TO artio';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.views
        WHERE table_schema = 'superset'
          AND table_name = 'event_quality_summary'
    ) THEN
        EXECUTE 'ALTER VIEW superset.event_quality_summary OWNER TO artio';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.views
        WHERE table_schema = 'superset'
          AND table_name = 'moderation_summary'
    ) THEN
        EXECUTE 'ALTER VIEW superset.moderation_summary OWNER TO artio';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.views
        WHERE table_schema = 'superset'
          AND table_name = 'crawl_health_summary'
    ) THEN
        EXECUTE 'ALTER VIEW superset.crawl_health_summary OWNER TO artio';
    END IF;
END
$$;
