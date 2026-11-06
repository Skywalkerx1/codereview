"""Policy B2 — the `corroborated` gate profile (expert solution
§4.1, R3 form + R4 trigger rule; Step 2+3 of the B2 follow-up,
2026-11-05).

Evidence classes for blocking, all lenses: E0 (deterministic),
E2 (probe-confirmed) and E1 (corroborated across >= 2 distinct
families, or confirmed by a cross-family confirmation call with
a validated deciding quote) may block. E3 (single-source,
unverified) majors are demoted to visible minors and recorded
as unverified majors. A blocking-eligible model finding also
needs a validated quote and a concrete `trigger`; missing or
vague caps it at minor. The profile requires >= 2 correctness
families on the panel.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core, policy  # noqa: E402

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

QUOTE = "    return a - b"
TRIGGER = ("Calling sub(1, 2) after the cache is primed with a "
           "negative entry returns the stale value instead of -1")


def merged_finding(severity="major", sources=("seat-a",),
                   source_lenses=None, **kw):
    f = {"id": "fp-b2", "rule": "", "severity": severity,
         "category": "correctness", "file": "app/util.py",
         "line": 6, "title": "sub() returns a stale cached value",
         "evidence": QUOTE, "evidence_quote": QUOTE,
         "recommendation": "invalidate the cache entry",
         "confidence": 0.9, "sources": list(sources),
         "consensus": len(sources) > 1,
         "grounding": "grounded", "trigger": TRIGGER}
    if source_lenses is not None:
        f["source_lenses"] = source_lenses
    f.update(kw)
    return f


FAM = {"seat-a": "fam-a", "seat-b": "fam-b",
       "deterministic": "deterministic"}


class CorroboratedPureTests(unittest.TestCase):
    """_apply_gate_profile / evaluate_gate_policy, profile B2."""

    def apply(self, findings, **kw):
        kw.setdefault("family_by_source", FAM)
        return core._apply_gate_profile(
            findings, "corroborated", **kw)

    def test_e3_unconfirmed_is_demoted_as_unverified_major(self):
        f = merged_finding(source_lenses={"seat-a": ["correctness"]})
        out, demotions = self.apply([f])
        self.assertEqual(out[0]["severity"], "minor")
        self.assertEqual(out[0]["evidence_class"], "E3")
        self.assertIn("unverified_major", out[0])
        self.assertEqual(out[0]["unverified_major"]["from"], "major")
        dem = out[0]["profile_demotion"]
        self.assertEqual(dem["rule"], "B2")
        self.assertEqual(dem["basis"], "unverified_single_source")
        self.assertEqual(len(demotions), 1)
        # The demotion RECORD (gate_profile.demotions) carries
        # the basis too — the gate-reason summary renders from
        # it (house-review dispute, 2026-11-05).
        self.assertEqual(demotions[0]["basis"],
                         "unverified_single_source")

    def test_e3_confirmed_with_valid_quote_promotes_to_e1(self):
        f = merged_finding(source_lenses={"seat-a": ["correctness"]})
        out, demotions = self.apply([f], confirmation_outcomes={
            "fp-b2": {"outcome": "confirmed", "by": "seat-b",
                      "family": "fam-b", "evidence_quote": QUOTE,
                      "reason": "reproduced from the region",
                      "quote_valid": True}})
        self.assertEqual(out[0]["severity"], "major")
        self.assertEqual(out[0]["evidence_class"], "E1")
        self.assertEqual(demotions, [])
        self.assertEqual(
            out[0]["corroboration"]["outcome"], "confirmed")

    def test_e3_confirmed_without_valid_quote_stays_unverified(self):
        f = merged_finding(source_lenses={"seat-a": ["correctness"]})
        out, _ = self.apply([f], confirmation_outcomes={
            "fp-b2": {"outcome": "confirmed", "by": "seat-b",
                      "family": "fam-b", "evidence_quote": "",
                      "reason": "bare say-so", "quote_valid": False}})
        self.assertEqual(out[0]["severity"], "minor")
        self.assertEqual(out[0]["evidence_class"], "E3")
        self.assertIn("unverified_major", out[0])

    def test_e3_refuted_with_valid_quote_is_demoted_as_refuted(self):
        f = merged_finding(source_lenses={"seat-a": ["correctness"]})
        out, _ = self.apply([f], confirmation_outcomes={
            "fp-b2": {"outcome": "refuted", "by": "seat-b",
                      "family": "fam-b", "evidence_quote": QUOTE,
                      "reason": "the cache is keyed by arguments",
                      "quote_valid": True}})
        self.assertEqual(out[0]["severity"], "minor")
        self.assertEqual(
            out[0]["profile_demotion"]["basis"],
            "cross_family_refuted")
        self.assertNotIn("unverified_major", out[0])

    def test_two_sources_same_family_are_still_e3(self):
        f = merged_finding(
            sources=("seat-a", "seat-a2"),
            source_lenses={"seat-a": ["correctness"],
                           "seat-a2": ["correctness"]})
        fam = dict(FAM)
        fam["seat-a2"] = "fam-a"
        out, _ = core._apply_gate_profile(
            [f], "corroborated", family_by_source=fam)
        self.assertEqual(out[0]["evidence_class"], "E3")
        self.assertEqual(out[0]["severity"], "minor")

    def test_two_sources_distinct_families_block_as_e1(self):
        f = merged_finding(
            sources=("seat-a", "seat-b"),
            source_lenses={"seat-a": ["correctness"],
                           "seat-b": ["correctness"]})
        out, demotions = self.apply([f])
        self.assertEqual(out[0]["severity"], "major")
        self.assertEqual(out[0]["evidence_class"], "E1")
        self.assertEqual(demotions, [])

    def test_deterministic_e0_blocks_without_a_model_trigger(self):
        f = merged_finding(
            sources=("deterministic",),
            source_lenses={"deterministic": ["deterministic"]},
            trigger="")
        out, demotions = self.apply([f])
        self.assertEqual(out[0]["severity"], "major")
        self.assertEqual(out[0]["evidence_class"], "E0")
        self.assertEqual(demotions, [])

    def test_probe_confirmed_e2_blocks(self):
        f = merged_finding(source_lenses={"seat-a": ["correctness"]},
                           probe_confirmed=True)
        out, _ = self.apply([f])
        self.assertEqual(out[0]["severity"], "major")
        self.assertEqual(out[0]["evidence_class"], "E2")

    def test_missing_trigger_caps_an_e1_at_minor(self):
        f = merged_finding(
            sources=("seat-a", "seat-b"),
            source_lenses={"seat-a": ["correctness"],
                           "seat-b": ["correctness"]},
            trigger="")
        out, _ = self.apply([f])
        self.assertEqual(out[0]["severity"], "minor")
        self.assertEqual(
            out[0]["profile_demotion"]["basis"],
            "trigger_requirement")

    def test_vague_trigger_caps_an_e1_at_minor(self):
        f = merged_finding(
            sources=("seat-a", "seat-b"),
            source_lenses={"seat-a": ["correctness"],
                           "seat-b": ["correctness"]},
            trigger="might break under some conditions")
        out, _ = self.apply([f])
        self.assertEqual(out[0]["severity"], "minor")
        self.assertEqual(
            out[0]["profile_demotion"]["basis"],
            "trigger_requirement")

    def test_unvalidated_quote_caps_at_minor(self):
        f = merged_finding(
            sources=("seat-a", "seat-b"),
            source_lenses={"seat-a": ["correctness"],
                           "seat-b": ["correctness"]},
            grounding="unresolved")
        out, _ = self.apply([f])
        self.assertEqual(out[0]["severity"], "minor")
        self.assertEqual(
            out[0]["profile_demotion"]["basis"], "quote_requirement")

    def test_r2_stage_skips_the_trigger_rule(self):
        # The offline sweep's R2/R3 evaluation must not apply R4:
        # the stored findings carry no trigger field at all.
        f = merged_finding(
            sources=("seat-a", "seat-b"),
            source_lenses={"seat-a": ["correctness"],
                           "seat-b": ["correctness"]},
            trigger="")
        out, _ = self.apply([f], require_trigger=False)
        self.assertEqual(out[0]["severity"], "major")

    def test_unavailable_confirmation_is_recorded(self):
        f = merged_finding(source_lenses={"seat-a": ["correctness"]})
        out, _ = self.apply([f], confirmation_outcomes={
            "fp-b2": {"outcome": "unavailable", "by": None,
                      "family": None, "evidence_quote": "",
                      "reason": "no other correctness family served",
                      "quote_valid": False}})
        self.assertEqual(out[0]["severity"], "minor")
        self.assertEqual(
            out[0]["corroboration"]["outcome"], "unavailable")
        self.assertIn("unverified_major", out[0])

    def test_evaluate_gate_policy_groups_then_applies(self):
        # Grouping included: two raw findings from two families
        # merge into ONE E1 finding that still blocks.
        raw_a = core._normalize_finding(
            {"severity": "major", "category": "correctness",
             "file": "app/util.py", "line": 6,
             "title": "sub() returns a stale cached value",
             "evidence": QUOTE, "evidence_quote": QUOTE,
             "recommendation": "invalidate", "confidence": 0.9,
             "trigger": TRIGGER}, "seat-a", lens="correctness")
        raw_b = core._normalize_finding(
            {"severity": "major", "category": "correctness",
             "file": "app/util.py", "line": 6,
             "title": "sub() returns a stale cached value",
             "evidence": QUOTE, "evidence_quote": QUOTE,
             "recommendation": "invalidate", "confidence": 0.8,
             "trigger": TRIGGER}, "seat-b", lens="correctness")
        out, demotions = core.evaluate_gate_policy(
            [raw_a, raw_b], "corroborated", family_by_source=FAM)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["severity"], "major")
        self.assertEqual(out[0]["evidence_class"], "E1")
        self.assertEqual(out[0]["trigger"], TRIGGER)
        self.assertEqual(demotions, [])


RAW_FINDING = {
    "severity": "major", "category": "correctness",
    "file": "app/util.py", "line": 6,
    "title": "sub() returns a stale cached value",
    "evidence": QUOTE, "evidence_quote": QUOTE,
    "recommendation": "invalidate the cache entry",
    "confidence": 0.9, "trigger": TRIGGER}


def raiser_provider():
    """seat-a: raises the finding under the correctness lens."""
    def serve(prompt):
        if "CORRECTNESS & SECURITY lens" in prompt:
            return json.dumps(
                {"summary": "stub", "findings": [RAW_FINDING]})
        return json.dumps({"summary": "stub", "findings": []})
    return serve


def checker_provider(confirm="confirm"):
    """seat-b: raises nothing; answers the cross-family
    confirmation pass per `confirm`."""
    def serve(prompt):
        if "CROSS-FAMILY CONFIRMATION pass" in prompt:
            if confirm == "confirm":
                return json.dumps({
                    "verdict": "confirm", "evidence_quote": QUOTE,
                    "reason": "the region shows the stale read"})
            if confirm == "refute":
                return json.dumps({
                    "verdict": "refute", "evidence_quote": QUOTE,
                    "reason": "the cache is keyed by arguments"})
            return json.dumps({"verdict": "undecided",
                               "evidence_quote": "",
                               "reason": "cannot tell"})
        return json.dumps({"summary": "stub", "findings": []})
    return serve


META2 = {"seat-a": {"family": "fam-a", "tier": "unknown"},
         "seat-b": {"family": "fam-b", "tier": "unknown"}}
BIND2 = {"seat-a": ["correctness"],
         "seat-b": ["correctness", "operations"]}


class CorroboratedRunTests(unittest.TestCase):
    def review(self, confirm="confirm", **kw):
        kw.setdefault("seat_meta", META2)
        kw.setdefault("seat_lenses", BIND2)
        kw.setdefault("gate_profile", "corroborated")
        return core.run_review(
            PATCH, {"seat-a": raiser_provider(),
                    "seat-b": checker_provider(confirm)}, **kw)

    def test_confirmed_e3_blocks_and_is_recorded(self):
        rep = self.review("confirm")
        self.assertEqual(rep["gate"], "blocked")
        gp = rep["gate_profile"]
        self.assertEqual(gp["profile"], "corroborated")
        self.assertEqual(gp["unverified_major_count"], 0)
        self.assertTrue(gp["prompt_sha256"])
        self.assertEqual(len(gp["prompt_sha256"]), 64)
        f = rep["findings"][0]
        self.assertEqual(f["severity"], "major")
        self.assertEqual(f["evidence_class"], "E1")
        self.assertEqual(f["corroboration"]["outcome"], "confirmed")
        md = core.render_markdown(rep)
        self.assertIn("E1", md)

    def test_unresolved_e3_is_an_unverified_major_and_passes(self):
        rep = self.review("undecided")
        self.assertEqual(rep["gate"], "pass")
        gp = rep["gate_profile"]
        self.assertEqual(gp["unverified_major_count"], 1)
        self.assertEqual(len(rep["unverified_majors"]), 1)
        f = rep["findings"][0]
        self.assertEqual(f["severity"], "minor")
        self.assertIn("unverified_major", f)
        md = core.render_markdown(rep)
        self.assertIn("Unverified majors", md)

    def test_refuted_e3_does_not_block(self):
        rep = self.review("refute")
        self.assertEqual(rep["gate"], "pass")
        f = rep["findings"][0]
        self.assertEqual(f["severity"], "minor")
        self.assertEqual(f["profile_demotion"]["basis"],
                         "cross_family_refuted")

    def test_single_correctness_family_is_a_loud_error(self):
        meta = {"seat-a": {"family": "fam-a", "tier": "unknown"},
                "seat-b": {"family": "fam-a", "tier": "unknown"}}
        with self.assertRaises(ValueError):
            self.review("confirm", seat_meta=meta)

    def test_unknown_profile_still_a_loud_error(self):
        with self.assertRaises(ValueError):
            self.review("confirm", gate_profile="quiet")


class MergeTriggerTests(unittest.TestCase):
    def test_merge_prefers_a_concrete_trigger(self):
        # House review 2026-11-05: first-source-wins kept a
        # vague trigger and would cap a corroborated finding
        # whose other source stated the trigger properly.
        vague = merged_finding(sources=("seat-a",),
                               trigger="might break")
        concrete = merged_finding(sources=("seat-b",),
                                  trigger=TRIGGER)
        merged = core.merge_findings([vague, concrete])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["trigger"], TRIGGER)
        applied, _ = core._apply_gate_profile(
            merged, "corroborated", family_by_source=FAM)
        self.assertEqual(applied[0]["severity"], "major")
        self.assertEqual(applied[0]["evidence_class"], "E1")


class PromptAndPolicyTests(unittest.TestCase):
    def test_b2_prompt_carries_intent_rubric_and_trigger(self):
        prompt = core.review_prompt_for_profile("corroborated")
        self.assertIn("Intent-relative review", prompt)
        self.assertIn('"trigger"', prompt)
        self.assertIn("missing hardening", prompt.lower())
        self.assertNotIn('"trigger"', core.review_prompt_for_profile(
            "strict"))
        self.assertEqual(
            len(core.review_prompt_sha256("corroborated")), 64)
        self.assertNotEqual(core.review_prompt_sha256("corroborated"),
                            core.review_prompt_sha256("strict"))

    def test_normalize_finding_keeps_trigger(self):
        f = core._normalize_finding(RAW_FINDING, "seat-a",
                                    lens="correctness")
        self.assertEqual(f["trigger"], TRIGGER)

    def test_policy_loads_corroborated(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".codereview.toml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('[gate]\nprofile = "corroborated"\n')
            pol = policy.load_policy(path)
        self.assertEqual(pol["gate"]["profile"], "corroborated")

    def test_profiles_pin_core_and_policy(self):
        self.assertEqual(policy.KNOWN_GATE_PROFILES,
                         core.GATE_PROFILES)
        self.assertIn("corroborated", core.GATE_PROFILES)


if __name__ == "__main__":
    unittest.main()
