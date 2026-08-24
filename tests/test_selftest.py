"""The selftest is the load-bearing part, so it gets tested too.

If these ever pass while the gate is broken, testgate is decorative.
"""
from testgate import redgate, selftest


def test_selftest_passes_on_a_healthy_gate():
    passed, cases = selftest.run()
    failed = [c.name for c in cases if not c.ok]
    assert passed, f"selftest cases disagreed: {failed}"


def test_selftest_declares_both_verdicts():
    """A suite of only-GOOD cases would make the positive control vacuous."""
    _, cases = selftest.run()
    names = [c.name for c in cases]
    assert any(n.startswith("BAD_") for n in names)
    assert any(n.startswith("GOOD_") for n in names)


def test_selftest_expects_a_violation_somewhere():
    """At least one case must require the gate to actually fail something."""
    _, cases = selftest.run()
    assert any(c.expected_exit == redgate.VIOLATION for c in cases)


def test_selftest_expects_an_unusable_verdict():
    """Scanning nothing must be distinguishable from scanning cleanly."""
    _, cases = selftest.run()
    assert any(c.expected_exit == redgate.UNUSABLE for c in cases)


def test_exit_codes_are_distinct():
    assert len({redgate.OK, redgate.VIOLATION, redgate.UNUSABLE}) == 3
    assert redgate.OK == 0
