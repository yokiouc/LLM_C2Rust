-- pgvector-only vector search (cosine distance)
-- Parameters:
--   :query_vector  vector(1536)
--   :snapshot_id   bigint
--   :top_k         integer
-- Optional:
--   :max_dist      float

SELECT
  chunk_id,
  embedding <=> :query_vector AS dist
FROM chunk_embeddings
WHERE snapshot_id = :snapshot_id
  AND (:max_dist::double precision IS NULL OR (embedding <=> :query_vector) <= :max_dist::double precision)
ORDER BY dist ASC
LIMIT :top_k;

-- Index (GiST, cosine):
-- CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_embedding
--   ON chunk_embeddings USING gist (embedding gist_vector_cosine_ops);

-- EXPLAIN example:
-- EXPLAIN (ANALYZE, BUFFERS)
-- SELECT
--   chunk_id,
--   embedding <=> '[0,0,0]'::vector AS dist
-- FROM chunk_embeddings
-- WHERE snapshot_id = 1
-- ORDER BY dist ASC
-- LIMIT 10;
