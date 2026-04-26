select
    id as crawl_run_id,
    source_id,
    source_name,
    spider_name,
    run_status,
    started_at,
    finished_at,
    records_found,
    records_inserted,
    records_updated,
    records_failed,
    error_message,
    created_at
from {{ source('raw', 'crawl_runs') }}
