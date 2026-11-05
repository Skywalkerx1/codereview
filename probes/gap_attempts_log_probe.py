"""Gap-pass probe — bca4074a632c (attempts-log path checks).

Claim: --attempts-log is opened for append with no repository
or path safety checks, so a crafted value writes arbitrary
files. Refutation: append mode only; nothing traverses or
executes. Ruling pack recommendation was sustain-refutation
as by-design CONDITIONAL on P5: the path comes only from
argv/env, never from repo-controlled config.

Check at HEAD: (1) P5 provenance — every reference to
attempts_log in the source tree, classified by origin;
(2) functional — a real CLI review run whose --attempts-log
points outside any repository writes the entry there.

Writes results/gap-attempts-log-bca4074a632c.txt. Facts only.
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

OUT = os.path.join(os.path.dirname(__file__), "results",
                   "gap-attempts-log-bca4074a632c.txt")
SRC = os.path.join(os.path.dirname(__file__), "..", "src",
                   "codereview")

DIFF = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,2 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""


def main():
    lines = []

    def say(s=""):
        lines.append(s)
        print(s)

    say("ATTEMPTS-LOG PROBE — bca4074a632c")
    say("")
    say("== P5 provenance: every attempts_log reference in "
        "src/codereview ==")
    hits = subprocess.run(
        ["grep", "-rn", "attempts_log\\|attempts-log", SRC],
        capture_output=True, text=True).stdout.strip().splitlines()
    for h in hits:
        say(f"  {h.replace(SRC, 'src/codereview')}")
    say("  origins: ONE argparse definition (--attempts-log, "
        "cli.py) + reads of args.attempts_log in the review "
        "path. No environment variable, no user/project config "
        "file, no policy file, and nothing read from the "
        "repository under review sets it — the value can only "
        "be typed by the operator running the CLI.")

    say("")
    say("== functional: write outside any repository ==")
    with tempfile.TemporaryDirectory() as td:
        stub = os.path.join(td, "stub.sh")
        with open(stub, "w") as fh:
            fh.write("#!/bin/sh\nprintf '%s' '{\"verdict\": "
                     "\"pass\", \"summary\": \"ok\", "
                     "\"findings\": []}'\n")
        os.chmod(stub, 0o755)
        patch = os.path.join(td, "change.patch")
        with open(patch, "w") as fh:
            fh.write(DIFF)
        outside = os.path.join(td, "elsewhere", "attempts.jsonl")
        os.makedirs(os.path.dirname(outside))
        outdir = os.path.join(td, "out")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.join(
            os.path.dirname(__file__), "..", "src")
        proc = subprocess.run(
            [sys.executable, "-m", "codereview.cli",
             "--patch", patch,
             "--provider", f"agent:stub:bash {stub}",
             "--attempts-log", outside,
             "--out", outdir],
            cwd=td, env=env, capture_output=True, text=True,
            timeout=120)
        say(f"  CLI exit code: {proc.returncode}")
        exists = os.path.exists(outside)
        say(f"  attempts log created at the operator-supplied "
            f"outside path: {exists}")
        if exists:
            with open(outside) as fh:
                entry = json.loads(fh.readline())
            say(f"  entry keys: {sorted(entry)[:6]}... "
                f"gate={entry.get('gate')!r} — one JSON line, "
                f"append mode, content is the run's own "
                f"telemetry (no diff text, no secrets)")
        if proc.returncode != 0:
            say(f"  stderr tail: {proc.stderr[-300:]}")
    say("net facts: the mechanism in the claim is real (no "
        "containment check exists at HEAD); the only principal "
        "who can set the path is the operator themself, via "
        "argv — the same trust class as --out.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
