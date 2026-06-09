# SW-04 Source Record

## Project

- Project: rxi/log.c
- URL: https://github.com/rxi/log.c
- Selected files: `src/log.c` / `src/log.h`
- License: MIT

## Reason For Selection

rxi/log.c is a compact C99 logging library with formatting buffer and copy
logic. It is suitable for a C-derived pointer-copy repair experiment focused on
turning memcpy-style unsafe Rust code into safe slice or buffer copy operations.

## Artifact Boundary

This artifact records the upstream source basis for SW-04. The formal repair
experiment uses the baseline workspace at:

`experiments/workspaces/SW-04_logc_c_derived_workspace`

The formal repair results are stored under `results/stage9b3_final_*`.
