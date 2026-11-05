"""Regression tests for the VERIFY-mode evidence-visibility fix.

The closing chain's verification rounds (2026-11-05) could not
clear round-1 blockers because the panel literally could not
see the fix evidence:

1. Verify prompt construction showed seats an ~80k-char PREFIX
   of the delta. On a 2.37M-char delta dominated by committed
   record directories, the src/ fix hunks sat at offset ~2.32M —
   outside the slice. (Review mode already solved this with
   sectioned batching + the §5.4 archived-text exclusion;
   verify applied the exclusion only to findings
   classification, not to prompt construction.)
2. Prior findings were serialised into the prompt truncated at
   20,000 chars (29,849 needed for 20 blockers) — findings
   #15-#20 never reached the seats and defaulted to "unclear".

These tests pin the fixed behaviour: archived material never
consumes the evidence window, every kept hunk is reachable in
some batch, and every prior finding reaches every seat.
"""

import json
import re
import unittest

from codereview import core


def _section(path, added_lines):
    body = "".join(f"+{ln}\n" for ln in added_lines)
    return (f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n"
            f"@@ -0,0 +1,{len(added_lines)} @@\n{body}")


def _finding(fid, file="src/app.py", sources=("a",)):
    return {"id": fid, "severity": "major",
            "category": "reliability", "file": file, "line": 6,
            "title": f"Finding {fid}",
            "evidence": "the alert path has no dedup guard",
            "evidence_quote": "sendmail in loop",
            "recommendation": "add a dedup guard",
            "confidence": 0.8, "sources": list(sources),
            "consensus": False}


class BatchPriorFindingsTests(unittest.TestCase):
    def test_every_finding_in_exactly_one_batch(self):
        prior = [_finding(f"f{i:02d}") for i in range(30)]
        # Force small batches: each finding serialises to ~450
        # chars, so a 2000-char budget holds ~4.
        batches = core._batch_prior_findings(prior, max_chars=2000)
        self.assertGreater(len(batches), 1)
        seen = [fid for _text, ids in batches for fid in ids]
        self.assertEqual(sorted(seen),
                         sorted(f["id"] for f in prior))
        for text, _ids in batches:
            self.assertLessEqual(len(text), 2000 + 500)

    def test_oversized_single_finding_gets_own_whole_batch(self):
        big = _finding("big1")
        big["evidence"] = "x" * 25000 + " TAILMARKER"
        batches = core._batch_prior_findings(
            [_finding("small1"), big, _finding("small2")],
            max_chars=20000)
        texts = [t for t, _ids in batches]
        carrier = [t for t in texts if "TAILMARKER" in t]
        self.assertEqual(len(carrier), 1)
        # The batch is over budget but COMPLETE — never cut.
        self.assertGreater(len(carrier[0]), 20000)
        self.assertIn('"small1"', "".join(texts))
        self.assertIn('"small2"', "".join(texts))

    def test_empty_prior_yields_one_empty_batch(self):
        self.assertEqual(core._batch_prior_findings([]),
                         [("[]", [])])


class CombineResolutionTests(unittest.TestCase):
    FILES = [["src/a.py"], ["src/b.py"]]

    def _entry(self, status):
        return {"status": status, "evidence": "e"}

    def test_still_present_stands_over_fixed(self):
        out = core._combine_resolution(
            [(0, self._entry("fixed")),
             (1, self._entry("still_present"))],
            _finding("x", file="src/b.py"), self.FILES)
        self.assertEqual(out["status"], "still_present")

    def test_clear_beats_uninformed_unclear(self):
        out = core._combine_resolution(
            [(0, self._entry("unclear")),
             (1, self._entry("fixed"))],
            _finding("x", file="src/b.py"), self.FILES)
        self.assertEqual(out["status"], "fixed")

    def test_file_matching_pass_preferred_among_clears(self):
        out = core._combine_resolution(
            [(0, self._entry("fixed")),
             (1, self._entry("invalid"))],
            _finding("x", file="src/b.py"), self.FILES)
        self.assertEqual(out["status"], "invalid")

    def test_all_unclear_stays_unclear(self):
        out = core._combine_resolution(
            [(0, self._entry("unclear")),
             (1, self._entry("unclear"))],
            _finding("x"), self.FILES)
        self.assertEqual(out["status"], "unclear")


