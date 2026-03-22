from retrieval.rrf import compute_rrf


def test_rrf_empty():
    out = compute_rrf([], [])
    assert out == []


def test_rrf_single_side():
    out = compute_rrf([{"chunk_id": 1, "rank": 1}], [], k=60, lexical_weight=1.0, vector_weight=1.0)
    assert out[0]["chunk_id"] == 1
    assert out[0]["lexical_rank"] == 1
    assert out[0]["vector_rank"] is None
    assert abs(out[0]["rrf"] - (1.0 / 61.0)) < 1e-12


def test_rrf_formula_precision():
    lex = [{"chunk_id": 10, "rank": 1}, {"chunk_id": 20, "rank": 2}]
    vec = [{"chunk_id": 10, "rank": 3}, {"chunk_id": 30, "rank": 1}]
    out = compute_rrf(lex, vec, k=60, lexical_weight=0.5, vector_weight=0.5)
    by_id = {x["chunk_id"]: x for x in out}
    s10 = 0.5 / 61.0 + 0.5 / 63.0
    assert abs(by_id[10]["rrf"] - s10) < 1e-12
