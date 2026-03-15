-- ===================================================================
-- LEGAL AI SEARCH - ULTRA-FAST VERSION
-- Target: <500ms average
-- Strategy: Minimal scoring, maximum index usage, no ILIKE in SELECT
-- ===================================================================

DROP FUNCTION IF EXISTS search_law(text, legal_domain[], int);

CREATE OR REPLACE FUNCTION search_law(
    query_text TEXT,
    filter_domains legal_domain[] DEFAULT NULL,
    match_count INT DEFAULT 20
)
RETURNS TABLE(
    chunk_id UUID,
    law_id UUID,
    law_title TEXT,
    law_number TEXT,
    article TEXT,
    chunk_title TEXT,
    content TEXT,
    domains legal_domain[],
    rank FLOAT
) AS $$
DECLARE
    normalized_query TEXT;
    key_words TEXT[];
    stop_words TEXT[] := ARRAY[
        'là', 'của', 'có', 'và', 'các', 'này', 'đó', 'cho', 'với',
        'trong', 'không', 'được', 'theo', 'về', 'khi', 'nào', 'bao',
        'nhiêu', 'lâu', 'thế', 'như', 'gì', 'tại', 'từ', 'đến',
        'hay', 'hoặc', 'nhưng', 'mà', 'thì', 'nếu', 'bị', 'đã',
        'sẽ', 'đang', 'vậy', 'rồi', 'cần', 'phải', 'tối', 'đa'
    ];
    tsquery_obj TSQUERY;
    law_domain_boost FLOAT := 0.0;
BEGIN
    normalized_query := lower(trim(query_text));
    
    -- Detect law domain for boosting
    IF normalized_query LIKE '%lao động%' THEN
        law_domain_boost := 10.0;
    ELSIF normalized_query LIKE '%doanh nghiệp%' OR normalized_query LIKE '%công ty%' THEN
        law_domain_boost := 10.0;
    ELSIF normalized_query LIKE '%thuế%' THEN
        law_domain_boost := 10.0;
    END IF;
    
    -- Extract keywords
    SELECT array_agg(w) INTO key_words
    FROM (
        SELECT unnest(regexp_split_to_array(normalized_query, '\s+')) as w
    ) t
    WHERE length(w) > 1 AND w != ALL(stop_words);
    
    IF key_words IS NULL OR array_length(key_words, 1) = 0 THEN
        key_words := ARRAY[normalized_query];
    END IF;
    
    -- Limit keywords
    IF array_length(key_words, 1) > 6 THEN
        key_words := key_words[1:6];
    END IF;
    
    -- Build tsquery
    tsquery_obj := to_tsquery('simple', 
        array_to_string(
            (SELECT array_agg(w || ':*') FROM unnest(key_words) w),
            ' | '
        )
    );
    
    RETURN QUERY
    SELECT 
        lc.id AS chunk_id,
        lc.law_id,
        ld.title AS law_title,
        ld.law_number,
        lc.article,
        lc.title AS chunk_title,
        lc.content,
        lc.domains,
        -- Ultra-simple scoring (NO expensive string operations in SELECT)
        (
            -- Primary: ts_rank (uses precomputed tsvector)
            ts_rank(lc.tsv, tsquery_obj, 1 | 4) * 20.0  -- normalization 1|4 = length + unique words
            +
            -- Law domain match boost (precomputed)
            CASE 
                WHEN law_domain_boost > 0 AND (
                    ld.title ILIKE '%lao động%' OR
                    ld.title ILIKE '%doanh nghiệp%' OR
                    ld.title ILIKE '%thuế%'
                ) THEN law_domain_boost
                ELSE 0.0
            END
            +
            -- Short article reference bonus
            CASE WHEN lc.article IS NOT NULL AND length(lc.article) < 15 THEN 3.0 ELSE 0.0 END
        )
        *
        -- Length penalty for very long or very short chunks
        CASE 
            WHEN length(lc.content) < 100 THEN 0.6
            WHEN length(lc.content) > 3000 THEN 0.7
            ELSE 1.0
        END
        AS rank
    FROM law_chunks lc
    INNER JOIN law_documents ld ON ld.id = lc.law_id
    WHERE 
        (filter_domains IS NULL OR lc.domains && filter_domains)
        AND lc.tsv @@ tsquery_obj  -- ONLY indexed tsvector search
    ORDER BY rank DESC, length(lc.content) ASC
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- Ensure GIN index on tsvector exists and is used
CREATE INDEX IF NOT EXISTS idx_law_chunks_tsv ON law_chunks USING gin(tsv);

-- Update table statistics for optimal query planning
ANALYZE law_chunks;
ANALYZE law_documents;

SELECT 'Ultra-fast search deployed! Optimized for <500ms response.' AS status;
