# SW-04 Formal Repair Result

This record summarizes the formal 9B-3-final result using:

- `results/stage9b3_final_summary.json`
- `results/stage9b3_final_group_compare.csv`
- `results/stage9b3_final_failures.json`

It does not use live demo runs.

## Formal Run IDs

| Group | Run ID | Result |
|---|---|---|
| baseline | `1d60bcf2-1c8b-411c-b38f-1fa4d29957d2` | SUCCESS |
| template-enhanced | `98ab857e-7153-49a2-8167-b4868b5abc93` | FAILED |
| llm-rag-enhanced | `25c97630-3756-48d1-8220-f685aae60046` | SUCCESS |

## LLM-RAG Result

| Field | Value |
|---|---|
| status | SUCCESS |
| final_stop_reason | success |
| patch_backend | openai |
| model | DeepSeek-V3.2 |
| llm_mode | replacement_block |
| replacement_block_used | true |
| fallback_used | false |
| build/test/lint | pass / pass / pass |
| unsafe | 1 -> 0 |
| ptr_copy | 1 -> 0 |

## Patch Summary

The accepted formal LLM-RAG patch replaced unsafe memcpy-style pointer copy with
safe buffer copy logic. The key repair is equivalent to:

```rust
buffer.copy_from_slice(src);
```

The patch passed the same validator and build/test/lint pipeline as the other
formal runs. Replacement-block mode controlled the LLM output format; it did not
bypass validation.
