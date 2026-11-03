"""Unit tests for reviewloop core — fake providers, no network."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from reviewloop import core  # noqa: E402

BUGGY = """diff --git a/app/alerts.py b/app/alerts.py
--- a/app/alerts.py
+++ b/app/alerts.py
@@ -1,2 +1,6 @@
 import smtplib
+
+API_KEY = "sk-live-9f8e7d6c5b4a3210"
+
+def check(db):
+    db.execute(f"SELECT * FROM t WHERE id = {uid}")
+    sendmail("admin@example.com", "something is wrong")
"""

CLEAN = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,1 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""


def pass_provider(prompt):
    return json.dumps({"verdict": "pass", "summary": "looks fine",
                       "findings": []})


def strict_provider(prompt):
    return json.dumps({
        "verdict": "changes_requested", "summary": "alert has no dedup",
        "findings": [{
            "severity": "major", "category": "reliability",
            "file": "app/alerts.py", "line": 6,
            "title": "Alert fires on every check with no dedup guard",
            "evidence": 'sendmail("admin@example.com", ...)',
            "recommendation": "Persist last-alert state and suppress "
                              "repeats.",
            "confidence": 0.8}]})


class DeterministicScanTests(unittest.TestCase):
    def test_catches_secret_and_sqli_and_alert(self):
        findings = core.deterministic_scan(BUGGY)
        rules = {f["rule"] for f in findings}
        self.assertIn("hardcoded-secret", rules)
        self.assertIn("alert-no-guard", rules)

    def test_clean_patch_has_no_deterministic_findings(self):
        self.assertEqual(core.deterministic_scan(CLEAN), [])

    def test_failing_test_is_blocker(self):
        findings = core.deterministic_scan(
            CLEAN, [{"command": "pytest", "ok": False,
                     "output_tail": "1 failed"}])
        self.assertTrue(any(f["severity"] == "blocker"
                            for f in findings))

    def test_redaction_removes_secret_values(self):
        out = core.redact_secrets(BUGGY)
        self.assertNotIn("sk-live-9f8e7d6c5b4a3210", out)
        self.assertIn("REDACTED", out)


class ReviewLoopTests(unittest.TestCase):
    def test_pass_when_reviewers_pass(self):
        report = core.run_review(
            CLEAN, {"a": pass_provider, "b": pass_provider})
        self.assertEqual(report["gate"], "pass")

    def test_blocked_by_deterministic_even_if_models_pass(self):
        report = core.run_review(
            BUGGY, {"a": pass_provider, "b": pass_provider})
        self.assertEqual(report["gate"], "blocked")

    def test_blocked_by_reviewer_major(self):
        report = core.run_review(
            CLEAN, {"a": strict_provider, "b": pass_provider})
        # strict_provider's finding is on a file not in CLEAN, but the
        # gate only weighs severity, not file membership.
        self.assertEqual(report["gate"], "blocked")

    def test_inconclusive_when_all_providers_fail(self):
        def boom(prompt):
            raise RuntimeError("provider down")
        report = core.run_review(CLEAN, {"a": boom, "b": boom})
        self.assertEqual(report["gate"], "inconclusive")

    def test_json_repair_retry(self):
        calls = {"n": 0}

        def flaky(prompt):
            calls["n"] += 1
            if calls["n"] == 1:
                return '{"verdict": "pass", "summary": "has "bad" quotes"}'
            return json.dumps({"verdict": "pass", "summary": "ok",
                               "findings": []})
        parsed = core._call_and_parse(flaky, "review this")
        self.assertEqual(parsed["summary"], "ok")
        self.assertEqual(calls["n"], 2)

    def test_consensus_merge(self):
        merged = core.merge_findings([
            {"id": "1", "rule": "", "severity": "major",
             "category": "reliability", "file": "a.py", "line": 3,
             "title": "Alert fires with no dedup guard",
             "evidence": "", "recommendation": "", "confidence": 0.6,
             "sources": ["a"], "consensus": False},
            {"id": "2", "rule": "", "severity": "blocker",
             "category": "reliability", "file": "a.py", "line": 3,
             "title": "Alert fires with no dedup or cooldown guard",
             "evidence": "", "recommendation": "", "confidence": 0.7,
             "sources": ["b"], "consensus": False},
        ])
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0]["consensus"])
        self.assertEqual(merged[0]["severity"], "blocker")


class EdgeCaseTests(unittest.TestCase):
    def test_empty_patch_reviews_clean(self):
        report = core.run_review(
            "", {"a": pass_provider, "b": pass_provider})
        self.assertEqual(report["gate"], "pass")
        self.assertEqual(report["findings"], [])

    def test_oversized_patch_truncates_and_strict_is_inconclusive(self):
        big = CLEAN + ("\n+// filler line\n" * 5000)
        report = core.run_review(
            big, {"a": pass_provider, "b": pass_provider},
            max_patch_chars=2000, strict=True)
        self.assertTrue(report["truncated"])
        self.assertEqual(report["gate"], "inconclusive")

    def test_provider_timeout_degrades_not_passes_silently(self):
        def slow(prompt):
            raise TimeoutError("provider timed out")
        report = core.run_review(
            CLEAN, {"a": slow, "b": pass_provider})
        self.assertTrue(report["degraded"])
        self.assertEqual(report["gate"], "pass")  # one reviewer served
        strict = core.run_review(
            CLEAN, {"a": slow, "b": pass_provider}, strict=True)
        self.assertEqual(strict["gate"], "inconclusive")


class VerificationTests(unittest.TestCase):
    def _previous(self):
        return {"gate": "blocked", "findings": [{
            "id": "abc123", "severity": "major",
            "category": "reliability", "file": "app/alerts.py",
            "line": 6, "title": "Alert has no dedup",
            "evidence": "", "recommendation": "", "confidence": 0.8,
            "sources": ["a"], "consensus": False}]}

    _GOOD_EVIDENCE = ("return a + b and return a - b are the only "
                      "helpers left in app/util.py and the sendmail "
                      "alert is removed")

    def test_clears_only_on_consensus(self):
        def fixed(prompt):
            return json.dumps({
                "resolutions": [{"finding_id": "abc123",
                                 "status": "fixed",
                                 "evidence": self._GOOD_EVIDENCE}],
                "new_findings": []})
        report = core.run_verification(
            CLEAN, {"a": fixed, "b": fixed}, self._previous(), "fixed it")
        self.assertEqual(report["gate"], "pass")
        self.assertEqual(len(report["cleared"]), 1)

    def test_empty_evidence_does_not_clear(self):
        # External Review 1, finding 1: a bare "fixed" assertion with
        # no evidence must not clear a blocker.
        def bare(prompt):
            return json.dumps({
                "resolutions": [{"finding_id": "abc123",
                                 "status": "fixed", "evidence": ""}],
                "new_findings": []})
        report = core.run_verification(
            CLEAN, {"a": bare, "b": bare}, self._previous(), "trust me")
        self.assertEqual(report["gate"], "blocked")
        self.assertEqual(len(report["remaining"]), 1)

    def test_bogus_status_does_not_clear(self):
        def bogus(prompt):
            return json.dumps({
                "resolutions": [{"finding_id": "abc123",
                                 "status": "totally_fixed",
                                 "evidence": self._GOOD_EVIDENCE}],
                "new_findings": []})
        report = core.run_verification(
            CLEAN, {"a": bogus, "b": bogus}, self._previous(), "done")
        self.assertEqual(report["gate"], "blocked")

    def test_strict_degraded_verification_is_inconclusive(self):
        # External Review 1, finding 2: strict mode must not PASS a
        # verification round in which a reviewer failed.
        def fixed(prompt):
            return json.dumps({
                "resolutions": [{"finding_id": "abc123",
                                 "status": "fixed",
                                 "evidence": self._GOOD_EVIDENCE}],
                "new_findings": []})

        def boom(prompt):
            raise RuntimeError("provider down")
        relaxed = core.run_verification(
            CLEAN, {"a": fixed, "b": boom}, self._previous(), "fixed")
        self.assertEqual(relaxed["gate"], "pass")
        strict = core.run_verification(
            CLEAN, {"a": fixed, "b": boom}, self._previous(), "fixed",
            strict=True)
        self.assertEqual(strict["gate"], "inconclusive")

    def test_split_verdict_keeps_block(self):
        def fixed(prompt):
            return json.dumps({
                "resolutions": [{"finding_id": "abc123",
                                 "status": "fixed",
                                 "evidence": self._GOOD_EVIDENCE}],
                "new_findings": []})

        def unclear(prompt):
            return json.dumps({
                "resolutions": [{"finding_id": "abc123",
                                 "status": "unclear", "evidence": "?"}],
                "new_findings": []})
        report = core.run_verification(
            CLEAN, {"a": fixed, "b": unclear}, self._previous(), "fixed")
        self.assertEqual(report["gate"], "blocked")


class LoopTests(unittest.TestCase):
    """The full workflow: review -> builder fix + work report ->
    verification -> advance (or stop for a human)."""

    _EVIDENCE = ("alert removed from app/alerts.py and the return "
                 "helpers remain")

    def _panel(self):
        import re

        def reviewer(prompt):
            if "VERIFICATION round" in prompt:
                ids = re.findall(r'"id":\s*"([0-9a-f]{12})"', prompt)
                return json.dumps({
                    "resolutions": [
                        {"finding_id": i, "status": "fixed",
                         "evidence": self._EVIDENCE} for i in ids],
                    "new_findings": []})
            return json.dumps({"findings": [{
                "severity": "blocker", "category": "reliability",
                "file": "app/alerts.py", "line": 3,
                "title": "Alert sent per violation with no dedup",
                "evidence": "sendmail in loop",
                "recommendation": "add a state-file guard",
                "confidence": 0.9}], "summary": "blocked"})
        return {"a": reviewer, "b": reviewer}

    def test_loop_advances_after_builder_fix(self):
        state = {"patch": BUGGY}

        def builder(packet):
            self.assertEqual(packet["gate"], "blocked")
            self.assertTrue(packet["open_findings"])
            state["patch"] = CLEAN
            lines = [f"- Finding {f['id']}: fixed — guard added, "
                     "alerts batched" for f in packet["open_findings"]]
            return "Work report:\n" + "\n".join(lines)
        result = core.run_loop(lambda: state["patch"], builder,
                               self._panel(), max_rounds=3)
        self.assertEqual(result["final_gate"], "pass")
        self.assertTrue(result["advanced"])
        self.assertEqual(result["workflow_state"], "approved")
        self.assertEqual(result["work_report_gaps"], [])
        self.assertTrue(result["finding_states"])
        self.assertTrue(all(
            s["state"] == "fixed_verified"
            for s in result["finding_states"].values()))
        self.assertEqual(len(result["rounds"]), 2)

    def test_loop_flags_missing_dispositions(self):
        state = {"patch": BUGGY}

        def sloppy_builder(packet):
            state["patch"] = CLEAN
            return "I fixed everything, trust me."
        result = core.run_loop(lambda: state["patch"], sloppy_builder,
                               self._panel(), max_rounds=2)
        self.assertTrue(result["work_report_gaps"])
        self.assertEqual(result["final_gate"], "pass")

    def test_loop_stops_for_human_at_max_rounds(self):
        calls = {"n": 0}

        def get_patch():
            calls["n"] += 1
            return BUGGY + f"\n# attempt {calls['n']}"

        def stubborn(prompt):
            if "VERIFICATION round" in prompt:
                import re
                ids = re.findall(r'"id":\s*"([0-9a-f]{12})"', prompt)
                return json.dumps({
                    "resolutions": [
                        {"finding_id": i, "status": "still_present",
                         "evidence": "unchanged"} for i in ids],
                    "new_findings": []})
            return json.dumps({"findings": [{
                "severity": "blocker", "category": "reliability",
                "file": "app/alerts.py", "line": 3,
                "title": "Alert sent per violation with no dedup",
                "evidence": "sendmail in loop",
                "recommendation": "add a state-file guard",
                "confidence": 0.9}], "summary": "blocked"})
        result = core.run_loop(get_patch, lambda packet: "tried",
                               {"a": stubborn, "b": stubborn},
                               max_rounds=2)
        self.assertEqual(result["final_gate"], "blocked")
        self.assertFalse(result["advanced"])
        self.assertEqual(len(result["rounds"]), 3)

    def test_loop_inconclusive_when_builder_makes_no_change(self):
        result = core.run_loop(lambda: BUGGY, lambda packet: "done",
                               self._panel(), max_rounds=2)
        self.assertEqual(result["final_gate"], "inconclusive")
        self.assertIn("no new change", result["stop_reason"])


if __name__ == "__main__":
    unittest.main()
