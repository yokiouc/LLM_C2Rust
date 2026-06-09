# SW-03 Baseline Validation

This record is based on `experiments/experiment_manifest.json`,
`experiments/experiment_manifest.csv`, and the existing formal stage reports. It
does not claim a new command transcript and does not contain newly rerun stdout.

## Workspace

`experiments/workspaces/SW-03_inih_c_derived_workspace`

## Validation Status

| Check | Result |
|---|---|
| `cargo build` | pass |
| `cargo test` | pass, 2 tests |
| `cargo clippy -- -D warnings` | pass |

## Baseline Metrics

| Metric | Value |
|---|---:|
| LOC | 126 |
| unsafe_block | 1 |
| raw_ptr | 1 |
| pointer_arithmetic | 1 |
| ptr_copy | 0 |

## Notes

SW-03 is the inih-derived parser case. It is used to represent byte-level parser
pointer walk behavior in a C-derived C2Rust-style unsafe Rust workspace.
