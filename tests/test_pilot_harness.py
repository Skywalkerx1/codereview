"""Tests for the B3 dev-pilot scaffolding (design §8):
bench probe-channel wiring, codereview.pilot's hash split,
eligibility screen, and calibration table. Scripted seats and
in-memory fixtures only — no network, no provider calls, no
live probe executions."""

import copy
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import bench, core, pilot  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")

PAYMENT_DIFF = """diff --git a/billing/charge.py b/billing/charge.py
--- a/billing/charge.py
+++ b/billing/charge.py
@@ -3,4 +3,4 @@ def checkout(order, card):
     # The gateway bills in cents.
     total = order.total_dollars()
-    return gateway.charge(card, int(total * 100))
+    return gateway.charge(card, total)
"""

CLEAN_DIFF = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,2 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""

PAYMENT_EXPECTED = [{
    "severity": "blocker", "category": "correctness",
    "file": "billing/charge.py", "line": 5,
    "title": "Charge amount passed in dollars where the gateway "
             "expects cents",
    "keywords": ["cents", "dollars", "amount"]}]


def _write_case(root, cid, diff, expected, split="public",
                category="correctness"):
    cdir = os.path.join(root, cid)
    os.makedirs(cdir)
    meta = {"id": cid, "title": f"case {cid}", "category": category,
            "split": split, "source": "test fixture",
            "license": "MIT", "expected": expected}
    with open(os.path.join(cdir, "case.json"), "w") as fh:
        json.dump(meta, fh)
    with open(os.path.join(cdir, "diff.patch"), "w") as fh:
        fh.write(diff)


def _finding(**over):
    f = {"id": "f-1", "severity": "major",
         "category": "correctness", "file": "billing/charge.py",
         "line": 5,
         "title": "Parser crashes on empty input",
         "trigger": "Calling parse('') with an empty string "
                    "raises IndexError instead of returning []",
         "evidence": "parse indexes tokens[0] without a length "
                     "check",
         "evidence_quote": "return tokens[0]",
         "sources": ["scripted"], "evidence_class": "E3",
         "confidence": 0.9}
    f.update(over)
    return f


# ------------------------------------------------------------- split

class SplitTests(unittest.TestCase):
    IDS = [f"case-{i:02d}" for i in range(24)]

    def test_deterministic_and_order_independent(self):
        a = pilot.split_cases(self.IDS)
        b = pilot.split_cases(list(reversed(self.IDS)))
        self.assertEqual(a, b)
        self.assertEqual(a, pilot.split_cases(self.IDS))

    def test_disjoint_and_exhaustive(self):
        parts = pilot.split_cases(self.IDS)
        cal, ev = set(parts["calibration"]), set(parts["evaluation"])
        self.assertFalse(cal & ev)
        self.assertEqual(cal | ev, set(self.IDS))
        # Both slices populated for a 24-case set under the
        # default salt (a degenerate one-sided split would make
        # the calibration method meaningless).
        self.assertTrue(cal and ev)

    def test_slice_for_case_agrees_with_partition(self):
        parts = pilot.split_cases(self.IDS)
        for cid in self.IDS:
            self.assertIn(cid, parts[pilot.slice_for_case(cid)])

    def test_manifest_hash_stable_and_verifiable(self):
        m1 = pilot.build_split_manifest(self.IDS)
        m2 = pilot.build_split_manifest(list(reversed(self.IDS)))
        self.assertEqual(m1, m2)  # pure function of the inputs
        self.assertTrue(pilot.verify_split_manifest(m1, self.IDS))

    def test_manifest_detects_reroll(self):
        m = pilot.build_split_manifest(self.IDS)
        # A different case set cannot verify against the manifest.
        self.assertFalse(pilot.verify_split_manifest(
            m, self.IDS + ["case-99"]))
        # A hand-edited partition cannot verify either.
        tampered = copy.deepcopy(m)
        moved = tampered["calibration"].pop()
        tampered["evaluation"].append(moved)
        self.assertFalse(pilot.verify_split_manifest(
            tampered, self.IDS))
        # Nor can the same set under a quietly changed salt.
        other = pilot.build_split_manifest(
            self.IDS, salt="someone-elses-salt")
        self.assertNotEqual(other["inputs_sha256"],
                            m["inputs_sha256"])
        self.assertFalse(pilot.verify_split_manifest(other,
                                                     self.IDS)
                         and other["salt"] == m["salt"])


