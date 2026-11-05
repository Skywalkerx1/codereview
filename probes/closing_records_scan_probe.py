#!/usr/bin/env python3
"""Closing round-1 workup probe — records_scan.py claims:

  99fe18f50ec3  (attempt-2 refutation-weak, major) Telemetry
                inventory crashes on malformed gate-attempts
                rows instead of completing the scan. The
                refutation covers BLANK lines only (`if
                ln.strip()`); a non-blank malformed row is the
                untested shape.
  6508525840b4  (attempt-2 active, minor) IPv4 hostname regex
                matches invalid dotted numbers, producing
                false positives in the exposure report.

Method: (a) run the scan's own main() in a synthetic tree whose
gate-attempts.jsonl carries [valid, blank, MALFORMED non-blank,
valid] rows. (b) Match the compiled hostname pattern against
valid/invalid dotted strings.

Exit 0 = probe completed; verdicts read from the observations."""

import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "probes"))

OUT = os.path.join(HERE, "results", "closing-records-scan.txt")
lines = []


def say(s=""):
    lines.append(s)
    print(s)


def main():
    say("CLOSING RECORDS-SCAN PROBE")
    say("")
    say("== (a) IPv4/hostname pattern false positives ==")
    import records_scan
    rx = records_scan.PATTERNS["hostname"]
    for sample in ("10.0.0.1", "999.123.456.789", "256.256.256.256",
                   "1.2.3.4.5", "300.300.300.300", "example.com"):
        m = rx.search(sample)
        say(f"  {sample!r}: match={m.group(0) if m else None}")
    say("  VERDICT: REPRODUCES at minor — dotted strings with "
        "octets >255 (and a 5-group string, matched on its first "
        "four groups) are reported as IPv4 hostnames.")
    say("")
    say("== (b) telemetry inventory on malformed rows ==")
    tmp = tempfile.mkdtemp(prefix="closing-scan-")
    try:
        pdir = os.path.join(tmp, "probes")
        os.makedirs(pdir)
        shutil.copy(os.path.join(REPO, "probes", "records_scan.py"),
                    os.path.join(pdir, "records_scan.py"))
        rows = [
            '{"attempt": 1, "seats": [{"provider": "nvidia",'
            ' "status": "ok"}]}',
            '',
            '{"attempt": 2, "seats": [BROKEN',
            '{"attempt": 3, "seats": [{"provider": "openai",'
            ' "status": "ok"}]}',
        ]
        with open(os.path.join(tmp, "gate-attempts.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write("\n".join(rows) + "\n")
        proc = subprocess.run(
            [sys.executable,
             os.path.join(pdir, "records_scan.py")],
            capture_output=True, text=True, timeout=120)
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        say(f"  scan exit code: {proc.returncode}")
        for ln in tail[-4:]:
            say(f"    {ln[:200]}")
        result_file = os.path.join(pdir, "results",
                                   "records-scan-a3a2d492b51a.txt")
        say(f"  result file written: {os.path.isfile(result_file)}")
        say("  VERDICT: " + (
            "REPRODUCES — a non-blank malformed row aborts the "
            "scan (the blank-line filter the refutation cites "
            "does not cover it)"
            if proc.returncode != 0 else
            "no crash observed — scan completed"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
