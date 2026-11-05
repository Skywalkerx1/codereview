#!/usr/bin/env python3
"""Closing-A probe — attempt-2 7514429a36b2 (render_markdown
references 'grounding' field allegedly not guaranteed) and
7c8ec49fb549 (render_markdown tier/family without schema guarantee).

Render reports whose findings carry NO 'grounding' key at all and
whose reviewer_reports carry NO 'family'/'tier' keys at all, plus
mixed variants, and watch for KeyError/crash vs clean output.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS, "closingA-render-fields.txt")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


def try_render(label, report):
    try:
        md = core.render_markdown(report)
        interesting = [ln for ln in md.splitlines()
                       if "seatA" in ln or "seatB" in ln
                       or "seatC" in ln or "Bare finding" in ln]
        emit(f"{label}: RENDERED ok ({len(md)} chars)")
        for ln in interesting:
            emit(f"  {ln}")
    except BaseException as exc:  # noqa: BLE001
        emit(f"{label}: RAISED {type(exc).__name__}: {exc}")


BASE = {"mode": "review", "gate": "blocked", "created_at": "t",
        "patch_sha256": "0" * 64}
FINDING = {"id": "f1", "severity": "major", "title": "Bare finding",
           "file": "a.py", "line": 3, "sources": ["seatA"],
           "consensus": False, "evidence": "ev", "recommendation": "fix"}
# NOTE: FINDING deliberately has no "grounding" key.

try_render("no grounding + no family/tier keys",
           {**BASE, "findings": [dict(FINDING)],
            "reviewer_reports": [
                {"provider": "seatA", "status": "ok", "lens": "verify"}]})
try_render("family present, tier key absent",
           {**BASE, "findings": [dict(FINDING)],
            "reviewer_reports": [
                {"provider": "seatB", "status": "ok", "lens": "verify",
                 "family": "famX"}]})
try_render("tier present, family absent; finding grounding present",
           {**BASE, "findings": [dict(FINDING, grounding="unresolved")],
            "reviewer_reports": [
                {"provider": "seatC", "status": "ok", "lens": "verify",
                 "tier": "pro"}]})

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
