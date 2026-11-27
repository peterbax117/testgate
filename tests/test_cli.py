import json
import os
import subprocess
import sys
from pathlib import Path


def _git(root: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


def _repo_without_origin(root: Path) -> None:
    (root / "tests").mkdir()
    (root / "tests" / "test_placeholder.py").write_text(
        "def test_placeholder():\n    assert True\n", encoding="utf-8"
    )
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "testgate@example.invalid")
    _git(root, "config", "user.name", "testgate test")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")


def _run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    project_root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = (
        project_root
        if not env.get("PYTHONPATH")
        else project_root + os.pathsep + env["PYTHONPATH"]
    )
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "testgate.cli",
            "red",
            str(root),
            "--skip-selftest",
            *args,
        ],
        capture_output=True,
        text=True,
        env=env,
    )


def test_red_missing_base_ref_is_unusable_through_cli(tmp_path):
    _repo_without_origin(tmp_path)

    proc = _run_cli(tmp_path)

    assert proc.returncode == 2
    assert "cannot resolve base ref 'origin/main'" in proc.stdout
    assert "git fetch origin main" in proc.stdout
    assert "--base <ref>" in proc.stdout


def test_red_missing_base_ref_json_is_unusable_through_cli(tmp_path):
    _repo_without_origin(tmp_path)

    proc = _run_cli(tmp_path, "--json")

    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["exit_code"] == 2
    assert "cannot resolve base ref 'origin/main'" in payload["detail"]
    assert "git fetch origin main" in payload["detail"]
    assert "--base <ref>" in payload["detail"]
