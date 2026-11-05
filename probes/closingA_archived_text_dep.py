#!/usr/bin/env python3
"""Closing-A probe — attempt-2 afe66da23121: verification's
archived-text classification is built from split_patch_sections
output (`_vfy_sections = split_patch_sections(clean_patch)`),
so it allegedly depends on that splitter handling every patch
shape.

Reproduce the verification path's exact composition for three
patch shapes carrying the SAME archived-record content:
 1. canonical unified diff (diff --git ... b/<path> headers);
 2. raw non-diff text (no headers at all);
 3. diff headers without a ` b/` target.
In each, a finding whose quote appears ONLY in the review-record
section: is it classified archived-text or kept?
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS, "closingA-archived-text-dep.txt")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


QUOTE = "the old buggy line from the record"
FINDING = {"id": "fx", "file": "notes.txt", "severity": "major",
           "title": "claim about old code", "evidence_quote": QUOTE}

RECORD_BODY = f"+{QUOTE}\n"
APP_BODY = "+alpha beta gamma\n"

SHAPES = {
    "canonical diff": (
        "diff --git a/src/app.py b/src/app.py\n"
        "+++ b/src/app.py\n@@ -0,0 +1 @@\n" + APP_BODY +
        "diff --git a/review-r1/rec.json b/review-r1/rec.json\n"
        "+++ b/review-r1/rec.json\n@@ -0,0 +1 @@\n" + RECORD_BODY),
    "raw non-diff text": APP_BODY + RECORD_BODY,
    "header without b/ target": (
        "diff --git src/app.py\n" + APP_BODY +
        "diff --git review-r1/rec.json\n" + RECORD_BODY),
}

for label, patch in SHAPES.items():
    # Exact composition used by run_verification at HEAD.
    sections = core.split_patch_sections(patch)
    archived = [s for s in sections if core._archived_rule(s[0])]
    kept_secs = [s for s in sections if not core._archived_rule(s[0])]
    import copy
    kept, arch = core._split_archived_text(
        [copy.deepcopy(FINDING)], {n for n, _t in kept_secs},
        "\n".join(t for _n, t in kept_secs), archived)
    emit(f"{label}: sections={[n for n, _t in sections]} "
         f"archived_sections={[n for n, _t in archived]} "
         f"-> finding kept={len(kept)} archived={len(arch)}"
         + (f" basis={arch[0].get('archived_text')}" if arch else ""))

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
