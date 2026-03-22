import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RRFConfig:
    k: int = 60
    lexical_weight: float = 0.5
    vector_weight: float = 0.5


def load_rrf_config() -> RRFConfig:
    k = int(os.getenv("RRF_K", "60"))
    lw = float(os.getenv("RRF_LEXICAL_WEIGHT", "0.5"))
    vw = float(os.getenv("RRF_VECTOR_WEIGHT", "0.5"))
    return RRFConfig(k=k, lexical_weight=lw, vector_weight=vw)


def compute_rrf(
    lexical_ranks: list[dict],
    vector_ranks: list[dict],
    k: int = 60,
    lexical_weight: float = 0.5,
    vector_weight: float = 0.5,
) -> list[dict]:
    lex_rank_by_id: dict[int, int] = {}
    for i, item in enumerate(lexical_ranks, start=1):
        cid = int(item["chunk_id"])
        rank = int(item.get("rank", i))
        if cid not in lex_rank_by_id or rank < lex_rank_by_id[cid]:
            lex_rank_by_id[cid] = rank

    vec_rank_by_id: dict[int, int] = {}
    for i, item in enumerate(vector_ranks, start=1):
        cid = int(item["chunk_id"])
        rank = int(item.get("rank", i))
        if cid not in vec_rank_by_id or rank < vec_rank_by_id[cid]:
            vec_rank_by_id[cid] = rank

    all_ids = set(lex_rank_by_id) | set(vec_rank_by_id)
    out: list[dict] = []
    for cid in all_ids:
        lr = lex_rank_by_id.get(cid)
        vr = vec_rank_by_id.get(cid)
        score = 0.0
        if lr is not None:
            score += lexical_weight / (k + lr)
        if vr is not None:
            score += vector_weight / (k + vr)
        out.append(
            {
                "chunk_id": cid,
                "lexical_rank": lr,
                "vector_rank": vr,
                "rrf": score,
            }
        )

    out.sort(key=lambda x: (-x["rrf"], x["chunk_id"]))
    return out
