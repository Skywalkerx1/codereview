#!/usr/bin/env python3
"""Closing-A probe — attempt-2 07a9a2646925 / attempt-1 023d2c9b1b20:
zero/negative batch budget allegedly loops forever in
_batch_sections_detailed / _split_section (`range(0, len, room)`).

Each budget runs in a SUBPROCESS with a hard timeout, so a real
hang would be reported as a timeout instead of hanging the probe.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS, "closingA-batch-budget.txt")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


CHILD = r"""
import sys
sys.path.insert(0, {src!r})
from codereview import core
budget = int(sys.argv[1])
sections = [("a.py", "diff --git a/a.py b/a.py\n" + "+x = 1\n" * 40),
            ("b.py", "diff --git a/b.py b/b.py\n" + "+y = 2\n" * 10)]
batches, files, incomplete = core._batch_sections_detailed(sections, budget)
b2, inc2 = core._batch_sections(sections, budget)
pieces, unplaceable = core._split_section(sections[0][1], budget)
print(f"budget={{budget}} detailed_batches={{len(batches)}} "
      f"incomplete={{incomplete}} batch_sections incomplete={{inc2}} "
      f"split_pieces={{len(pieces)}} unplaceable={{unplaceable}}")
""".format(src=os.path.join(REPO, "src"))

for budget in (0, -3, 1):
    try:
        proc = subprocess.run(
            [sys.executable, "-c", CHILD, str(budget)],
            capture_output=True, text=True, timeout=15)
        emit(f"budget {budget}: exit={proc.returncode} "
             f"{proc.stdout.strip()} {proc.stderr.strip()[-200:]}")
    except subprocess.TimeoutExpired:
        emit(f"budget {budget}: TIMEOUT after 15s — LOOP CONFIRMED")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
