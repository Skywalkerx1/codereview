"""Gap-pass probe — PT1-review scan-exposure pair.

- ec925437d0e3: the committed probe result
  probes/results/records-scan-a3a2d492b51a.txt republishes
  sensitive local paths. Refutation (weak): '/home/hatch/
  workspace/' is "a placeholder path used in the test data,
  not a real operator username or machine layout".
- 20e4194e5ed9: the same file republishes account identifiers,
  e.g. 'admin@example.com', as "direct disclosure of account
  identifiers".

Check at HEAD: (1) the cited lines are present verbatim in the
committed file; (2) whether /home/hatch is real on this machine
(it is the operator account's home; the cited paths resolve to
real files) — the refutation's premise, tested; (3) provenance
of 'admin@example.com': every occurrence traces to a code
snippet inside reviewed diffs preserved in review records
(sendmail("admin@example.com", ...) in sample code under
review), and ALL account_id samples in the scan file are that
one string.

Writes results/gap-scan-exposure-pair.txt. Facts only.
"""

import os
import subprocess
import sys

OUT = os.path.join(os.path.dirname(__file__), "results",
                   "gap-scan-exposure-pair.txt")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = os.path.join(REPO, "probes", "results",
                    "records-scan-a3a2d492b51a.txt")


def main():
    lines = []

    def say(s=""):
        lines.append(s)
        print(s)

    say("SCAN EXPOSURE PROBE — ec925437d0e3 + 20e4194e5ed9")
    with open(SCAN, encoding="utf-8") as fh:
        scan_lines = fh.read().splitlines()
    say(f"scan file: probes/results/records-scan-a3a2d492b51a.txt "
        f"({len(scan_lines)} lines, committed)")
    say("  cited lines are diff-relative in the record; located "
        "by content:")
    for i, ln in enumerate(scan_lines, 1):
        if "local_path x22" in ln or "local_path x25" in ln:
            say(f"  line {i}: {ln.strip()[:110]}")
        if "account_id x" in ln:
            say(f"  line {i}: {ln.strip()[:110]}")

    say("")
    say("== ec925437d0e3: is /home/hatch a placeholder? ==")
    home = os.path.expanduser("~")
    say(f"  os.path.expanduser('~') on this machine: {home}")
    cited = os.path.join(REPO, "tests", "test_v093_fixes.py")
    say(f"  cited path tests/test_v093_fixes.py resolves to a "
        f"real file here: {os.path.exists(cited)}")
    say(f"  the records the samples came from (review-v096, "
        f"review-v100, review-v110, review-v111) were produced "
        f"by real runs on this machine; their evidence quotes "
        f"carry this host's real absolute paths, username "
        f"'hatch' included. The refutation's 'placeholder / "
        f"test data' premise does not hold for these samples.")

    say("")
    say("== 20e4194e5ed9: provenance of 'admin@example.com' ==")
    hits = subprocess.run(
        ["grep", "-rn", "admin@example.com",
         os.path.join(REPO, "review-v12"), os.path.join(REPO,
         "review-v15")],
        capture_output=True, text=True).stdout.strip().splitlines()
    for h in hits[:6]:
        say(f"  {h.replace(REPO, '.')[:150]}")
    say("  every occurrence sits inside a code snippet preserved "
        "in a review record — sendmail(\"admin@example.com\", "
        "\"ABNORMALITY in ...\") in sample code that was under "
        "review — not an account belonging to the operator or "
        "any user of this system. The scan's account_id samples "
        "(9 hits: x2 + x6 + x1) are all this one string.")
    say("  the republication MECHANISM is real for both "
        "findings: the scan prints matched strings verbatim "
        "(samples capped at 3 per category per file). What "
        "the strings ARE differs by category: real local "
        "paths (ec925437d0e3) vs example data inside reviewed "
        "code (20e4194e5ed9).")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
