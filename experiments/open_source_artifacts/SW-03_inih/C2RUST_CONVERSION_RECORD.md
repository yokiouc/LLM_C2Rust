# SW-03 C2Rust Conversion Record

## Source Basis

- Original project: inih
- URL: https://github.com/benhoyt/inih
- Selected source module: `ini.c` / `ini.h`
- License: BSD-3-Clause / New BSD

## Baseline Workspace

- Baseline workspace:
  `experiments/workspaces/SW-03_inih_c_derived_workspace`
- Workspace type: C-derived C2Rust-style unsafe Rust baseline
- Main risk pattern: INI parser byte walk with raw pointer arithmetic

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
