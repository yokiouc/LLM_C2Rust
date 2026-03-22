DROP TABLE IF EXISTS metrics CASCADE;
DROP TABLE IF EXISTS patches CASCADE;
DROP TABLE IF EXISTS agent_steps CASCADE;
DROP TABLE IF EXISTS agent_runs CASCADE;
DROP TABLE IF EXISTS chunk_embeddings CASCADE;
DROP TABLE IF EXISTS code_chunks CASCADE;
DROP TABLE IF EXISTS repo_snapshots CASCADE;
DROP TABLE IF EXISTS projects CASCADE;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE projects (
  project_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL UNIQUE,
  description text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE repo_snapshots (
  snapshot_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  project_id bigint NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE,
  commit_sha text NOT NULL DEFAULT 'mock',
  branch text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, commit_sha)
);

CREATE TABLE code_chunks (
  chunk_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  snapshot_id bigint NOT NULL REFERENCES repo_snapshots (snapshot_id) ON DELETE CASCADE,
  kind varchar(64) NOT NULL,
  lang varchar(32) NOT NULL,
  content text NOT NULL,
  content_tsv tsvector NOT NULL,
  meta jsonb NOT NULL,
  content_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT code_chunks_meta_has_file_check CHECK (meta ? 'file'),
  CONSTRAINT code_chunks_snapshot_kind_lang_hash_uniq UNIQUE (snapshot_id, kind, lang, content_hash)
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

CREATE TRIGGER trg_code_chunks_content_tsv
BEFORE INSERT OR UPDATE OF content ON code_chunks
FOR EACH ROW
EXECUTE FUNCTION code_chunks_content_tsv_update();

CREATE INDEX code_chunks_snapshot_id_idx ON code_chunks (snapshot_id);
CREATE INDEX code_chunks_content_hash_idx ON code_chunks (content_hash);
CREATE INDEX code_chunks_content_tsv_gin_idx ON code_chunks USING gin (content_tsv);

CREATE TABLE chunk_embeddings (
  embedding_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chunk_id bigint NOT NULL REFERENCES code_chunks (chunk_id) ON DELETE CASCADE,
  model text NOT NULL,
  dim integer NOT NULL,
  embedding vector(768) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (chunk_id, model)
);

CREATE INDEX chunk_embeddings_chunk_id_idx ON chunk_embeddings (chunk_id);
CREATE INDEX chunk_embeddings_embedding_ivfflat_idx
  ON chunk_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

CREATE TABLE agent_runs (
  run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  project_id bigint NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE,
  snapshot_id bigint NOT NULL REFERENCES repo_snapshots (snapshot_id) ON DELETE CASCADE,
  status text NOT NULL,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX agent_runs_project_id_idx ON agent_runs (project_id);
CREATE INDEX agent_runs_snapshot_id_idx ON agent_runs (snapshot_id);

CREATE TABLE agent_steps (
  step_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES agent_runs (run_id) ON DELETE CASCADE,
  step_index integer NOT NULL,
  phase text NOT NULL,
  status text NOT NULL,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, step_index)
);

CREATE INDEX agent_steps_run_id_idx ON agent_steps (run_id);

CREATE TABLE patches (
  patch_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES agent_runs (run_id) ON DELETE CASCADE,
  step_id bigint REFERENCES agent_steps (step_id) ON DELETE SET NULL,
  round integer NOT NULL,
  diff_text text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX patches_run_id_idx ON patches (run_id);

CREATE TABLE metrics (
  metric_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES agent_runs (run_id) ON DELETE CASCADE,
  key text NOT NULL,
  value_json jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, key)
);

CREATE INDEX metrics_run_id_idx ON metrics (run_id);
