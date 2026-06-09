"""Centralized configuration for the C2Rust repair system."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def get_database_url() -> str:
    """Resolve database URL from environment variables."""
    dsn = os.getenv("POSTGRES_DSN", "")
    if dsn:
        return dsn

    dsn = os.getenv("DATABASE_URL", "")
    if dsn:
        return dsn

    host = os.getenv("POSTGRES_HOST", "")
    if not host:
        raise RuntimeError("DATABASE_URL is not set")

    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "root")
    password = os.getenv("POSTGRES_PASSWORD", "root")
    db = os.getenv("POSTGRES_DB", "postgres")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def get_repo_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    """System-wide configuration."""

    # Database
    database_url: str = ""
    db_timeout_seconds: int = 5

    # Embedding
    default_model_id: str = "stub-1536"
    embedding_batch_size: int = 128

    # Retrieval
    retrieval_top_k: int = 50
    rrf_k: int = 60
    rrf_lexical_weight: float = 0.5
    rrf_vector_weight: float = 0.5

    # Patch
    patch_backend: str = "template"
    patch_max_iters: int = 20
    patch_no_progress_limit: int = 5
    patch_validate_timeout: int = 300
    patch_max_changed_pairs: int = 20
    patch_max_total_lines: int = 120

    # Runner
    runner_mode: str = "mock"
    runner_timeout: int = 30
    runner_log_keep_days: int = 7

    # Tree-sitter
    tree_sitter_max_bytes: int = 1_048_576
    fallback_window_lines: int = 50

    # Paths
    repo_root: Path = field(default_factory=get_repo_root)


def get_config() -> Config:
    """Build config from environment variables with defaults."""
    return Config(
        database_url=get_database_url() if os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN") or os.getenv("POSTGRES_HOST") else "",
        db_timeout_seconds=int(os.getenv("DB_TIMEOUT_SECONDS", "5")),
        default_model_id=os.getenv("RETRIEVAL_MODEL_ID", "stub-1536"),
        patch_backend=os.getenv("PATCH_BACKEND", "template"),
        runner_mode=os.getenv("RUNNER_MODE", "mock"),
        runner_timeout=int(os.getenv("RUNNER_TIMEOUT", "30")),
        tree_sitter_max_bytes=int(os.getenv("TREE_SITTER_MAX_BYTES", "1048576")),
        fallback_window_lines=int(os.getenv("FALLBACK_WINDOW_LINES", "50")),
    )
