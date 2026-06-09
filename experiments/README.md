# Formal Experiment Workspaces

This directory contains the Stage 9B-0 fixed experiment workspaces.

Before formal Stage 9B execution, run the baseline precheck for each workspace:

```powershell
cargo build
cargo test
cargo clippy -- -D warnings
```

The Stage 9B-0.6 real-runner precheck passed for the original five workspaces:

- `cargo build`
- `cargo test` with 2 tests passing per workspace
- `cargo clippy -- -D warnings`

Stage 9B-2.9 adds two small open-source C-derived workspaces:

- `SW-03_inih_c_derived_workspace`: inspired by inih, a small BSD-style INI parser in C. The baseline keeps a C2Rust-style raw pointer byte walk over an input buffer.
- `SW-04_logc_c_derived_workspace`: inspired by rxi/log.c, a small MIT-licensed C99 logging library. The baseline keeps a C2Rust-style `ptr::copy_nonoverlapping` buffer copy.

Both added C-derived workspaces passed:

- `cargo build`
- `cargo test` with 2 tests passing per workspace
- `cargo clippy -- -D warnings`

The C-derived entries are marked in the manifest with `c_derived=true`, `c2rust_style_baseline=true`, source project, source URL, and license metadata.

The workspaces are ready for formal baseline/enhanced experiments.
