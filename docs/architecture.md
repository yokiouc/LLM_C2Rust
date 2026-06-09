# System Architecture

## Overview

```
                    ┌──────────────┐
                    │   Frontend   │
                    │  (Next.js)   │
                    └──────┬───────┘
                           │ HTTP
                    ┌──────▼───────┐
                    │   FastAPI    │
                    │   (API)      │
                    └──────┬───────┘
                           │
              ┌────────────▼────────────┐
              │    Repair Agent FSM     │
              │  (packages/repair/agent)│
              └────────────┬────────────┘
                           │
          ┌────────┬───────┼───────┬────────┐
          ▼        ▼       ▼       ▼        ▼
     ┌────────┐┌───────┐┌──────┐┌───────┐┌───────┐
     │Hotspot ││Slice  ││Patch ││Runner ││Metrics│
     │Discover││Builder││Engine││Valid. ││Collect│
     └───┬────┘└───┬───┘└──┬───┘└───┬───┘└───┬───┘
         │         │       │        │        │
         └─────────┴───────┴────────┴────────┘
                           │
              ┌────────────▼────────────┐
              │   PostgreSQL + pgvector │
              │   (Evidence DB)         │
              └─────────────────────────┘
```

## Data Flow

```
C Source → C2Rust → Baseline Rust Workspace
                         │
                    ┌────▼────┐
                    │ Ingest  │ tree-sitter chunking
                    └────┬────┘ + embedding
                         │
                    ┌────▼────┐
                    │Evidence │ code_chunks + chunk_embeddings
                    │   DB    │ lexical_search + vector_search
                    └────┬────┘
                         │
                    ┌────▼────────────────────────────┐
                    │        Repair Agent FSM          │
                    │                                  │
                    │  INIT → PRECHECK                 │
                    │    → HOTSPOT_DISCOVERY            │
                    │    → SLICE_SELECT                 │
                    │    → RETRIEVE_EVIDENCE            │
                    │    → BUILD_PROMPT                 │
                    │    → GENERATE_PATCH               │
                    │    → VALIDATE_PATCH               │
                    │    → APPLY_PATCH                  │
                    │    → RUN_BUILD/TEST/LINT          │
                    │    → SCORE_PROGRESS               │
                    │      ├→ SUCCESS                   │
                    │      ├→ STOP_NO_PROGRESS          │
                    │      ├→ STOP_MAX_ITERS            │
                    │      └→ DIAGNOSE → ROLLBACK → ↩  │
                    └────┬────────────────────────────┘
                         │
                    ┌────▼────┐
                    │ Metrics │ safety before/after
                    │ Export  │ engineering + evaluation
                    └────┬────┘
                         │
                    ┌────▼────┐
                    │ Compare │ baseline vs enhanced
                    └─────────┘
```

## Database Schema (16 tables)

### Core tables (existing)
- `projects` — project registry
- `repo_snapshots` — commit snapshots
- `code_chunks` — code slices + evidence (tsvector indexed)
- `embedding_models` — model registry
- `chunk_embeddings` — vector embeddings (pgvector)

### Agent tables (existing)
- `agent_runs` — repair run tracking
- `agent_steps` — FSM step log
- `patches` — generated patches
- `metrics` — key-value metrics store

### Repair tables (new in iter6)
- `hotspots` — discovered unsafe code locations
- `repair_slices` — minimal repair slices with constraints
- `evidence_links` — slice ↔ evidence chunk associations
- `validation_results` — structured build/test/clippy/fmt results
- `patch_rollbacks` — rollback event tracking

## Package Architecture

```
packages/
├── core/           # Config, constants (25 FSM states, 9 evidence types,
│                   #   8 hotspot kinds), shared types, DB connection
├── evidence/       # Schema, retrieval (hybrid), RRF, chunker, embed facade,
│                   #   repository (hotspots/slices/links), linker
├── repair/         # Hotspot discovery (tree-sitter + regex + scoring),
│                   #   slice builder (function boundaries + constraints),
│                   #   patch engine/generator/validator, prompt builder,
│                   #   diagnose, LLM providers, agent FSM (states/handlers/engine)
├── runner/         # Command execution (mock/real), cargo detection,
│                   #   phased validation (build/test/clippy/fmt)
└── metrics/        # Safety scanning (unsafe/raw_ptr/api/mem),
                    #   collector (engineering + evaluation metrics),
                    #   export (CSV/JSON + SHA256), compare (baseline vs enhanced)
```
