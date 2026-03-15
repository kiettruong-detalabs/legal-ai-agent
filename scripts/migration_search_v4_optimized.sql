-- ============================================
-- LEGAL AI SEARCH OPTIMIZATION V4 - HIGHLY OPTIMIZED
-- Target: <500ms average response time
-- Strategy: Single-pass scoring, no expensive subqueries
-- ============================================

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
    -- Compound Vietnamese phrases
    compound_phrases TEXT[] := ARRAY[
        'hợp đồng lao động',
        'bảo hiểm xã hội',
        'công ty cổ phần',
        'công ty tnhh',
        'thuế thu nhập',
        'người lao động',
        'xác định thời hạn',
        'không xác định thời hạn',
        'sa thải',
        'chấm dứt hợp đồng',
        'thành lập công ty',
        'loại hợp đồng',
        'tranh chấp lao động'
    ];
    normalized_query TEXT;
    found_phrase TEXT := NULL;
    key_words TEXT[];
    stop_words TEXT[] := ARRAY[
        'là', 'của', 'có', 'và', 'các', 'này', 'đó', 'cho', 'với',
        'trong', 'không', 'được', 'theo', 'về', 'khi', 'nào', 'bao',
        'nhiêu', 'lâu', 'thế', 'như', 'gì', 'tại', 'từ', 'đến',
        'hay', 'hoặc', 'nhưng', 'mà', 'thì', 'nếu', 'bị', 'đã',
        'sẽ', 'đang', 'vậy', 'rồi', 'cần', 'phải', 'tối', 'đa'
    ];
    tsquery_obj TSQUERY;
BEGIN
    normalized_query := lower(trim(query_text));
    
    -- Find phrase match
    FOREACH found_phrase IN ARRAY compound_phrases LOOP
        IF position(found_phrase IN normalized_query) > 0 THEN
            EXIT;
        END IF;
    END LOOP;
    
    IF found_phrase IS NULL OR position(found_phrase IN normalized_query) = 0 THEN
        found_phrase := NULL;
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
    
    -- Limit keywords for performance
    IF array_length(key_words, 1) > 5 THEN
        key_words := key_words[1:5];
    END IF;
    
    -- Build tsquery
    tsquery_obj := to_tsquery('simple', 
        array_to_string(
            (SELECT array_agg(w || ':*') FROM unnest(key_words) w),
            ' | '
        )
    );
    
    -- Single-pass query with all scoring inline
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
        -- Inline scoring (single pass!)
        (
            -- Phrase match (highest priority)
            CASE 
                WHEN found_phrase IS NOT NULL AND lc.content ILIKE '%' || found_phrase || '%' 
                THEN 20.0 
                ELSE 0.0 
            END
            +
            -- TS rank (moderate weight)
            ts_rank(lc.tsv, tsquery_obj, 1) * 10.0
            +
            -- Law title relevance
            CASE 
                WHEN ld.title ILIKE '%lao động%' AND normalized_query LIKE '%lao động%' THEN 3.0
                WHEN ld.title ILIKE '%doanh nghiệp%' AND normalized_query LIKE '%doanh nghiệp%' THEN 3.0
                WHEN ld.title ILIKE '%thuế%' AND normalized_query LIKE '%thuế%' THEN 3.0
                WHEN ld.title ILIKE '%đất đai%' AND normalized_query LIKE '%đất đai%' THEN 3.0
                ELSE 0.0
            END
            +
            -- Article number query bonus
            CASE 
                WHEN normalized_query LIKE '%điều%' AND lc.article IS NOT NULL THEN 1.5
                ELSE 0.0
            END
        ) * 
        -- Length factor (prefer concise relevant content)
        CASE 
            WHEN length(lc.content) < 100 THEN 0.5
            WHEN length(lc.content) BETWEEN 100 AND 800 THEN 1.0
            WHEN length(lc.content) BETWEEN 800 AND 2500 THEN 0.85
            ELSE 0.65
        END AS rank
    FROM law_chunks lc
    JOIN law_documents ld ON ld.id = lc.law_id
    WHERE 
        (filter_domains IS NULL OR lc.domains && filter_domains)
        AND (
            -- Primary: indexed tsvector search
            lc.tsv @@ tsquery_obj
            OR
            -- Secondary: phrase match (trigram index)
            (found_phrase IS NOT NULL AND lc.content ILIKE '%' || found_phrase || '%')
        )
    ORDER BY rank DESC, length(lc.content) ASC
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- Ensure critical indexes exist
CREATE INDEX IF NOT EXISTS idx_law_chunks_tsv ON law_chunks USING gin(tsv);
CREATE INDEX IF NOT EXISTS idx_law_chunks_content_trgm ON law_chunks USING gin(content gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_law_docs_title_trgm ON law_documents USING gin(title gin_trgm_ops);

ANALYZE law_chunks;
ANALYZE law_documents;

SELECT 'Search V4 optimized deployed! Single-pass scoring for maximum speed.' AS status;
