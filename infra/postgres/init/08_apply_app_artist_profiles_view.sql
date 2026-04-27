\connect artio

-- Ensure app.artist_profiles keeps the runtime shape and latest edit join in real Docker runs.
-- This file is mounted into /docker-entrypoint-initdb.d and can be re-applied manually.
CREATE OR REPLACE VIEW app.artist_profiles AS
WITH artist_rollup AS (
    SELECT
        ar.artist_name,
        ar.source_domain,
        COUNT(*) AS artwork_count,
        MAX(ar.crawl_timestamp) AS last_seen
    FROM app.artwork_records ar
    WHERE ar.artist_name IS NOT NULL
    GROUP BY ar.artist_name, ar.source_domain
),
latest_profile_row AS (
    SELECT DISTINCT ON (ar.artist_name, ar.source_domain)
        ar.artist_name,
        ar.source_domain,
        ar.source_url AS profile_url,
        ar.description AS original_artist_bio
    FROM app.artwork_records ar
    WHERE ar.artist_name IS NOT NULL
    ORDER BY
        ar.artist_name,
        ar.source_domain,
        (ar.source_url IS NOT NULL AND ar.description IS NOT NULL) DESC,
        ar.crawl_timestamp DESC NULLS LAST
),
latest_bio_edits AS (
    SELECT DISTINCT ON (artist_name, source_domain)
        artist_name,
        source_domain,
        edited_bio,
        edited_by,
        edit_notes,
        created_at AS edited_at
    FROM app.artist_profile_edits
    ORDER BY artist_name, source_domain, created_at DESC
),
bio_inputs AS (
    SELECT
        r.artist_name,
        r.source_domain,
        p.profile_url,
        p.original_artist_bio,
        lbe.edited_bio,
        lbe.edited_by,
        lbe.edit_notes,
        lbe.edited_at,
        r.artwork_count,
        r.last_seen
    FROM artist_rollup r
    LEFT JOIN latest_profile_row p
        ON p.artist_name = r.artist_name
       AND p.source_domain = r.source_domain
    LEFT JOIN latest_bio_edits lbe
        ON lbe.artist_name = r.artist_name
       AND lbe.source_domain = r.source_domain
),
bio_cleaning AS (
    SELECT
        bi.*,
        COALESCE(bi.original_artist_bio, '') ~* '[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}' AS contains_email,
        COALESCE(bi.original_artist_bio, '') ~* '(?:\+?\d[\d\-\s().]{7,}\d)' AS contains_phone,
        COALESCE(bi.original_artist_bio, '') ~* '(about the artist|artworks\s*[▼v]|painting prints|earlier works)' AS navigation_noise,
        regexp_replace(
            regexp_replace(COALESCE(bi.original_artist_bio, ''), '[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}', ' ', 'gi'),
            '(?:\+?\d[\d\-\s().]{7,}\d)',
            ' ',
            'g'
        ) AS bio_contact_removed
    FROM bio_inputs bi
),
bio_dedup AS (
    SELECT
        bc.*,
        (
            SELECT COALESCE(string_agg(paragraph, E'\n\n' ORDER BY paragraph_index), '')
            FROM (
                SELECT DISTINCT ON (lower(btrim(paragraph)))
                    paragraph_index,
                    btrim(paragraph) AS paragraph
                FROM regexp_split_to_table(
                    regexp_replace(
                        regexp_replace(
                            regexp_replace(
                                bc.bio_contact_removed,
                                '(?im)^\s*(about the artist|artworks\s*[▼v]|painting prints|earlier works)\s*$',
                                ' ',
                                'g'
                            ),
                            '(?im)^\s*(?:19|20)\d{2}\s*[-–:|].*$',
                            ' ',
                            'g'
                        ),
                        '[\r\t]+',
                        ' ',
                        'g'
                    ),
                    E'\n{2,}'
                ) WITH ORDINALITY AS split_paragraph(paragraph, paragraph_index)
                WHERE btrim(paragraph) <> ''
            ) normalized_paragraphs
        ) AS bio_paragraphs_cleaned
    FROM bio_cleaning bc
),
bio_sentence_dedup AS (
    SELECT
        bd.*,
        (
            SELECT COALESCE(string_agg(sentence, '. ' ORDER BY sentence_index), '')
            FROM (
                SELECT DISTINCT ON (lower(btrim(sentence)))
                    sentence_index,
                    btrim(sentence) AS sentence
                FROM regexp_split_to_table(
                    regexp_replace(bd.bio_paragraphs_cleaned, E'\s+', ' ', 'g'),
                    '[.!?]+'
                ) WITH ORDINALITY AS split_sentence(sentence, sentence_index)
                WHERE btrim(sentence) <> ''
            ) normalized_sentences
        ) AS bio_sentence_cleaned
    FROM bio_dedup bd
),
bio_scored AS (
    SELECT
        bsd.*,
        NULLIF(btrim(regexp_replace(bsd.bio_sentence_cleaned, '\s+', ' ', 'g')), '') AS cleaned_artist_bio,
        (bsd.bio_contact_removed <> COALESCE(bsd.original_artist_bio, ''))
            OR (COALESCE(bsd.bio_paragraphs_cleaned, '') <> COALESCE(bsd.bio_contact_removed, ''))
            OR (COALESCE(bsd.bio_sentence_cleaned, '') <> COALESCE(bsd.bio_paragraphs_cleaned, '')) AS duplicate_content,
        length(COALESCE(NULLIF(btrim(regexp_replace(bsd.bio_sentence_cleaned, '\s+', ' ', 'g')), ''), '')) < 80 AS too_short,
        CASE
            WHEN length(regexp_replace(COALESCE(bsd.original_artist_bio, ''), '[^A-Za-z]', '', 'g')) < 20 THEN false
            ELSE (
                length(regexp_replace(COALESCE(bsd.original_artist_bio, ''), '[^A-Z]', '', 'g'))::numeric
                / NULLIF(length(regexp_replace(COALESCE(bsd.original_artist_bio, ''), '[^A-Za-z]', '', 'g')), 0)
            ) > 0.60
        END AS noisy_uppercase
    FROM bio_sentence_dedup bsd
)
SELECT
    bs.artist_name,
    bs.source_domain,
    bs.profile_url,
    COALESCE(bs.edited_bio, bs.cleaned_artist_bio, bs.original_artist_bio) AS artist_bio,
    bs.original_artist_bio,
    bs.cleaned_artist_bio,
    GREATEST(
        0,
        LEAST(
            100,
            100
            - CASE WHEN bs.contains_email THEN 30 ELSE 0 END
            - CASE WHEN bs.contains_phone THEN 20 ELSE 0 END
            - CASE WHEN bs.navigation_noise THEN 20 ELSE 0 END
            - CASE WHEN bs.duplicate_content THEN 10 ELSE 0 END
            - CASE WHEN bs.too_short THEN 10 ELSE 0 END
            - CASE WHEN bs.noisy_uppercase THEN 10 ELSE 0 END
        )
    )::INT AS bio_quality_score,
    array_remove(
        ARRAY[
            CASE WHEN bs.contains_email THEN 'contains_email' END,
            CASE WHEN bs.contains_phone THEN 'contains_phone' END,
            CASE WHEN bs.navigation_noise THEN 'navigation_noise' END,
            CASE WHEN bs.too_short THEN 'too_short' END,
            CASE WHEN bs.duplicate_content THEN 'duplicate_content' END
        ],
        NULL
    ) AS bio_quality_flags,
    bs.edited_bio,
    bs.edited_by,
    bs.edited_at,
    bs.edited_bio AS edited_artist_bio,
    bs.edited_by AS bio_edited_by,
    bs.edit_notes AS bio_edit_notes,
    bs.edited_at AS bio_last_edited_at,
    bs.artwork_count,
    bs.last_seen
FROM bio_scored bs;
