from dataclasses import dataclass
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from db import connect
from .exceptions import EmbeddingException
from .providers import provider_from_model_row


@dataclass(frozen=True)
class Chunk:
    chunk_id: int
    content: str


def _vector_literal(v: list[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in v) + "]"


def _execute_values_upsert(
    conn: Connection,
    *,
    rows: list[tuple[int, str, int, str]],
) -> int:
    if not rows:
        return 0

    placeholders = ",".join(["(%s,%s,%s,%s::vector)"] * len(rows))
    flat: list[Any] = []
    for r in rows:
        flat.extend(r)

    sql = (
        "INSERT INTO chunk_embeddings (chunk_id, model_id, snapshot_id, embedding) VALUES "
        + placeholders
        + " ON CONFLICT (chunk_id, model_id) DO UPDATE SET "
        + " snapshot_id = EXCLUDED.snapshot_id, "
        + " embedding = EXCLUDED.embedding, "
        + " updated_at = now()"
    )

    with conn.cursor() as cur:
        cur.execute(sql, flat)
        return int(cur.rowcount or 0)


def batch_embed_and_upsert(
    *,
    chunks: list[Chunk],
    model_id: str,
    snapshot_id: int,
) -> int:
    try:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT model_id, provider_type, dimension, config_jsonb FROM embedding_models WHERE model_id = %s;",
                    (model_id,),
                )
                row = cur.fetchone()
            if not row:
                raise EmbeddingException("model_not_found")

            provider = provider_from_model_row(
                model_id=str(row["model_id"]),
                provider_type=str(row["provider_type"]),
                dimension=int(row["dimension"]),
                config=dict(row["config_jsonb"] or {}),
            )

            texts = [c.content for c in chunks]
            vectors = provider.embed(texts)
            if len(vectors) != len(chunks):
                raise EmbeddingException("vector_count_mismatch")

            dim = provider.dimension
            for v in vectors:
                if len(v) != dim:
                    raise EmbeddingException("dimension_mismatch")

            total = 0
            with conn.transaction():
                batch_rows: list[tuple[int, str, int, str]] = []
                for c, v in zip(chunks, vectors, strict=True):
                    batch_rows.append((c.chunk_id, model_id, snapshot_id, _vector_literal(v)))
                    if len(batch_rows) >= 128:
                        total += _execute_values_upsert(conn, rows=batch_rows)
                        batch_rows = []
                if batch_rows:
                    total += _execute_values_upsert(conn, rows=batch_rows)

            return total
    except EmbeddingException:
        raise
    except Exception as e:
        raise EmbeddingException("batch_embed_and_upsert_failed") from e


def ensure_embedding_model(
    *,
    model_id: str,
    provider_type: str,
    dimension: int,
    config: dict[str, Any],
) -> None:
    with connect() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO embedding_models (model_id, provider_type, dimension, config_jsonb)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (model_id) DO NOTHING;
                    """,
                    (model_id, provider_type, dimension, Jsonb(config)),
                )
