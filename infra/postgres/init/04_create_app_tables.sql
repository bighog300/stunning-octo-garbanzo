\connect artio

CREATE TABLE IF NOT EXISTS app.review_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artwork_id UUID NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT DEFAULT 'normal',
    assigned_to TEXT,
    review_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by TEXT
);

CREATE TABLE IF NOT EXISTS app.approved_artworks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artwork_id UUID NOT NULL,
    approved_by TEXT,
    approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    public_visibility BOOLEAN NOT NULL DEFAULT false,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS app.rejected_artworks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artwork_id UUID NOT NULL,
    rejection_reason TEXT NOT NULL,
    rejected_by TEXT,
    rejected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS app.record_enrichments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artwork_id UUID NOT NULL,
    enriched_field TEXT NOT NULL,
    original_value TEXT,
    enriched_value TEXT NOT NULL,
    enriched_by TEXT,
    enriched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS app.artist_profile_edits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artist_name TEXT NOT NULL,
    source_domain TEXT NOT NULL DEFAULT 'art.co.za',
    edited_bio TEXT NOT NULL,
    edited_by TEXT,
    edit_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_artist_profile_edits_artist
ON app.artist_profile_edits (artist_name, source_domain, created_at DESC);

CREATE TABLE IF NOT EXISTS app.data_quality_flags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    artist_name TEXT,
    issue_type TEXT NOT NULL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    resolved_by TEXT,
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_data_quality_flags_status
ON app.data_quality_flags (status);

CREATE INDEX IF NOT EXISTS idx_data_quality_flags_entity_type
ON app.data_quality_flags (entity_type);

CREATE INDEX IF NOT EXISTS idx_data_quality_flags_artist_name
ON app.data_quality_flags (artist_name);

CREATE INDEX IF NOT EXISTS idx_data_quality_flags_issue_type
ON app.data_quality_flags (issue_type);

CREATE INDEX IF NOT EXISTS idx_data_quality_flags_created_at_desc
ON app.data_quality_flags (created_at DESC);

CREATE TABLE IF NOT EXISTS app.artist_moderation_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artist_name TEXT NOT NULL,
    source_domain TEXT NOT NULL DEFAULT 'art.co.za',
    is_hidden BOOLEAN NOT NULL DEFAULT false,
    canonical_artist_name TEXT,
    reason TEXT,
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (artist_name, source_domain)
);

CREATE TABLE IF NOT EXISTS app.event_moderation_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL UNIQUE,
    is_hidden BOOLEAN NOT NULL DEFAULT false,
    is_approved BOOLEAN NOT NULL DEFAULT false,
    canonical_event_title TEXT,
    event_type TEXT,
    moderation_reason TEXT,
    moderator_notes TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.event_moderation_corrections (
    correction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL,
    field_name TEXT NOT NULL,
    original_value TEXT,
    suggested_value TEXT,
    final_value TEXT,
    suggestion_confidence NUMERIC(5,4),
    suggestion_reason TEXT,
    action TEXT NOT NULL,
    source_domain TEXT,
    event_title TEXT,
    event_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT
);

CREATE TABLE IF NOT EXISTS app.event_learned_rules (
    rule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    field_name TEXT NOT NULL,
    pattern TEXT NOT NULL,
    suggested_value TEXT NOT NULL,
    confidence NUMERIC(5,4) NOT NULL DEFAULT 0.5,
    support_count INTEGER NOT NULL DEFAULT 1,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    source_domain TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (field_name, pattern, suggested_value, source_domain)
);
