"""testgate command line.

Exit codes are the contract:
  0  gate passed
  1  gate found a violation
  2  gate could not run, or could not prove itself. NEVER treat as a pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, config, mutate, redgate, selftest


def _print_selftest(cases) -> None:
    for case in cases:
        mark = "ok  " if case.ok else "FAIL"
        print(f"  [{mark}] {case.name}: expected exit {case.expected_exit}, "
              f"got {case.actual_exit} ({case.summary})")


def cmd_selftest(args) -> int:
    if args.red_only:
        passed, cases = selftest.run()
    elif args.mutation_only:
        passed, cases = selftest.run_mutation()
    else:
        passed, cases = selftest.run_all()
    print("testgate selftest (positive control)")
    _print_selftest(cases)
    if passed:
        print(f"selftest OK: {len(cases)} case(s), the gates provably bite.")
        return 0
    print("selftest FAILED. testgate cannot be trusted in this environment, "
          "so no result it produces is evidence.")
    return 2


def _guard_selftest(runner, skip: bool) -> int | None:
    """A clean result only means something if the gate proved it can fail."""
    if skip:
        return None
    passed, cases = runner()
    if passed:
        return None
    print("refusing to run: selftest failed, so a clean result would "
          "be meaningless.")
    _print_selftest(cases)
    return 2


def cmd_red(args) -> int:
    guard = _guard_selftest(selftest.run, args.skip_selftest)
    if guard is not None:
        return guard

    try:
        cfg = config.load(Path(args.path))
    except config.ConfigError as exc:
        print(f"config error: {exc}")
        return 2
    if args.base:
        cfg.base_ref = args.base

    result = redgate.run(cfg)

    if args.json:
        print(json.dumps({
            "exit_code": result.exit_code,
            "summary": result.summary,
            "scanned_files": len(result.scanned_files),
            "added_tests": result.added_tests,
            "violations": result.violations,
            "pins": result.pins,
            "detail": result.detail,
        }, indent=2))
        return result.exit_code

    print(f"testgate red-evidence gate  (runner: {cfg.preset.name}, "
          f"base: {cfg.base_ref})")
    print(f"  scanned      : {len(result.scanned_files)} test file(s)")
    print(f"  added tests  : {result.added_count}")
    if result.pins:
        print(f"  declared pins: {len(result.pins)}")
        for pin in result.pins:
            print(f"      pin {pin}")
    if result.violations:
        print(f"  VIOLATIONS   : {len(result.violations)}")
        for bad in result.violations:
            print(f"      passed on base: {bad}")
    print(f"  verdict      : {result.summary}")
    if result.detail:
        print(f"  {result.detail}")
    return result.exit_code


def cmd_mutate(args) -> int:
    guard = _guard_selftest(selftest.run_mutation, args.skip_selftest)
    if guard is not None:
        return guard

    try:
        cfg = config.load(Path(args.path))
    except config.ConfigError as exc:
        print(f"config error: {exc}")
        return 2
    if args.max_mutants:
        cfg.max_mutants = args.max_mutants
    if args.threshold is not None:
        cfg.mutation_threshold = args.threshold

    result = mutate.run(cfg)

    if args.json:
        print(json.dumps({
            "exit_code": result.exit_code,
            "summary": result.summary,
            "scanned_sources": len(result.scanned_sources),
            "generated": result.generated,
            "killed": result.killed,
            "survived": [
                {"id": r.mutant.id, "operator": r.mutant.operator,
                 "path": r.mutant.path, "line": r.mutant.line_no,
                 "before": r.mutant.before.strip(),
                 "after": r.mutant.after.strip()}
                for r in result.survived
            ],
            "score": round(result.score, 4),
            "threshold": cfg.mutation_threshold,
            "detail": result.detail,
        }, indent=2))
        return result.exit_code

    print(f"testgate mutation gate  (runner: {cfg.preset.name})")
    print(f"  source files : {len(result.scanned_sources)}")
    print(f"  generated    : {result.generated}")
    if result.survived:
        print(f"  SURVIVED     : {len(result.survived)}")
        for res in result.survived:
            print(f"      {res.mutant.id}")
            print(f"        - {res.mutant.before.strip()}")
            print(f"        + {res.mutant.after.strip()}")
    print(f"  verdict      : {result.summary}")
    if result.detail:
        print(f"  {result.detail}")
    return result.exit_code


def cmd_doctor(args) -> int:
    try:
        cfg = config.load(Path(args.path))
    except config.ConfigError as exc:
        print(f"config error: {exc}")
        return 2
    from . import gitops
    files = gitops.discover_test_files(cfg.root, cfg.globs)
    print(f"root       : {cfg.root}")
    print(f"runner     : {cfg.preset.name}")
    print(f"globs      : {cfg.globs}")
    print(f"base_ref   : {cfg.base_ref}")
    print(f"pin marker : {cfg.pin_marker}")
    print(f"test files : {len(files)}")
    for path in files[:10]:
        print(f"    {path}")
    if len(files) > 10:
        print(f"    ... and {len(files) - 10} more")
    if not files:
        print("no test files matched. That is a configuration problem, and "
              "the gate will report 'scanned nothing' rather than passing.")
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="testgate",
        description="Deterministic test-quality gates.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_self = sub.add_parser("selftest", help="prove the gates can fail")
    p_self.add_argument("--red-only", action="store_true")
    p_self.add_argument("--mutation-only", action="store_true")
    p_self.set_defaults(func=cmd_selftest)

    p_mut = sub.add_parser("mutate", help="mutation gate")
    p_mut.add_argument("path", nargs="?", default=".")
    p_mut.add_argument("--max-mutants", type=int)
    p_mut.add_argument("--threshold", type=float)
    p_mut.add_argument("--json", action="store_true")
    p_mut.add_argument("--skip-selftest", action="store_true",
                       help="not recommended: results are no longer evidence")
    p_mut.set_defaults(func=cmd_mutate)

    p_red = sub.add_parser("red", help="red-evidence gate")
    p_red.add_argument("path", nargs="?", default=".")
    p_red.add_argument("--base", help="base ref (default: config, or origin/main)")
    p_red.add_argument("--json", action="store_true")
    p_red.add_argument("--skip-selftest", action="store_true",
                       help="not recommended: results are no longer evidence")
    p_red.set_defaults(func=cmd_red)

    p_doc = sub.add_parser("doctor", help="show what the gate would scan")
    p_doc.add_argument("path", nargs="?", default=".")
    p_doc.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
