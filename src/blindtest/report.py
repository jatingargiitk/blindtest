"""Plain-text rendering of a grade."""

from __future__ import annotations

from typing import List

from .grade import Grade


def render(g: Grade) -> str:
    lines: List[str] = []
    n_fixed_pass = sum(1 for o in g.fixed.outcomes.values() if o == "pass")
    lines.append(
        f"fixed revision: {n_fixed_pass}/{len(g.fixed.outcomes)} sealed tests pass"
        + (" (timed out)" if g.fixed.timed_out else "")
    )
    caught = len(g.buggy) - len(g.missed)
    lines.append(f"buggy revisions caught: {caught}/{len(g.buggy)}")
    lines.append("")
    width = max([len(b.label) for b in g.buggy] + [6])
    for b in g.buggy:
        tids = g.caught.get(b.label, [])
        extra = " (timed out)" if b.timed_out else ""
        if tids:
            lines.append(f"  {b.label.ljust(width)}  CAUGHT by {len(tids)} test(s){extra}")
        else:
            lines.append(f"  {b.label.ljust(width)}  MISSED, no test that passes on fixed fails here{extra}")
        for t in tids:
            lines.append(f"  {' ' * width}    - {t}")
    lines.append("")

    groups = {"catches": [], "blind": [], "wrong": [], "skipped": []}
    for tid, d in g.tests.items():
        groups[d["verdict"]].append(tid)
    lines.append(
        "tests: "
        f"{len(groups['catches'])} catch a bug, "
        f"{len(groups['blind'])} pass on every revision, "
        f"{len(groups['wrong'])} fail on the fixed revision, "
        f"{len(groups['skipped'])} skipped"
    )
    if groups["wrong"]:
        lines.append("")
        lines.append("fail on the fixed revision (the test disagrees with the code you trust):")
        for t in groups["wrong"]:
            lines.append(f"  - {t} [{g.tests[t]['fixed']}]")
    if groups["blind"]:
        lines.append("")
        lines.append("pass on every revision (catch none of the supplied bugs):")
        for t in groups["blind"]:
            lines.append(f"  - {t}")
    lines.append("")
    lines.append("verdict: " + ("PASS" if g.ok else "FAIL"))
    if not g.ok:
        reasons = []
        if not any(o == "pass" for o in g.fixed.outcomes.values()):
            reasons.append("no sealed test passes on the fixed revision")
        if g.wrong:
            reasons.append(f"{len(g.wrong)} test(s) fail on the fixed revision")
        if g.missed:
            reasons.append("missed: " + ", ".join(g.missed))
        lines.append("  " + "; ".join(reasons))
    return "\n".join(lines) + "\n"
