# Open Source Experiment Artifacts

This directory preserves documentation artifacts for the open-source C project
cases used in the paper discussion.

These files are archival records only. They do not replace the formal
experiment outputs under `results/stage9b3_final_*`, and they are not live demo
run records.

## Scope

- `source_snapshot/`: placeholder or manually preserved upstream C source files.
- `SOURCE.md`: upstream project URL, selected source files, license, and rationale.
- `C2RUST_CONVERSION_RECORD.md`: relationship between upstream C modules and the
  C2Rust-style unsafe Rust baseline workspace used by the experiment.
- `BASELINE_VALIDATION.md`: baseline build/test/clippy status and static risk
  counts from the manifest and formal reports.
- `REPAIR_RESULT.md`: formal 9B-3-final repair result summary.

## Formal Results Boundary

Paper statistics should use only the formal 9B-3-final exports:

- `results/stage9b3_final_run_ids.json`
- `results/stage9b3_final_summary.json`
- `results/stage9b3_final_group_compare.csv`
- `results/stage9b3_final_failures.json`
- `results/table1_safety.csv`
- `results/table2_cost.csv`
- `results/all_metrics.csv`

The 9D-2 live demo runs under `demo_assets/live_demo_run_ids.json` are for
frontend walkthroughs only. They must not replace or be mixed with the formal
paper results.

## Important Wording

- The system repairs C2Rust-style unsafe Rust baselines after translation.
- The experiment does not evaluate the C2Rust translator itself.
- The template-enhanced group is an ablation group, not the main method.
- SW-03 and SW-04 are C-derived C2Rust-style workspaces based on selected modules
  from complete upstream C projects.