# ------------------------------------------------------- eligibility

class EligibilityTests(unittest.TestCase):
    def test_executable_claim_with_trigger_is_eligible(self):
        out = pilot.classify_eligibility(_finding())
        self.assertTrue(out["eligible"])
        self.assertEqual(out["basis"], "crash_or_exception")
        self.assertEqual(out["reason"], "eligible")

    def test_executable_claim_without_trigger_is_not(self):
        out = pilot.classify_eligibility(_finding(trigger=None))
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"], "no_concrete_trigger")
        self.assertEqual(out["basis"], "crash_or_exception")

    def test_nonexecutable_claim_is_not_eligible(self):
        out = pilot.classify_eligibility(_finding(
            title="No test covers the new parse path",
            evidence="the module has no tests",
            evidence_quote=""))
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"], "non_executable_claim")
        self.assertEqual(out["claim_class"],
                         "missing_test_or_coverage")

    def test_non_blocking_tier_is_not_eligible(self):
        out = pilot.classify_eligibility(_finding(severity="minor"))
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"], "not_blocking_tier")

    def test_vague_claim_is_not_eligible(self):
        out = pilot.classify_eligibility(_finding(
            title="This code could be cleaner",
            evidence="general concern", evidence_quote=""))
        self.assertFalse(out["eligible"])
        self.assertEqual(out["claim_class"], "vague_or_advisory")


# ------------------------------------------------- bench probe wiring

