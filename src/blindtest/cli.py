"""Command line interface for blindtest."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from . import __version__
from .grade import grade
from .report import render
from .room import RoomError, check_inputs, load_manifest, prepare, seal, verify_seal

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def _parse_buggy(values: List[str]) -> List[Tuple[str, Path]]:
    out = []
    for v in values:
        if "=" in v and not Path(v).exists():
            label, path = v.split("=", 1)
        else:
            path = v
            label = Path(v).resolve().name
        out.append((label, Path(path)))
    return out


def cmd_prepare(args) -> int:
    manifest = prepare(Path(args.room), args.spec, args.interface or [], force=args.force)
    print(f"room ready: {args.room}")
    for e in manifest["inputs"]:
        print(f"  {e['kind']:<9} inputs/{e['path']}  {e['sha256'][:12]}")
    print(f"agent instructions: {Path(args.room) / 'BLINDTEST.md'}")
    return EXIT_OK


def cmd_write(args) -> int:
    room = Path(args.room)
    load_manifest(room)
    command = args.command
    if not command:
        raise RoomError("give the agent command after --, e.g. blindtest write ROOM -- my-agent ...")
    env = dict(os.environ)
    env["BLINDTEST_ROOM"] = str(room.resolve())
    env["BLINDTEST_INSTRUCTIONS"] = str((room / "BLINDTEST.md").resolve())
    started = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(command, cwd=room, env=env, timeout=args.timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        code, timed_out = -1, True
    except FileNotFoundError:
        raise RoomError(f"command not found: {command[0]}")
    run = {
        "command": command,
        "exit_code": code,
        "timed_out": timed_out,
        "seconds": round(time.monotonic() - started, 2),
    }
    if code != 0:
        print(f"agent command exited with {code}{' (timed out)' if timed_out else ''}", file=sys.stderr)
        if not args.seal_on_failure:
            return EXIT_FAIL
    return _do_seal(room, run)


def cmd_seal(args) -> int:
    return _do_seal(Path(args.room), None)


def _do_seal(room: Path, run) -> int:
    data = seal(room, run)
    print(f"sealed {len(data['tests'])} test file(s) in {room}")
    for rel, digest in data["tests"].items():
        print(f"  {rel}  {digest[:12]}")
    for p in data["input_problems"]:
        print(f"warning: {p}", file=sys.stderr)
    for p in data["other_files"]:
        print(f"note: agent left a file outside tests/: {p}", file=sys.stderr)
    return EXIT_FAIL if data["input_problems"] else EXIT_OK


def cmd_verify(args) -> int:
    room = Path(args.room)
    problems = check_inputs(room) + verify_seal(room)
    if problems:
        for p in problems:
            print(p)
        return EXIT_FAIL
    print("seal intact: inputs and sealed tests are unchanged")
    return EXIT_OK


def cmd_grade(args) -> int:
    g = grade(
        Path(args.room),
        Path(args.fixed),
        _parse_buggy(args.buggy),
        timeout=args.timeout,
        python=args.python,
    )
    if args.json:
        print(json.dumps(g.to_dict(), indent=2, sort_keys=True))
    else:
        sys.stdout.write(render(g))
    if args.verbose:
        for r in [g.fixed] + g.buggy:
            print(f"\n--- pytest output, {r.label} ---\n{r.output_tail}", file=sys.stderr)
    return EXIT_OK if g.ok else EXIT_FAIL


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="blindtest",
        description="Have an agent write tests from the spec only, seal them, and grade them "
        "against a fixed revision and known-buggy revisions.",
    )
    p.add_argument("--version", action="version", version=f"blindtest {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("prepare", help="create a clean room with only the spec and interface")
    sp.add_argument("room", help="directory to create")
    sp.add_argument("--spec", action="append", required=True, help="spec file (repeatable)")
    sp.add_argument("--interface", action="append", help="interface/stub file (repeatable)")
    sp.add_argument("--force", action="store_true", help="replace an existing room")
    sp.set_defaults(func=cmd_prepare)

    sw = sub.add_parser(
        "write",
        help="run the agent inside the room, then seal its tests",
        usage="blindtest write ROOM [--timeout S] [--seal-on-failure] -- COMMAND [ARGS...]",
    )
    sw.add_argument("room")
    sw.add_argument("--timeout", type=float, default=1800.0, help="seconds (default 1800)")
    sw.add_argument("--seal-on-failure", action="store_true", help="seal even if the agent exits non-zero")
    sw.set_defaults(func=cmd_write)

    ss = sub.add_parser("seal", help="seal tests you had an agent write some other way")
    ss.add_argument("room")
    ss.set_defaults(func=cmd_seal)

    sv = sub.add_parser("verify", help="check inputs and sealed tests are unchanged")
    sv.add_argument("room")
    sv.set_defaults(func=cmd_verify)

    sg = sub.add_parser("grade", help="run sealed tests on the fixed and buggy revisions")
    sg.add_argument("room")
    sg.add_argument("--fixed", required=True, help="directory with the trusted implementation")
    sg.add_argument("--buggy", action="append", required=True,
                    help="directory with a known-buggy implementation, optionally LABEL=DIR (repeatable)")
    sg.add_argument("--timeout", type=float, default=600.0, help="seconds per revision (default 600)")
    sg.add_argument("--python", help="interpreter that has pytest (default: this one)")
    sg.add_argument("--json", action="store_true", help="print the grade as JSON")
    sg.add_argument("-v", "--verbose", action="store_true", help="print pytest output to stderr")
    sg.set_defaults(func=cmd_grade)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command: List[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1:]
    args = build_parser().parse_args(argv)
    args.command = command
    try:
        return args.func(args)
    except RoomError as exc:
        print(f"blindtest: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
