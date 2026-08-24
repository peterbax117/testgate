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


@dataclass(frozen=True)
class Preset:
    name: str
    command: list[str]
    test_globs: list[str]
    # Must expose a capture group named "name" for the test identifier.
    test_decl_pattern: str
    pin_marker: str | None = None


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
    ),
    "vitest": Preset(
        name="vitest",
        command=["npx", "vitest", "run", PATHS,
                 "--reporter=junit", f"--outputFile={REPORT}"],
        test_globs=["**/*.test.ts", "**/*.test.js", "**/*.spec.ts"],
        test_decl_pattern=r"""^\s*(?:it|test)\s*\(\s*['"`](?P<name>[^'"`]+)""",
        pin_marker="PIN:",
    ),
    "pester": Preset(
        name="pester",
        command=["pwsh", "-NoProfile", "-Command", PATHS, REPORT],
        test_globs=["**/*.Tests.ps1"],
        test_decl_pattern=r"""^\s*It\s+['"](?P<name>[^'"]+)""",
        pin_marker="-Tag 'Pin'",
    ),
}


@dataclass
class Config:
    root: Path
    preset: Preset
    test_globs: list[str] = field(default_factory=list)
    pin_marker: str | None = None
    base_ref: str = "origin/main"

    @property
    def globs(self) -> list[str]:
        return self.test_globs or self.preset.test_globs


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
    )


def build_argv(preset: Preset, paths: list[str], report: Path) -> list[str]:
    """Expand the argv template. {paths} expands in place to many arguments."""
    argv: list[str] = []
    for item in preset.command:
        if item == PATHS:
            argv.extend(paths)
        else:
            argv.append(item.replace(REPORT, str(report)))
    return argv
