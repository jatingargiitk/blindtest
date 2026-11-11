"""Run the sealed tests against a fixed revision and one or more buggy ones."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .room import RoomError, load_seal, verify_seal

IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules", "*.pyc"
)

PASS, FAIL, ERROR, SKIP = "pass", "fail", "error", "skip"


@dataclass
class RevisionRun:
    label: str
    path: str
    outcomes: Dict[str, str] = field(default_factory=dict)
    returncode: int = 0
    timed_out: bool = False
    output_tail: str = ""


@dataclass
class Grade:
    fixed: RevisionRun
    buggy: List[RevisionRun]
    tests: Dict[str, Dict] = field(default_factory=dict)
    caught: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def wrong(self) -> List[str]:
        return [t for t, d in self.tests.items() if d["verdict"] == "wrong"]

    @property
    def missed(self) -> List[str]:
        return [b.label for b in self.buggy if not self.caught.get(b.label)]

    @property
    def ok(self) -> bool:
        has_passing = any(o == PASS for o in self.fixed.outcomes.values())
        return has_passing and not self.wrong and not self.missed

    def to_dict(self) -> Dict:
        return {
            "ok": self.ok,
            "score": {"caught": len(self.buggy) - len(self.missed), "buggy": len(self.buggy)},
            "fixed": _run_dict(self.fixed),
            "buggy": [_run_dict(b) for b in self.buggy],
            "caught_by": self.caught,
            "missed": self.missed,
            "wrong": self.wrong,
            "tests": self.tests,
        }


def _run_dict(r: RevisionRun) -> Dict:
    return {
        "label": r.label,
        "path": r.path,
        "returncode": r.returncode,
        "timed_out": r.timed_out,
        "outcomes": r.outcomes,
    }


def parse_junit(path: Path) -> Dict[str, str]:
    """Map test id -> outcome from a pytest junit XML file."""
    outcomes: Dict[str, str] = {}
    if not path.is_file():
        return outcomes
    root = ET.parse(path).getroot()
    for case in root.iter("testcase"):
        cls = case.get("classname", "")
        name = case.get("name", "")
        tid = f"{cls}::{name}" if cls else name
        if case.find("failure") is not None:
            outcome = FAIL
        elif case.find("error") is not None:
            outcome = ERROR
        elif case.find("skipped") is not None:
            outcome = SKIP
        else:
            outcome = PASS
        # a test can appear twice when teardown errors; keep the worst outcome
        prev = outcomes.get(tid)
        if prev is None or _rank(outcome) > _rank(prev):
            outcomes[tid] = outcome
    return outcomes


def _rank(outcome: str) -> int:
    return {PASS: 0, SKIP: 1, FAIL: 2, ERROR: 3}[outcome]


def run_revision(
    room: Path,
    test_files: List[str],
    label: str,
    rev: Path,
    timeout: float = 600.0,
    python: Optional[str] = None,
) -> RevisionRun:
    """Copy ``rev`` and the sealed tests into a scratch dir and run pytest there.

    The revision's own tests and pytest config are never used: pytest runs with
    an empty ini file and only the sealed test files.
    """
    if not rev.is_dir():
        raise RoomError(f"revision is not a directory: {rev}")
    python = python or sys.executable
    run = RevisionRun(label=label, path=str(rev))
    with tempfile.TemporaryDirectory(prefix="blindtest-") as tmp:
        tmp_path = Path(tmp)
        code = tmp_path / "rev"
        shutil.copytree(rev, code, ignore=IGNORE)
        for rel in test_files:
            dest = tmp_path / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(room / rel, dest)
        ini = tmp_path / "pytest.ini"
        ini.write_text("[pytest]\n", encoding="utf-8")
        junit = tmp_path / "junit.xml"

        env = dict(os.environ)
        paths = [str(code)]
        if (code / "src").is_dir():
            paths.append(str(code / "src"))
        if env.get("PYTHONPATH"):
            paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(paths)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        cmd = [
            python, "-m", "pytest", "tests",
            "-c", str(ini), "--rootdir", str(tmp_path),
            "-p", "no:cacheprovider", "-q", "--tb=line",
            f"--junitxml={junit}", "-o", "junit_family=xunit2",
        ]
        try:
            proc = subprocess.run(
                cmd, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=timeout
            )
            run.returncode = proc.returncode
            out = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired as exc:
            run.timed_out = True
            run.returncode = -1
            out = str(exc.stdout or "")
        run.output_tail = "\n".join(out.strip().splitlines()[-20:])
        run.outcomes = parse_junit(junit)
        if run.returncode == 4 or (not run.outcomes and run.returncode not in (0, 5)):
            if "No module named pytest" in out:
                raise RoomError(f"pytest is not installed for {python}")
    return run


def grade(
    room: Path,
    fixed: Path,
    buggy: List[Tuple[str, Path]],
    timeout: float = 600.0,
    python: Optional[str] = None,
) -> Grade:
    problems = verify_seal(room)
    if problems:
        raise RoomError("seal check failed: " + "; ".join(problems))
    if not buggy:
        raise RoomError("at least one --buggy revision is required")
    labels = [lbl for lbl, _ in buggy]
    if len(set(labels)) != len(labels) or "fixed" in labels:
        raise RoomError("buggy revision labels must be unique and not 'fixed'")
    test_files = sorted(load_seal(room)["tests"])

    fixed_run = run_revision(room, test_files, "fixed", fixed, timeout, python)
    buggy_runs = [run_revision(room, test_files, lbl, p, timeout, python) for lbl, p in buggy]
    g = Grade(fixed=fixed_run, buggy=buggy_runs)

    all_ids = sorted(set(fixed_run.outcomes).union(*[b.outcomes for b in buggy_runs]))
    g.caught = {b.label: [] for b in buggy_runs}
    for tid in all_ids:
        on_fixed = fixed_run.outcomes.get(tid, "missing")
        fails_on = []
        for b in buggy_runs:
            o = b.outcomes.get(tid, "missing")
            if o in (FAIL, ERROR, "missing"):
                fails_on.append(b.label)
        if on_fixed == PASS:
            verdict = "catches" if fails_on else "blind"
            for lbl in fails_on:
                g.caught[lbl].append(tid)
        elif on_fixed == SKIP:
            verdict = "skipped"
        else:
            verdict = "wrong"
        g.tests[tid] = {"fixed": on_fixed, "fails_on": fails_on if on_fixed == PASS else [], "verdict": verdict}
    return g
