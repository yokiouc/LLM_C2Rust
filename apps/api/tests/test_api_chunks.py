from fastapi.testclient import TestClient

from main import app


def test_project_snapshot_chunk_flow():
    client = TestClient(app)

    r = client.post("/projects", json={"name": "p1", "desc": "d"})
    assert r.status_code == 201
    project_id = r.json()["project_id"]
    assert isinstance(project_id, int)

    r = client.post("/snapshots", json={"project_id": project_id, "commit_sha": "abc", "branch": "main"})
    assert r.status_code == 201
    snapshot_id = r.json()["snapshot_id"]
    assert isinstance(snapshot_id, int)

    r = client.post(
        "/chunks",
        json={
            "snapshot_id": snapshot_id,
            "kind": "rust_baseline",
            "lang": "rust",
            "content": "unsafe fn f() {}",
            "meta": {"file": "src/lib.rs", "symbol": "f"},
        },
    )
    assert r.status_code == 201
    chunk_id = r.json()["chunk_id"]
    assert isinstance(chunk_id, int)

    r = client.get(f"/chunks?snapshot_id={snapshot_id}&limit=10&offset=0")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["chunk_id"] == chunk_id
    assert rows[0]["kind"] == "rust_baseline"
    assert rows[0]["lang"] == "rust"
    assert rows[0]["meta"]["file"] == "src/lib.rs"

    r = client.delete(f"/chunks/{chunk_id}")
    assert r.status_code == 204
    r = client.get(f"/chunks?snapshot_id={snapshot_id}&limit=10&offset=0")
    assert r.status_code == 200
    assert r.json() == []


def test_foreign_key_violation_snapshot():
    client = TestClient(app)
    r = client.post("/snapshots", json={"project_id": 999999, "commit_sha": "abc"})
    assert r.status_code == 409
    assert r.json()["code"] == "foreign_key_violation"


def test_chunk_requires_meta_file():
    client = TestClient(app)

    r = client.post("/projects", json={"name": "p1"})
    project_id = r.json()["project_id"]
    r = client.post("/snapshots", json={"project_id": project_id})
    snapshot_id = r.json()["snapshot_id"]

    r = client.post(
        "/chunks",
        json={
            "snapshot_id": snapshot_id,
            "kind": "rust_baseline",
            "lang": "rust",
            "content": "fn f() {}",
            "meta": {"symbol": "f"},
        },
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


def test_duplicate_chunk_conflict():
    client = TestClient(app)

    project_id = client.post("/projects", json={"name": "p1"}).json()["project_id"]
    snapshot_id = client.post("/snapshots", json={"project_id": project_id}).json()["snapshot_id"]

    payload = {
        "snapshot_id": snapshot_id,
        "kind": "rust_baseline",
        "lang": "rust",
        "content": "fn f() {}",
        "meta": {"file": "src/lib.rs"},
    }

    r = client.post("/chunks", json=payload)
    assert r.status_code == 201
    r = client.post("/chunks", json=payload)
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"


def test_cascade_delete_project_deletes_snapshot_and_chunks():
    client = TestClient(app)

    project_id = client.post("/projects", json={"name": "p1"}).json()["project_id"]
    snapshot_id = client.post("/snapshots", json={"project_id": project_id}).json()["snapshot_id"]
    client.post(
        "/chunks",
        json={
            "snapshot_id": snapshot_id,
            "kind": "rust_baseline",
            "lang": "rust",
            "content": "fn f() {}",
            "meta": {"file": "src/lib.rs"},
        },
    )

    r = client.delete(f"/projects/{project_id}")
    assert r.status_code == 204

    r = client.get(f"/chunks?snapshot_id={snapshot_id}")
    assert r.status_code == 200
    assert r.json() == []
