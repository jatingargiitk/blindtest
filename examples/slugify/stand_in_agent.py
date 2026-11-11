"""A deterministic stand-in for a test-writing agent, so the example runs offline.

It reads only the room it is started in (BLINDTEST.md and inputs/) and writes
tests/test_slugify.py, the way an agent following the instructions would. Like
a real agent it covers some of the spec and not all of it: it never tests
rule 5 (max_len), so one of the example's buggy revisions goes uncaught.
Swap it for your own agent's non-interactive command.
"""

from pathlib import Path

spec = Path("inputs/SPEC.md").read_text(encoding="utf-8")
assert "slugify" in spec and Path("inputs/slugify.pyi").is_file()

Path("tests").mkdir(exist_ok=True)
Path("tests/test_slugify.py").write_text(
    '''import pytest

from slugify import slugify


def test_lowercases():
    assert slugify("Hello World") == "hello-world"


def test_folds_accents():
    assert slugify("Café Crème") == "cafe-creme"


def test_collapses_runs_to_one_sep():
    assert slugify("a  --  b") == "a-b"


def test_custom_sep():
    assert slugify("a b c", sep="_") == "a_b_c"


def test_no_leading_or_trailing_sep():
    assert slugify("  !hello!  ") == "hello"


def test_only_symbols_gives_empty():
    assert slugify("!!! ???") == ""


def test_rejects_non_str():
    with pytest.raises(TypeError):
        slugify(42)
''',
    encoding="utf-8",
)
print("wrote tests/test_slugify.py")
