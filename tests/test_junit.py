import textwrap
from pathlib import Path

import pytest

from testgate import junit


def _write(tmp_path: Path, xml: str) -> Path:
    report = tmp_path / "junit.xml"
    report.write_text(textwrap.dedent(xml).strip(), encoding="utf-8")
    return report


def test_passed_case_has_no_children(tmp_path):
    report = _write(tmp_path, """
        <testsuites><testsuite name="pytest">
          <testcase classname="tests.test_a" name="test_ok" time="0.01"/>
        </testsuite></testsuites>
    """)
    cases = junit.parse(report)
    assert len(cases) == 1
    assert cases[0].outcome == junit.PASSED
    assert cases[0].id == "tests.test_a::test_ok"


def test_failure_and_error_both_count_as_failed(tmp_path):
    report = _write(tmp_path, """
        <testsuites><testsuite name="pytest">
          <testcase classname="c" name="test_f"><failure message="x"/></testcase>
          <testcase classname="c" name="test_e"><error message="y"/></testcase>
        </testsuite></testsuites>
    """)
    outcomes = {c.name: c.outcome for c in junit.parse(report)}
    assert outcomes == {"test_f": junit.FAILED, "test_e": junit.FAILED}


def test_skipped_is_not_passed(tmp_path):
    report = _write(tmp_path, """
        <testsuites><testsuite name="pytest">
          <testcase classname="c" name="test_s"><skipped/></testcase>
        </testsuite></testsuites>
    """)
    assert junit.parse(report)[0].outcome == junit.SKIPPED


def test_missing_report_is_an_error_not_an_empty_pass(tmp_path):
    with pytest.raises(junit.JUnitError):
        junit.parse(tmp_path / "nope.xml")


def test_malformed_xml_is_an_error(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text("<testsuites>", encoding="utf-8")
    with pytest.raises(junit.JUnitError):
        junit.parse(report)


def test_outcomes_by_name_collects_duplicates(tmp_path):
    report = _write(tmp_path, """
        <testsuites><testsuite name="pytest">
          <testcase classname="a" name="test_dup"/>
          <testcase classname="b" name="test_dup"><failure/></testcase>
        </testsuite></testsuites>
    """)
    by_name = junit.outcomes_by_name(junit.parse(report))
    assert by_name["test_dup"] == {junit.PASSED, junit.FAILED}