class VerifyEvidenceVisibilityTests(unittest.TestCase):
    """The synthetic large-delta case: archived record material
    dominates the delta and the fix hunk sits beyond an 80k
    prefix — every kept hunk and every finding must still reach
    the panel, and the round must be able to clear."""

    FIX_LINE = "DEDUP_GUARD = True  # one alert per violation"

    def _delta(self):
        filler = [f"ARCHIVED_FILLER line {i} " + "y" * 40
                  for i in range(700)]  # ~35k chars per section
        parts = [
            _section("review-closing-r1/record.json", filler),
            _section("review-v15/record.md", filler),
            _section("review-closing-verify/notes.txt", filler),
            _section("src/other.py",
                     [f"unrelated change {i}" for i in range(50)]),
            _section("src/app.py", [
                "def send_alert(violation):",
                f"    {self.FIX_LINE}",
                "    sendmail(violation)",
            ]),
        ]
        return "".join(parts)

    def test_fix_beyond_80k_prefix_reaches_panel_and_clears(self):
        patch = self._delta()
        offset = patch.index(self.FIX_LINE)
        self.assertGreater(offset, 80000)  # outside the old slice
        prompts = []

        def seat(prompt):
            prompts.append(prompt)
            resolutions = []
            if '"id": "fix1"' in prompt:
                if self.FIX_LINE in prompt:
                    resolutions.append({
                        "finding_id": "fix1", "status": "fixed",
                        "evidence": "DEDUP_GUARD = True added in "
                                    "src/app.py; the alert path "
                                    "now dedups per violation"})
                else:
                    resolutions.append({
                        "finding_id": "fix1", "status": "unclear",
                        "evidence": "fix not in this section"})
            return json.dumps({"resolutions": resolutions,
                               "new_findings": []})

        previous = {"gate": "blocked",
                    "findings": [_finding("fix1")]}
        report = core.run_verification(
            patch, {"a": seat, "b": seat}, previous,
            "added the dedup guard in src/app.py",
            max_patch_chars=20000)
        # Archived material never consumed the evidence window.
        self.assertTrue(all("ARCHIVED_FILLER" not in p
                            for p in prompts))
        self.assertEqual(
            {e["path"] for e in report["archived_exclusions"]},
            {"review-closing-r1/record.json",
             "review-v15/record.md",
             "review-closing-verify/notes.txt"})
        # The fix hunk WAS reachable by the panel.
        self.assertTrue(any(self.FIX_LINE in p for p in prompts))
        # ...and the round could therefore clear.
        self.assertFalse(report["truncated"])
        self.assertEqual(report["gate"], "pass",
                         report["gate_reasons"])
        self.assertEqual([f["id"] for f in report["cleared"]],
                         ["fix1"])
        for rec in report["reviewer_reports"]:
            self.assertEqual(rec["judged_finding_ids"], ["fix1"])

    def test_more_than_20k_of_findings_all_reach_panel(self):
        # 24 findings x ~1.3k serialised = >30k chars of prior
        # findings — the old 20,000-char cut dropped the tail.
        prior = []
        for i in range(24):
            f = _finding(f"bulk{i:02d}")
            f["evidence"] = ("detailed evidence narrative "
                             + "z" * 1100)
            prior.append(f)
        serialised = json.dumps(prior, ensure_ascii=False,
                                indent=1)
        self.assertGreater(len(serialised), 20000)
        seen_ids = set()

        def seat(prompt):
            resolutions = []
            for fid in re.findall(r'"id":\s*"(bulk\d+)"', prompt):
                seen_ids.add(fid)
                resolutions.append({
                    "finding_id": fid, "status": "fixed",
                    "evidence": "the dedup guard line is present "
                                "in the src/app.py diff section"})
            return json.dumps({"resolutions": resolutions,
                               "new_findings": []})

        patch = _section("src/app.py", [
            "def send_alert(violation):",
            f"    {self.FIX_LINE}",
            "    sendmail(violation)"])
        previous = {"gate": "blocked", "findings": prior}
        report = core.run_verification(
            patch, {"a": seat, "b": seat}, previous, "fixed all")
        self.assertEqual(seen_ids, {f["id"] for f in prior})
        self.assertEqual(report["gate"], "pass",
                         report["gate_reasons"])
        self.assertEqual(len(report["cleared"]), 24)
        self.assertEqual(report["remaining"], [])


if __name__ == "__main__":
    unittest.main()
