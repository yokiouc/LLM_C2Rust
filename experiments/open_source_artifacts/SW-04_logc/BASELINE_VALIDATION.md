# SW-04 Baseline Validation

This record is based on `experiments/experiment_manifest.json`,
`experiments/experiment_manifest.csv`, and the existing formal stage reports. It
does not claim a new command transcript and does not contain newly rerun stdout.

## Workspace

`experiments/workspaces/SW-04_logc_c_derived_workspace`

## Validation Status

| Check | Result |
|---|---|
| `cargo build` | pass |
| `cargo test` | pass, 2 tests |
| `cargo clippy -- -D warnings` | pass |

## Baseline Metrics

| Metric | Value |
|---|---:|
| LOC | 70 |
| unsafe_block | 1 |
| raw_ptr | 2 |
| pointer_arithmetic | 0 |
| ptr_copy | 1 |

## Notes

SW-04 is the rxi/log.c-derived logging buffer case. It is used to represent
memcpy-style pointer-copy behavior in a C-derived C2Rust-style unsafe Rust
workspace.
