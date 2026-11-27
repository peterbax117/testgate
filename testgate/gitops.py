"""Git operations for the red-evidence gate.

All comparisons run from the merge-base to the **working tree**, not to HEAD,
so uncommitted work is covered too. A gate that only inspects committed state
is trivially bypassed by not committing yet.
"""
from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a git-style glob (supporting **) into a regex."""
    out = ["^"]
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def matches_any(path: str, patterns: list[str]) -> bool:
    norm = path.replace("\\", "/")
    return any(glob_to_regex(p).match(norm) for p in patterns)


def merge_base(root: Path, base_ref: str) -> str:
    try:
        git(root, "rev-parse", "--verify", "--quiet", base_ref)
    except GitError as exc:
        fetch_hint = ""
        remote, separator, branch = base_ref.partition("/")
        if separator and remote in git(root, "remote").splitlines():
            fetch_hint = f"Run `git fetch {remote} {branch}`, or "
        raise GitError(
            f"cannot resolve base ref {base_ref!r}. "
            f"{fetch_hint}pass `--base <ref>` for a ref that exists."
        ) from exc
    try:
        return git(root, "merge-base", base_ref, "HEAD").strip()
    except GitError as exc:
        raise GitError(
            f"base ref {base_ref!r} has no common ancestor with HEAD. "
            "Choose a ref from this repository's history with `--base <ref>`."
        ) from exc


def discover_test_files(root: Path, globs: list[str]) -> list[str]:
    """Every tracked file matching the test globs, regardless of change status."""
    tracked = git(root, "ls-files").splitlines()
    return sorted(p for p in tracked if matches_any(p, globs))


def changed_test_files(root: Path, base: str, globs: list[str]) -> list[str]:
    out = git(root, "diff", "--name-status", base)
    files: list[str] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0], parts[-1]
        if status.startswith("D"):
            continue
        if matches_any(path, globs):
            files.append(path)
    return sorted(set(files))


def added_test_names(root: Path, base: str, path: str, decl: str) -> set[str]:
    """Test names whose declaration line is ADDED relative to base."""
    pattern = re.compile(decl)
    out = git(root, "diff", "-U0", base, "--", path)
    names: set[str] = set()
    for line in out.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        match = pattern.match(line[1:])
        if match:
            names.add(match.group("name"))
    return names


@contextlib.contextmanager
def worktree_at(root: Path, sha: str):
    """A detached worktree pinned at sha, removed on exit."""
    tmp = Path(tempfile.mkdtemp(prefix="testgate-base-"))
    target = tmp / "tree"
    try:
        git(root, "worktree", "add", "--detach", str(target), sha)
        yield target
    finally:
        with contextlib.suppress(Exception):
            git(root, "worktree", "remove", "--force", str(target))
        with contextlib.suppress(Exception):
            git(root, "worktree", "prune")
        shutil.rmtree(tmp, ignore_errors=True)
