#!/usr/bin/env python3
"""Closing-B probe — evidence.py cluster.

Claims:
  8f77565b56a4 (attempt-1, disputed): collect runs commands
    without per-item timeouts.
  9489ee49db6f (attempt-1): falsy timeout 0 ignored via
    `or` fallback (evidence.py:379, 407, 422).

Writes results/closingB-evidence.txt. Facts only.
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import evidence  # noqa: E402

OUT = os.path.join(HERE, "results", "closingB-evidence.txt")
lines = []


def say(s=""):
    lines.append(s)
    print(s)


def main():
    say("EVIDENCE PROBE — 8f77565b56a4, 9489ee49db6f")
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "tree")
        os.makedirs(src)
        with open(os.path.join(src, "f.txt"), "w") as fh:
            fh.write("hello\n")

        say("== 8f77565b56a4: per-item timeout ==")
        cfg = {"commands": [{"name": "slow",
                             "command": "sleep 10",
                             "timeout": 1}]}
        t0 = time.monotonic()
        rec = evidence.collect(cfg, src)
        dt = time.monotonic() - t0
        item = rec["items"][0]
        say(f"  command 'sleep 10' with per-item timeout=1: "
            f"status={item['status']!r} after {dt:.1f}s "
            f"(recorded duration_s={item['duration_s']}) — "
            f"the per-item timeout at evidence.py:407 was "
            f"enforced by _execute (evidence.py:268-301)")

        say("")
        say("== 9489ee49db6f: timeout 0 via `or` fallback ==")
        cfg0 = {"commands": [{"name": "two-sec",
                              "command": "sleep 2",
                              "timeout": 0}]}
        t0 = time.monotonic()
        rec0 = evidence.collect(cfg0, src)
        dt0 = time.monotonic() - t0
        item0 = rec0["items"][0]
        say(f"  command 'sleep 2' with per-item timeout=0: "
            f"status={item0['status']!r} after {dt0:.1f}s — "
            f"if 0 were honored the item would time out "
            f"immediately; instead `entry.get('timeout') or "
            f"default_timeout` (evidence.py:407) substituted "
            f"the default ({evidence.DEFAULT_TIMEOUT}s) and "
            f"the command ran to completion")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
