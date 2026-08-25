"""Positive control.

testgate refuses to report a clean result unless it has demonstrated, in the
same run, that it is capable of reporting a dirty one. A checker with no
known-bad input to catch cannot be told apart from a checker that always says
yes.

Each case builds a real throwaway git repository, runs the real gate against
it, and asserts the verdict its name declares. If any case disagrees, every
other testgate command is untrustworthy and refuses to pass.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import config, redgate

CONFTEST = ""  # empty file at root, so pytest puts the repo root on sys.path
TESTGATE_TOML = """[testgate]
runner = "pytest"
test_globs = ["tests/**/test_*.py"]
base_ref = "main"
"""
NO_MATCH_TOML = """[testgate]
runner = "pytest"
test_globs = ["no/such/place/**/test_*.py"]
base_ref = "main"
"""

CORRECT_SRC = "def add(a, b):\n    return a + b\n"
BUGGY_SRC = "def add(a, b):\n    return a - b\n"

# Passes against the base source, so it proves nothing about this change.
BAD_TEST = """import calc


def test_add_that_already_worked():
    assert calc.add(1, 2) == 3
"""

# Fails against the buggy base source, so it is real evidence.
GOOD_TEST = """import calc


def test_add_is_fixed():
    assert calc.add(1, 2) == 3
"""

PINNED_TEST = """import pytest

import calc


@pytest.mark.pin
def test_add_that_already_worked():
    assert calc.add(1, 2) == 3
"""

# --- mutation-gate fixtures ------------------------------------------------

MUT_SRC = """def add(a, b):
    return a + b


def is_positive(n):
    if n > 0:
        return True
    return False
"""

# Exercises the boundary, so a > to >= mutation is caught.
REAL_TEST = """import calc


def test_add():
    assert calc.add(2, 3) == 5


def test_is_positive_true():
    assert calc.is_positive(5) is True


def test_is_positive_false():
    assert calc.is_positive(-1) is False


def test_is_positive_at_the_boundary():
    assert calc.is_positive(0) is False
"""

# Green, and completely worthless. Exactly the failure mode being guarded.
VACUOUS_TEST = """def test_it_works():
    assert True


def test_also_works():
    assert 1 == 1
"""

FAILING_TEST = """import calc


def test_that_is_already_red():
    assert calc.add(1, 1) == 99
