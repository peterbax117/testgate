"""The mutation gate.

Coverage says a line ran. This says the line *mattered*: break one behaviour,
and require some test to notice. A mutant that survives names the exact
behaviour nothing defends.

Determinism is the whole point, so:
  - mutants are generated in a fixed order and selected by stride, never at
    random, so the same tree always yields the same mutant set;
  - a broken baseline aborts, because killed/survived means nothing if the
    suite was already red;
  - generating zero mutants is an error, not a clean pass;
  - a timeout is recorded as its own outcome and never counted as a kill.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import gitops, junit
from .config import Config, build_argv, build_check_argv

OK = 0
VIOLATION = 1
UNUSABLE = 2

KILLED = "killed"
SURVIVED = "survived"
INVALID = "invalid"
TIMEOUT = "timeout"

_COMMENT = re.compile(r"^\s*#")
_TRIPLE = ('"""', "'''")


def mutable_lines(text: str) -> list[tuple[int, str]]:
    """Lines worth mutating: not blank, not a comment, not inside a docstring.

    Mutating prose inside a triple-quoted block produces a mutant no test can
    ever kill, which shows up as a false survivor and erodes trust in the
    score. Found by running this gate against its own source.
    """
    out: list[tuple[int, str]] = []
    inside: str | None = None
    for line_no, line in enumerate(text.splitlines(), start=1):
        if inside is not None:
            if inside in line:
                inside = None
            continue
        stripped = line.strip()
        if not stripped or _COMMENT.match(line):
            continue
        opened = None
        for quote in _TRIPLE:
            first = line.find(quote)
            if first != -1 and quote not in line[first + 3:]:
                opened = quote
                break
        if opened is not None:
            inside = opened
            continue
        if any(line.count(q) >= 2 for q in _TRIPLE):
            continue  # a whole docstring on one line
        out.append((line_no, line))
    return out


@dataclass(frozen=True)
class Mutant:
    path: str
    line_no: int
    operator: str
    before: str
    after: str

    @property
    def id(self) -> str:
        return f"{self.path}:{self.line_no}:{self.operator}"


@dataclass
class MutantResult:
    mutant: Mutant
    outcome: str


@dataclass
class Result:
    exit_code: int
    summary: str
    detail: str = ""
    scanned_sources: list[str] = field(default_factory=list)
    generated: int = 0
    results: list[MutantResult] = field(default_factory=list)

    def _count(self, outcome: str) -> int:
        return sum(1 for r in self.results if r.outcome == outcome)

    @property
    def killed(self) -> int:
        return self._count(KILLED)

    @property
    def survived(self) -> list[MutantResult]:
        return [r for r in self.results if r.outcome == SURVIVED]

    @property
    def scored(self) -> int:
        return self.killed + len(self.survived)

    @property
    def score(self) -> float:
        return self.killed / self.scored if self.scored else 0.0


def generate(root: Path, sources: list[str], operators, cap: int) -> list[Mutant]:
    """Every candidate mutation, in a fixed order, then evenly sampled.

    Sampling by stride rather than by truncation keeps coverage spread across
    the whole tree instead of exhausting the first file, and stays
    deterministic.
    """
    candidates: list[Mutant] = []
    for path in sorted(sources):
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_no, line in mutable_lines(text):
            for op in operators:
                mutated, count = re.subn(op.pattern, op.replacement, line, count=1)
                if count and mutated != line:
                    candidates.append(
                        Mutant(path, line_no, op.name, line, mutated)
                    )
    if cap <= 0 or len(candidates) <= cap:
        return candidates
    stride = len(candidates) / cap
    return [candidates[int(i * stride)] for i in range(cap)]


def _copy_tree(root: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="testgate-mutate-"))
    dest = tmp / "tree"
    shutil.copytree(
        root, dest,
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.egg-info", ".pytest_cache",
            ".venv", "venv", "node_modules",
        ),
    )
    return dest


def _apply(tree: Path, mutant: Mutant) -> None:
    target = tree / mutant.path
    lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    idx = mutant.line_no - 1
    ending = "\n" if lines[idx].endswith("\n") else ""
    lines[idx] = mutant.after + ending
    target.write_text("".join(lines), encoding="utf-8")


def _syntax_ok(cfg: Config, tree: Path, mutant: Mutant) -> bool:
    argv = build_check_argv(cfg.preset, tree / mutant.path)
    if argv is None:
        return True
    proc = subprocess.run(argv, cwd=str(tree), capture_output=True, text=True)
    return proc.returncode == 0


