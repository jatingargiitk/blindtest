"""The clean room: a directory holding only the spec and interface files.

blindtest does not sandbox the agent. It controls what is *in* the working
directory the agent is started in, records hashes of every input, and seals
the tests the agent wrote so they cannot change between writing and grading.
Run the agent in a container if you need real isolation.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional

META_DIR = ".blindtest"
MANIFEST = "manifest.json"
SEAL = "seal.json"
TESTS_DIR = "tests"
INSTRUCTIONS = "BLINDTEST.md"


class RoomError(Exception):
    """Raised for anything wrong with a room, its inputs or its seal."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _room_relpath(src: Path, base: Path) -> str:
    """Where an input file lives inside the room's inputs/ folder."""
    src = src.resolve()
    try:
        rel = src.relative_to(base.resolve())
    except ValueError:
        rel = Path(src.name)
    return rel.as_posix()


def instructions_text(specs: List[str], interfaces: List[str]) -> str:
    lines = [
        "# Write tests from the spec only",
        "",
        "You are writing tests for code you cannot see. Everything you are allowed",
        "to know is in `inputs/`:",
        "",
    ]
    for s in specs:
        lines.append(f"- spec: `inputs/{s}`")
    for i in interfaces:
        lines.append(f"- interface: `inputs/{i}`")
    lines += [
        "",
        "Rules:",
        "",
        "1. Write pytest tests under `tests/` (files named `test_*.py`).",
        "2. Import the code under test by the module names in the interface files.",
        "   The real implementation is put on the import path when the tests are graded.",
        "3. Test behaviour the spec states. Do not guess at behaviour it leaves open.",
        "4. Do not edit anything in `inputs/`.",
        "",
    ]
    return "\n".join(lines)


def prepare(
    out: Path,
    specs: Iterable[Path],
    interfaces: Iterable[Path] = (),
    base: Optional[Path] = None,
    force: bool = False,
) -> Dict:
    """Create a room at ``out`` holding copies of the spec and interface files."""
    base = base or Path.cwd()
    specs = [Path(p) for p in specs]
    interfaces = [Path(p) for p in interfaces]
    if not specs:
        raise RoomError("at least one --spec file is required")
    for p in specs + interfaces:
        if not p.is_file():
            raise RoomError(f"input is not a file: {p}")

    if out.exists():
        if not force:
            raise RoomError(f"{out} already exists (use --force to replace it)")
        shutil.rmtree(out)
    (out / "inputs").mkdir(parents=True)
    (out / TESTS_DIR).mkdir()
    (out / META_DIR).mkdir()

    entries = []
    seen = set()
    for kind, paths in (("spec", specs), ("interface", interfaces)):
        for p in paths:
            rel = _room_relpath(p, base)
            if rel in seen:
                raise RoomError(f"two inputs map to the same room path: {rel}")
            seen.add(rel)
            dest = out / "inputs" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
            entries.append({"kind": kind, "path": rel, "sha256": sha256_file(dest)})

    (out / INSTRUCTIONS).write_text(
        instructions_text(
            [e["path"] for e in entries if e["kind"] == "spec"],
            [e["path"] for e in entries if e["kind"] == "interface"],
        ),
        encoding="utf-8",
    )
    manifest = {
        "version": 1,
        "created_at": _now(),
        "inputs": entries,
        "instructions_sha256": sha256_file(out / INSTRUCTIONS),
    }
    _write_json(out / META_DIR / MANIFEST, manifest)
    return manifest


def load_manifest(room: Path) -> Dict:
    path = room / META_DIR / MANIFEST
    if not path.is_file():
        raise RoomError(f"{room} is not a blindtest room (no {META_DIR}/{MANIFEST})")
    return json.loads(path.read_text(encoding="utf-8"))


def check_inputs(room: Path) -> List[str]:
    """Return a list of problems with the room's inputs (empty when untouched)."""
    manifest = load_manifest(room)
    problems = []
    for e in manifest["inputs"]:
        p = room / "inputs" / e["path"]
        if not p.is_file():
            problems.append(f"input removed: inputs/{e['path']}")
        elif sha256_file(p) != e["sha256"]:
            problems.append(f"input changed: inputs/{e['path']}")
    known = {e["path"] for e in manifest["inputs"]}
    inputs_root = room / "inputs"
    for p in sorted(inputs_root.rglob("*")):
        if p.is_file() and p.relative_to(inputs_root).as_posix() not in known:
            problems.append(f"input added: inputs/{p.relative_to(inputs_root).as_posix()}")
    return problems


def collect_tests(room: Path) -> List[str]:
    """Every .py file under the room's tests/ folder, as room-relative paths."""
    tdir = room / TESTS_DIR
    files = []
    for p in sorted(tdir.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        files.append(p.relative_to(room).as_posix())
    return files


def other_files(room: Path) -> List[str]:
    """Files the agent left outside inputs/, tests/ and the metadata folder."""
    skip_top = {"inputs", TESTS_DIR, META_DIR, INSTRUCTIONS}
    out = []
    for p in sorted(room.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(room)
        if rel.parts[0] in skip_top or "__pycache__" in rel.parts:
            continue
        out.append(rel.as_posix())
    return out


def seal(room: Path, run: Optional[Dict] = None) -> Dict:
    """Hash every test file in the room and write the seal."""
    manifest = load_manifest(room)
    tests = collect_tests(room)
    if not any(Path(t).name.startswith("test_") for t in tests):
        raise RoomError(f"no test_*.py files found under {room / TESTS_DIR}")
    data = {
        "version": 1,
        "sealed_at": _now(),
        "manifest_created_at": manifest["created_at"],
        "input_problems": check_inputs(room),
        "other_files": other_files(room),
        "tests": {t: sha256_file(room / t) for t in tests},
    }
    if run is not None:
        data["run"] = run
    _write_json(room / META_DIR / SEAL, data)
    return data


def load_seal(room: Path) -> Dict:
    path = room / META_DIR / SEAL
    if not path.is_file():
        raise RoomError(f"{room} has no seal yet (run `blindtest write` or `blindtest seal`)")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_seal(room: Path) -> List[str]:
    """Return problems with the sealed tests (empty when intact)."""
    data = load_seal(room)
    problems = []
    for rel, digest in data["tests"].items():
        p = room / rel
        if not p.is_file():
            problems.append(f"sealed test removed: {rel}")
        elif sha256_file(p) != digest:
            problems.append(f"sealed test changed: {rel}")
    for rel in collect_tests(room):
        if rel not in data["tests"]:
            problems.append(f"test added after sealing: {rel}")
    return problems


def _write_json(path: Path, data: Dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
