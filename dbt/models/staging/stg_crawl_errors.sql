select
    id as crawl_error_id,
    crawl_run_id,
    source_id,
    spider_name,
    source_url,
    error_type,
    error_message,
    http_status,
    retry_count,
    created_at
from {{ source('raw', 'crawl_errors') }}
