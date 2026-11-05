"""Gap-pass probe — c5f02551d077 (verification quorum).

Claim: with multiple providers configured but only one
succeeding, "later logic can still return pass when there are
no open findings and degraded is false in non-strict mode".

Check (HEAD): drive core.run_verification in the claim's exact
scenario — 2 configured seats, 1 raises, the survivor clears the
prior blocker with the finder among the successful — in both
relaxed and strict modes; plus the two controls (both succeed ->
pass; solo panel -> pass with the solo label that v0.9.6 shipped
citing this finding).

Writes results/gap-quorum-c5f02551d077.txt. Facts only.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "results",
                   "gap-quorum-c5f02551d077.txt")

CLEAN = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,2 +1,2 @@
 def add(a, b):
     return a + b
"""

EVIDENCE = ("return a + b and return a - b are the only helpers "
            "left in app/util.py and the sendmail alert is removed")


def _previous():
    return {"gate": "blocked", "findings": [{
        "id": "abc123", "severity": "major",
        "category": "reliability", "file": "app/alerts.py",
        "line": 6, "title": "Alert has no dedup",
        "evidence": "", "recommendation": "", "confidence": 0.8,
        "sources": ["a"], "consensus": False}]}


def _fixed(_prompt):
    return json.dumps({
        "resolutions": [{"finding_id": "abc123", "status": "fixed",
                         "evidence": EVIDENCE}],
        "new_findings": []})


def _boom(_prompt):
    raise RuntimeError("provider down")


def main():
    lines = []

    def say(s=""):
        lines.append(s)
        print(s)

    say("QUORUM PROBE — c5f02551d077")
    say("function under test: core.run_verification (HEAD)")
    for strict in (False, True):
        rep = core.run_verification(
            CLEAN, {"a": _fixed, "b": _boom}, _previous(), "fixed",
            strict=strict)
        say(f"  2 configured / 1 succeeds / finder cleared / "
            f"strict={strict}: gate={rep['gate']!r} "
            f"reasons={rep['gate_reasons']}")
    rep = core.run_verification(
        CLEAN, {"a": _fixed, "b": _fixed}, _previous(), "fixed")
    say(f"  control, both succeed: gate={rep['gate']!r} "
        f"cleared={len(rep['cleared'])}")
    rep = core.run_verification(
        CLEAN, {"a": _fixed}, _previous(), "fixed")
    say(f"  control, solo panel (1 configured): gate="
        f"{rep['gate']!r} reasons={rep['gate_reasons']}")
    say("gate order at HEAD (core.py run_verification): "
        "no-success -> inconclusive; open items -> blocked; "
        "unjudged -> inconclusive; NOT quorum_ok -> "
        "inconclusive — all BEFORE the pass branch, in both "
        "modes. quorum_ok = len(ok_recs) >= 2 or "
        "len(providers) <= 1.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
