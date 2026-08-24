import pytest

from testgate import gitops


@pytest.mark.parametrize("pattern,path,expected", [
    ("tests/**/test_*.py", "tests/test_a.py", True),
    ("tests/**/test_*.py", "tests/unit/test_a.py", True),
    ("tests/**/test_*.py", "tests/unit/deep/test_a.py", True),
    ("tests/**/test_*.py", "tests/helper.py", False),
    ("tests/**/test_*.py", "src/test_a.py", False),
    ("**/*.test.ts", "web/app.test.ts", True),
    ("**/*.test.ts", "app.test.ts", True),
    ("**/*.test.ts", "app.spec.ts", False),
    ("*.py", "a.py", True),
    ("*.py", "pkg/a.py", False),
])
def test_glob_to_regex_matches(pattern, path, expected):
    assert bool(gitops.glob_to_regex(pattern).match(path)) is expected


def test_matches_any_normalises_windows_separators():
    assert gitops.matches_any("tests\\unit\\test_a.py", ["tests/**/test_*.py"])


def test_matches_any_is_false_when_no_pattern_matches():
    assert not gitops.matches_any("src/main.py", ["tests/**/test_*.py"])


def test_glob_special_chars_are_escaped_not_interpreted():
    # A dot must be a literal dot, not "any character".
    assert not gitops.glob_to_regex("a.py").match("axpy")
    assert gitops.glob_to_regex("a.py").match("a.py")
