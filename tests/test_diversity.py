"""Epic E3 — panel-diversity enforcement.

The check judges the COMPOSED panel (the seats handed to
core.run_review, before any is called): at least N distinct
known vendor families ([diversity] min_families), and — when
the caller knows the builder's family and the policy opts in —
exclusion of the builder's own family whenever the remaining
panel still meets the minimum. A violation labels the run
degraded; [diversity] enforce = "block" also makes it a
blocking policy violation. Unconfigured ⇒ nothing runs and
nothing changes (the pre-E3 construction, byte-identical).

Families come from seat metadata (registry tags / --seat-meta),
never seat names; 'unknown' never counts. Exclusion never
reassigns a lens: an excluded seat is simply absent, and the
existing binding machinery treats it as such.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core, diversity, policy  # noqa: E402

PATCH = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,1 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""


def clean_provider(calls=None, name=None):
    """A stub seat that finds nothing. Records its calls."""
    def serve(prompt):
        if calls is not None:
            calls.append(name)
        return json.dumps({"verdict": "pass", "summary": "fine",
                           "findings": []})
    return serve


def write_policy(tmp, text):
    path = os.path.join(tmp, ".codereview.toml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return policy.load_policy(path)


def run(panel, pol=None, **kw):
    """panel: {seat: family}. Runs one clean review round."""
    calls = kw.pop("calls", None)
    providers = {name: clean_provider(calls, name)
                 for name in panel}
    meta = {name: {"family": fam, "tier": "unknown"}
            for name, fam in panel.items()}
    return core.run_review(PATCH, providers, seat_meta=meta,
                           policy=pol, **kw)


class AssessPanelTests(unittest.TestCase):
    def test_enough_families_no_violation(self):
        out = diversity.assess_panel(
            {"a": "openai", "b": "google"}, min_families=2)
        self.assertFalse(out["violation"])
        self.assertEqual(out["families"], ["google", "openai"])
        self.assertEqual(out["excluded_seats"], [])
        self.assertIsNone(out["builder_kept_reason"])

    def test_too_few_families_violation(self):
        out = diversity.assess_panel(
            {"a": "openai", "b": "openai"}, min_families=2)
        self.assertTrue(out["violation"])
        self.assertEqual(out["families"], ["openai"])
        self.assertIn("at least 2", out["detail"])

    def test_unknown_family_never_counts(self):
        out = diversity.assess_panel(
            {"a": "unknown", "b": "unknown"}, min_families=1)
        self.assertTrue(out["violation"])
        self.assertEqual(out["families"], [])

    def test_no_minimum_no_violation(self):
        out = diversity.assess_panel({"a": "openai"})
        self.assertFalse(out["violation"])
        self.assertEqual(out["min_families"], 0)

    def test_builder_exclusion_when_minimum_still_met(self):
        out = diversity.assess_panel(
            {"a": "openai", "b": "google", "c": "anthropic"},
            min_families=2, builder_family="anthropic",
            exclude_builder=True)
        self.assertEqual(out["excluded_seats"], ["c"])
        self.assertTrue(out["builder_excluded"])
        self.assertEqual(out["families"], ["google", "openai"])
        self.assertEqual(out["families_before"],
                         ["anthropic", "google", "openai"])
        self.assertFalse(out["violation"])
        self.assertIsNone(out["builder_kept_reason"])

    def test_builder_exclusion_refused_when_it_breaches_minimum(self):
        out = diversity.assess_panel(
            {"a": "openai", "b": "anthropic"}, min_families=2,
            builder_family="anthropic", exclude_builder=True)
        self.assertEqual(out["excluded_seats"], [])
        self.assertFalse(out["builder_excluded"])
        self.assertIn("below the configured minimum",
                      out["builder_kept_reason"])
        # Kept, so the minimum is met by the full panel.
        self.assertFalse(out["violation"])

    def test_builder_kept_and_violation_when_minimum_unmet_anyway(self):
        out = diversity.assess_panel(
            {"a": "openai", "b": "anthropic"}, min_families=3,
            builder_family="anthropic", exclude_builder=True)
        self.assertEqual(out["excluded_seats"], [])
        self.assertTrue(out["violation"])

    def test_builder_exclusion_with_no_minimum(self):
        out = diversity.assess_panel(
            {"a": "openai", "b": "anthropic"}, min_families=0,
            builder_family="anthropic", exclude_builder=True)
        self.assertEqual(out["excluded_seats"], ["b"])
        self.assertFalse(out["violation"])

    def test_builder_exclusion_never_empties_the_panel(self):
        out = diversity.assess_panel(
            {"a": "anthropic", "b": "anthropic"}, min_families=0,
            builder_family="anthropic", exclude_builder=True)
        self.assertEqual(out["excluded_seats"], [])
        self.assertIn("empty the panel", out["builder_kept_reason"])

    def test_builder_family_unknown_means_no_exclusion(self):
        for bf in (None, "", "unknown"):
            out = diversity.assess_panel(
                {"a": "openai", "b": "google"}, min_families=1,
                builder_family=bf, exclude_builder=True)
            self.assertEqual(out["excluded_seats"], [])
            self.assertIn("builder family unknown",
                          out["builder_kept_reason"])

    def test_builder_family_absent_from_panel_is_a_no_op(self):
        out = diversity.assess_panel(
            {"a": "openai", "b": "google"}, min_families=1,
            builder_family="anthropic", exclude_builder=True)
        self.assertEqual(out["excluded_seats"], [])
        self.assertIsNone(out["builder_kept_reason"])

    def test_exclusion_off_keeps_builder_seats(self):
        out = diversity.assess_panel(
            {"a": "openai", "b": "google", "c": "anthropic"},
            min_families=2, builder_family="anthropic",
            exclude_builder=False)
        self.assertEqual(out["excluded_seats"], [])
        self.assertIsNone(out["builder_kept_reason"])


class FamilyNormalisationTests(unittest.TestCase):
    """P2-03 — family tags are operator-typed: case and
    surrounding whitespace must not split one family into two,
    for counting or for builder exclusion."""

    def test_case_variants_count_as_one_family(self):
        self.assertEqual(
            diversity.known_families(
                {"a": "OpenAI", "b": "openai"}),
            ["openai"])
        out = diversity.assess_panel(
            {"a": "OpenAI", "b": "openai"}, min_families=2)
        self.assertEqual(out["families"], ["openai"])
        self.assertTrue(out["violation"])

    def test_whitespace_variants_count_as_one_family(self):
        out = diversity.assess_panel(
            {"a": "openai ", "b": "openai"}, min_families=2)
        self.assertEqual(out["families"], ["openai"])
        self.assertTrue(out["violation"])

    def test_unknown_stays_uncounted_in_any_case(self):
        self.assertEqual(
            diversity.known_families(
                {"a": "Unknown", "b": "UNKNOWN"}),
            [])

    def test_builder_exclusion_matches_case_insensitively(self):
        out = diversity.assess_panel(
            {"a": "openai", "b": "google", "c": "anthropic"},
            min_families=2, builder_family="OpenAI",
            exclude_builder=True)
        self.assertTrue(out["builder_excluded"])
        self.assertEqual(out["excluded_seats"], ["a"])
        self.assertIsNone(out["builder_kept_reason"])
        # The record keeps the builder family as given.
        self.assertEqual(out["builder_family"], "OpenAI")
        self.assertEqual(out["families"], ["anthropic", "google"])


class PolicyConfigTests(unittest.TestCase):
    def test_full_table_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = write_policy(
                tmp, "[diversity]\nmin_families = 2\n"
                     "exclude_builder_family = true\n"
                     "enforce = \"block\"\n")
        self.assertEqual(pol["diversity"],
                         {"min_families": 2,
                          "exclude_builder_family": True,
                          "enforce": "block"})
        cfg = diversity.policy_config(pol)
        self.assertEqual(cfg["min_families"], 2)
        self.assertEqual(cfg["enforce"], "block")

    def test_defaults_present_and_unconfigured(self):
        pol = policy.default_policy()
        self.assertEqual(pol["diversity"],
                         {"min_families": 0,
                          "exclude_builder_family": False,
                          "enforce": "degrade"})
        self.assertIsNone(diversity.policy_config(pol))
        self.assertIsNone(diversity.policy_config(None))

    def test_exclusion_alone_configures_the_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = write_policy(
                tmp, "[diversity]\nexclude_builder_family = true\n")
        cfg = diversity.policy_config(pol)
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["min_families"], 0)
        self.assertEqual(cfg["enforce"], "degrade")

    def test_bad_enforce_is_line_referenced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".codereview.toml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("[diversity]\nenforce = \"warn\"\n")
            with self.assertRaises(policy.PolicyError) as cm:
                policy.load_policy(path)
        self.assertIn("enforce", str(cm.exception))
        self.assertIn(":2:", str(cm.exception))

    def test_bad_types_rejected(self):
        for text in ("[diversity]\nmin_families = -1\n",
                     "[diversity]\nmin_families = \"two\"\n",
                     "[diversity]\nexclude_builder_family = 1\n",
                     "[diversity]\nbogus_key = 1\n"):
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, ".codereview.toml")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                with self.assertRaises(policy.PolicyError,
                                       msg=text):
                    policy.load_policy(path)

    def test_render_omits_diversity_at_defaults(self):
        # Behaviour pin: a policy that does not configure
        # diversity renders exactly as before Epic E3.
        rendered = policy.render_effective(policy.default_policy())
        self.assertNotIn("[diversity]", rendered)

    def test_render_shows_configured_diversity(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = write_policy(
                tmp, "[diversity]\nmin_families = 2\n"
                     "enforce = \"block\"\n")
        rendered = policy.render_effective(pol)
        self.assertIn("[diversity]", rendered)
        self.assertIn("min_families = 2", rendered)
        self.assertIn('enforce = "block"', rendered)


class RunReviewDiversityTests(unittest.TestCase):
    def test_violation_labels_degraded_but_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = write_policy(tmp, "[diversity]\nmin_families = 2\n")
        report = run({"a": "openai", "b": "openai"}, pol)
        self.assertEqual(report["gate"], "pass")
        self.assertTrue(report["degraded"])
        self.assertIn("panel diversity below minimum",
                      report["degraded_causes"])
        self.assertTrue(report["diversity"]["violation"])
        self.assertEqual(report["diversity"]["enforce"], "degrade")
        applied = {a["rule"]: a["status"]
                   for a in report["policy"]["applied"]}
        self.assertEqual(applied["diversity.min_families"],
                         "violated")
        violations = {v["rule"]: v["enforce"]
                      for v in report["policy"]["violations"]}
        self.assertEqual(violations["diversity.min_families"],
                         "advisory")

    def test_block_mode_blocks_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = write_policy(
                tmp, "[diversity]\nmin_families = 2\n"
                     "enforce = \"block\"\n")
        report = run({"a": "openai", "b": "openai"}, pol)
        self.assertEqual(report["gate"], "blocked")
        self.assertTrue(report["degraded"])
        violations = {v["rule"]: v["enforce"]
                      for v in report["policy"]["violations"]}
        self.assertEqual(violations["diversity.min_families"],
                         "block")
        self.assertTrue(any("diversity.min_families" in r
                            for r in report["gate_reasons"]))

    def test_satisfied_minimum_records_no_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = write_policy(tmp, "[diversity]\nmin_families = 2\n")
        report = run({"a": "openai", "b": "google"}, pol)
        self.assertEqual(report["gate"], "pass")
        self.assertFalse(report["degraded"])
        self.assertFalse(report["diversity"]["violation"])
        applied = {a["rule"]: a["status"]
                   for a in report["policy"]["applied"]}
        self.assertEqual(applied["diversity.min_families"],
                         "satisfied")
        self.assertEqual(report["policy"]["violations"], [])

    def test_untagged_panel_violates_a_configured_minimum(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = write_policy(tmp, "[diversity]\nmin_families = 1\n")
        providers = {"a": clean_provider(), "b": clean_provider()}
        report = core.run_review(PATCH, providers, policy=pol)
        self.assertTrue(report["diversity"]["violation"])
        self.assertTrue(report["degraded"])

    def test_builder_seats_excluded_and_never_called(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = write_policy(
                tmp, "[diversity]\nmin_families = 2\n"
                     "exclude_builder_family = true\n")
        calls = []
        report = run({"a": "openai", "b": "google",
                      "c": "anthropic"}, pol, calls=calls,
                     builder_family="anthropic")
        self.assertNotIn("c", calls)
        served = {r["provider"] for r in report["reviewer_reports"]}
        self.assertNotIn("c", served)
        self.assertEqual(report["diversity"]["excluded_seats"],
                         ["c"])
        self.assertTrue(report["diversity"]["builder_excluded"])
        self.assertFalse(report["diversity"]["violation"])
        self.assertEqual(report["gate"], "pass")

    def test_builder_seats_kept_when_exclusion_would_breach(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = write_policy(
                tmp, "[diversity]\nmin_families = 2\n"
                     "exclude_builder_family = true\n")
        calls = []
        report = run({"a": "openai", "b": "anthropic"}, pol,
                     calls=calls, builder_family="anthropic")
        self.assertIn("b", calls)
        self.assertEqual(report["diversity"]["excluded_seats"], [])
        self.assertIn("below the configured minimum",
                      report["diversity"]["builder_kept_reason"])
        self.assertFalse(report["diversity"]["violation"])

    def test_no_builder_signal_means_no_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = write_policy(
                tmp, "[diversity]\nmin_families = 2\n"
                     "exclude_builder_family = true\n")
        calls = []
        report = run({"a": "openai", "b": "google",
                      "c": "anthropic"}, pol, calls=calls)
        self.assertIn("c", calls)
        self.assertEqual(report["diversity"]["excluded_seats"], [])
        self.assertIn("builder family unknown",
                      report["diversity"]["builder_kept_reason"])

    def test_unconfigured_run_is_identical(self):
        # Behaviour pin: no policy, and a policy with no
        # [diversity] table, produce the pre-E3 record shape —
        # no diversity section, same gate/degradation/findings.
        plain = run({"a": "openai", "b": "google"}, None)
        with tempfile.TemporaryDirectory() as tmp:
            pol = write_policy(tmp, "[panel]\nmin_seats = 1\n")
        other = run({"a": "openai", "b": "google"}, pol)
        for report in (plain, other):
            self.assertNotIn("diversity", report)
            self.assertFalse(report["degraded"])
        self.assertEqual(plain["gate"], other["gate"])
        self.assertEqual(plain["findings"], other["findings"])
        self.assertEqual(
            [r["provider"] for r in plain["reviewer_reports"]],
            [r["provider"] for r in other["reviewer_reports"]])


if __name__ == "__main__":
    unittest.main()