class BenchProbeWiringTests(unittest.TestCase):
    """The probe channel in bench.run_bench: OFF by default with
    byte-identical call shape and record shape; ON records
    outcomes as data and changes no verdict."""

    # The exact key set of a bench result record before the B3
    # wiring existed — the pin the default path must not move.
    DEFAULT_RECORD_KEYS = {
        "schema", "config", "config_sha256", "seat_lenses",
        "case_id", "split", "category", "created_at", "gate",
        "degraded", "duration_ms", "calls", "cost_usd",
        "patch_sha256", "findings", "reviewer_reports"}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self.corpus = os.path.join(root, "corpus")
        os.makedirs(os.path.join(root, "configs"))
        os.makedirs(os.path.join(root, "scripts"))
        self.out = os.path.join(root, "out")
        _write_case(self.corpus, "pay-bug", PAYMENT_DIFF,
                    PAYMENT_EXPECTED, category="payments")
        _write_case(self.corpus, "clean-one", CLEAN_DIFF, [],
                    category="clean")
        script = {
            "pay-bug": {"verdict": "changes_requested",
                        "summary": "found it", "findings": [{
                            "severity": "blocker",
                            "category": "correctness",
                            "file": "billing/charge.py", "line": 5,
                            "title": "Charge amount passed in "
                                     "dollars where the gateway "
                                     "expects cents",
                            "confidence": 0.9}]},
            "clean-one": {"verdict": "pass", "summary": "clean",
                          "findings": []}}
        with open(os.path.join(root, "scripts", "oracle.json"),
                  "w") as fh:
            json.dump(script, fh)
        self.config_path = os.path.join(root, "configs",
                                        "oracle.json")
        self._write_config(False)

    def _write_config(self, probes):
        cfg = {"name": "oracle",
               "providers": [{"name": "oracle",
                              "script": "../scripts/oracle.json"}]}
        if probes:
            cfg["probes"] = True
        with open(self.config_path, "w") as fh:
            json.dump(cfg, fh)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_with_spy(self, **kwargs):
        seen = []
        real = core.run_review

        def spy(patch, providers, **kw):
            seen.append(kw)
            return real(patch, providers, **kw)

        with mock.patch.object(core, "run_review", spy):
            results = bench.run_bench(self.corpus, ["oracle"],
                                      self.out, force=True, **kwargs)
        return results, seen

    def test_default_off_is_byte_identical_in_shape(self):
        results, seen = self._run_with_spy()
        self.assertTrue(seen)
        for kw in seen:
            self.assertNotIn("probe_fn", kw)
        for rec in results["oracle"]:
            self.assertEqual(set(rec.keys()),
                             self.DEFAULT_RECORD_KEYS)

    def test_flag_on_wires_channel_and_records_outcomes(self):
        results, seen = self._run_with_spy(probes=True)
        self.assertTrue(seen)
        for kw in seen:
            self.assertIn("probe_fn", kw)
            self.assertTrue(callable(kw["probe_fn"]))
        for rec in results["oracle"]:
            self.assertTrue(rec["probes_enabled"])
            # Scripted seats raise no disputes, so no probe ran;
            # the recorded outcome list is present and empty.
            self.assertEqual(rec["probe_outcomes"], [])

    def test_flag_on_changes_no_verdict(self):
        off, _ = self._run_with_spy()
        on, _ = self._run_with_spy(probes=True)
        strip = ("created_at", "duration_ms", "probes_enabled",
                 "probe_outcomes")
        for cfg in ("oracle",):
            off_rows = [{k: v for k, v in r.items()
                         if k not in strip}
                        for r in off[cfg]]
            on_rows = [{k: v for k, v in r.items()
                        if k not in strip}
                       for r in on[cfg]]
            self.assertEqual(off_rows, on_rows)

    def test_config_flag_opts_in_and_moves_config_hash(self):
        plain = bench.load_config(self.config_path)
        self.assertFalse(plain["probes"])
        self._write_config(True)
        probed = bench.load_config(self.config_path)
        self.assertTrue(probed["probes"])
        self.assertNotEqual(bench._config_sha(plain),
                            bench._config_sha(probed))
        results, seen = self._run_with_spy()
        for kw in seen:
            self.assertIn("probe_fn", kw)
        for rec in results["oracle"]:
            self.assertTrue(rec["probes_enabled"])


# ------------------------------------------------- calibration table

