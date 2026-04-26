select
    id as source_id,
    source_name,
    source_domain,
    base_url,
    source_type,
    risk_level,
    is_active,
    created_at,
    updated_at
from {{ source('raw', 'sources') }}
