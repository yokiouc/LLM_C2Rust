-- Migration 006: Full repair system tables
-- Adds: hotspots, repair_slices, evidence_links, validation_results, patch_rollbacks
-- Also widens agent_runs.status for the v2 FSM states.
-- Compatible with existing agent_runs, agent_steps, patches, metrics tables.

ALTER TABLE agent_runs
  DROP CONSTRAINT IF EXISTS agent_runs_status_check;

ALTER TABLE agent_runs
  ADD CONSTRAINT agent_runs_status_check CHECK (status IN (
    'INIT','PRECHECK','HOTSPOT_DISCOVERY','SLICE_SELECT',
    'RETRIEVE_EVIDENCE','BUILD_PROMPT','GENERATE_PATCH','VALIDATE_PATCH',
    'APPLY_PATCH','RUN_BUILD','RUN_TEST','RUN_LINT','DIAGNOSE',
    'SCORE_PROGRESS','ROLLBACK','SUCCESS','STOP_NO_PROGRESS',
    'STOP_MAX_ITERS','STOP_HARD_ERROR',
    'RETRIEVE','GENERATE','APPLY','EXECUTE','STOP','FAILED'
  ));

-- ---------------------------------------------------------------------------
-- 1. hotspots — discovered high-risk unsafe code locations
-- ---------------------------------------------------------------------------
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

  CONSTRAINT hotspots_risk_level_check
    CHECK (risk_level IN ('low', 'medium', 'high')),
  CONSTRAINT hotspots_kind_check
    CHECK (hotspot_kind IN (
      'unsafe_block', 'raw_ptr_deref', 'ptr_arithmetic',
      'manual_mem_api', 'memcpy_memmove', 'cross_func_resource',
      'unsafe_fn_decl', 'extern_call'
    ))
);

CREATE INDEX IF NOT EXISTS hotspots_run_id_idx ON hotspots (run_id);
CREATE INDEX IF NOT EXISTS hotspots_snapshot_id_idx ON hotspots (snapshot_id);
CREATE INDEX IF NOT EXISTS hotspots_file_path_idx ON hotspots (file_path);

-- ---------------------------------------------------------------------------
-- 2. repair_slices — minimal repair slices with boundary constraints
-- ---------------------------------------------------------------------------
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

  -- Interface boundary constraints
  keep_signature      boolean NOT NULL DEFAULT true,
  no_global_rename    boolean NOT NULL DEFAULT true,
  min_patch           boolean NOT NULL DEFAULT true,
  forbidden_regions   jsonb   NOT NULL DEFAULT '[]'::jsonb,

  -- Related analysis
  related_vars        jsonb   NOT NULL DEFAULT '[]'::jsonb,
  related_unsafe_ops  jsonb   NOT NULL DEFAULT '[]'::jsonb,

  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS repair_slices_hotspot_id_idx ON repair_slices (hotspot_id);
CREATE INDEX IF NOT EXISTS repair_slices_run_id_idx ON repair_slices (run_id);
CREATE INDEX IF NOT EXISTS repair_slices_file_path_idx ON repair_slices (file_path);

-- ---------------------------------------------------------------------------
-- 3. evidence_links — connects repair slices to retrieved evidence chunks
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- 4. validation_results — structured build/test/clippy/fmt results
-- ---------------------------------------------------------------------------
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

  CONSTRAINT validation_results_stage_check
    CHECK (stage IN ('build', 'test', 'clippy', 'fmt')),
  CONSTRAINT validation_results_status_check
    CHECK (status IN ('pending', 'pass', 'fail', 'error', 'skip'))
);

CREATE INDEX IF NOT EXISTS validation_results_run_id_idx ON validation_results (run_id);
CREATE INDEX IF NOT EXISTS validation_results_patch_id_idx ON validation_results (patch_id);
CREATE INDEX IF NOT EXISTS validation_results_stage_idx ON validation_results (stage);

-- ---------------------------------------------------------------------------
-- 5. patch_rollbacks — rollback event tracking for repair traceability
-- ---------------------------------------------------------------------------
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
