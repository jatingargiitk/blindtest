import json
from pathlib import Path

import pytest

from blindtest.room import (
    RoomError,
    check_inputs,
    collect_tests,
    load_seal,
    other_files,
    prepare,
    seal,
    verify_seal,
)


def make_room(example):
    return prepare(Path("room"), [Path("SPEC.md")], [Path("slugify.pyi")])


def write_test(room, name="test_a.py", body="def test_x():\n    assert True\n"):
    p = room / "tests" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def test_prepare_copies_only_inputs(example):
    manifest = make_room(example)
    room = Path("room")
    assert sorted(p.relative_to(room).as_posix() for p in room.rglob("*") if p.is_file()) == [
        ".blindtest/manifest.json",
        "BLINDTEST.md",
        "inputs/SPEC.md",
        "inputs/slugify.pyi",
    ]
    kinds = {e["path"]: e["kind"] for e in manifest["inputs"]}
    assert kinds == {"SPEC.md": "spec", "slugify.pyi": "interface"}
    assert not (room / "fixed").exists()


def test_instructions_name_every_input(example):
    make_room(example)
    text = Path("room/BLINDTEST.md").read_text()
    assert "inputs/SPEC.md" in text and "inputs/slugify.pyi" in text
    assert "tests/" in text


def test_prepare_refuses_existing_room_without_force(example):
    make_room(example)
    with pytest.raises(RoomError, match="already exists"):
        make_room(example)
    prepare(Path("room"), [Path("SPEC.md")], force=True)
    assert not Path("room/inputs/slugify.pyi").exists()


def test_prepare_requires_a_spec_and_real_files(example):
    with pytest.raises(RoomError, match="spec"):
        prepare(Path("room"), [])
    with pytest.raises(RoomError, match="not a file"):
        prepare(Path("room"), [Path("nope.md")])


def test_prepare_keeps_relative_paths(example):
    Path("docs").mkdir()
    Path("docs/SPEC.md").write_text("other spec")
    m = prepare(Path("room"), [Path("SPEC.md"), Path("docs/SPEC.md")])
    assert [e["path"] for e in m["inputs"]] == ["SPEC.md", "docs/SPEC.md"]
    assert Path("room/inputs/docs/SPEC.md").read_text() == "other spec"


def test_check_inputs_detects_change_removal_and_addition(example):
    make_room(example)
    room = Path("room")
    assert check_inputs(room) == []
    (room / "inputs/SPEC.md").write_text("rewritten by the agent")
    (room / "inputs/slugify.pyi").unlink()
    (room / "inputs/impl.py").write_text("x = 1")
    assert check_inputs(room) == [
        "input changed: inputs/SPEC.md",
        "input removed: inputs/slugify.pyi",
        "input added: inputs/impl.py",
    ]


def test_seal_hashes_tests_and_records_other_files(example):
    make_room(example)
    room = Path("room")
    write_test(room)
    write_test(room, "helpers.py", "X = 1\n")
    (room / "notes.txt").write_text("scratch")
    data = seal(room, {"command": ["agent"], "exit_code": 0})
    assert sorted(data["tests"]) == ["tests/helpers.py", "tests/test_a.py"]
    assert data["other_files"] == ["notes.txt"]
    assert data["run"]["command"] == ["agent"]
    assert load_seal(room)["tests"] == data["tests"]


def test_seal_requires_a_test_file(example):
    make_room(example)
    write_test(Path("room"), "helpers.py", "X = 1\n")
    with pytest.raises(RoomError, match="no test_"):
        seal(Path("room"))


def test_verify_seal_detects_tampering(example):
    make_room(example)
    room = Path("room")
    t = write_test(room)
    seal(room)
    assert verify_seal(room) == []
    t.write_text("def test_x():\n    assert 1\n")
    write_test(room, "test_new.py")
    assert verify_seal(room) == [
        "sealed test changed: tests/test_a.py",
        "test added after sealing: tests/test_new.py",
    ]
    t.unlink()
    assert "sealed test removed: tests/test_a.py" in verify_seal(room)


def test_collect_tests_skips_pycache(example):
    make_room(example)
    room = Path("room")
    write_test(room)
    (room / "tests/__pycache__").mkdir()
    (room / "tests/__pycache__/junk.py").write_text("")
    assert collect_tests(room) == ["tests/test_a.py"]
    assert other_files(room) == []


def test_not_a_room(tmp_path):
    with pytest.raises(RoomError, match="not a blindtest room"):
        seal(tmp_path)
    with pytest.raises(RoomError, match="no seal"):
        load_seal(tmp_path)


def test_manifest_is_valid_json(example):
    make_room(example)
    data = json.loads(Path("room/.blindtest/manifest.json").read_text())
    assert data["version"] == 1 and len(data["inputs"]) == 2
