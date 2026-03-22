CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS projects (
  project_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL UNIQUE,
  description text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS repo_snapshots (
  snapshot_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  project_id bigint NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE,
  commit_sha text NOT NULL DEFAULT 'mock',
  branch text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, commit_sha)
);

CREATE TABLE IF NOT EXISTS code_chunks (
  chunk_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  snapshot_id bigint NOT NULL REFERENCES repo_snapshots (snapshot_id) ON DELETE CASCADE,
  kind varchar(64) NOT NULL,
  lang varchar(32) NOT NULL,
  content text NOT NULL,
  content_tsv tsvector NOT NULL,
  meta jsonb NOT NULL,
  content_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION code_chunks_content_tsv_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.content_tsv := to_tsvector('simple', coalesce(NEW.content, ''));
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_code_chunks_content_tsv ON code_chunks;
CREATE TRIGGER trg_code_chunks_content_tsv
BEFORE INSERT OR UPDATE OF content ON code_chunks
FOR EACH ROW
EXECUTE FUNCTION code_chunks_content_tsv_update();

ALTER TABLE code_chunks
  DROP CONSTRAINT IF EXISTS code_chunks_meta_has_file_check;
ALTER TABLE code_chunks
  ADD CONSTRAINT code_chunks_meta_has_file_check CHECK (meta ? 'file');

ALTER TABLE code_chunks
  DROP CONSTRAINT IF EXISTS code_chunks_snapshot_kind_lang_hash_uniq;
ALTER TABLE code_chunks
  ADD CONSTRAINT code_chunks_snapshot_kind_lang_hash_uniq UNIQUE (snapshot_id, kind, lang, content_hash);

CREATE INDEX IF NOT EXISTS code_chunks_snapshot_id_idx ON code_chunks (snapshot_id);
CREATE INDEX IF NOT EXISTS code_chunks_content_hash_idx ON code_chunks (content_hash);
CREATE INDEX IF NOT EXISTS code_chunks_content_tsv_gin_idx ON code_chunks USING gin (content_tsv);

DROP TABLE IF EXISTS chunk_embeddings CASCADE;
DROP TABLE IF EXISTS embedding_models CASCADE;

CREATE TABLE IF NOT EXISTS embedding_models (
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

CREATE TABLE IF NOT EXISTS chunk_embeddings (
  chunk_id bigint NOT NULL REFERENCES code_chunks (chunk_id) ON DELETE CASCADE,
  model_id text NOT NULL REFERENCES embedding_models (model_id) ON DELETE CASCADE,
  snapshot_id bigint NOT NULL REFERENCES repo_snapshots (snapshot_id) ON DELETE CASCADE,
  embedding vector(1536) NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (chunk_id, model_id)
);

CREATE INDEX IF NOT EXISTS chunk_embeddings_snapshot_model_idx ON chunk_embeddings (snapshot_id, model_id);
CREATE INDEX IF NOT EXISTS chunk_embeddings_embedding_ivfflat_idx
  ON chunk_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

DROP TABLE IF EXISTS patches CASCADE;
DROP TABLE IF EXISTS agent_steps CASCADE;
DROP TABLE IF EXISTS agent_runs CASCADE;
DROP TABLE IF EXISTS metrics CASCADE;

CREATE TABLE IF NOT EXISTS agent_runs (
  run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_url text NOT NULL,
  ref text NOT NULL,
  task_description text NOT NULL,
  status text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT agent_runs_status_check CHECK (status IN ('INIT','RETRIEVE','GENERATE','APPLY','EXECUTE','DIAGNOSE','STOP','FAILED'))
);

CREATE INDEX IF NOT EXISTS agent_runs_status_idx ON agent_runs (status);
CREATE INDEX IF NOT EXISTS agent_runs_created_at_idx ON agent_runs (created_at);

CREATE TABLE IF NOT EXISTS agent_steps (
  step_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES agent_runs (run_id) ON DELETE CASCADE,
  step_name text NOT NULL,
  input_json jsonb NOT NULL,
  output_json jsonb NOT NULL,
  ok boolean NOT NULL,
  error_msg text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_steps_run_id_idx ON agent_steps (run_id);
CREATE INDEX IF NOT EXISTS agent_steps_created_at_idx ON agent_steps (created_at);

CREATE TABLE IF NOT EXISTS patches (
  patch_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES agent_runs (run_id) ON DELETE CASCADE,
  file_path text NOT NULL,
  unified_diff text NOT NULL,
  status text NOT NULL,
  error_msg text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT patches_status_check CHECK (status IN ('applied','rolled_back'))
);

CREATE INDEX IF NOT EXISTS patches_run_id_idx ON patches (run_id);

CREATE TABLE IF NOT EXISTS metrics (
  metric_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES agent_runs (run_id) ON DELETE CASCADE,
  key text NOT NULL,
  value_json jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, key)
);

CREATE INDEX IF NOT EXISTS metrics_run_id_idx ON metrics (run_id);
