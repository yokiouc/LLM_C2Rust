DROP TABLE IF EXISTS patches CASCADE;
DROP TABLE IF EXISTS agent_steps CASCADE;
DROP TABLE IF EXISTS agent_runs CASCADE;

CREATE TABLE agent_runs (
  run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_url text NOT NULL,
  ref text NOT NULL,
  task_description text NOT NULL,
  status text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT agent_runs_status_check CHECK (status IN ('INIT','RETRIEVE','GENERATE','APPLY','EXECUTE','DIAGNOSE','STOP','FAILED'))
);

CREATE INDEX agent_runs_status_idx ON agent_runs (status);
CREATE INDEX agent_runs_created_at_idx ON agent_runs (created_at);

CREATE TABLE agent_steps (
  step_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES agent_runs (run_id) ON DELETE CASCADE,
  step_name text NOT NULL,
  input_json jsonb NOT NULL,
  output_json jsonb NOT NULL,
  ok boolean NOT NULL,
  error_msg text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX agent_steps_run_id_idx ON agent_steps (run_id);
CREATE INDEX agent_steps_created_at_idx ON agent_steps (created_at);

CREATE TABLE patches (
  patch_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES agent_runs (run_id) ON DELETE CASCADE,
  file_path text NOT NULL,
  unified_diff text NOT NULL,
  status text NOT NULL,
  error_msg text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT patches_status_check CHECK (status IN ('applied','rolled_back'))
);

CREATE INDEX patches_run_id_idx ON patches (run_id);
