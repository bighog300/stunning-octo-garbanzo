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
