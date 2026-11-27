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

testgate selftest      # prove the gates can fail
testgate red           # red-evidence gate on the current branch
testgate mutate        # mutation gate
testgate doctor        # show what it would scan, and why
```

Exit codes are the contract:

| Code | Meaning |
|---|---|
| `0` | Gate passed |
| `1` | An added test passed on the base source, and is named |
| `2` | The gate could not run (for example, its base ref cannot be resolved), or could not prove itself. **Never a pass.** |

The only escape hatch is a declared pin (`@pytest.mark.pin` for pytest). A
characterisation test is legitimate, but the author has to say so in code where
a reviewer can see it, not in a commit message they wrote for themselves.

## The mutation gate

The red-evidence gate proves a test was *written* for a reason. The mutation
gate proves the suite *notices* when behaviour changes. It is the check that
catches tests produced to look like work.

```
testgate mutate                       # break behaviour, require a test to notice
testgate mutate --max-mutants 10 --threshold 0.8
```

It breaks one behaviour at a time and re-runs the suite. A mutant that survives
names the exact behaviour nothing defends.

```
testgate mutation gate  (runner: pytest)
  source files : 7
  generated    : 3
  SURVIVED     : 1
      testgate/config.py:134:or_to_and
        - return self.src_globs or self.preset.src_globs
        + return self.src_globs and self.preset.src_globs
  verdict      : mutations: 3, killed: 2, survived: 1 (score 67%, threshold 75%)
```

Determinism is the point, so:

- mutants are generated in a fixed order and sampled by **stride, never at
  random**, so the same tree always yields the same mutant set;
- a **red baseline aborts** with exit 2, because killed-versus-survived is
  meaningless if the suite was already failing;
- **generating zero mutants is an error**, not a clean pass;
- a **timeout is its own outcome** and is never counted as a kill;
- a mutant that breaks syntax is discarded rather than counted as killed.

Operators are declarative too, so a new language does not need new code:

```toml
[[tool.testgate.operators]]
name = "true_to_false"
pattern = "\\bTrue\\b"
replacement = "False"
```

### Known limitation

Mutation cost scales with suite runtime: every mutant re-runs the tests. Cap it
with `max_mutants` and raise the cap in CI rather than locally.

Prose inside docstrings and comments is excluded, because mutating an English
"or" produces a mutant no test can kill. That fix came from running this gate
against its own source, which is also where the `config.py` survivor above came
from.

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

The mutation gate has its own control, including a repository whose tests are
green and completely worthless:

```
  [ok  ] BAD_vacuous_tests_kill_nothing: expected exit 1, got 1 (score 0%)
  [ok  ] GOOD_real_tests_kill_mutants:   expected exit 0, got 0 (score 100%)
  [ok  ] BAD_baseline_not_green:         expected exit 2, got 2
  [ok  ] BAD_mutates_nothing:            expected exit 2, got 2
```

And the controls themselves are falsified rather than trusted. Deliberately
breaking each gate (suppressing violations, downgrading "scanned nothing" to a
pass, ignoring pins, miscounting survivors as kills) makes the matching case go
red every time: **7 deliberate breakages, 7 caught, 0 survivors.** A green
self-test proves nothing until you have shown it can go red.

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
  declarative language presets.
- **v0.2** mutation gate with a deterministic mutant set, threshold, and
  machine-readable report. *(current)*
- **v0.3** pre-push hook and CI recipes, and a `--changed` mode so mutation
  targets only what the branch touched.

## License

MIT
