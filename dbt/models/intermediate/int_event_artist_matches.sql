select distinct
    ec.event_id,
    a.artist_id,
    'exact_name'::text as match_type
from {{ ref('stg_event_artist_candidates') }} ec
inner join {{ ref('int_artist_normalized') }} a
    on a.normalized_artist_name = ec.normalized_candidate_artist_name
where ec.normalized_candidate_artist_name is not null
  and a.normalized_artist_name is not null
  -- phase 2 scaffold: fuzzy matching threshold placeholder (not enabled)
  and 1 = 1
