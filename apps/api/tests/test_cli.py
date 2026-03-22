import json
import os

from typer.testing import CliRunner

from cli import app


def test_cli_create_and_list_chunks(database_url: str):
    runner = CliRunner()

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url

    result = runner.invoke(app, ["create_project", "p1", "--desc", "d"], env=env)
    assert result.exit_code == 0
    project_id = json.loads(result.stdout)["project_id"]

    result = runner.invoke(app, ["create_snapshot", str(project_id), "--commit_sha", "abc", "--branch", "main"], env=env)
    assert result.exit_code == 0
    snapshot_id = json.loads(result.stdout)["snapshot_id"]

    result = runner.invoke(
        app,
        [
            "insert_chunk",
            str(snapshot_id),
            "--kind",
            "rust_baseline",
            "--lang",
            "rust",
            "--content",
            "fn f() {}",
            "--meta",
            '{"file":"src/lib.rs"}',
        ],
        env=env,
    )
    assert result.exit_code == 0
    chunk_id = json.loads(result.stdout)["chunk_id"]

    result = runner.invoke(app, ["list_chunks", str(snapshot_id), "--limit", "10", "--offset", "0"], env=env)
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert rows[0]["chunk_id"] == chunk_id


def test_cli_foreign_key_violation(database_url: str):
    runner = CliRunner()
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url

    result = runner.invoke(app, ["create_snapshot", "999999", "--commit_sha", "abc"], env=env)
    assert result.exit_code != 0
    err = json.loads(result.stderr)
    assert err["code"] == "foreign_key_violation"
