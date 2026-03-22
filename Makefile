SHELL := /bin/sh

.PHONY: up down build test py-compile lint typecheck check-deliverables demo export-experiments

up:
	docker compose up -d --build

down:
	docker compose down -v

build:
	docker compose build

py-compile:
	python -m py_compile main.py db.py crud.py cli.py embed/exceptions.py embed/providers.py embed/service.py retrieval/rrf.py retrieval/service.py agent/fsm.py patch/generator.py patch/apply.py patch/llm_provider.py patch/engine.py runner/cmd.py runner/cargo.py runner/types.py diagnose/parser.py metrics/export.py tools/c2rust_runner.py ingest/treesitter_chunker.py

test:
	python -m py_compile main.py db.py crud.py cli.py embed/exceptions.py embed/providers.py embed/service.py retrieval/rrf.py retrieval/service.py agent/fsm.py patch/generator.py patch/apply.py patch/llm_provider.py patch/engine.py runner/cmd.py runner/cargo.py runner/types.py diagnose/parser.py metrics/export.py tools/c2rust_runner.py ingest/treesitter_chunker.py
	python -m pytest -q

lint:
	python -m ruff check .

typecheck:
	python -m mypy .

check-deliverables:
	python -c "from pathlib import Path; req=[Path('apps/api/patch/controlled_prompt.md'),Path('apps/api/patch/llm_provider.py'),Path('apps/api/metrics/export.py'),Path('docs/REPRODUCE.md')]; miss=[str(p) for p in req if not p.exists()]; import sys; sys.exit(1 if miss else 0)"

demo:
	python scripts/run_demo.py

export-experiments:
	python scripts/export_experiments_csv.py --out experiments.csv
