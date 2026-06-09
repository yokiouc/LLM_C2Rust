"""Evidence type definitions and meta validation."""

from packages.core.constants import EvidenceType, ALL_EVIDENCE_TYPES


# Required meta fields for all evidence chunks
REQUIRED_META_FIELDS = {"file"}

# Full meta field set supported by the evidence system
SUPPORTED_META_FIELDS = {
    "file",
    "symbol",
    "kind",
    "evidence_type",
    "risk_tags",
    "constraint_tags",
    "api_tags",
    "origin",
    "slice_id",
    "boundary",
    "interface",
    "linked_c_symbols",
    "strategy_tags",
    "strategy_id",
    "strategy_title",
    "applies_to_risk",
    "signature",
    "calls",
    "start_line",
    "end_line",
}


def validate_meta(meta: dict) -> list[str]:
    """Validate evidence meta fields. Returns list of error messages (empty = valid)."""
    errors: list[str] = []
    for f in REQUIRED_META_FIELDS:
        if f not in meta:
            errors.append(f"missing required meta field: {f}")
    ev_type = meta.get("evidence_type")
    if ev_type and ev_type not in ALL_EVIDENCE_TYPES:
        errors.append(f"unknown evidence_type: {ev_type}")
    return errors


def default_evidence_type(*, kind: str, meta: dict) -> str:
    """Infer evidence_type from kind and meta if not explicitly set."""
    explicit = str(meta.get("evidence_type") or "").strip()
    if explicit:
        return explicit
    k = str(kind or "")
    if k == "rust_function_slice":
        return EvidenceType.RUST_FUNCTION_SLICE.value
    if k in ALL_EVIDENCE_TYPES:
        return k
    return "code_slice"
