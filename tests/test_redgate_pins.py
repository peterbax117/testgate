"""Pin detection, the red gate's only escape hatch.

If this is wrong in either direction the gate is unusable: too strict and
legitimate characterisation tests are blocked, too loose and anyone can opt out
of the gate silently.
"""
from testgate import redgate
from testgate.config import PRESETS

DECL = PRESETS["pytest"].test_decl_pattern
MARKER = "pytest.mark.pin"


def test_decorator_above_the_declaration_is_a_pin():
    source = "@pytest.mark.pin\ndef test_thing():\n    assert True\n"
    assert redgate._declared_pin(source, "test_thing", DECL, MARKER)


def test_marker_on_the_declaration_line_is_a_pin():
    """Found by the mutation gate: this branch had no test."""
    source = "def test_thing():  # pytest.mark.pin\n    assert True\n"
    assert redgate._declared_pin(source, "test_thing", DECL, MARKER)


def test_unmarked_test_is_not_a_pin():
    source = "def test_thing():\n    assert True\n"
    assert not redgate._declared_pin(source, "test_thing", DECL, MARKER)


def test_a_pin_on_a_different_test_does_not_leak():
    source = (
        "@pytest.mark.pin\n"
        "def test_pinned():\n"
        "    assert True\n"
        "\n\n\n\n\n\n\n"
        "def test_other():\n"
        "    assert True\n"
    )
    assert redgate._declared_pin(source, "test_pinned", DECL, MARKER)
    assert not redgate._declared_pin(source, "test_other", DECL, MARKER)


def test_no_marker_configured_means_nothing_is_a_pin():
    source = "@pytest.mark.pin\ndef test_thing():\n    assert True\n"
    assert not redgate._declared_pin(source, "test_thing", DECL, None)


def test_marker_far_above_is_not_a_pin():
    source = (
        "# pytest.mark.pin appears here in a comment\n"
        + "\n" * 12
        + "def test_thing():\n    assert True\n"
    )
    assert not redgate._declared_pin(source, "test_thing", DECL, MARKER)
