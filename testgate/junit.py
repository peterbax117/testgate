"""JUnit XML parsing.

Every runner emits JUnit XML and testgate parses only that. Human-readable
stdout is never parsed: a repo's own verbosity settings must not be able to
change what the gate concludes.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"


@dataclass(frozen=True)
class Case:
    classname: str
    name: str
    outcome: str

    @property
    def id(self) -> str:
        return f"{self.classname}::{self.name}" if self.classname else self.name


class JUnitError(RuntimeError):
    pass


def _outcome(testcase: ET.Element) -> str:
    for child in testcase:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag in ("failure", "error"):
            return FAILED
        if tag == "skipped":
            return SKIPPED
    return PASSED


def parse(report: Path) -> list[Case]:
    report = Path(report)
    if not report.is_file():
        raise JUnitError(
            f"no JUnit report at {report}. The runner did not produce one, so "
            f"there is no evidence to read."
        )
    try:
        tree = ET.parse(report)
    except ET.ParseError as exc:
        raise JUnitError(f"JUnit report at {report} is not valid XML: {exc}") from exc

    cases: list[Case] = []
    for testcase in tree.getroot().iter():
        if testcase.tag.rsplit("}", 1)[-1] != "testcase":
            continue
        cases.append(
            Case(
                classname=testcase.get("classname", "") or testcase.get("file", ""),
                name=testcase.get("name", ""),
                outcome=_outcome(testcase),
            )
        )
    return cases


def outcomes_by_name(cases: list[Case]) -> dict[str, set[str]]:
    """Map bare test name to the set of outcomes seen under that name."""
    out: dict[str, set[str]] = {}
    for case in cases:
        out.setdefault(case.name, set()).add(case.outcome)
    return out
