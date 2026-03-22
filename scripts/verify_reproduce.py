import argparse
import csv
import hashlib
import json
from pathlib import Path


CSV_COLUMNS = [
    "iteration",
    "unsafe_blocks",
    "unsafe_line_pct",
    "raw_ptr_count",
    "test_pass_rate",
    "timestamp_utc",
    "commit",
    "config_hash",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_sha256(path: Path) -> None:
    sha_path = path.with_suffix(path.suffix + ".sha256")
    if not sha_path.exists():
        raise SystemExit(f"missing_sha256: {sha_path}")
    got = sha_path.read_text(encoding="utf-8", errors="replace").strip()
    exp = _sha256(path)
    if got != exp:
        raise SystemExit(f"sha256_mismatch: {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics-dir", required=True)
    args = ap.parse_args()

    root = Path(args.metrics_dir).resolve()
    if not root.exists():
        raise SystemExit("metrics_dir_not_found")

    csv_files = sorted(root.glob("*.csv"))
    json_files = sorted(root.glob("*.json"))
    if not csv_files or not json_files:
        raise SystemExit("no_metrics_files_found")

    for p in csv_files:
        _check_sha256(p)
        with p.open("r", encoding="utf-8", newline="") as f:
            r = csv.reader(f)
            header = next(r)
        if header != CSV_COLUMNS:
            raise SystemExit(f"csv_header_invalid: {p}")

    for p in json_files:
        _check_sha256(p)
        obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        if "meta" not in obj or "metrics" not in obj:
            raise SystemExit(f"json_schema_invalid: {p}")
        for k in ["timestamp_utc", "commit", "config_hash"]:
            if k not in obj["meta"]:
                raise SystemExit(f"json_meta_missing_{k}: {p}")
        for k in ["unsafe_blocks", "unsafe_line_pct", "raw_ptr_count", "test_pass_rate"]:
            if k not in obj["metrics"]:
                raise SystemExit(f"json_metrics_missing_{k}: {p}")

    print(json.dumps({"ok": True, "csv": len(csv_files), "json": len(json_files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

