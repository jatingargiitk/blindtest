# blindtest

[![CI](https://github.com/jatingargiitk/blindtest/actions/workflows/ci.yml/badge.svg)](https://github.com/jatingargiitk/blindtest/actions/workflows/ci.yml)

When the same agent writes the code and the tests, the tests tend to share the code's blind spots. blindtest splits the job: an agent writes tests from **the spec and interface only**, blindtest **seals** those tests by hash, then **grades** them by running them on a revision you trust and on revisions with bugs you know about.

A good suite passes on the fixed revision and fails on every buggy one. The report tells you which bugs slipped through and which tests catch nothing.

- Works with any agent: blindtest runs whatever command you give it, inside a folder that holds only the spec.
- No dependencies beyond the standard library; grading needs `pytest` in the Python you grade with.
- Python 3.9+.

## Install

```bash
pip install git+https://github.com/jatingargiitk/blindtest
```

## Try it on the bundled example

`examples/slugify` has a seven-rule spec, an interface stub, a correct implementation and three buggy ones. `stand_in_agent.py` is a deterministic stand-in for an agent so the example runs offline; like a real agent, it covers most of the spec but not all of it.

```bash
cd examples/slugify
blindtest prepare room --spec SPEC.md --interface slugify.pyi
```

```
room ready: room
  spec      inputs/SPEC.md  cd2cacd13c98
  interface inputs/slugify.pyi  699cb55d9c0a
agent instructions: room/BLINDTEST.md
```

The room contains copies of the inputs, an instructions file for the agent (`BLINDTEST.md`), an empty `tests/` folder and a manifest of input hashes. The implementations are not in it.

```bash
blindtest write room -- python ../stand_in_agent.py
```

```
wrote tests/test_slugify.py
sealed 1 test file(s) in room
  tests/test_slugify.py  cbe19c3c2656
```

`write` starts the command with the room as its working directory, then seals every `.py` file under `tests/`. If the agent edited, added or deleted anything in `inputs/`, sealing warns and exits 1.

```bash
blindtest grade room --fixed fixed --buggy buggy-no-strip --buggy buggy-drops-accents --buggy buggy-max-len
```

```
fixed revision: 7/7 sealed tests pass
buggy revisions caught: 2/3

  buggy-no-strip       CAUGHT by 2 test(s)
                         - tests.test_slugify::test_no_leading_or_trailing_sep
                         - tests.test_slugify::test_only_symbols_gives_empty
  buggy-drops-accents  CAUGHT by 1 test(s)
                         - tests.test_slugify::test_folds_accents
  buggy-max-len        MISSED, no test that passes on fixed fails here

tests: 3 catch a bug, 4 pass on every revision, 0 fail on the fixed revision, 0 skipped

pass on every revision (catch none of the supplied bugs):
  - tests.test_slugify::test_collapses_runs_to_one_sep
  - tests.test_slugify::test_custom_sep
  - tests.test_slugify::test_lowercases
  - tests.test_slugify::test_rejects_non_str

verdict: FAIL
  missed: buggy-max-len
```

The exit code is 1. The stand-in never tested rule 5 of the spec (`max_len`), so the truncation bug went uncaught. "Pass on every revision" only means those tests catch none of *these* bugs; they may still be worth keeping.

Tests are judged like this:

| on fixed | on a buggy revision | verdict |
| --- | --- | --- |
| pass | fails or errors on at least one | catches a bug |
| pass | passes on all | passes on every revision |
| fail or error | anything | fails on the fixed revision, so the test disagrees with code you trust and can't count as a catch |

A buggy revision that can't even be imported counts as caught.

## Tamper check

The seal is checked again before grading. Editing a test after sealing stops the grade:

```bash
echo "# edited" >> room/tests/test_slugify.py
blindtest verify room
```

```
sealed test changed: tests/test_slugify.py
```

`verify` exits 1, and `grade` refuses to run with exit code 2:

```
blindtest: seal check failed: sealed test changed: tests/test_slugify.py
```

## JSON output

`blindtest grade ... --json` prints the same result as JSON: `ok`, `score` (`caught` and `buggy`), `caught_by`, `missed`, `wrong`, per-revision `outcomes`, and a per-test `verdict`.

## Commands

| command | what it does |
| --- | --- |
| `blindtest prepare ROOM --spec FILE [--interface FILE] [--force]` | create the room; `--spec` and `--interface` repeat |
| `blindtest write ROOM [--timeout S] [--seal-on-failure] -- COMMAND...` | run the agent in the room (default timeout 1800 s), then seal; a non-zero agent exit skips sealing unless `--seal-on-failure` |
| `blindtest seal ROOM` | seal tests that got into `tests/` some other way, for example from an interactive agent session |
| `blindtest verify ROOM` | check inputs and sealed tests are unchanged |
| `blindtest grade ROOM --fixed DIR --buggy [LABEL=]DIR ... [--json] [--timeout S] [--python PATH] [-v]` | run the sealed tests on each revision |

`write` sets `BLINDTEST_ROOM` and `BLINDTEST_INSTRUCTIONS` in the agent's environment. Point your agent's non-interactive mode at `BLINDTEST.md` as its prompt.

Exit codes: 0 means success or a passing grade, 1 means a failing grade, a failed check, or an agent that exited non-zero, and 2 means a usage or seal error.

## How grading runs

For each revision, blindtest copies the directory to a scratch folder (skipping `.git`, virtualenvs and caches), copies in the sealed tests, and runs `python -m pytest` on just those tests with an empty pytest config. The revision's own tests, `conftest.py` and pytest settings are not used. The revision root, plus `src/` if it exists, goes on `PYTHONPATH`, so tests import the code by module name.

Where buggy revisions come from is up to you: a commit before a bug fix, a hand-planted bug, or the output of a mutation tool. Check out each one into its own directory and pass it with `--buggy`.

## Limits

- blindtest is **not a sandbox**. It controls what is in the agent's working directory, not what the agent can read elsewhere on your machine. For real isolation, run the agent in a container that mounts only the room.
- Grading is pytest-only for now.
- A score only covers the bugs you supplied. Catching all of them does not prove the suite is complete.

## License

MIT
