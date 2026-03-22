import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write_sha256(path: Path) -> None:
    raw = path.read_bytes()
    path.with_suffix(path.suffix + ".sha256").write_text(_sha256_bytes(raw) + "\n", encoding="utf-8")


def export_metrics(iteration: int, metrics: dict[str, Any], out_dir: Path) -> None:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = dict(metrics.get("meta") or {})
    timestamp_utc = str(meta.get("timestamp_utc") or datetime.now(timezone.utc).isoformat())
    commit = str(meta.get("commit") or "")
    config_hash = str(meta.get("config_hash") or "")

    unsafe_blocks = int(metrics.get("unsafe_blocks") or 0)
    raw_ptr_count = int(metrics.get("raw_ptr_count") or 0)
    unsafe_line_pct = float(metrics.get("unsafe_line_pct") or 0.0)
    test_pass_rate = float(metrics.get("test_pass_rate") or 0.0)

    row = {
        "iteration": int(iteration),
        "unsafe_blocks": unsafe_blocks,
        "unsafe_line_pct": f"{unsafe_line_pct:.2f}",
        "raw_ptr_count": raw_ptr_count,
        "test_pass_rate": f"{test_pass_rate:.2f}",
        "timestamp_utc": timestamp_utc,
        "commit": commit,
        "config_hash": config_hash,
    }

    csv_path = out_dir / f"{iteration:04d}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerow(row)
    _write_sha256(csv_path)

    json_path = out_dir / f"{iteration:04d}.json"
    obj = {
        "meta": {"timestamp_utc": timestamp_utc, "commit": commit, "config_hash": config_hash},
        "iteration": int(iteration),
        "metrics": {
            "unsafe_blocks": unsafe_blocks,
            "unsafe_line_pct": round(unsafe_line_pct, 2),
            "raw_ptr_count": raw_ptr_count,
            "test_pass_rate": round(test_pass_rate, 2),
        },
    }
    json_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_sha256(json_path)