class CalibrationTableTests(unittest.TestCase):
    """Table shape + factor inputs on a small fake record set —
    hand-built findings, no run_review, no live calls."""

    def setUp(self):
        self.cases = [
            {"id": "defect-one",
             "expected": [dict(PAYMENT_EXPECTED[0])]},
            {"id": "clean-one", "expected": []},
        ]
        defect_finding = _finding(
            id="f-def",
            title="Charge amount passed in dollars where the "
                  "gateway expects cents crashes billing",
            evidence="gateway.charge raises on float dollars",
            adjudication={"probe": {
                "outcome": "fail", "evidence_quote": "boom",
                "detail": "harness probe fail (exit 1)"}})
        clean_finding = _finding(
            id="f-clean", file="app/util.py", line=3,
            title="add() can crash on None input",
            sources=["scripted"], evidence_class="E3")
        self.records = [
            {"case_id": "defect-one", "gate": "blocked",
             "degraded": False, "gate_profile": {"profile": "strict"},
             "findings": [defect_finding]},
            {"case_id": "clean-one", "gate": "blocked",
             "degraded": False, "gate_profile": {"profile": "strict"},
             "findings": [clean_finding]},
        ]
        self.family = {"scripted": "test-family",
                       "deterministic": "deterministic"}
        self.manifest = pilot.build_split_manifest(
            ["clean-one", "defect-one"])

    def test_table_shape(self):
        table = pilot.build_calibration_table(
            self.records, self.cases, self.family,
            split_manifest=self.manifest)
        self.assertEqual(table["schema"], pilot.TABLE_SCHEMA)
        self.assertEqual(
            table["split_manifest_inputs_sha256"],
            self.manifest["inputs_sha256"])
        self.assertEqual(table["profiles"],
                         list(core.GATE_PROFILES))
        self.assertEqual([r["case_id"] for r in table["cases"]],
                         ["clean-one", "defect-one"])
        for row in table["cases"]:
            self.assertEqual(row["slice"],
                             pilot.slice_for_case(row["case_id"]))
            for profile in core.GATE_PROFILES:
                self.assertIn(profile, row["profiles"])
                for key in ("blocked", "blocking_findings",
                            "defects_blocked", "defects_matched",
                            "demotions"):
                    self.assertIn(key, row["profiles"][profile])
            for fr in row["findings"]:
                for key in ("eligibility", "probe_outcome",
                            "matches_expected_defect",
                            "blocking_tier", "evidence_class"):
                    self.assertIn(key, fr)
        for name in ("calibration", "evaluation", "all"):
            factors = table["factors"][name]
            for key in ("p_base_inputs", "p_elig_inputs",
                        "p_settle_inputs", "eligibility",
                        "clean_blocked_by_profile",
                        "defect_blocked_by_profile"):
                self.assertIn(key, factors)

    def test_factor_inputs_are_the_hand_computed_counts(self):
        table = pilot.build_calibration_table(
            self.records, self.cases, self.family,
            split_manifest=self.manifest)
        factors = table["factors"]["all"]
        # One defect case; its matching finding is E3 (not
        # E0/E1), so nothing blocks without probes yet.
        self.assertEqual(factors["p_base_inputs"], {
            "defect_cases": 1, "blocking_without_probes": 0,
            "ratio": 0.0})
        # The defect case remains, and its finding is eligible
        # + E3 + blocking -> p_elig numerator 1 of 1.
        self.assertEqual(factors["p_elig_inputs"], {
            "remaining_defect_cases": 1,
            "with_eligible_e3_blocking_finding": 1, "ratio": 1.0})
        # The eligible true-defect finding carries a probe
        # outcome ("fail" via the adjudication channel).
        settle = factors["p_settle_inputs"]
        self.assertEqual(settle["eligible_true_defect_findings"], 1)
        self.assertEqual(settle["with_probe_outcome"], 1)
        self.assertEqual(settle["outcome_histogram"], {"fail": 1})
        # The clean case's eligible finding blocks it under
        # every current profile (single-source E3: strict and
        # balanced keep it blocking; corroborated demotes it —
        # so clean-blocked is 1 for strict/balanced, 0 there).
        clean = factors["clean_blocked_by_profile"]
        self.assertEqual(clean["strict"]["blocked"], 1)
        self.assertEqual(clean["balanced"]["blocked"], 1)
        self.assertEqual(clean["corroborated"]["blocked"], 0)

    def test_table_is_deterministic(self):
        a = pilot.build_calibration_table(
            self.records, self.cases, self.family,
            split_manifest=self.manifest)
        b = pilot.build_calibration_table(
            copy.deepcopy(self.records), self.cases, self.family,
            split_manifest=self.manifest)
        self.assertEqual(a, b)

    def test_manifest_mismatch_is_a_loud_error(self):
        other = pilot.build_split_manifest(["clean-one", "zz-9"])
        with self.assertRaises(ValueError):
            pilot.build_calibration_table(
                self.records, self.cases, self.family,
                split_manifest=other)

    def test_unknown_case_is_a_loud_error(self):
        bad = [dict(self.records[0], case_id="nope")]
        with self.assertRaises(ValueError):
            pilot.build_calibration_table(
                bad, self.cases, self.family,
                split_manifest=self.manifest)


if __name__ == "__main__":
    unittest.main()
