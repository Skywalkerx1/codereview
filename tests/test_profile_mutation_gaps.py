"""Mutation-gap pins for the gate-profile machinery (L6 rerun,
2026-11-07): the tester's partial mutation pass over the RC
source found 14 of the first 30 mutants SURVIVING, concentrated
in core._apply_gate_profile (9 — the balanced/corroborated
demotion logic) and core._evidence_class (4). Her run was
interrupted and the full mutant list is still hers to send;
this file pins the DOCUMENTED behaviour of those two functions
branch by branch (policies B1/B2 as written in
core._apply_gate_profile's and core._evidence_class's
docstrings), so the branches her survivors exercised have a
test whose assertions a mutation of the branch condition or
its outcome would break. Behaviour is pinned as documented —
nothing here changes what the profiles do.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core  # noqa: E402

CONCRETE = ("calling sub() with a negative input value "
            "retries forever")
VAGUE = "might break under some conditions"


def finding(severity="major", sources=("seat-a",),
            source_lenses=None, **kw):
    f = {"id": "f1", "rule": "", "severity": severity,
         "category": "reliability", "file": "app/util.py",
         "line": 6, "title": "t", "evidence": "e",
         "evidence_quote": "return a - b",
         "recommendation": "r", "confidence": 0.9,
         "sources": list(sources), "trigger": CONCRETE}
    if source_lenses is not None:
        f["source_lenses"] = source_lenses
    f.update(kw)
    return f


def apply(findings, profile, **kw):
    return core._apply_gate_profile(findings, profile, **kw)


class EvidenceClassPins(unittest.TestCase):
    def test_deterministic_source_is_e0(self):
        f = finding(sources=("deterministic", "seat-a"))
        self.assertEqual(core._evidence_class(f), "E0")

    def test_deterministic_beats_probe_confirmed(self):
        f = finding(sources=("deterministic",),
                    probe_confirmed=True)
        self.assertEqual(core._evidence_class(f), "E0")

    def test_probe_confirmed_is_e2(self):
        f = finding(probe_confirmed=True)
        self.assertEqual(core._evidence_class(f), "E2")

    def test_prestamped_e2_is_e2(self):
        f = finding(evidence_class="E2")
        self.assertEqual(core._evidence_class(f), "E2")

    def test_validated_confirmation_is_e1(self):
        f = finding(corroboration={"outcome": "confirmed",
                                   "quote_valid": True})
        self.assertEqual(core._evidence_class(f), "E1")

    def test_unvalidated_confirmation_is_not_e1(self):
        f = finding(corroboration={"outcome": "confirmed",
                                   "quote_valid": False})
        self.assertEqual(core._evidence_class(f), "E3")

    def test_refutation_is_not_e1(self):
        f = finding(corroboration={"outcome": "refuted",
                                   "quote_valid": True})
        self.assertEqual(core._evidence_class(f), "E3")

    def test_two_families_via_map_is_e1(self):
        f = finding(sources=("seat-a", "seat-b"))
        fams = {"seat-a": "openai", "seat-b": "deepseek"}
        self.assertEqual(core._evidence_class(f, fams), "E1")

    def test_one_family_via_map_is_e3(self):
        f = finding(sources=("seat-a", "seat-b"))
        fams = {"seat-a": "openai", "seat-b": "openai"}
        self.assertEqual(core._evidence_class(f, fams), "E3")

    def test_map_knowing_one_source_applies_strictly(self):
        # The map knows seat-a's family and says nothing about
        # seat-b: strictly applied, only one family is known —
        # the second source does NOT stand in as its own family.
        f = finding(sources=("seat-a", "seat-b"))
        self.assertEqual(
            core._evidence_class(f, {"seat-a": "openai"}), "E3")

    def test_map_knowing_nothing_sources_stand_in(self):
        f = finding(sources=("seat-a", "seat-b"))
        self.assertEqual(core._evidence_class(f, {}), "E1")

    def test_unknown_family_values_do_not_count(self):
        f = finding(sources=("seat-a", "seat-b"))
        fams = {"seat-a": "unknown", "seat-b": "unknown"}
        self.assertEqual(core._evidence_class(f, fams), "E1")

    def test_no_map_distinct_sources_are_e1(self):
        f = finding(sources=("seat-a", "seat-b"))
        self.assertEqual(core._evidence_class(f), "E1")

    def test_single_source_is_e3(self):
        self.assertEqual(core._evidence_class(finding()), "E3")


class BalancedProfilePins(unittest.TestCase):
    def test_ops_only_blocking_is_demoted(self):
        f = finding(source_lenses={"seat-a": ["operations"]})
        _out, demotions = apply([f], "balanced")
        self.assertEqual(f["severity"], "minor")
        self.assertEqual(f["profile_demotion"]["rule"], "B1")
        self.assertEqual(len(demotions), 1)
        self.assertEqual(demotions[0]["rule"], "B1")

    def test_ops_plus_correctness_is_not_demoted(self):
        f = finding(
            sources=("seat-a", "seat-b"),
            source_lenses={"seat-a": ["operations"],
                           "seat-b": ["correctness"]})
        _out, demotions = apply([f], "balanced")
        self.assertEqual(f["severity"], "major")
        self.assertEqual(demotions, [])

    def test_one_seat_serving_both_lenses_is_not_demoted(self):
        f = finding(source_lenses={
            "seat-a": ["operations", "correctness"]})
        _out, demotions = apply([f], "balanced")
        self.assertEqual(f["severity"], "major")
        self.assertEqual(demotions, [])

    def test_unattributed_source_is_not_demoted(self):
        # seat-b has no recorded lens: fail-safe towards strict.
        f = finding(
            sources=("seat-a", "seat-b"),
            source_lenses={"seat-a": ["operations"]})
        _out, demotions = apply([f], "balanced")
        self.assertEqual(f["severity"], "major")
        self.assertEqual(demotions, [])

    def test_deterministic_source_is_not_demoted(self):
        f = finding(sources=("deterministic", "seat-a"),
                    source_lenses={"seat-a": ["operations"]})
        _out, demotions = apply([f], "balanced")
        self.assertEqual(f["severity"], "major")
        self.assertEqual(demotions, [])

    def test_non_blocking_ops_only_is_untouched(self):
        f = finding(severity="minor",
                    source_lenses={"seat-a": ["operations"]})
        _out, demotions = apply([f], "balanced")
        self.assertEqual(f["severity"], "minor")
        self.assertNotIn("profile_demotion", f)
        self.assertEqual(demotions, [])

    def test_no_sources_is_untouched(self):
        f = finding(sources=(), source_lenses={})
        _out, demotions = apply([f], "balanced")
        self.assertEqual(f["severity"], "major")
        self.assertEqual(demotions, [])

    def test_strict_profile_never_demotes(self):
        f = finding(source_lenses={"seat-a": ["operations"]})
        _out, demotions = apply([f], "strict")
        self.assertEqual(f["severity"], "major")
        self.assertEqual(demotions, [])
        # ...but the evidence class is still stamped.
        self.assertEqual(f["evidence_class"], "E3")


class CorroboratedProfilePins(unittest.TestCase):
    def test_e3_without_confirmation_is_unverified_major(self):
        f = finding()
        _out, demotions = apply([f], "corroborated")
        self.assertEqual(f["severity"], "minor")
        self.assertEqual(f["profile_demotion"]["basis"],
                         "unverified_single_source")
        self.assertEqual(f["unverified_major"]["from"], "major")
        self.assertEqual(demotions[0]["basis"],
                         "unverified_single_source")

    def test_e3_confirmed_with_valid_quote_promotes(self):
        f = finding()
        outcomes = {"f1": {"outcome": "confirmed",
                           "quote_valid": True, "by": "seat-b",
                           "family": "deepseek"}}
        _out, demotions = apply(
            [f], "corroborated", confirmation_outcomes=outcomes)
        self.assertEqual(f["severity"], "major")
        self.assertEqual(f["evidence_class"], "E1")
        self.assertEqual(f["cross_family"], "confirmed")
        self.assertEqual(demotions, [])

    def test_e3_confirmed_without_valid_quote_does_not_promote(self):
        f = finding()
        outcomes = {"f1": {"outcome": "confirmed",
                           "quote_valid": False}}
        _out, demotions = apply(
            [f], "corroborated", confirmation_outcomes=outcomes)
        self.assertEqual(f["severity"], "minor")
        self.assertEqual(f["profile_demotion"]["basis"],
                         "unverified_single_source")

    def test_e3_refuted_with_valid_quote_demotes_as_refuted(self):
        f = finding()
        outcomes = {"f1": {"outcome": "refuted",
                           "quote_valid": True, "by": "seat-b",
                           "family": "deepseek"}}
        _out, demotions = apply(
            [f], "corroborated", confirmation_outcomes=outcomes)
        self.assertEqual(f["severity"], "minor")
        self.assertEqual(f["profile_demotion"]["basis"],
                         "cross_family_refuted")
        self.assertNotIn("unverified_major", f)

    def test_e3_unresolved_outcome_is_unverified_major(self):
        f = finding()
        outcomes = {"f1": {"outcome": "unresolved",
                           "quote_valid": False}}
        _out, _demotions = apply(
            [f], "corroborated", confirmation_outcomes=outcomes)
        self.assertEqual(f["severity"], "minor")
        self.assertEqual(f["profile_demotion"]["basis"],
                         "unverified_single_source")

    def test_confirm_fn_channel_is_used(self):
        f = finding()
        seen = []

        def confirm(finding_):
            seen.append(finding_["id"])
            return {"outcome": "confirmed", "quote_valid": True,
                    "by": "seat-b", "family": "deepseek"}

        _out, _demotions = apply([f], "corroborated",
                                 confirm_fn=confirm)
        self.assertEqual(seen, ["f1"])
        self.assertEqual(f["severity"], "major")
        self.assertEqual(f["evidence_class"], "E1")

    def test_e1_blocking_passes_untouched(self):
        f = finding(sources=("seat-a", "seat-b"))
        _out, demotions = apply(
            [f], "corroborated",
            family_by_source={"seat-a": "openai",
                              "seat-b": "deepseek"})
        self.assertEqual(f["severity"], "major")
        self.assertEqual(f["evidence_class"], "E1")
        self.assertEqual(demotions, [])

    def test_e0_is_exempt_from_trigger_rule(self):
        f = finding(sources=("deterministic",), trigger="")
        _out, demotions = apply([f], "corroborated",
                                require_trigger=True)
        self.assertEqual(f["severity"], "major")
        self.assertEqual(demotions, [])

    def test_e2_is_exempt_from_trigger_rule(self):
        f = finding(probe_confirmed=True, trigger="")
        _out, demotions = apply([f], "corroborated",
                                require_trigger=True)
        self.assertEqual(f["severity"], "major")
        self.assertEqual(demotions, [])

    def test_unvalidated_quote_demotes_before_confirmation(self):
        f = finding(grounding="ungrounded")
        outcomes = {"f1": {"outcome": "confirmed",
                           "quote_valid": True}}
        _out, demotions = apply(
            [f], "corroborated", confirmation_outcomes=outcomes)
        self.assertEqual(f["severity"], "minor")
        self.assertEqual(f["profile_demotion"]["basis"],
                         "quote_requirement")

    def test_vague_trigger_demotes_when_required(self):
        f = finding(sources=("seat-a", "seat-b"), trigger=VAGUE)
        _out, demotions = apply(
            [f], "corroborated",
            family_by_source={"seat-a": "openai",
                              "seat-b": "deepseek"},
            require_trigger=True)
        self.assertEqual(f["severity"], "minor")
        self.assertEqual(f["profile_demotion"]["basis"],
                         "trigger_requirement")

    def test_vague_trigger_passes_when_not_required(self):
        f = finding(sources=("seat-a", "seat-b"), trigger=VAGUE)
        _out, demotions = apply(
            [f], "corroborated",
            family_by_source={"seat-a": "openai",
                              "seat-b": "deepseek"},
            require_trigger=False)
        self.assertEqual(f["severity"], "major")
        self.assertEqual(demotions, [])

    def test_non_blocking_e3_is_untouched(self):
        f = finding(severity="minor")
        _out, demotions = apply([f], "corroborated")
        self.assertEqual(f["severity"], "minor")
        self.assertNotIn("profile_demotion", f)
        self.assertEqual(demotions, [])


if __name__ == "__main__":
    unittest.main()
