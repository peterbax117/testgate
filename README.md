# testgate

Deterministic test-quality gates. Coverage answers "did this line run". This
answers the question that actually bites: **can this test fail?**

The point is that the verdict is **mechanical**. A test suite, a human, or an
agent can all claim a test is meaningful. `testgate` decides it with an exit
code, and refuses to report a clean result unless it has proved, in the same
run, that it is capable of reporting a dirty one.

## The red-evidence gate

A test added by your branch must **fail against the base source**. If it passes
there, it is not evidence for your change: it either characterises behaviour
that already worked, or it sits at the wrong layer.

```
pip install testgate

testgate selftest      # prove the gate can fail
testgate red           # run the gate on the current branch
testgate doctor        # show what it would scan, and why
```

Exit codes are the contract:

| Code | Meaning |
|---|---|
| `0` | Gate passed |
| `1` | An added test passed on the base source, and is named |
| `2` | The gate could not run, or could not prove itself. **Never a pass.** |

The only escape hatch is a declared pin (`@pytest.mark.pin` for pytest). A
characterisation test is legitimate, but the author has to say so in code where
a reviewer can see it, not in a commit message they wrote for themselves.

## Why it self-tests before it reports

A checker with no known-bad input to catch cannot be told apart from a checker
that always says yes. `testgate red` runs the positive control first and refuses
to proceed if it fails:

```
testgate selftest (positive control)
  [ok  ] BAD_passes_on_base: expected exit 1, got 1
  [ok  ] GOOD_fails_on_base: expected exit 0, got 0
  [ok  ] GOOD_declared_pin: expected exit 0, got 0
  [ok  ] BAD_scans_nothing: expected exit 2, got 2
selftest OK: 4 case(s), the gate provably bites.
```

Each case builds a real throwaway git repository and runs the real gate against
it. `BAD_scans_nothing` exists because the most dangerous failure in a checker
is not a wrong answer, it is an **empty** answer that reads as clean. Matching
zero files reports "scanned nothing" and exits 2, never 0.

## Language-agnostic by design

The gate's logic does not care about your language: find the merge-base,
identify the tests the branch adds, run them against the old source, fail any
that pass. Only four things are language-specific, and all four are **config,
not code**.

`testgate` parses **JUnit XML only**. It never parses human-readable test
output, because a repo's own verbosity settings must not be able to change what
the gate concludes. pytest, vitest, jest, Pester, `go test` and `dotnet test`
can all emit JUnit XML.

```toml
# pyproject.toml, or a standalone testgate.toml
[tool.testgate]
runner = "pytest"                        # built-in preset
test_globs = ["tests/**/test_*.py"]
base_ref = "origin/main"
```

Built-in presets: `pytest`, `vitest`, `pester`.

Any stack can be defined inline without touching the core:

```toml
[tool.testgate]
runner = "mystack"
command = ["mytool", "{paths}", "--junit={report}"]
test_decl_pattern = "^\\s*TEST\\((?P<name>\\w+)"
test_globs = ["t/**/*.my"]
pin_marker = "PIN:"
```

`command` is an argv **list**, never a shell string, so Windows paths are never
run through `shlex` and silently mangled. `test_decl_pattern` must expose a
capture group named `name`.

## Roadmap

- **v0.1** red-evidence gate, self-test precondition, nothing-scanned guard,
  declarative language presets. *(current)*
- **v0.2** mutation gate: break the implementation, require a test to go red,
  with a threshold and a machine-readable report. This is the stronger check,
  and the one that catches tests written to look like work.
- **v0.3** pre-push hook and CI recipes.

## License

MIT
