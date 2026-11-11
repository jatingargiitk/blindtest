import subprocess
from pathlib import Path

import pytest

from blindtest.grade import grade, parse_junit
from blindtest.room import RoomError, prepare, seal

BUGGY = [
    ("buggy-no-strip", Path("buggy-no-strip")),
    ("buggy-drops-accents", Path("buggy-drops-accents")),
    ("buggy-max-len", Path("buggy-max-len")),
]


def sealed_example(py):
    room = Path("room")
    prepare(room, [Path("SPEC.md")], [Path("slugify.pyi")])
    subprocess.run([py, "../stand_in_agent.py"], cwd=room, check=True, capture_output=True)
    seal(room)
    return room


def add_test(room, body, name="test_extra.py"):
    (room / "tests" / name).write_text(body)
    seal(room)


def test_example_grade_matches_readme(example, py):
    room = sealed_example(py)
    g = grade(room, Path("fixed"), BUGGY, python=py)
    assert all(o == "pass" for o in g.fixed.outcomes.values())
    assert len(g.fixed.outcomes) == 7
    assert g.missed == ["buggy-max-len"]
    assert g.caught["buggy-drops-accents"] == ["tests.test_slugify::test_folds_accents"]
    assert sorted(g.caught["buggy-no-strip"]) == [
        "tests.test_slugify::test_no_leading_or_trailing_sep",
        "tests.test_slugify::test_only_symbols_gives_empty",
    ]
    assert g.wrong == []
    assert not g.ok
    verdicts = [d["verdict"] for d in g.tests.values()]
    assert verdicts.count("catches") == 3 and verdicts.count("blind") == 4


def test_adding_a_max_len_test_catches_every_bug(example, py):
    room = sealed_example(py)
    add_test(room, "from slugify import slugify\n\n"
                   "def test_max_len_never_ends_with_sep():\n"
                   "    assert slugify('ab cd', max_len=3) == 'ab'\n")
    g = grade(room, Path("fixed"), BUGGY, python=py)
    assert g.missed == []
    assert g.ok
    d = g.to_dict()
    assert d["score"] == {"caught": 3, "buggy": 3} and d["ok"] is True


def test_test_failing_on_fixed_is_wrong_and_cannot_catch(example, py):
    room = sealed_example(py)
    add_test(room, "from slugify import slugify\n\n"
                   "def test_keeps_case():\n"
                   "    assert slugify('AB') == 'AB'\n"
                   "\n"
                   "def test_max_len():\n"
                   "    assert slugify('ab cd', max_len=3) == 'ab'\n")
    g = grade(room, Path("fixed"), BUGGY, python=py)
    assert g.wrong == ["tests.test_extra::test_keeps_case"]
    assert g.tests["tests.test_extra::test_keeps_case"]["fails_on"] == []
    assert not g.ok


def test_buggy_revision_that_breaks_import_counts_as_caught(example, py):
    room = sealed_example(py)
    broken = Path("buggy-syntax")
    broken.mkdir()
    (broken / "slugify.py").write_text("def slugify(:\n")
    g = grade(room, Path("fixed"), [("buggy-syntax", broken)], python=py)
    assert g.missed == []
    assert g.caught["buggy-syntax"]


def test_revision_tests_and_pytest_config_are_ignored(example, py):
    room = sealed_example(py)
    fixed = Path("fixed")
    (fixed / "tests").mkdir()
    (fixed / "tests" / "test_maintainer.py").write_text("def test_secret():\n    assert False\n")
    (fixed / "pytest.ini").write_text("[pytest]\naddopts = --definitely-not-an-option\n")
    (fixed / "conftest.py").write_text("raise RuntimeError('should not load')\n")
    g = grade(room, fixed, BUGGY[:1], python=py)
    assert len(g.fixed.outcomes) == 7
    assert not any("maintainer" in t for t in g.fixed.outcomes)
    assert all(o == "pass" for o in g.fixed.outcomes.values())


def test_src_layout_is_importable(example, py):
    room = sealed_example(py)
    src_fixed = Path("srcfixed/src")
    src_fixed.mkdir(parents=True)
    (src_fixed / "slugify.py").write_text(Path("fixed/slugify.py").read_text())
    g = grade(room, Path("srcfixed"), BUGGY[:1], python=py)
    assert all(o == "pass" for o in g.fixed.outcomes.values())


def test_grade_refuses_tampered_seal(example, py):
    room = sealed_example(py)
    with open(room / "tests/test_slugify.py", "a") as fh:
        fh.write("\n# edited after sealing\n")
    with pytest.raises(RoomError, match="seal check failed"):
        grade(room, Path("fixed"), BUGGY, python=py)


def test_grade_validates_labels_and_dirs(example, py):
    room = sealed_example(py)
    with pytest.raises(RoomError, match="at least one"):
        grade(room, Path("fixed"), [], python=py)
    with pytest.raises(RoomError, match="unique"):
        grade(room, Path("fixed"), [("a", Path("fixed")), ("a", Path("fixed"))], python=py)
    with pytest.raises(RoomError, match="not a directory"):
        grade(room, Path("nope"), BUGGY[:1], python=py)


def test_timeout_is_reported(example, py):
    room = sealed_example(py)
    add_test(room, "import time\n\ndef test_slow():\n    time.sleep(30)\n")
    g = grade(room, Path("fixed"), BUGGY[:1], python=py, timeout=3)
    assert g.fixed.timed_out
    assert not g.ok


def test_parse_junit_outcomes(tmp_path):
    xml = tmp_path / "j.xml"
    xml.write_text(
        '<testsuites><testsuite>'
        '<testcase classname="t.m" name="a"/>'
        '<testcase classname="t.m" name="b"><failure message="x"/></testcase>'
        '<testcase classname="t.m" name="c"><skipped/></testcase>'
        '<testcase classname="t.m" name="d"/>'
        '<testcase classname="t.m" name="d"><error message="teardown"/></testcase>'
        '</testsuite></testsuites>'
    )
    assert parse_junit(xml) == {"t.m::a": "pass", "t.m::b": "fail", "t.m::c": "skip", "t.m::d": "error"}
    assert parse_junit(tmp_path / "missing.xml") == {}
