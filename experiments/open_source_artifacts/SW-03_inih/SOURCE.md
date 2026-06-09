# SW-03 Source Record

## Project

- Project: inih
- URL: https://github.com/benhoyt/inih
- Selected files: `ini.c` / `ini.h`
- License: BSD-3-Clause / New BSD

## Reason For Selection

inih is a compact INI parser with byte-level string and buffer scanning logic.
Its parsing loop is suitable for studying pointer and buffer repair behavior in
a C-derived C2Rust-style unsafe Rust baseline.

## Artifact Boundary

This artifact records the upstream source basis for SW-03. The formal repair
experiment uses the baseline workspace at:

`experiments/workspaces/SW-03_inih_c_derived_workspace`

The formal repair results are stored under `results/stage9b3_final_*`.
