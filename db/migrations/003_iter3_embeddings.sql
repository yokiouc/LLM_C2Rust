DROP TABLE IF EXISTS chunk_embeddings CASCADE;
DROP TABLE IF EXISTS embedding_models CASCADE;

CREATE TABLE embedding_models (
  model_id text PRIMARY KEY,
  provider_type text NOT NULL,
  dimension integer NOT NULL,
  config_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO embedding_models (model_id, provider_type, dimension, config_jsonb)
VALUES
  ('stub-1536', 'stub', 1536, '{"seed": 1337, "dimension": 1536}'::jsonb),
  ('openai-text-embedding-3-small', 'openai', 1536, '{"model":"text-embedding-3-small","timeout_seconds":30,"batch_size":128,"concurrency":8}'::jsonb)
ON CONFLICT (model_id) DO NOTHING;

CREATE TABLE chunk_embeddings (
  chunk_id bigint NOT NULL REFERENCES code_chunks (chunk_id) ON DELETE CASCADE,
  model_id text NOT NULL REFERENCES embedding_models (model_id) ON DELETE CASCADE,
  snapshot_id bigint NOT NULL REFERENCES repo_snapshots (snapshot_id) ON DELETE CASCADE,
  embedding vector(1536) NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (chunk_id, model_id)
);

CREATE INDEX chunk_embeddings_snapshot_model_idx ON chunk_embeddings (snapshot_id, model_id);
CREATE INDEX chunk_embeddings_embedding_ivfflat_idx
  ON chunk_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
