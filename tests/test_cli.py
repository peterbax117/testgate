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


def _run_cli(
    root: Path, command: str = "red", *args: str
) -> subprocess.CompletedProcess[str]:
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
            command,
            str(root),
            *args,
        ],
        capture_output=True,
        text=True,
        env=env,
    )


def test_red_missing_base_ref_is_unusable_through_cli(tmp_path):
    _repo_without_origin(tmp_path)

    proc = _run_cli(tmp_path, "red", "--skip-selftest")

    assert proc.returncode == 2
    assert "cannot resolve base ref 'origin/main'" in proc.stdout
    assert "git fetch origin main" not in proc.stdout
    assert "--base <ref>" in proc.stdout


def test_red_missing_base_ref_json_is_unusable_through_cli(tmp_path):
    _repo_without_origin(tmp_path)

    proc = _run_cli(tmp_path, "red", "--skip-selftest", "--json")

    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["exit_code"] == 2
    assert "cannot resolve base ref 'origin/main'" in payload["detail"]
    assert "git fetch origin main" not in payload["detail"]
    assert "--base <ref>" in payload["detail"]


def test_red_not_a_git_repo_is_unusable_through_cli(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_placeholder.py").write_text(
        "def test_placeholder():\n    assert True\n", encoding="utf-8"
    )

    proc = _run_cli(tmp_path, "red", "--skip-selftest")

    assert proc.returncode == 2
    assert "not a git repository" in proc.stdout
    assert "Traceback" not in proc.stdout


def test_red_not_a_git_repo_json_is_unusable_through_cli(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_placeholder.py").write_text(
        "def test_placeholder():\n    assert True\n", encoding="utf-8"
    )

    proc = _run_cli(tmp_path, "red", "--skip-selftest", "--json")

    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["exit_code"] == 2
    assert "not a git repository" in payload["detail"]


def test_doctor_not_a_git_repo_is_unusable_through_cli(tmp_path):
    (tmp_path / "tests").mkdir()

    proc = _run_cli(tmp_path, "doctor")

    assert proc.returncode == 2
    assert "not a git repository" in proc.stdout
    assert "Traceback" not in proc.stdout


def test_mutate_not_a_git_repo_is_unusable_through_cli(tmp_path):
    (tmp_path / "tests").mkdir()

    proc = _run_cli(tmp_path, "mutate", "--skip-selftest")

    assert proc.returncode == 2
    assert "not a git repository" in proc.stdout
    assert "Traceback" not in proc.stdout


def test_mutate_not_a_git_repo_json_is_unusable_through_cli(tmp_path):
    (tmp_path / "tests").mkdir()

    proc = _run_cli(tmp_path, "mutate", "--skip-selftest", "--json")

    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["exit_code"] == 2
    assert "not a git repository" in payload["detail"]


def test_missing_ref_suggests_fetch_only_for_existing_remote(tmp_path):
    _repo_without_origin(tmp_path)
    _git(tmp_path, "remote", "add", "upstream", "https://example.invalid/repo.git")

    proc = _run_cli(
        tmp_path, "red", "--skip-selftest", "--base", "upstream/main"
    )

    assert proc.returncode == 2
    assert "git fetch upstream main" in proc.stdout
    assert "--base <ref>" in proc.stdout


def test_slash_in_local_ref_does_not_suggest_fetch(tmp_path):
    _repo_without_origin(tmp_path)

    proc = _run_cli(
        tmp_path, "red", "--skip-selftest", "--base", "release/1.0"
    )

    assert proc.returncode == 2
    assert "git fetch release 1.0" not in proc.stdout
    assert "--base <ref>" in proc.stdout


def test_unrelated_history_is_unusable_without_fetch_hint(tmp_path):
    _repo_without_origin(tmp_path)
    _git(tmp_path, "checkout", "--orphan", "unrelated")
    (tmp_path / "README.txt").write_text("unrelated\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(
        tmp_path, "-c", "user.email=testgate@example.invalid", "-c",
        "user.name=testgate test", "commit", "-q", "-m", "unrelated"
    )

    proc = _run_cli(
        tmp_path, "red", "--skip-selftest", "--base", "main"
    )

    assert proc.returncode == 2
    assert "no common ancestor with HEAD" in proc.stdout
    assert "git fetch" not in proc.stdout
    assert "failed: )" not in proc.stdout
