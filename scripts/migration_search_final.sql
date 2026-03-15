-- ===================================================================
-- LEGAL AI SEARCH - FINAL OPTIMIZED VERSION
-- Target: <1s, accurate Vietnamese legal search
-- Simplified scoring, no complex arrays
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
BEGIN
    normalized_query := lower(trim(query_text));
    
    -- Extract keywords
    SELECT array_agg(w) INTO key_words
    FROM (
        SELECT unnest(regexp_split_to_array(normalized_query, '\s+')) as w
    ) t
    WHERE length(w) > 1 AND w != ALL(stop_words);
    
    IF key_words IS NULL OR array_length(key_words, 1) = 0 THEN
        key_words := ARRAY[normalized_query];
    END IF;
    
    -- Limit to 6 keywords for performance
    IF array_length(key_words, 1) > 6 THEN
        key_words := key_words[1:6];
    END IF;
    
    -- Build tsquery with OR
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
        -- Simplified but effective scoring
        (
            -- Exact phrase matches (Vietnamese common legal phrases)
            (CASE WHEN lc.content ILIKE '%hợp đồng lao động%' AND normalized_query LIKE '%hợp đồng lao động%' THEN 20.0 ELSE 0.0 END)
            + (CASE WHEN lc.content ILIKE '%bảo hiểm xã hội%' AND normalized_query LIKE '%bảo hiểm xã hội%' THEN 20.0 ELSE 0.0 END)
            + (CASE WHEN lc.content ILIKE '%công ty cổ phần%' AND normalized_query LIKE '%công ty cổ phần%' THEN 20.0 ELSE 0.0 END)
            + (CASE WHEN lc.content ILIKE '%thuế thu nhập%' AND normalized_query LIKE '%thuế thu nhập%' THEN 20.0 ELSE 0.0 END)
            + (CASE WHEN lc.content ILIKE '%xác định thời hạn%' AND normalized_query LIKE '%thời hạn%' THEN 15.0 ELSE 0.0 END)
            + (CASE WHEN lc.content ILIKE '%loại hợp đồng%' AND normalized_query LIKE '%loại%' THEN 15.0 ELSE 0.0 END)
            + (CASE WHEN lc.content ILIKE '%sa thải%' AND normalized_query LIKE '%sa thải%' THEN 20.0 ELSE 0.0 END)
            + (CASE WHEN lc.content ILIKE '%thành lập%' AND normalized_query LIKE '%thành lập%' THEN 20.0 ELSE 0.0 END)
            +
            -- Full-text search score
            COALESCE(ts_rank(lc.tsv, tsquery_obj, 1) * 12.0, 0.0)
            +
            -- Law document domain relevance
            (CASE 
                WHEN normalized_query LIKE '%lao động%' AND ld.title ILIKE '%lao động%' THEN 10.0
                WHEN normalized_query LIKE '%doanh nghiệp%' AND ld.title ILIKE '%doanh nghiệp%' THEN 10.0
                WHEN normalized_query LIKE '%công ty%' AND ld.title ILIKE '%doanh nghiệp%' THEN 10.0
                WHEN normalized_query LIKE '%thuế%' AND ld.title ILIKE '%thuế%' THEN 10.0
                WHEN normalized_query LIKE '%hợp đồng%' AND ld.title ILIKE '%lao động%' THEN 6.0
                ELSE 0.0
            END)
            +
            -- Article-specific query bonus
            (CASE 
                WHEN normalized_query LIKE '%điều%' AND lc.article IS NOT NULL THEN 3.0
                ELSE 0.0
            END)
            +
            -- Keyword coverage
            ((SELECT COUNT(*)::FLOAT FROM unnest(key_words) kw WHERE lc.content ILIKE '%' || kw || '%')
             / array_length(key_words, 1)::FLOAT) * 5.0
        )
        *
        -- Length normalization factor
        (CASE 
            WHEN length(lc.content) < 80 THEN 0.5
            WHEN length(lc.content) BETWEEN 80 AND 700 THEN 1.0
            WHEN length(lc.content) BETWEEN 700 AND 2000 THEN 0.9
            ELSE 0.7
        END)
        AS rank
    FROM law_chunks lc
    INNER JOIN law_documents ld ON ld.id = lc.law_id
    WHERE 
        (filter_domains IS NULL OR lc.domains && filter_domains)
        AND lc.tsv @@ tsquery_obj
    ORDER BY rank DESC NULLS LAST, length(lc.content) ASC
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_law_chunks_tsv ON law_chunks USING gin(tsv);
CREATE INDEX IF NOT EXISTS idx_law_chunks_content_trgm ON law_chunks USING gin(content gin_trgm_ops);

ANALYZE law_chunks;
ANALYZE law_documents;

SELECT 'Search FINAL deployed successfully!' AS status;
