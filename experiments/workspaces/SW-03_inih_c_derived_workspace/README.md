# SW-03 inih C-derived Workspace

Source project: inih (INI Not Invented Here)

Source URL: https://github.com/benhoyt/inih

License: New BSD / BSD-3-Clause style license.

This workspace is a small C2Rust-style baseline inspired by inih's line-oriented INI parsing. The original C project is intentionally small and uses C string/buffer traversal patterns. This Rust baseline keeps a translated-style raw pointer byte walk so the repair system can evaluate unsafe-to-safe repair on a realistic parser-shaped workload.

Risk points:

- Raw pointer obtained from an input byte slice.
- Pointer arithmetic through `.add(index)`.
- Unsafe dereference while scanning buffer contents.

The crate is self-contained and uses unit tests instead of the original C build system.
