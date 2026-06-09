# SW-04 rxi/log.c C-derived Workspace

Source project: rxi/log.c

Source URL: https://github.com/rxi/log.c

License: MIT.

This workspace is a small C2Rust-style baseline inspired by rxi/log.c, a compact C99 logging library. The original library formats log records into caller-provided streams and buffers. This Rust baseline keeps an unsafe memcpy-style copy into a fixed output buffer to represent a typical C-derived buffer formatting pattern.

Risk points:

- Raw source and destination pointers derived from slices.
- `std::ptr::copy_nonoverlapping` memcpy-style operation.
- Unsafe block around buffer copy.

The crate is self-contained and uses unit tests instead of the original C build flow.
