"""Configuration and language presets.

Language support is declarative on purpose. A preset is a command argv, a set
of globs, a regex that recognises a test declaration, and an optional pin
marker. Adding a language means adding a preset, never touching the core.

The command is an argv **list**, never a shell string. On Windows a string
template would be split with shlex, which eats backslashes and silently turns
absolute paths into relative ones.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PATHS = "{paths}"
REPORT = "{report}"
FILE = "{file}"


@dataclass(frozen=True)
class Operator:
    """A declarative mutation: break one behaviour, deterministically.

    Applied one match at a time, to one line at a time. `pattern` is a regex
    and `replacement` is a re.sub template.
    """
    name: str
    pattern: str
    replacement: str


# Operators that remove a BEHAVIOUR rather than just editing a line. Order is
# fixed, because mutant ordering must be deterministic across runs.
COMMON_OPERATORS: list[Operator] = [
    Operator("true_to_false", r"\bTrue\b", "False"),
    Operator("false_to_true", r"\bFalse\b", "True"),
    Operator("eq_to_ne", r"==", "!="),
    Operator("ne_to_eq", r"!=", "=="),
    Operator("and_to_or", r"\band\b", "or"),
    Operator("or_to_and", r"\bor\b", "and"),
    Operator("gt_to_ge", r"(?<![<>=!])>(?![=>])", ">="),
    Operator("lt_to_le", r"(?<![<>=!])<(?![=<])", "<="),
    Operator("drop_not", r"\bnot\s+", ""),
]

PY_OPERATORS: list[Operator] = COMMON_OPERATORS + [
    Operator("raise_to_pass", r"^(\s*)raise\b.*$", r"\1pass"),
    Operator("guard_always_false", r"^(\s*)if\b(.*):\s*$", r"\1if False:"),
]

JS_OPERATORS: list[Operator] = COMMON_OPERATORS + [
    Operator("throw_to_noop", r"^(\s*)throw\b.*$", r"\1;"),
    Operator("strict_eq_to_loose", r"===", "=="),
]


@dataclass(frozen=True)
class Preset:
    name: str
    command: list[str]
    test_globs: list[str]
    # Must expose a capture group named "name" for the test identifier.
    test_decl_pattern: str
    pin_marker: str | None = None
    src_globs: list[str] = field(default_factory=list)
    operators: list[Operator] = field(default_factory=list)
    # argv template with {file}; used to reject syntactically broken mutants.
    syntax_check: list[str] | None = None


PRESETS: dict[str, Preset] = {
    "pytest": Preset(
        name="pytest",
        command=[
            "python", "-m", "pytest", PATHS,
            f"--junit-xml={REPORT}",
            "-p", "no:cacheprovider",
            "-o", "addopts=",  # never inherit a repo's addopts; it broke a real gate
            "-q",
        ],
        test_globs=["tests/**/test_*.py", "tests/**/*_test.py"],
        test_decl_pattern=r"^\s*(?:async\s+)?def\s+(?P<name>test\w*)\s*\(",
        pin_marker="pytest.mark.pin",
        src_globs=["**/*.py"],
        operators=PY_OPERATORS,
        syntax_check=[
            "python", "-c",
            "import sys,py_compile;py_compile.compile(sys.argv[1],doraise=True)",
            FILE,
        ],
    ),
    "vitest": Preset(
        name="vitest",
        command=["npx", "vitest", "run", PATHS,
                 "--reporter=junit", f"--outputFile={REPORT}"],
        test_globs=["**/*.test.ts", "**/*.test.js", "**/*.spec.ts"],
        test_decl_pattern=r"""^\s*(?:it|test)\s*\(\s*['"`](?P<name>[^'"`]+)""",
        pin_marker="PIN:",
        src_globs=["src/**/*.ts", "src/**/*.js"],
        operators=JS_OPERATORS,
    ),
    "pester": Preset(
        name="pester",
        command=["pwsh", "-NoProfile", "-Command", PATHS, REPORT],
        test_globs=["**/*.Tests.ps1"],
        test_decl_pattern=r"""^\s*It\s+['"](?P<name>[^'"]+)""",
        pin_marker="-Tag 'Pin'",
        src_globs=["**/*.ps1"],
        operators=COMMON_OPERATORS,
    ),
}


@dataclass
class Config:
    root: Path
    preset: Preset
    test_globs: list[str] = field(default_factory=list)
    pin_marker: str | None = None
    base_ref: str = "origin/main"
    src_globs: list[str] = field(default_factory=list)
    max_mutants: int = 25
    mutation_threshold: float = 0.75
    timeout: int = 300

    @property
    def globs(self) -> list[str]:
        return self.test_globs or self.preset.test_globs

    @property
    def source_globs(self) -> list[str]:
        return self.src_globs or self.preset.src_globs


class ConfigError(RuntimeError):
    pass


def _read_table(root: Path) -> dict:
    """Read [tool.testgate] from pyproject.toml, or a standalone testgate.toml."""
    standalone = root / "testgate.toml"
    if standalone.is_file():
        with standalone.open("rb") as fh:
            return tomllib.load(fh).get("testgate", {})
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        with pyproject.open("rb") as fh:
            return tomllib.load(fh).get("tool", {}).get("testgate", {})
    return {}


def load(root: Path) -> Config:
    root = Path(root).resolve()
    table = _read_table(root)

    runner = table.get("runner", "pytest")
    if runner in PRESETS:
        preset = PRESETS[runner]
    else:
        # Fully inline preset: a repo can define a stack we have never seen.
        try:
            preset = Preset(
                name=runner,
                command=list(table["command"]),
                test_globs=list(table.get("test_globs", [])),
                test_decl_pattern=table["test_decl_pattern"],
                pin_marker=table.get("pin_marker"),
                src_globs=list(table.get("src_globs", [])),
                operators=[
                    Operator(o["name"], o["pattern"], o["replacement"])
                    for o in table.get("operators", [])
                ] or COMMON_OPERATORS,
                syntax_check=list(table["syntax_check"])
                if table.get("syntax_check") else None,
            )
        except KeyError as exc:
            raise ConfigError(
                f"unknown runner {runner!r} and no inline preset. "
                f"Known runners: {', '.join(sorted(PRESETS))}. "
                f"An inline preset needs 'command' and 'test_decl_pattern' "
                f"(missing {exc})."
            ) from exc

    return Config(
        root=root,
        preset=preset,
        test_globs=list(table.get("test_globs", [])),
        pin_marker=table.get("pin_marker", preset.pin_marker),
        base_ref=table.get("base_ref", "origin/main"),
        src_globs=list(table.get("src_globs", [])),
        max_mutants=int(table.get("max_mutants", 25)),
        mutation_threshold=float(table.get("mutation_threshold", 0.75)),
        timeout=int(table.get("timeout", 300)),
    )


def build_check_argv(preset: Preset, file: Path) -> list[str] | None:
    if not preset.syntax_check:
        return None
    return [part.replace(FILE, str(file)) for part in preset.syntax_check]


def build_argv(preset: Preset, paths: list[str], report: Path) -> list[str]:
    """Expand the argv template. {paths} expands in place to many arguments."""
    argv: list[str] = []
    for item in preset.command:
        if item == PATHS:
            argv.extend(paths)
        else:
            argv.append(item.replace(REPORT, str(report)))
    return argv
