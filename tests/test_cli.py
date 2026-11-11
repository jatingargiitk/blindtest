import json
import sys
from pathlib import Path

from blindtest.cli import _parse_buggy, main

GRADE = ["grade", "room", "--fixed", "fixed",
         "--buggy", "buggy-no-strip", "--buggy", "buggy-drops-accents", "--buggy", "buggy-max-len"]


def run_flow(capsys):
    assert main(["prepare", "room", "--spec", "SPEC.md", "--interface", "slugify.pyi"]) == 0
    assert main(["write", "room", "--", sys.executable, "../stand_in_agent.py"]) == 0
    capsys.readouterr()


def test_full_flow_text_report(example, capsys):
    run_flow(capsys)
    assert main(["verify", "room"]) == 0
    assert "seal intact" in capsys.readouterr().out
    assert main(GRADE) == 1
    out = capsys.readouterr().out
    assert "fixed revision: 7/7 sealed tests pass" in out
    assert "buggy revisions caught: 2/3" in out
    assert "buggy-max-len        MISSED" in out
    assert "verdict: FAIL" in out and "missed: buggy-max-len" in out


def test_json_report(example, capsys):
    run_flow(capsys)
    assert main(GRADE + ["--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["score"] == {"caught": 2, "buggy": 3}
    assert data["missed"] == ["buggy-max-len"]
    assert data["fixed"]["label"] == "fixed"


def test_write_records_run_and_env(example, capsys):
    assert main(["prepare", "room", "--spec", "SPEC.md"]) == 0
    agent = Path("agent.py")
    agent.write_text(
        "import os, pathlib\n"
        "assert pathlib.Path.cwd() == pathlib.Path(os.environ['BLINDTEST_ROOM'])\n"
        "assert os.environ['BLINDTEST_INSTRUCTIONS'].endswith('BLINDTEST.md')\n"
        "pathlib.Path('tests/test_ok.py').write_text('def test_ok():\\n    pass\\n')\n"
    )
    assert main(["write", "room", "--", sys.executable, str(agent.resolve())]) == 0
    seal = json.loads(Path("room/.blindtest/seal.json").read_text())
    assert seal["run"]["exit_code"] == 0
    assert seal["run"]["command"][-1].endswith("agent.py")


def test_write_failing_agent_does_not_seal(example, capsys):
    assert main(["prepare", "room", "--spec", "SPEC.md"]) == 0
    cmd = ["write", "room", "--", sys.executable, "-c",
           "import pathlib,sys; pathlib.Path('tests/test_a.py').write_text('def test_a(): pass'); sys.exit(3)"]
    assert main(cmd) == 1
    assert not Path("room/.blindtest/seal.json").exists()
    assert "exited with 3" in capsys.readouterr().err
    assert main(cmd[:2] + ["--seal-on-failure"] + cmd[2:]) == 0
    assert json.loads(Path("room/.blindtest/seal.json").read_text())["run"]["exit_code"] == 3


def test_write_flags_edited_spec(example, capsys):
    assert main(["prepare", "room", "--spec", "SPEC.md"]) == 0
    code = ("import pathlib; pathlib.Path('inputs/SPEC.md').write_text('easier spec');"
            "pathlib.Path('tests/test_a.py').write_text('def test_a(): pass')")
    assert main(["write", "room", "--", sys.executable, "-c", code]) == 1
    assert "input changed: inputs/SPEC.md" in capsys.readouterr().err
    assert main(["verify", "room"]) == 1


def test_errors_exit_2(example, capsys):
    assert main(["seal", "nowhere"]) == 2
    assert "not a blindtest room" in capsys.readouterr().err
    assert main(["prepare", "room", "--spec", "SPEC.md"]) == 0
    assert main(["write", "room"]) == 2
    assert main(["write", "room", "--", "definitely-not-a-command-xyz"]) == 2
    assert main(["seal", "room"]) == 2
    assert "no test_" in capsys.readouterr().err


def test_manual_seal_then_grade(example, capsys):
    assert main(["prepare", "room", "--spec", "SPEC.md"]) == 0
    Path("room/tests/test_one.py").write_text(
        "from slugify import slugify\n\ndef test_trim():\n    assert slugify(' a ') == 'a'\n"
    )
    assert main(["seal", "room"]) == 0
    assert main(["grade", "room", "--fixed", "fixed", "--buggy", "strip=buggy-no-strip"]) == 0
    assert "strip   CAUGHT by 1 test(s)" in capsys.readouterr().out


def test_parse_buggy_labels(example):
    assert _parse_buggy(["buggy-max-len"]) == [("buggy-max-len", Path("buggy-max-len"))]
    assert _parse_buggy(["x=buggy-max-len"]) == [("x", Path("buggy-max-len"))]


def test_module_entrypoint_version():
    import subprocess
    out = subprocess.run([sys.executable, "-m", "blindtest", "--version"], capture_output=True, text=True)
    assert out.stdout.strip() == "blindtest 0.1.0"
