"""Evidence linker: connects repair slices to retrieved evidence chunks.

Provides the bridge between hotspot/slice discovery and the RAG evidence system.
Creates evidence_links records that associate slices with their supporting evidence.
"""

from typing import Any

from packages.core.types import SliceInfo


def link_slices_to_evidence(
    *,
    conn: Any,
    slice_ids: list[int],
    slices: list[SliceInfo],
    evidence_items: list[dict[str, Any]],
) -> list[int]:
    """Link repair slices to evidence items from retrieval.

    For each slice, finds relevant evidence by matching file paths and content overlap,
    then creates evidence_links records.

    Args:
        conn: Database connection
        slice_ids: List of persisted slice IDs (aligned with slices)
        slices: List of SliceInfo objects
        evidence_items: List of evidence dicts from hybrid_retrieve_evidence()
            Each item should have: chunk_id, score (dict with rrf), kind, meta

    Returns:
        List of created evidence_link IDs.
    """
    from packages.evidence.repository import link_evidence

    link_ids: list[int] = []

    for sid, sl in zip(slice_ids, slices):
        # Rank evidence items by relevance to this slice
        scored: list[tuple[float, int, dict[str, Any]]] = []
        for rank_idx, item in enumerate(evidence_items):
            chunk_id = int(item.get("chunk_id", 0))
            if not chunk_id:
                continue

            # Compute relevance score
            score = 0.0
            meta = item.get("meta") or {}

            # File match bonus
            item_file = str(meta.get("file") or "")
            if item_file and item_file == sl.file:
                score += 5.0

            # RRF score
            score_dict = item.get("score") or {}
            rrf = float(score_dict.get("rrf") or 0.0)
            score += rrf * 10.0

            # Risk relevance bonus
            risk_dict = score_dict.get("risk") or {}
            risk_score = int(risk_dict.get("score") or 0)
            score += risk_score * 0.5

            # Evidence type bonus — strategies and constraints are high value
            ev_type = str(meta.get("evidence_type") or item.get("kind") or "")
            if ev_type in ("replacement_strategy", "interface_constraint", "behavior_constraint"):
                score += 3.0
            elif ev_type in ("compile_fix_hint",):
                score += 2.0

            scored.append((score, rank_idx, item))

        # Sort by score descending, take top N
        scored.sort(key=lambda x: -x[0])
        top_n = scored[:20]

        for rank, (final_score, _orig_rank, item) in enumerate(top_n, start=1):
            chunk_id = int(item.get("chunk_id", 0))
            lid = link_evidence(
                conn,
                slice_id=sid,
                chunk_id=chunk_id,
                score=round(final_score, 4),
                rank=rank,
                link_type="retrieval",
            )
            link_ids.append(lid)

    return link_ids


def build_evidence_pack(
    *,
    conn: Any,
    slice_id: int,
) -> dict[str, Any]:
    """Build an evidence pack for a slice, ready for prompt construction.

    Returns a dict containing the slice info and its linked evidence,
    structured for consumption by the prompt builder.
    """
    from packages.evidence.repository import get_slice, list_evidence_links

    sl = get_slice(conn, slice_id=slice_id)
    if not sl:
        return {"slice": None, "evidence": [], "strategies": [], "constraints": []}

    links = list_evidence_links(conn, slice_id=slice_id, limit=50)

    evidence_items: list[dict[str, Any]] = []
    strategies: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []

    for link in links:
        meta = dict(link.get("meta") or {}) if isinstance(link.get("meta"), dict) else {}
        ev_type = str(meta.get("evidence_type") or link.get("kind") or "")

        item = {
            "chunk_id": link.get("chunk_id"),
            "kind": link.get("kind"),
            "excerpt": link.get("excerpt"),
            "meta": meta,
            "score": link.get("score"),
            "rank": link.get("rank"),
        }

        if ev_type in ("replacement_strategy", "rust_idiom_template"):
            strategies.append(item)
        elif ev_type in ("interface_constraint", "behavior_constraint"):
            constraints.append(item)
        else:
            evidence_items.append(item)

    return {
        "slice": dict(sl),
        "evidence": evidence_items,
        "strategies": strategies,
        "constraints": constraints,
    }
