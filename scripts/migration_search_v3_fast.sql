-- ============================================
-- LEGAL AI SEARCH OPTIMIZATION V3 - FAST
-- Vietnamese text search optimized for <1s response
-- Uses ONLY indexed operations (no similarity() scan)
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
    -- Vietnamese compound phrases that should stay together
    compound_phrases TEXT[] := ARRAY[
        'hợp đồng lao động',
        'bảo hiểm xã hội',
        'công ty cổ phần',
        'công ty tnhh',
        'thuế thu nhập',
        'người lao động',
        'người sử dụng lao động',
        'thời hạn',
        'xác định thời hạn',
        'không xác định thời hạn',
        'sa thải',
        'chấm dứt hợp đồng',
        'thành lập công ty',
        'quyền và nghĩa vụ',
        'bồi thường thiệt hại',
        'vi phạm hợp đồng',
        'tranh chấp lao động',
        'loại hợp đồng',
        'hợp đồng thương mại'
    ];
    normalized_query TEXT;
    found_phrase TEXT;
    phrase_found BOOLEAN := FALSE;
    key_words TEXT[];
    stop_words TEXT[] := ARRAY[
        'là', 'của', 'có', 'và', 'các', 'này', 'đó', 'cho', 'với',
        'trong', 'không', 'được', 'theo', 'về', 'khi', 'nào', 'bao',
        'nhiêu', 'lâu', 'thế', 'như', 'gì', 'tại', 'từ', 'đến',
        'hay', 'hoặc', 'nhưng', 'mà', 'thì', 'nếu', 'bị', 'đã',
        'sẽ', 'đang', 'vậy', 'rồi', 'cần', 'phải', 'tối', 'đa',
        'mấy', 'sao', 'ai', 'đâu', 'chưa', 'một', 'hai', 'ba'
    ];
    tsquery_obj TSQUERY;
    min_should_match INT;
BEGIN
    normalized_query := lower(trim(query_text));
    
    -- Check for compound phrases
    FOREACH found_phrase IN ARRAY compound_phrases LOOP
        IF normalized_query LIKE '%' || found_phrase || '%' THEN
            phrase_found := TRUE;
            EXIT;
        END IF;
    END LOOP;
    
    -- Extract keywords (skip stop words, keep words > 1 char)
    SELECT array_agg(w) INTO key_words
    FROM (
        SELECT unnest(regexp_split_to_array(normalized_query, '\s+')) as w
    ) t
    WHERE length(w) > 1 AND w != ALL(stop_words);
    
    IF key_words IS NULL OR array_length(key_words, 1) = 0 THEN
        key_words := ARRAY[normalized_query];
    END IF;
    
    -- Limit to top 6 keywords to keep query efficient
    IF array_length(key_words, 1) > 6 THEN
        key_words := key_words[1:6];
    END IF;
    
    -- Build tsquery: OR of all keywords with prefix matching
    tsquery_obj := to_tsquery('simple', 
        array_to_string(
            (SELECT array_agg(w || ':*') FROM unnest(key_words) w),
            ' | '
        )
    );
    
    -- Minimum keywords that should match
    min_should_match := CASE 
        WHEN array_length(key_words, 1) <= 2 THEN array_length(key_words, 1)
        ELSE 2
    END;
    
    RETURN QUERY
    WITH candidate_chunks AS (
        -- Stage 1: Fast pre-filter using ONLY indexed operations
        SELECT 
            lc.id,
            lc.law_id,
            lc.article,
            lc.title,
            lc.content,
            lc.domains,
            ld.title AS law_doc_title,
            ld.law_number,
            -- Count how many keywords match (for min_should_match)
            (SELECT COUNT(*) 
             FROM unnest(key_words) kw 
             WHERE lc.tsv @@ to_tsquery('simple', kw || ':*')
            ) AS matched_keywords
        FROM law_chunks lc
        JOIN law_documents ld ON ld.id = lc.law_id
        WHERE 
            (filter_domains IS NULL OR lc.domains && filter_domains)
            AND (
                -- Primary: tsvector match (uses GIN index - FAST!)
                lc.tsv @@ tsquery_obj
                OR
                -- Secondary: exact phrase match using trigram index
                (phrase_found AND lc.content ILIKE '%' || found_phrase || '%')
            )
    ),
    scored_chunks AS (
        -- Stage 2: Score only the pre-filtered candidates
        SELECT 
            cc.*,
            -- Phrase match bonus (highest priority)
            CASE 
                WHEN phrase_found AND cc.content ILIKE '%' || found_phrase || '%' THEN 15.0
                ELSE 0.0
            END AS phrase_bonus,
            -- Full-text search relevance
            ts_rank(
                (SELECT tsv FROM law_chunks WHERE id = cc.id),
                tsquery_obj,
                1  -- normalization method 1 (divide by document length)
            ) * 8.0 AS ts_score,
            -- Keyword coverage bonus
            (cc.matched_keywords::FLOAT / array_length(key_words, 1)::FLOAT) * 3.0 AS coverage_bonus,
            -- Law document title match (check if any keyword appears in law title)
            (SELECT CASE 
                WHEN COUNT(*) > 0 THEN 2.5 
                ELSE 0.0 
            END
            FROM unnest(key_words) kw
            WHERE cc.law_doc_title ILIKE '%' || kw || '%'
            ) AS law_match_bonus,
            -- Article mention bonus
            CASE 
                WHEN normalized_query LIKE '%điều%' AND cc.article IS NOT NULL THEN 2.0
                ELSE 0.0
            END AS article_bonus,
            -- Content length factor (prefer mid-size chunks)
            CASE 
                WHEN length(cc.content) < 80 THEN 0.4
                WHEN length(cc.content) BETWEEN 80 AND 600 THEN 1.0
                WHEN length(cc.content) BETWEEN 600 AND 2000 THEN 0.85
                ELSE 0.6
            END AS length_factor
        FROM candidate_chunks cc
        WHERE cc.matched_keywords >= min_should_match
    )
    SELECT 
        sc.id AS chunk_id,
        sc.law_id,
        sc.law_doc_title AS law_title,
        sc.law_number,
        sc.article,
        sc.title AS chunk_title,
        sc.content,
        sc.domains,
        (
            sc.phrase_bonus +
            sc.ts_score +
            sc.coverage_bonus +
            sc.law_match_bonus +
            sc.article_bonus
        ) * sc.length_factor AS rank
    FROM scored_chunks sc
    ORDER BY rank DESC, length(sc.content) ASC
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- Ensure indexes are in place
CREATE INDEX IF NOT EXISTS idx_law_chunks_tsv ON law_chunks USING gin(tsv);
CREATE INDEX IF NOT EXISTS idx_law_chunks_content_trgm ON law_chunks USING gin(content gin_trgm_ops);

-- Update statistics for query planner
ANALYZE law_chunks;
ANALYZE law_documents;

SELECT 'Search V3 (Fast) deployed! Target: <1 second.' AS status;
