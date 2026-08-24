"""The red-evidence gate.

A test added by this branch must FAIL against the base source. If it passes
there, it is not evidence for this change: it either characterises behaviour
that already worked, or it sits at the wrong layer.

The only escape hatch is an explicit pin marker in the code, because the author
has to declare that intent somewhere a reviewer can see, not in a commit
message the author wrote for themselves.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import gitops, junit
from .config import Config, build_argv

OK = 0
VIOLATION = 1
UNUSABLE = 2


@dataclass
class Result:
    exit_code: int
    summary: str
    scanned_files: list[str] = field(default_factory=list)
    added_tests: dict[str, list[str]] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    pins: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def added_count(self) -> int:
        return sum(len(v) for v in self.added_tests.values())


def _declared_pin(source: str, name: str, decl: str, marker: str | None) -> bool:
    if not marker:
        return False
    lines = source.splitlines()
    pattern = re.compile(decl)
    for idx, line in enumerate(lines):
        match = pattern.match(line)
        if not match or match.group("name") != name:
            continue
        # Look back over decorators and adjacent comments.
        for back in range(max(0, idx - 6), idx):
            if marker in lines[back]:
                return True
        if marker in line:
            return True
    return False


def run(cfg: Config) -> Result:
    root = cfg.root
    globs = cfg.globs

    all_tests = gitops.discover_test_files(root, globs)
    if not all_tests:
        return Result(
            exit_code=UNUSABLE,
            summary="scanned nothing",
            detail=(
                f"no tracked files matched the test globs {globs}. "
                f"That is not a clean result, it means the gate looked at "
                f"nothing. Fix test_globs in your testgate config."
            ),
        )

    base = gitops.merge_base(root, cfg.base_ref)
    changed = gitops.changed_test_files(root, base, globs)

    added: dict[str, list[str]] = {}
    for path in changed:
        names = gitops.added_test_names(root, base, path, cfg.preset.test_decl_pattern)
        if names:
            added[path] = sorted(names)

    if not added:
        return Result(
            exit_code=OK,
            summary="no added tests",
            scanned_files=all_tests,
            detail=(
                f"scanned {len(all_tests)} test file(s), {len(changed)} changed "
                f"since {base[:9]}, 0 added tests. Nothing to prove."
            ),
        )

    # Separate declared pins before doing any work.
    pins: list[str] = []
    to_check: dict[str, list[str]] = {}
    for path, names in added.items():
        source = (root / path).read_text(encoding="utf-8", errors="replace")
        keep = []
        for name in names:
            if _declared_pin(source, name, cfg.preset.test_decl_pattern, cfg.pin_marker):
                pins.append(f"{path}::{name}")
            else:
                keep.append(name)
        if keep:
            to_check[path] = keep

    if not to_check:
        return Result(
            exit_code=OK,
            summary="all added tests are declared pins",
            scanned_files=all_tests,
            added_tests=added,
            pins=pins,
            detail=f"{len(pins)} declared pin(s), nothing else added.",
        )

    with gitops.worktree_at(root, base) as tree:
        # Overlay the branch's versions of the changed test files onto base source.
        for path in to_check:
            dest = tree / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / path, dest)

        report_dir = Path(tempfile.mkdtemp(prefix="testgate-report-"))
        report = report_dir / "junit.xml"
        argv = build_argv(cfg.preset, list(to_check), report)
        subprocess.run(argv, cwd=str(tree), capture_output=True, text=True)

        try:
            cases = junit.parse(report)
        except junit.JUnitError as exc:
            return Result(
                exit_code=UNUSABLE,
                summary="runner produced no usable report",
                scanned_files=all_tests,
                added_tests=added,
                detail=str(exc),
            )
        finally:
            shutil.rmtree(report_dir, ignore_errors=True)

    outcomes = junit.outcomes_by_name(cases)

    violations: list[str] = []
    unseen: list[str] = []
    for path, names in to_check.items():
        for name in names:
            seen = outcomes.get(name)
            if seen is None:
                unseen.append(f"{path}::{name}")
            elif junit.PASSED in seen and junit.FAILED not in seen:
                violations.append(f"{path}::{name}")

    if violations:
        return Result(
            exit_code=VIOLATION,
            summary=f"{len(violations)} added test(s) passed on the base source",
            scanned_files=all_tests,
            added_tests=added,
            violations=violations,
            pins=pins,
            detail=(
                "These tests cannot have failed for the reason this change "
                "exists. Move them to the layer that holds the defect, or "
                f"declare them pins with {cfg.pin_marker!r}."
            ),
        )

    note = ""
    if unseen:
        note = (
            f" {len(unseen)} added test(s) never appeared in the report "
            f"(likely a collection error on base, which counts as red)."
        )
    return Result(
        exit_code=OK,
        summary=f"{len(cases)} case(s) ran on base, no added test passed",
        scanned_files=all_tests,
        added_tests=added,
        pins=pins,
        detail=f"gate OK: every added test failed against {base[:9]}.{note}",
    )