"""

MUT_TOML = """[testgate]
runner = "pytest"
test_globs = ["tests/**/test_*.py"]
base_ref = "main"
max_mutants = 3
mutation_threshold = 0.5
"""

MUT_NOSRC_TOML = """[testgate]
runner = "pytest"
test_globs = ["tests/**/test_*.py"]
src_globs = ["nowhere/**/*.py"]
base_ref = "main"
max_mutants = 3
mutation_threshold = 0.5
"""


@dataclass
class Case:
    name: str
    expected_exit: int
    actual_exit: int | None = None
    summary: str = ""

    @property
    def ok(self) -> bool:
        return self.actual_exit == self.expected_exit


def _git(root: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")


def _build_repo(root: Path, base_src: str, head_src: str,
                test_body: str, toml: str) -> None:
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (root / "testgate.toml").write_text(toml, encoding="utf-8")
    (root / "calc.py").write_text(base_src, encoding="utf-8")
    (root / "tests" / "test_placeholder.py").write_text(
        "def test_placeholder():\n    assert True\n", encoding="utf-8"
    )

    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "selftest@testgate.local")
    _git(root, "config", "user.name", "testgate selftest")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")

    # The branch: fix the source if it was buggy, and add the new test.
    _git(root, "checkout", "-q", "-b", "feature")
    (root / "calc.py").write_text(head_src, encoding="utf-8")
    (root / "tests" / "test_added.py").write_text(test_body, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "feature")


def _run_case(name: str, base_src: str, head_src: str, test_body: str,
              toml: str, expected: int) -> Case:
    case = Case(name=name, expected_exit=expected)
    tmp = Path(tempfile.mkdtemp(prefix=f"testgate-selftest-{name}-"))
    repo = tmp / "repo"
    repo.mkdir()
    try:
        _build_repo(repo, base_src, head_src, test_body, toml)
        cfg = config.load(repo)
        result = redgate.run(cfg)
        case.actual_exit = result.exit_code
        case.summary = result.summary
    except Exception as exc:  # a crash is also a failed positive control
        case.actual_exit = -1
        case.summary = f"selftest case raised: {exc}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return case


def _build_flat_repo(root: Path, src: str, test_body: str, toml: str) -> None:
    """A single-commit repo: the mutation gate needs tracked files, not a diff."""
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (root / "testgate.toml").write_text(toml, encoding="utf-8")
    (root / "calc.py").write_text(src, encoding="utf-8")
    (root / "tests" / "test_suite.py").write_text(test_body, encoding="utf-8")

    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "selftest@testgate.local")
    _git(root, "config", "user.name", "testgate selftest")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")


def _run_mutation_case(name: str, src: str, test_body: str, toml: str,
                       expected: int) -> Case:
    from . import mutate

    case = Case(name=name, expected_exit=expected)
    tmp = Path(tempfile.mkdtemp(prefix=f"testgate-selftest-{name}-"))
    repo = tmp / "repo"
    repo.mkdir()
    try:
        _build_flat_repo(repo, src, test_body, toml)
        result = mutate.run(config.load(repo))
        case.actual_exit = result.exit_code
        case.summary = result.summary
    except Exception as exc:
        case.actual_exit = -1
        case.summary = f"selftest case raised: {exc}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return case


def run() -> tuple[bool, list[Case]]:
    cases = [
        # The gate MUST catch a test that passes against base source.
        _run_case("BAD_passes_on_base", CORRECT_SRC, CORRECT_SRC,
                  BAD_TEST, TESTGATE_TOML, redgate.VIOLATION),
        # The gate MUST NOT flag a test that genuinely fails against base.
        _run_case("GOOD_fails_on_base", BUGGY_SRC, CORRECT_SRC,
                  GOOD_TEST, TESTGATE_TOML, redgate.OK),
        # A declared pin is the one legitimate escape hatch.
        _run_case("GOOD_declared_pin", CORRECT_SRC, CORRECT_SRC,
                  PINNED_TEST, TESTGATE_TOML, redgate.OK),
        # Matching no files must be "unusable", never a clean pass.
        _run_case("BAD_scans_nothing", CORRECT_SRC, CORRECT_SRC,
                  GOOD_TEST, NO_MATCH_TOML, redgate.UNUSABLE),
    ]
    return all(c.ok for c in cases), cases


def run_mutation() -> tuple[bool, list[Case]]:
    from . import mutate

    cases = [
        # Green but worthless tests must fail the mutation gate.
        _run_mutation_case("BAD_vacuous_tests_kill_nothing", MUT_SRC,
                           VACUOUS_TEST, MUT_TOML, mutate.VIOLATION),
        # Tests that exercise behaviour, including the boundary, must pass.
        _run_mutation_case("GOOD_real_tests_kill_mutants", MUT_SRC,
                           REAL_TEST, MUT_TOML, mutate.OK),
        # A red baseline makes killed-vs-survived meaningless.
        _run_mutation_case("BAD_baseline_not_green", MUT_SRC,
                           FAILING_TEST, MUT_TOML, mutate.UNUSABLE),
        # Mutating nothing is not a pass.
        _run_mutation_case("BAD_mutates_nothing", MUT_SRC,
                           REAL_TEST, MUT_NOSRC_TOML, mutate.UNUSABLE),
    ]
    return all(c.ok for c in cases), cases


def run_all() -> tuple[bool, list[Case]]:
    red_ok, red_cases = run()
    mut_ok, mut_cases = run_mutation()
    return red_ok and mut_ok, red_cases + mut_cases
