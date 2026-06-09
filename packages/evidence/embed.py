"""Embedding service facade.

This module provides a thin facade over the existing apps/api/embed/ subsystem.
The actual implementation stays in apps/api/embed/ — this facade just provides
a unified entry point for the packages layer.
"""

from typing import Any


def batch_embed_and_upsert(*, chunks: list[Any], model_id: str, snapshot_id: int) -> int:
    """Delegate to the existing embed service."""
    from embed.service import batch_embed_and_upsert as _impl, Chunk
    typed_chunks = [Chunk(chunk_id=c.chunk_id, content=c.content) if not isinstance(c, Chunk) else c for c in chunks]
    return _impl(chunks=typed_chunks, model_id=model_id, snapshot_id=snapshot_id)


def ensure_embedding_model(*, model_id: str, provider_type: str, dimension: int, config: dict[str, Any]) -> None:
    """Delegate to the existing embed service."""
    from embed.service import ensure_embedding_model as _impl
    _impl(model_id=model_id, provider_type=provider_type, dimension=dimension, config=config)