def _run_tests(cfg: Config, tree: Path, tests: list[str]) -> tuple[str, list]:
    report_dir = Path(tempfile.mkdtemp(prefix="testgate-mreport-"))
    report = report_dir / "junit.xml"
    argv = build_argv(cfg.preset, tests, report)
    try:
        subprocess.run(
            argv, cwd=str(tree), capture_output=True, text=True,
            timeout=cfg.timeout,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(report_dir, ignore_errors=True)
        return TIMEOUT, []
    try:
        cases = junit.parse(report)
    except junit.JUnitError:
        return INVALID, []
    finally:
        shutil.rmtree(report_dir, ignore_errors=True)
    return OK_MARKER, cases


OK_MARKER = "ran"


def _any_failure(cases) -> bool:
    return any(c.outcome == junit.FAILED for c in cases)


def run(cfg: Config) -> Result:
    root = cfg.root

    tests = gitops.discover_test_files(root, cfg.globs)
    if not tests:
        return Result(
            exit_code=UNUSABLE,
            summary="scanned nothing",
            detail=(
                f"no tracked files matched the test globs {cfg.globs}. "
                f"Nothing could have killed a mutant."
            ),
        )

    all_src = gitops.discover_test_files(root, cfg.source_globs)
    sources = [p for p in all_src if not gitops.matches_any(p, cfg.globs)]
    if not sources:
        return Result(
            exit_code=UNUSABLE,
            summary="no source files to mutate",
            detail=(
                f"source globs {cfg.source_globs} matched nothing outside the "
                f"test globs. That is a configuration problem, not a pass."
            ),
        )

    tree = _copy_tree(root)
    try:
        status, cases = _run_tests(cfg, tree, tests)
        if status == TIMEOUT:
            return Result(
                exit_code=UNUSABLE, summary="baseline timed out",
                scanned_sources=sources,
                detail=f"the suite exceeded {cfg.timeout}s before any mutation.",
            )
        if status == INVALID or not cases:
            return Result(
                exit_code=UNUSABLE, summary="baseline produced no usable report",
                scanned_sources=sources,
                detail="the runner did not emit parseable JUnit XML.",
            )
        if _any_failure(cases):
            return Result(
                exit_code=UNUSABLE, summary="baseline is not green",
                scanned_sources=sources,
                detail=(
                    "the suite fails before any mutation, so killed-versus-"
                    "survived would be meaningless. Fix the suite first."
                ),
            )

        mutants = generate(root, sources, cfg.preset.operators, cfg.max_mutants)
        if not mutants:
            return Result(
                exit_code=UNUSABLE, summary="mutated nothing",
                scanned_sources=sources,
                detail=(
                    "no operator matched any source line. A run that changed "
                    "nothing cannot be evidence that tests are meaningful."
                ),
            )

        results: list[MutantResult] = []
        for mutant in mutants:
            original = (tree / mutant.path).read_text(encoding="utf-8")
            _apply(tree, mutant)
            try:
                if not _syntax_ok(cfg, tree, mutant):
                    results.append(MutantResult(mutant, INVALID))
                    continue
                status, cases = _run_tests(cfg, tree, tests)
                if status == TIMEOUT:
                    results.append(MutantResult(mutant, TIMEOUT))
                elif status == INVALID:
                    results.append(MutantResult(mutant, INVALID))
                else:
                    results.append(MutantResult(
                        mutant, KILLED if _any_failure(cases) else SURVIVED
                    ))
            finally:
                (tree / mutant.path).write_text(original, encoding="utf-8")
    finally:
        shutil.rmtree(tree.parent, ignore_errors=True)

    result = Result(
        exit_code=OK, summary="", scanned_sources=sources,
        generated=len(mutants), results=results,
    )

    if result.scored == 0:
        result.exit_code = UNUSABLE
        result.summary = "no mutant was scorable"
        result.detail = (
            f"{len(mutants)} mutant(s) generated but every one was invalid or "
            f"timed out, so nothing was measured."
        )
        return result

    result.summary = (
        f"mutations: {result.scored}, killed: {result.killed}, "
        f"survived: {len(result.survived)} "
        f"(score {result.score:.0%}, threshold {cfg.mutation_threshold:.0%})"
    )
    if result.score < cfg.mutation_threshold:
        result.exit_code = VIOLATION
        result.detail = (
            "each surviving mutant names a behaviour no test defends. "
            "Add a test aimed at it, or lower mutation_threshold deliberately."
        )
    else:
        result.detail = "the suite notices when the implementation changes."
    return result
