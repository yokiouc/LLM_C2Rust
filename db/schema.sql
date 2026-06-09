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
  CONSTRAINT agent_runs_status_check CHECK (status IN (
    'INIT','PRECHECK','HOTSPOT_DISCOVERY','SLICE_SELECT',
    'RETRIEVE_EVIDENCE','BUILD_PROMPT','GENERATE_PATCH','VALIDATE_PATCH',
    'APPLY_PATCH','RUN_BUILD','RUN_TEST','RUN_LINT','DIAGNOSE',
    'SCORE_PROGRESS','ROLLBACK','SUCCESS','STOP_NO_PROGRESS',
    'STOP_MAX_ITERS','STOP_HARD_ERROR',
    'RETRIEVE','GENERATE','APPLY','EXECUTE','STOP','FAILED'
  ))
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

-- =========================================================================
-- Iter 6: Full repair system tables
-- =========================================================================

-- hotspots — discovered high-risk unsafe code locations
CREATE TABLE IF NOT EXISTS hotspots (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id      uuid        REFERENCES agent_runs (run_id) ON DELETE CASCADE,
  snapshot_id bigint      REFERENCES repo_snapshots (snapshot_id) ON DELETE CASCADE,
  file_path   text        NOT NULL,
  symbol      text,
  start_line  int         NOT NULL,
  end_line    int         NOT NULL,
  hotspot_kind text       NOT NULL,
  risk_score  float       NOT NULL DEFAULT 0.0,
  risk_level  text        NOT NULL DEFAULT 'low',
  risk_tags   jsonb       NOT NULL DEFAULT '[]'::jsonb,
  unsafe_count    int     NOT NULL DEFAULT 0,
  raw_ptr_count   int     NOT NULL DEFAULT 0,
  content     text        NOT NULL DEFAULT '',
  created_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT hotspots_risk_level_check CHECK (risk_level IN ('low', 'medium', 'high')),
  CONSTRAINT hotspots_kind_check CHECK (hotspot_kind IN (
    'unsafe_block', 'raw_ptr_deref', 'ptr_arithmetic',
    'manual_mem_api', 'memcpy_memmove', 'cross_func_resource',
    'unsafe_fn_decl', 'extern_call'
  ))
);

CREATE INDEX IF NOT EXISTS hotspots_run_id_idx ON hotspots (run_id);
CREATE INDEX IF NOT EXISTS hotspots_snapshot_id_idx ON hotspots (snapshot_id);
CREATE INDEX IF NOT EXISTS hotspots_file_path_idx ON hotspots (file_path);

-- repair_slices — minimal repair slices with boundary constraints
CREATE TABLE IF NOT EXISTS repair_slices (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  hotspot_id      bigint      NOT NULL REFERENCES hotspots (id) ON DELETE CASCADE,
  run_id          uuid        REFERENCES agent_runs (run_id) ON DELETE CASCADE,
  file_path       text        NOT NULL,
  symbol          text,
  slice_start     int         NOT NULL,
  slice_end       int         NOT NULL,
  anchor_line     int,
  signature_text  text,
  signature_line  int,
  content         text        NOT NULL DEFAULT '',
  keep_signature      boolean NOT NULL DEFAULT true,
  no_global_rename    boolean NOT NULL DEFAULT true,
  min_patch           boolean NOT NULL DEFAULT true,
  forbidden_regions   jsonb   NOT NULL DEFAULT '[]'::jsonb,
  related_vars        jsonb   NOT NULL DEFAULT '[]'::jsonb,
  related_unsafe_ops  jsonb   NOT NULL DEFAULT '[]'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS repair_slices_hotspot_id_idx ON repair_slices (hotspot_id);
CREATE INDEX IF NOT EXISTS repair_slices_run_id_idx ON repair_slices (run_id);
CREATE INDEX IF NOT EXISTS repair_slices_file_path_idx ON repair_slices (file_path);

-- evidence_links — connects repair slices to retrieved evidence chunks
CREATE TABLE IF NOT EXISTS evidence_links (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slice_id    bigint  NOT NULL REFERENCES repair_slices (id) ON DELETE CASCADE,
  chunk_id    bigint  NOT NULL REFERENCES code_chunks (chunk_id) ON DELETE CASCADE,
  score       float   NOT NULL DEFAULT 0.0,
  rank        int     NOT NULL DEFAULT 0,
  link_type   text    NOT NULL DEFAULT 'retrieval',
  created_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT evidence_links_unique UNIQUE (slice_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS evidence_links_slice_id_idx ON evidence_links (slice_id);
CREATE INDEX IF NOT EXISTS evidence_links_chunk_id_idx ON evidence_links (chunk_id);

-- validation_results — structured build/test/clippy/fmt results
CREATE TABLE IF NOT EXISTS validation_results (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id          uuid    NOT NULL REFERENCES agent_runs (run_id) ON DELETE CASCADE,
  patch_id        uuid    REFERENCES patches (patch_id) ON DELETE SET NULL,
  stage           text    NOT NULL,
  status          text    NOT NULL DEFAULT 'pending',
  exit_code       int,
  duration_ms     int,
  issue_count     int     NOT NULL DEFAULT 0,
  issue_kind      text,
  parsed_issues   jsonb   NOT NULL DEFAULT '[]'::jsonb,
  stdout_path     text,
  stderr_path     text,
  compared_against text,
  output          jsonb   NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT validation_results_stage_check CHECK (stage IN ('build', 'test', 'clippy', 'fmt')),
  CONSTRAINT validation_results_status_check CHECK (status IN ('pending', 'pass', 'fail', 'error', 'skip'))
);

CREATE INDEX IF NOT EXISTS validation_results_run_id_idx ON validation_results (run_id);
CREATE INDEX IF NOT EXISTS validation_results_patch_id_idx ON validation_results (patch_id);
CREATE INDEX IF NOT EXISTS validation_results_stage_idx ON validation_results (stage);

-- patch_rollbacks — rollback event tracking for repair traceability
CREATE TABLE IF NOT EXISTS patch_rollbacks (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id          uuid    NOT NULL REFERENCES agent_runs (run_id) ON DELETE CASCADE,
  patch_id        uuid    NOT NULL REFERENCES patches (patch_id) ON DELETE CASCADE,
  rollback_reason text    NOT NULL DEFAULT '',
  rollback_detail jsonb   NOT NULL DEFAULT '{}'::jsonb,
  backup_path     text,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS patch_rollbacks_run_id_idx ON patch_rollbacks (run_id);
CREATE INDEX IF NOT EXISTS patch_rollbacks_patch_id_idx ON patch_rollbacks (patch_id);
