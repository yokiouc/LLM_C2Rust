import os
from typing import Any

from psycopg.rows import dict_row

from db import connect
from embed.providers import provider_from_model_row
from embed.service import _vector_literal
from .rrf import compute_rrf, load_rrf_config


def _read_sql(path_parts: list[str]) -> str:
    base = os.path.dirname(__file__)
    path = os.path.join(base, *path_parts)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _vector_search(
    *,
    model_id: str,
    snapshot_id: int,
    query_text: str,
    top_k: int,
    max_dist: float | None,
) -> list[dict]:
    sql_raw = _read_sql(["sql", "vector_search.sql"])
    query_sql = (
        sql_raw.replace(":query_vector", "%(query_vector)s")
        .replace(":snapshot_id", "%(snapshot_id)s")
        .replace(":top_k", "%(top_k)s")
        .replace(":max_dist", "%(max_dist)s")
    )

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT model_id, provider_type, dimension, config_jsonb FROM embedding_models WHERE model_id = %s;", (model_id,))
            model_row = cur.fetchone()
        if not model_row:
            raise RuntimeError("model_not_found")

        provider = provider_from_model_row(
            model_id=str(model_row["model_id"]),
            provider_type=str(model_row["provider_type"]),
            dimension=int(model_row["dimension"]),
            config=dict(model_row["config_jsonb"] or {}),
        )
        vec = provider.embed([query_text])[0]
        vec_lit = _vector_literal(vec)

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                query_sql,
                {"query_vector": vec_lit, "snapshot_id": snapshot_id, "top_k": top_k, "max_dist": max_dist},
            )
            rows = cur.fetchall()

    out = []
    for idx, r in enumerate(rows, start=1):
        out.append({"chunk_id": int(r["chunk_id"]), "dist": float(r["dist"]), "rank": idx})
    return out


def _lexical_search(
    *,
    snapshot_id: int,
    query_text: str,
    kinds: list[str] | None,
    limit_cnt: int,
) -> list[dict]:
    try:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT chunk_id, rank FROM lexical_search(%s, %s, %s, %s);", (snapshot_id, query_text, kinds, limit_cnt))
                rows = cur.fetchall()
    except Exception:
        rows = []

    out = []
    for idx, r in enumerate(rows, start=1):
        out.append({"chunk_id": int(r["chunk_id"]), "rank": idx, "ts_rank": float(r["rank"])})
    return out


def hybrid_retrieve_evidence(
    *,
    snapshot_id: int,
    query_text: str,
    filters: dict,
    top_k: int = 50,
    model_id: str | None = None,
) -> dict:
    kinds = None
    if filters and "kind" in filters and filters["kind"]:
        kinds = [str(x) for x in filters["kind"]]

    model_id = str(model_id or os.getenv("RETRIEVAL_MODEL_ID", "stub-1536"))
    max_dist = None
    if filters and "max_dist" in filters:
        max_dist = float(filters["max_dist"])

    lexical = _lexical_search(snapshot_id=snapshot_id, query_text=query_text, kinds=kinds, limit_cnt=max(top_k, 50))

    vector_fetch_k = max(top_k * 3, 50)
    vector = _vector_search(model_id=model_id, snapshot_id=snapshot_id, query_text=query_text, top_k=vector_fetch_k, max_dist=max_dist)

    if kinds:
        allowed = set()
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT chunk_id FROM code_chunks WHERE snapshot_id = %s AND kind = ANY(%s);",
                    (snapshot_id, kinds),
                )
                rows = cur.fetchall()
        allowed = {int(r["chunk_id"]) for r in rows}
        lexical = [x for x in lexical if x["chunk_id"] in allowed]
        vector = [x for x in vector if x["chunk_id"] in allowed]
        for i, x in enumerate(lexical, start=1):
            x["rank"] = i
        for i, x in enumerate(vector, start=1):
            x["rank"] = i

    cfg = load_rrf_config()
    fused = compute_rrf(lexical, vector, k=cfg.k, lexical_weight=cfg.lexical_weight, vector_weight=cfg.vector_weight)
    fused = fused[:top_k]

    fused_by_id = {int(x["chunk_id"]): x for x in fused}
    ids = list(fused_by_id.keys())

    vector_by_id = {int(x["chunk_id"]): float(x["dist"]) for x in vector}

    items: list[dict[str, Any]] = []
    if ids:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT chunk_id, left(content, 200) AS excerpt, kind, lang, meta
                    FROM code_chunks
                    WHERE snapshot_id = %s AND chunk_id = ANY(%s::bigint[]);
                    """,
                    (snapshot_id, ids),
                )
                rows = cur.fetchall()

        chunk_by_id = {int(r["chunk_id"]): r for r in rows}
        for cid, score in fused_by_id.items():
            c = chunk_by_id.get(cid)
            if not c:
                continue
            meta = dict(c["meta"] or {}) if isinstance(c.get("meta"), dict) else dict(c["meta"] or {})
            risk_tags = meta.get("risk_tags")
            risk_score = 0
            if isinstance(risk_tags, list):
                weights = {"unsafe": 3, "raw_ptr": 3, "ptr_arith": 2, "manual_mem": 2, "memcpy_memmove": 2}
                for t in risk_tags:
                    k = str(t or "").strip()
                    if k:
                        risk_score += int(weights.get(k, 0))
            items.append(
                {
                    "chunk_id": cid,
                    "excerpt": c["excerpt"],
                    "kind": c["kind"],
                    "lang": c["lang"],
                    "meta": meta,
                    "score": {
                        "dist": vector_by_id.get(cid),
                        "lexical_rank": score["lexical_rank"],
                        "vector_rank": score["vector_rank"],
                        "rrf": score["rrf"],
                        "risk": {"score": risk_score, "tags": risk_tags if isinstance(risk_tags, list) else []},
                    },
                }
            )

    items.sort(key=lambda x: (-float(x["score"]["rrf"]), -int(x["score"]["risk"]["score"]), int(x["chunk_id"])))
    return {
        "rrf_config": {"k": cfg.k, "lexical_weight": cfg.lexical_weight, "vector_weight": cfg.vector_weight},
        "items": items,
    }
