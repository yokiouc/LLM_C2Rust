# SW-03 Formal Repair Result

This record summarizes the formal 9B-3-final result using:

- `results/stage9b3_final_summary.json`
- `results/stage9b3_final_group_compare.csv`
- `results/stage9b3_final_failures.json`

It does not use live demo runs.

## Formal Run IDs

| Group | Run ID | Result |
|---|---|---|
| baseline | `c0956794-a838-4420-b3f6-e4be958a54c2` | SUCCESS |
| template-enhanced | `838b21d6-36f7-4cf4-82fa-b3f29084c880` | FAILED |
| llm-rag-enhanced | `bcd76169-0f13-41a0-91ea-266cccba4a11` | FAILED |

## LLM-RAG Result

| Field | Value |
|---|---|
| status | FAILED |
| final_stop_reason | max_iters |
| failure | `patch_apply_failed:context_mismatch` |
| patch_backend | openai |
| model | DeepSeek-V3.2 |
| fallback_used | false |
| rollback | occurred, 2 rollbacks |
| unsafe | 1 -> 1 |
| pointer_arithmetic | 1 -> 1 |

## Interpretation

SW-03 is the formal parser and pointer-walk generalization failure case. The LLM
patch direction attempted to replace pointer arithmetic with indexed byte access,
but the unified diff context did not match the real file context exactly. The
system rejected the patch during apply and rolled back rather than accepting an
uncertain edit.
