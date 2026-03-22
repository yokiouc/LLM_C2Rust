-- Lexical full-text search for code chunks (tsvector)
-- Creates SQL function:
--   lexical_search(snapshot_id int, query_text text, kinds text[], limit_cnt int)
-- Returns:
--   chunk_id, rank (higher is better)

CREATE OR REPLACE FUNCTION lexical_search(
  snapshot_id int,
  query_text text,
  kinds text[],
  limit_cnt int
)
RETURNS TABLE (chunk_id bigint, rank double precision)
LANGUAGE sql
STABLE
AS $$
  WITH q AS (
    SELECT plainto_tsquery('simple', query_text) AS tsq
  )
  SELECT
    c.chunk_id,
    ts_rank_cd(c.content_tsv, q.tsq) AS rank
  FROM code_chunks c, q
  WHERE c.snapshot_id = lexical_search.snapshot_id
    AND c.content_tsv @@ q.tsq
    AND (kinds IS NULL OR c.kind = ANY(kinds))
  ORDER BY rank DESC, c.chunk_id ASC
  LIMIT limit_cnt;
$$;
