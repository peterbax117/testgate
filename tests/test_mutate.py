from pathlib import Path

import pytest

from testgate import mutate
from testgate.config import PRESETS, Operator

PY = PRESETS["pytest"].operators


def _src(tmp_path: Path, body: str, name: str = "calc.py") -> Path:
    (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


def test_generate_is_deterministic(tmp_path):
    root = _src(tmp_path, "x = True\ny = 1 == 2\nz = a and b\n")
    first = mutate.generate(root, ["calc.py"], PY, 0)
    second = mutate.generate(root, ["calc.py"], PY, 0)
    assert [m.id for m in first] == [m.id for m in second]
    assert first, "no mutants generated from mutable source"


def test_generate_skips_comments_and_blank_lines(tmp_path):
    root = _src(tmp_path, "# x = True\n\n#  a == b\n")
    assert mutate.generate(root, ["calc.py"], PY, 0) == []


def test_docstring_prose_is_not_mutated(tmp_path):
    """Regression: mutating 'or' inside a docstring made an unkillable mutant."""
    body = (
        'def f():\n'
        '    """Could not run, or could not prove itself.\n'
        '\n'
        '    More prose with True and == inside it.\n'
        '    """\n'
        '    return True\n'
    )
    root = _src(tmp_path, body)
    mutants = mutate.generate(root, ["calc.py"], PY, 0)
    assert mutants, "the real code line should still be mutable"
    assert all(m.line_no == 6 for m in mutants), \
        f"mutated docstring lines: {[m.line_no for m in mutants]}"


def test_single_line_docstring_is_not_mutated(tmp_path):
    root = _src(tmp_path, 'def f():\n    """One line or another."""\n    x = 1\n')
    assert all(m.line_no != 2 for m in mutate.generate(root, ["calc.py"], PY, 0))


def test_mutable_lines_reports_line_numbers_of_real_code():
    text = '"""header or thing"""\n\nx = True\n# y or z\nz = False\n'
    assert [n for n, _ in mutate.mutable_lines(text)] == [3, 5]


def test_generate_respects_the_cap(tmp_path):
    body = "\n".join(f"v{i} = True" for i in range(50)) + "\n"
    root = _src(tmp_path, body)
    assert len(mutate.generate(root, ["calc.py"], PY, 5)) == 5


def test_cap_of_zero_means_no_cap(tmp_path):
    body = "\n".join(f"v{i} = True" for i in range(10)) + "\n"
    root = _src(tmp_path, body)
    assert len(mutate.generate(root, ["calc.py"], PY, 0)) >= 10


def test_stride_sampling_spreads_across_the_file(tmp_path):
    """Truncation would only ever mutate the top of the first file."""
    body = "\n".join(f"v{i} = True" for i in range(100)) + "\n"
    root = _src(tmp_path, body)
    picked = mutate.generate(root, ["calc.py"], PY, 4)
    lines = [m.line_no for m in picked]
    assert lines == sorted(lines)
    assert max(lines) > 50, f"sampling clustered at the top: {lines}"


def test_mutant_actually_changes_the_line(tmp_path):
    root = _src(tmp_path, "flag = True\n")
    for mutant in mutate.generate(root, ["calc.py"], PY, 0):
        assert mutant.after != mutant.before


def test_true_and_false_operators_both_exist():
    names = {op.name for op in PY}
    assert {"true_to_false", "false_to_true"} <= names


def test_gt_operator_ignores_arrows_and_gte():
    import re
    op = next(o for o in PY if o.name == "gt_to_ge")
    assert not re.search(op.pattern, "a >= b")
    assert not re.search(op.pattern, "a => b")
    assert re.search(op.pattern, "a > b")


def test_apply_writes_only_the_target_line(tmp_path):
    root = _src(tmp_path, "a = 1\nflag = True\nb = 2\n")
    mutant = mutate.Mutant("calc.py", 2, "true_to_false",
                           "flag = True", "flag = False")
    mutate._apply(root, mutant)
    assert (root / "calc.py").read_text(encoding="utf-8") == \
        "a = 1\nflag = False\nb = 2\n"


def test_score_is_killed_over_scored():
    result = mutate.Result(exit_code=0, summary="")
    m = mutate.Mutant("f", 1, "op", "a", "b")
    result.results = [
        mutate.MutantResult(m, mutate.KILLED),
        mutate.MutantResult(m, mutate.KILLED),
        mutate.MutantResult(m, mutate.SURVIVED),
    ]
    assert result.scored == 3
    assert result.score == pytest.approx(2 / 3)


def test_invalid_and_timeout_are_not_counted_as_kills():
    result = mutate.Result(exit_code=0, summary="")
    m = mutate.Mutant("f", 1, "op", "a", "b")
    result.results = [
        mutate.MutantResult(m, mutate.KILLED),
        mutate.MutantResult(m, mutate.INVALID),
        mutate.MutantResult(m, mutate.TIMEOUT),
    ]
    assert result.killed == 1
    assert result.scored == 1
    assert result.score == 1.0


def test_score_of_an_empty_run_is_zero_not_one():
    """An unmeasured run must never look like a perfect one."""
    result = mutate.Result(exit_code=0, summary="")
    assert result.score == 0.0


def test_custom_operator_is_honoured(tmp_path):
    root = _src(tmp_path, "value = KEEP\n")
    ops = [Operator("keep_to_drop", r"\bKEEP\b", "DROP")]
    mutants = mutate.generate(root, ["calc.py"], ops, 0)
    assert len(mutants) == 1
    assert mutants[0].after.strip() == "value = DROP"
