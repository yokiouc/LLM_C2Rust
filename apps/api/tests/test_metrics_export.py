import hashlib
import json
from pathlib import Path

from metrics.export import CSV_COLUMNS, export_metrics


def test_export_metrics_writes_csv_json_and_sha256(tmp_path: Path):
    export_metrics(
        3,
        {
            "unsafe_blocks": 2,
            "unsafe_line_pct": 12.3456,
            "raw_ptr_count": 4,
            "test_pass_rate": 88.888,
            "meta": {"timestamp_utc": "2026-01-01T00:00:00+00:00", "commit": "abc", "config_hash": "h"},
        },
        tmp_path,
    )

    csv_path = tmp_path / "0003.csv"
    json_path = tmp_path / "0003.json"
    assert csv_path.exists()
    assert json_path.exists()

    csv_sha = (tmp_path / "0003.csv.sha256").read_text(encoding="utf-8").strip()
    assert csv_sha == hashlib.sha256(csv_path.read_bytes()).hexdigest()

    json_sha = (tmp_path / "0003.json.sha256").read_text(encoding="utf-8").strip()
    assert json_sha == hashlib.sha256(json_path.read_bytes()).hexdigest()

    csv_text = csv_path.read_text(encoding="utf-8").splitlines()
    assert csv_text[0].split(",") == CSV_COLUMNS
    assert "12.35" in csv_text[1]
    assert "88.89" in csv_text[1]

    obj = json.loads(json_path.read_text(encoding="utf-8"))
    assert obj["iteration"] == 3
    assert obj["meta"]["commit"] == "abc"
    assert obj["metrics"]["unsafe_blocks"] == 2

