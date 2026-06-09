# SW-04 C2Rust Conversion Record

## Source Basis

- Original project: rxi/log.c
- URL: https://github.com/rxi/log.c
- Selected source module: `src/log.c` / `src/log.h`
- License: MIT

## Baseline Workspace

- Baseline workspace:
  `experiments/workspaces/SW-04_logc_c_derived_workspace`
- Workspace type: C-derived C2Rust-style unsafe Rust baseline
- Main risk pattern: formatting buffer copy with `ptr::copy_nonoverlapping`

## Evaluation Boundary

This experiment evaluates unsafe Rust repair after a C2Rust-style baseline has
already been prepared. It does not evaluate the C2Rust translator itself.

The repair pipeline operates on the Rust baseline workspace using hotspot
discovery, repair slicing, retrieval evidence, patch generation, validation,
rollback, and metrics export.

## Baseline Validation Commands

The baseline workspace was validated with:

```bash
cargo build
cargo test
cargo clippy -- -D warnings
```
