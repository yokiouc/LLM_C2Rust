/** API response types for the C2Rust Repair System */

// --- Runs ---

export interface RunSummary {
  run_id: string;
  repo_url: string;
  ref: string;
  task_description: string;
  status: string;
  created_at: string;
  updated_at: string;
  mode: string | null;
  final_status: string | null;
  final_stop_reason: string | null;
  iteration_count: number | null;
  total_ms: number | null;
  rollback_count: number | null;
}

export interface RunStatus {
  run_id: string;
  status: string;
  iteration_count: number | null;
  final_status: string | null;
  final_stop_reason: string | null;
  progress_score_history: number[];
  rollback_count: number | null;
  total_ms: number | null;
  created_at: string;
  updated_at: string;
}

// --- Hotspots ---

export interface Hotspot {
  id: number;
  run_id: string;
  snapshot_id: number | null;
  file_path: string;
  symbol: string | null;
  start_line: number;
  end_line: number;
  hotspot_kind: string;
  risk_score: number;
  risk_level: string;
  risk_tags: string[];
  unsafe_count: number;
  raw_ptr_count: number;
  content: string;
  created_at: string;
}

export interface HotspotsResponse {
  run_id: string;
  hotspots: Hotspot[];
  count: number;
}

// --- Slices ---

export interface RepairSlice {
  id: number;
  hotspot_id: number;
  run_id: string;
  file_path: string;
  symbol: string | null;
  slice_start: number;
  slice_end: number;
  anchor_line: number | null;
  signature_text: string | null;
  signature_line: number | null;
  content: string;
  keep_signature: boolean;
  no_global_rename: boolean;
  min_patch: boolean;
  forbidden_regions: Array<{ start: number; end: number; reason: string }>;
  related_vars: string[];
  related_unsafe_ops: string[];
  created_at: string;
}

export interface SlicesResponse {
  run_id: string;
  slices: RepairSlice[];
  count: number;
}

// --- Validation ---

export interface ValidationResult {
  id: number;
  run_id: string;
  patch_id: string | null;
  stage: string;
  status: string;
  exit_code: number | null;
  duration_ms: number | null;
  issue_count: number;
  issue_kind: string | null;
  parsed_issues: Array<Record<string, unknown>>;
  created_at: string;
}

export interface ValidationSummary {
  build: ValidationResult | null;
  test: ValidationResult | null;
  clippy: ValidationResult | null;
  fmt: ValidationResult | null;
}

export interface ValidationResponse {
  run_id: string;
  results: ValidationResult[];
  summary: ValidationSummary;
}

// --- Metrics ---

export interface MetricsResponse {
  run_id: string;
  engineering: Record<string, unknown>;
  evaluation: Record<string, unknown>;
  other: Record<string, unknown>;
}

// --- Compare ---

export interface CompareResponse {
  project: string;
  baseline: {
    run_id: string;
    compile_ok: boolean;
    test_ok: boolean;
    unsafe_blocks: number;
    raw_ptr_count: number;
    total_ms: number;
  };
  enhanced: {
    run_id: string;
    compile_ok: boolean;
    test_ok: boolean;
    unsafe_blocks: number;
    raw_ptr_count: number;
    total_ms: number;
    iterations: number;
    rollbacks: number;
    stop_reason: string;
  };
  delta: {
    unsafe_blocks: number;
    raw_ptr: number;
    unsafe_api: number;
  };
}

// --- Patches ---

export interface Patch {
  patch_id: string;
  file_path: string;
  unified_diff: string;
  status: string;
  error_msg: string | null;
  created_at: string;
}

export interface PatchesResponse {
  run_id: string;
  patches: Patch[];
  rollbacks: Array<Record<string, unknown>>;
}
