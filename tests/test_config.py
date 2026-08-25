import re

import pytest

from testgate import config


def test_pytest_preset_declares_a_named_capture_group():
    preset = config.PRESETS["pytest"]
    assert "(?P<name>" in preset.test_decl_pattern
    match = re.match(preset.test_decl_pattern, "def test_thing():")
    assert match and match.group("name") == "test_thing"


@pytest.mark.parametrize("runner", sorted(config.PRESETS))
def test_every_preset_pattern_compiles_and_names_a_group(runner):
    preset = config.PRESETS[runner]
    compiled = re.compile(preset.test_decl_pattern)
    assert "name" in compiled.groupindex


@pytest.mark.parametrize("runner", sorted(config.PRESETS))
def test_every_preset_command_is_argv_not_a_shell_string(runner):
    """A shell string would be shlex-split, which eats Windows backslashes."""
    command = config.PRESETS[runner].command
    assert isinstance(command, list)
    assert all(isinstance(part, str) for part in command)


@pytest.mark.parametrize("runner", sorted(config.PRESETS))
def test_every_preset_has_both_placeholders(runner):
    command = config.PRESETS[runner].command
    assert config.PATHS in command
    assert any(config.REPORT in part for part in command)


def test_build_argv_expands_paths_in_place(tmp_path):
    preset = config.PRESETS["pytest"]
    argv = config.build_argv(preset, ["a.py", "b.py"], tmp_path / "r.xml")
    assert "a.py" in argv and "b.py" in argv
    assert config.PATHS not in argv
    assert any(str(tmp_path / "r.xml") in part for part in argv)


def test_build_argv_keeps_backslashes_intact(tmp_path):
    """Regression: a shlex-based template silently ate Windows paths."""
    report = tmp_path / "sub dir" / "r.xml"
    argv = config.build_argv(config.PRESETS["pytest"], ["x.py"], report)
    assert any(str(report) in part for part in argv)


def test_pytest_preset_neutralises_repo_addopts():
    """A repo's addopts once cancelled the flags a gate's parser depended on."""
    command = config.PRESETS["pytest"].command
    assert "addopts=" in command


def test_unknown_runner_without_inline_preset_is_an_error(tmp_path):
    (tmp_path / "testgate.toml").write_text(
        '[testgate]\nrunner = "nope"\n', encoding="utf-8"
    )
    with pytest.raises(config.ConfigError) as exc:
        config.load(tmp_path)
    assert "nope" in str(exc.value)


def test_inline_preset_supports_an_unknown_stack(tmp_path):
    (tmp_path / "testgate.toml").write_text(
        '[testgate]\n'
        'runner = "mystack"\n'
        'command = ["mytool", "{paths}", "--out={report}"]\n'
        'test_decl_pattern = "^TEST (?P<name>\\\\w+)"\n'
        'test_globs = ["t/**/*.my"]\n',
        encoding="utf-8",
    )
    cfg = config.load(tmp_path)
    assert cfg.preset.name == "mystack"
    assert cfg.globs == ["t/**/*.my"]


def test_defaults_to_pytest_when_no_config(tmp_path):
    cfg = config.load(tmp_path)
    assert cfg.preset.name == "pytest"
    assert cfg.base_ref == "origin/main"


def test_source_globs_fall_back_to_the_preset(tmp_path):
    """Found by running the mutation gate against testgate itself."""
    cfg = config.load(tmp_path)
    assert cfg.src_globs == []
    assert cfg.source_globs == config.PRESETS["pytest"].src_globs


def test_source_globs_override_the_preset(tmp_path):
    (tmp_path / "testgate.toml").write_text(
        '[testgate]\nrunner = "pytest"\nsrc_globs = ["lib/**/*.py"]\n',
        encoding="utf-8",
    )
    cfg = config.load(tmp_path)
    assert cfg.source_globs == ["lib/**/*.py"]


def test_test_globs_fall_back_to_the_preset(tmp_path):
    cfg = config.load(tmp_path)
    assert cfg.globs == config.PRESETS["pytest"].test_globs


def test_mutation_defaults_are_explicit(tmp_path):
    cfg = config.load(tmp_path)
    assert cfg.max_mutants == 25
    assert cfg.mutation_threshold == 0.75
    assert cfg.timeout == 300


@pytest.mark.parametrize("op_name,sample,expected", [
    ("true_to_false", "x = True", "x = False"),
    ("false_to_true", "x = False", "x = True"),
    ("eq_to_ne", "a == b", "a != b"),
    ("ne_to_eq", "a != b", "a == b"),
    ("and_to_or", "a and b", "a or b"),
    ("or_to_and", "a or b", "a and b"),
    ("gt_to_ge", "a > b", "a >= b"),
    ("lt_to_le", "a < b", "a <= b"),
    ("drop_not", "if not flag", "if flag"),
])
def test_each_operator_rewrites_as_declared(op_name, sample, expected):
    """Found by the mutation gate: nothing asserted the replacements."""
    op = next(o for o in config.PY_OPERATORS if o.name == op_name)
    assert re.sub(op.pattern, op.replacement, sample, count=1) == expected


def test_no_operator_is_a_no_op():
    """An operator that changes nothing would inflate the kill rate."""
    samples = ["x = True", "x = False", "a == b", "a != b", "a and b",
               "a or b", "a > b", "a < b", "if not flag", "raise ValueError()",
               "if cond:"]
    for op in config.PY_OPERATORS:
        changed = [s for s in samples
                   if re.sub(op.pattern, op.replacement, s, count=1) != s]
        assert changed, f"operator {op.name} never changes anything"
