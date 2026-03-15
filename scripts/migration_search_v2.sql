-- ============================================
-- LEGAL AI SEARCH OPTIMIZATION V2
-- Vietnamese text search with phrase support
-- Target: <1 second response time
-- ============================================

-- Drop old function
DROP FUNCTION IF EXISTS search_law(text, legal_domain[], int);

-- Create optimized search function
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
    -- Vietnamese compound phrases to keep together
    compound_phrases TEXT[] := ARRAY[
        'hợp đồng lao động',
        'bảo hiểm xã hội',
        'công ty cổ phần',
        'công ty tnhh',
        'thuế thu nhập',
        'người lao động',
        'người sử dụng lao động',
        'thời hạn',
        'sa thải',
        'chấm dứt hợp đồng',
        'thành lập công ty',
        'quyền và nghĩa vụ',
        'bồi thường thiệt hại',
        'vi phạm hợp đồng',
        'tranh chấp lao động',
        'thỏa ước lao động',
        'nội quy lao động',
        'hợp đồng thương mại',
        'hợp đồng dịch vụ'
    ];
    phrase_query TEXT;
    tsquery_simple TSQUERY;
    tsquery_phrase TSQUERY;
    key_words TEXT[];
    stop_words TEXT[] := ARRAY[
        'là', 'của', 'có', 'và', 'các', 'này', 'đó', 'cho', 'với',
        'trong', 'không', 'được', 'theo', 'về', 'khi', 'nào', 'bao',
        'nhiêu', 'lâu', 'thế', 'như', 'gì', 'tại', 'từ', 'đến',
        'hay', 'hoặc', 'nhưng', 'mà', 'thì', 'nếu', 'bị', 'đã',
        'sẽ', 'đang', 'vậy', 'rồi', 'cần', 'phải', 'tối', 'đa',
        'mấy', 'sao', 'ai', 'đâu', 'chưa'
    ];
    normalized_query TEXT;
    found_phrase TEXT;
BEGIN
    normalized_query := lower(trim(query_text));
    
    -- Check for compound phrases
    phrase_query := NULL;
    FOREACH found_phrase IN ARRAY compound_phrases LOOP
        IF normalized_query ILIKE '%' || found_phrase || '%' THEN
            -- Found a compound phrase, use phrase search
            phrase_query := found_phrase;
            EXIT;
        END IF;
    END LOOP;
    
    -- Extract keywords (excluding stop words)
    SELECT array_agg(w) INTO key_words
    FROM (
        SELECT unnest(regexp_split_to_array(normalized_query, '\s+')) as w
    ) t
    WHERE length(w) > 1 AND w != ALL(stop_words);
    
    IF key_words IS NULL OR array_length(key_words, 1) = 0 THEN
        key_words := ARRAY[normalized_query];
    END IF;
    
    -- Create tsquery (OR combination of keywords)
    tsquery_simple := to_tsquery('simple', array_to_string(
        array_agg(w || ':*'), ' | '
    )) FROM unnest(key_words) w;
    
    -- If we found a phrase, create phrase query
    IF phrase_query IS NOT NULL THEN
        tsquery_phrase := phraseto_tsquery('simple', phrase_query);
    END IF;
    
    RETURN QUERY
    WITH ranked_chunks AS (
        SELECT 
            lc.id,
            lc.law_id,
            ld.title AS law_title,
            ld.law_number,
            ld.title AS law_doc_title,
            lc.article,
            lc.title AS chunk_title,
            lc.content,
            lc.domains,
            -- Scoring components
            CASE 
                -- Phrase match bonus (highest priority)
                WHEN phrase_query IS NOT NULL AND lc.content ILIKE '%' || phrase_query || '%' THEN 10.0
                ELSE 0.0
            END AS phrase_bonus,
            -- Full-text search score
            ts_rank(lc.tsv, tsquery_simple, 1) * 5.0 AS ts_score,
            -- Trigram similarity for partial matches
            similarity(lc.content, normalized_query) * 3.0 AS trigram_score,
            -- Law title match bonus
            CASE 
                WHEN normalized_query ILIKE '%' || lower(ld.title) || '%' 
                  OR lower(ld.title) ILIKE '%' || normalized_query || '%' THEN 2.0
                ELSE 0.0
            END AS law_title_bonus,
            -- Article number bonus if query mentions "điều"
            CASE 
                WHEN normalized_query ILIKE '%điều%' AND lc.article IS NOT NULL THEN 1.5
                ELSE 0.0
            END AS article_bonus,
            -- Content length penalty (prefer concise relevant chunks)
            CASE 
                WHEN length(lc.content) < 100 THEN 0.5 -- too short, less useful
                WHEN length(lc.content) < 500 THEN 1.0 -- sweet spot
                WHEN length(lc.content) < 1500 THEN 0.9
                ELSE 0.7 -- long chunks, harder to parse
            END AS length_factor
        FROM law_chunks lc
        JOIN law_documents ld ON ld.id = lc.law_id
        WHERE 
            (filter_domains IS NULL OR lc.domains && filter_domains)
            AND (
                -- Use tsvector search (fast!)
                (lc.tsv @@ tsquery_simple)
                OR
                -- Phrase search if applicable
                (phrase_query IS NOT NULL AND lc.content ILIKE '%' || phrase_query || '%')
                OR
                -- Fallback to trigram for partial matches
                (similarity(lc.content, normalized_query) > 0.15)
            )
    )
    SELECT 
        rc.id AS chunk_id,
        rc.law_id,
        rc.law_title,
        rc.law_number,
        rc.article,
        rc.chunk_title,
        rc.content,
        rc.domains,
        -- Combined ranking score
        (
            rc.phrase_bonus +
            rc.ts_score +
            rc.trigram_score +
            rc.law_title_bonus +
            rc.article_bonus
        ) * rc.length_factor AS rank
    FROM ranked_chunks rc
    ORDER BY rank DESC, length(rc.content) ASC
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- Create index for phrase search (if not exists)
CREATE INDEX IF NOT EXISTS idx_law_chunks_content_lower 
ON law_chunks(lower(content) text_pattern_ops);

-- Analyze tables for query planner
ANALYZE law_chunks;
ANALYZE law_documents;

-- Verify
SELECT 'Search optimization V2 deployed successfully!' AS status;
