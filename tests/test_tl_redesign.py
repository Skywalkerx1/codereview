"""Tech Lead redesign — adjudication protocol v2
(honest-negatives solution §3.3 + §3.5): the seat returns
verdict + calibrated confidence only; the HARNESS owns
escalation (six named rules, no bare escalations);
settling probes decide deterministically with the seat
grading probe adequacy only; packets are canonicalised
so vendor-strip / family-swap invariance holds by
construction; draws are canonical + swapped; findings
are judged as raised; every entry carries its §3.5
authority stage with all stages disabled."""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core, techlead  # noqa: E402

REGION = ("import os\n"
          "VALUE = compute_total(items)\n"
          "print(VALUE)\n"
          "RESULT = VALUE * 2\n")
FINDING = {"id": "fx1", "file": "app.py", "line": 2,
           "severity": "major", "title": "Total without guard",
           "evidence": "VALUE = compute_total(items) is used "
                       "unbounded",
           "evidence_quote": "VALUE = compute_total(items)"}
MINOR_FINDING = dict(FINDING, id="fx2", severity="minor")
BLOCKER_FINDING = dict(FINDING, id="fx3", severity="blocker")
DISPUTE = {"by": "seatB", "family": "famB",
           "raiser_family": "famA",
           "evidence_quote": "print(VALUE)",
           "reason": "the claim fails on the printed value"}
GROUNDED_QUOTE = "RESULT = VALUE * 2"


def payload(verdict="sustain_finding", confidence=0.9,
            quote=GROUNDED_QUOTE, level="major", **over):
    p = {"verdict": verdict, "confidence": confidence,
         "deciding_quote": quote,
         "severity_after_rubric": {"level": level,
                                   "rubric_clause": None},
         "claim_restated": "the total lacks a guard",
         "position_a_addresses_claim": {"value": True,
                                        "why": "a addresses"},
         "position_b_addresses_claim": {"value": False,
                                        "why": "b misses"},
         "rationale": "the code shows it"}
    p.update(over)
    return p


def adequacy(tests_claim=True, confidence=0.9):
    return {"tests_claim": tests_claim,
            "confidence": confidence,
            "why": "the probe exercises the cited call"}


class Seat:
    """Queue seat: pops payloads in order, repeats the
    last; records every prompt it was shown."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        p = self.payloads.pop(0) if len(self.payloads) > 1 \
            else self.payloads[0]
        return p if isinstance(p, str) else json.dumps(p)


def adjudicate(seat, finding=None, dispute=None, **kw):
    kw.setdefault("seat_name", "tl")
    kw.setdefault("seat_family", "famC")
    return techlead.adjudicate(
        seat, dict(finding or FINDING), REGION,
        dict(dispute or DISPUTE), **kw)


class CanonicalisationTests(unittest.TestCase):
    def test_family_swap_is_byte_identical(self):
        swapped = dict(DISPUTE, family="famA",
                       raiser_family="famB")
        c1 = techlead.canonicalise_packet(
            dict(FINDING), dict(DISPUTE), REGION)
        c2 = techlead.canonicalise_packet(
            dict(FINDING), swapped, REGION)
        self.assertEqual(c1["packet"], c2["packet"])
        self.assertEqual(c1["packet_hash"],
                         c2["packet_hash"])
        self.assertEqual(c1["position_mapping"],
                         c2["position_mapping"])

    def test_family_swap_prompts_byte_identical(self):
        swapped = dict(DISPUTE, family="famA",
                       raiser_family="famB")
        s1 = Seat([payload(), payload()])
        s2 = Seat([payload(), payload()])
        adjudicate(s1)
        adjudicate(s2, dispute=swapped)
        self.assertEqual(s1.prompts, s2.prompts)

    def test_vendor_and_family_names_never_reach_seat(self):
        finding = dict(
            FINDING,
            evidence="flagged by OpenAI GPT-5 reviewers; "
                     "famA stands by it")
        dispute = dict(
            DISPUTE,
            reason="DeepSeek and Claude disagree; famB "
                   "maintains the printed value refutes it")
        seat = Seat([payload(), payload()])
        adjudicate(seat, finding=finding, dispute=dispute)
        shown = "\n".join(seat.prompts)
        for name in ("OpenAI", "GPT-5", "Claude", "DeepSeek",
                     "famA", "famB"):
            self.assertNotIn(name, shown)
        self.assertIn("[model]", shown)

    def test_canonical_order_is_content_keyed(self):
        c1 = techlead.canonicalise_packet(
            dict(FINDING), dict(DISPUTE), REGION)
        # Swap the two positions' TEXTS between the roles:
        # the canonical presentation order must not move,
        # only the recorded mapping flips.
        finding2 = dict(
            FINDING,
            title="the claim fails on the printed value",
            evidence="",
            evidence_quote=DISPUTE["evidence_quote"])
        dispute2 = dict(
            DISPUTE,
            reason="Total without guard VALUE = "
                   "compute_total(items) is used unbounded",
            evidence_quote=FINDING["evidence_quote"])
        c2 = techlead.canonicalise_packet(
            finding2, dispute2, REGION)
        self.assertEqual(
            [p["text"] for p in c1["packet"]["positions"]],
            [p["text"] for p in c2["packet"]["positions"]])
        self.assertNotEqual(c1["position_mapping"],
                            c2["position_mapping"])

    def test_invariance_labelled_by_construction(self):
        e = adjudicate(Seat([payload(), payload()]))
        self.assertEqual(
            e["canonicalisation"]["invariance"],
            "by_construction")
        note = techlead.summarise_paths([])[
            "invariance_note"]
        self.assertIn("BY CONSTRUCTION", note)
        self.assertIn("not a measured model property", note)


class NoEscalateTests(unittest.TestCase):
    def test_shadow_contract_and_versions(self):
        e = adjudicate(Seat([payload(), payload()]))
        self.assertEqual(e["mode"], "shadow")
        self.assertFalse(e["binding"])
        self.assertEqual(e["protocol_version"], 2)
        self.assertEqual(e["rubric_version"], 2)
        self.assertEqual(e["judging_frame"], "as_raised")

    def test_seat_escalate_is_not_a_verdict(self):
        seat = Seat([payload(verdict="escalate")])
        e = adjudicate(seat)
        self.assertEqual(e["state"], "unavailable")
        self.assertIsNone(e["decision"])
        self.assertIsNone(e["escalation_rule"])
        self.assertIn("not a model-selectable output",
                      e["error"])

    def test_seat_needs_probe_is_not_a_verdict(self):
        seat = Seat([payload(verdict="needs_probe")])
        e = adjudicate(seat)
        self.assertEqual(e["state"], "unavailable")
        self.assertIn("needs_probe", e["error"])

    def test_missing_confidence_is_invalid(self):
        p = payload()
        del p["confidence"]
        e = adjudicate(Seat([p]))
        self.assertEqual(e["state"], "unavailable")
        self.assertIn("confidence", e["error"])

    def test_word_confidence_is_invalid(self):
        e = adjudicate(Seat([payload(confidence="high")]))
        self.assertEqual(e["state"], "unavailable")

    def test_out_of_range_confidence_is_invalid(self):
        e = adjudicate(Seat([payload(confidence=1.5)]))
        self.assertEqual(e["state"], "unavailable")

    def test_no_bare_escalations(self):
        scenarios = [
            adjudicate(Seat([payload()]), protected=True),
            adjudicate(Seat([payload()]), seat_family="famA"),
            adjudicate(Seat([payload(),
                             payload(
                                 verdict="sustain_refutation")])),
            adjudicate(Seat([payload(
                verdict="sustain_refutation"),
                payload(verdict="sustain_refutation")])),
            adjudicate(Seat([payload(confidence=0.3,
                                     level="minor"),
                             payload(confidence=0.3,
                                     level="minor")]),
                       finding=MINOR_FINDING),
        ]
        for e in scenarios:
            self.assertEqual(e["state"], "escalated")
            self.assertIn(e["escalation_rule"],
                          techlead.ESCALATION_RULES)
            self.assertTrue(e["escalation_detail"])
            self.assertEqual(e["escalation_rules"][0],
                             e["escalation_rule"])


class EscalationRuleTests(unittest.TestCase):
    def test_protected_escalates_without_seat_call(self):
        seat = Seat([payload()])
        e = adjudicate(seat, protected=True)
        self.assertEqual(e["state"], "escalated")
        self.assertEqual(e["escalation_rule"],
                         "protected_class")
        self.assertEqual(seat.prompts, [])
        self.assertEqual(e["draws"], [])
        self.assertEqual(e["stage"], "never")

    def test_protected_carried_on_finding(self):
        finding = dict(FINDING, case_class="protected_class")
        seat = Seat([payload()])
        e = adjudicate(seat, finding=finding)
        self.assertEqual(e["escalation_rule"],
                         "protected_class")
        self.assertEqual(seat.prompts, [])

    def test_independence_unmet(self):
        seat = Seat([payload()])
        e = adjudicate(seat, seat_family="famA")
        self.assertEqual(e["escalation_rule"],
                         "independence_unmet")
        self.assertEqual(seat.prompts, [])

    def test_independence_unknown_family(self):
        e = adjudicate(Seat([payload()]), seat_family=None)
        self.assertEqual(e["escalation_rule"],
                         "independence_unmet")

    def test_draws_disagree(self):
        seat = Seat([payload(),
                     payload(verdict="sustain_refutation")])
        e = adjudicate(seat)
        self.assertEqual(e["state"], "escalated")
        self.assertEqual(e["escalation_rule"],
                         "draws_disagree")
        self.assertFalse(e["draws_agree"])

    def test_ungrounded_quote_is_evidence_ineligible(self):
        bad = payload(quote="NOT IN THE REGION AT ALL")
        e = adjudicate(Seat([bad, bad]))
        self.assertEqual(e["escalation_rule"],
                         "evidence_ineligible")
        check = e["draws"][0]["deciding_quote_check"]
        self.assertFalse(check["grounded"])
        self.assertFalse(check["eligible"])

    def test_major_dismissal_without_probe_escalates(self):
        d = payload(verdict="sustain_refutation")
        e = adjudicate(Seat([d, d]))
        self.assertEqual(e["state"], "escalated")
        self.assertEqual(
            e["escalation_rule"],
            "major_dismissal_without_probe")

    def test_all_firing_rules_recorded_in_precedence(self):
        d = payload(verdict="sustain_refutation",
                    quote="NOT IN THE REGION AT ALL")
        e = adjudicate(Seat([d, d]))
        self.assertEqual(
            e["escalation_rules"],
            ["evidence_ineligible",
             "major_dismissal_without_probe"])
        self.assertEqual(e["escalation_rule"],
                         "evidence_ineligible")

    def test_low_confidence_escalates(self):
        seat = Seat([payload(confidence=0.3, level="minor"),
                     payload(confidence=0.3, level="minor")])
        e = adjudicate(seat, finding=MINOR_FINDING)
        self.assertEqual(e["escalation_rule"],
                         "low_confidence")
        # The shaky first draw bought a second draw.
        self.assertEqual(len(e["draws"]), 2)
        self.assertTrue(e["draws_agree"])

    def test_threshold_is_configured(self):
        seat = Seat([payload(confidence=0.3, level="minor")])
        e = adjudicate(seat, finding=MINOR_FINDING,
                       confidence_threshold=0.2)
        self.assertEqual(e["state"], "decided")
        self.assertEqual(e["decision"], "sustain_finding")
        self.assertEqual(e["confidence_threshold"], 0.2)


class DismissalQuoteCheckerCompositionTests(unittest.TestCase):
    """The eligibility logic must CONSUME
    core._dismissal_quote_check (the harness-fixes entry
    point) when it exists, and fall back to grounding only
    — loudly — when it does not. The relevance screen is
    never reimplemented here."""

    def _dismiss(self, **kw):
        d = payload(verdict="sustain_refutation",
                    level="minor")
        return adjudicate(Seat([d, d]),
                          finding=MINOR_FINDING, **kw)

    def test_checker_ineligible_escalates(self):
        stub = lambda q, r, c: {  # noqa: E731
            "eligible": False, "distinct": False,
            "relevant": True, "shared_tokens": []}
        with mock.patch.object(core, "_dismissal_quote_check",
                               stub, create=True):
            e = self._dismiss()
        self.assertEqual(e["escalation_rule"],
                         "evidence_ineligible")
        check = e["draws"][0]["deciding_quote_check"]
        self.assertEqual(check["checker"],
                         "core._dismissal_quote_check")
        self.assertFalse(check["distinct"])

    def test_checker_eligible_decides(self):
        stub = lambda q, r, c: {  # noqa: E731
            "eligible": True, "distinct": True,
            "relevant": True, "shared_tokens": ["value"]}
        with mock.patch.object(core, "_dismissal_quote_check",
                               stub, create=True):
            e = self._dismiss()
        self.assertEqual(e["state"], "decided")
        self.assertEqual(e["decision"], "sustain_refutation")

    def test_fallback_is_grounding_only_and_labelled(self):
        with mock.patch.object(core, "_dismissal_quote_check",
                               None, create=True):
            e = self._dismiss()
        self.assertEqual(e["state"], "decided")
        check = e["draws"][0]["deciding_quote_check"]
        self.assertIn("fallback", check["checker"])
        self.assertIsNone(check["distinct"])
        self.assertIsNone(check["relevant"])


class ProbePathTests(unittest.TestCase):
    PASS_PROBE = {"id": "P1", "result": "PASS",
                  "summary": "assertion held on the "
                             "as-raised code"}
    FIX_PROBE = {"id": "P6", "result": "FIX_SHIPPED",
                 "summary": "the shared helper now serves "
                            "this call site"}

    def test_probe_decision_vocabulary(self):
        self.assertEqual(
            techlead.probe_decision(
                {"result": "FIX_SHIPPED"})["decision"],
            "sustain_finding")
        self.assertEqual(
            techlead.probe_decision(
                {"result": "PASS"})["decision"],
            "sustain_refutation")
        self.assertTrue(techlead.probe_decision(
            {"outcome": "pass", "can_rebut": True})[
                "settles"])
        self.assertFalse(techlead.probe_decision(
            {"outcome": "fail", "can_rebut": True,
             "can_support": False})["settles"])
        self.assertFalse(techlead.probe_decision(
            {"status": "wiring_error", "outcome": "error",
             "can_rebut": False})["settles"])

    def test_settling_probe_decides_deterministically(self):
        seat = Seat([adequacy(True)])
        e = adjudicate(seat, probe_result=self.PASS_PROBE)
        self.assertEqual(e["path"], "deterministic_probe")
        self.assertEqual(e["state"], "decided")
        self.assertEqual(e["decision"], "sustain_refutation")
        self.assertEqual(e["draws"], [])
        self.assertTrue(e["probe_adequacy"]["tests_claim"])
        self.assertEqual(e["stage"], 1)
        # The seat was asked ONLY the adequacy question.
        self.assertEqual(len(seat.prompts), 1)
        self.assertIn("whether a probe actually tests",
                      seat.prompts[0])

    def test_fix_shipped_probe_sustains(self):
        # The L06 shape: remediation presented as evidence.
        # In v2 it cannot be inverted into a dismissal —
        # the probe path decides before any seat verdict.
        seat = Seat([adequacy(True)])
        e = adjudicate(seat, probe_result=self.FIX_PROBE)
        self.assertEqual(e["decision"], "sustain_finding")
        self.assertEqual(e["path"], "deterministic_probe")
        self.assertIn("as raised",
                      e["decision_basis"])

    def test_adequacy_failure_falls_to_model_path(self):
        seat = Seat([adequacy(False), payload(), payload()])
        e = adjudicate(seat, probe_result=self.PASS_PROBE)
        self.assertEqual(e["path"], "model")
        self.assertEqual(e["probe_path_aborted"],
                         "adequacy_failed")
        self.assertEqual(e["state"], "decided")
        self.assertEqual(e["decision"], "sustain_finding")
        self.assertEqual(len(e["draws"]), 2)

    def test_ungradeable_adequacy_escalates(self):
        seat = Seat([{"no_grade_here": 1}])
        e = adjudicate(seat, probe_result=self.PASS_PROBE)
        self.assertEqual(e["state"], "escalated")
        self.assertEqual(e["escalation_rule"],
                         "evidence_ineligible")
        self.assertEqual(e["path"], "deterministic_probe")

    def test_non_settling_probe_leaves_model_path(self):
        probe = {"outcome": "fail", "can_rebut": True,
                 "can_support": False,
                 "detail": "prediction held"}
        seat = Seat([payload(), payload()])
        e = adjudicate(seat, probe_result=probe)
        self.assertEqual(e["path"], "model")
        self.assertEqual(e["state"], "decided")

    def test_adequacy_failed_probe_is_not_support(self):
        # A major dismissal after the probe was graded as
        # NOT testing the claim still has no probe support.
        d = payload(verdict="sustain_refutation")
        seat = Seat([adequacy(False), d, d])
        e = adjudicate(seat, probe_result=self.PASS_PROBE)
        self.assertEqual(e["path"], "model")
        self.assertEqual(
            e["escalation_rule"],
            "major_dismissal_without_probe")


class ABSwapTests(unittest.TestCase):
    def test_second_draw_swaps_positions(self):
        seat = Seat([payload(), payload()])
        adjudicate(seat)
        self.assertEqual(len(seat.prompts), 2)

        def pos1_text(prompt):
            return prompt.split("POSITION 1 argues:")[1] \
                .split("POSITION 1's evidence quote")[0]

        def pos2_text(prompt):
            return prompt.split("POSITION 2 argues:")[1] \
                .split("POSITION 2's evidence quote")[0]

        self.assertNotEqual(pos1_text(seat.prompts[0]),
                            pos1_text(seat.prompts[1]))
        self.assertEqual(pos1_text(seat.prompts[0]),
                         pos2_text(seat.prompts[1]))
        self.assertEqual(pos2_text(seat.prompts[0]),
                         pos1_text(seat.prompts[1]))

    def test_major_always_two_draws(self):
        seat = Seat([payload(confidence=0.95)])
        e = adjudicate(seat)
        self.assertEqual(len(e["draws"]), 2)
        self.assertTrue(e["draws_agree"])

    def test_minor_single_draw_when_confident(self):
        seat = Seat([payload(confidence=0.95, level="minor")])
        e = adjudicate(seat, finding=MINOR_FINDING)
        self.assertEqual(len(e["draws"]), 1)
        self.assertEqual(e["state"], "decided")

    def test_minor_evaluation_mode_two_draws(self):
        seat = Seat([payload(confidence=0.95, level="minor"),
                     payload(confidence=0.95, level="minor")])
        e = adjudicate(seat, finding=MINOR_FINDING,
                       evaluation_mode=True)
        self.assertEqual(len(e["draws"]), 2)
        self.assertTrue(e["draws_agree"])

    def test_grades_mapped_back_to_roles(self):
        seat = Seat([payload(), payload()])
        e = adjudicate(seat)
        self.assertEqual(set(e["grades"]),
                         {"raiser", "refuter"})
        first_role = e["draws"][0]["presentation"]["A"]
        self.assertTrue(e["grades"][first_role]["value"])


class FramingAndRubricTests(unittest.TestCase):
    def _prompt(self):
        seat = Seat([payload(), payload()])
        adjudicate(seat)
        return seat.prompts[0]

    def test_as_raised_frame_stated(self):
        prompt = self._prompt()
        self.assertIn("AS RAISED", prompt)
        self.assertIn("SUPPORTS the finding", prompt)
        self.assertIn("prediction fails on the as-raised "
                      "code", prompt)

    def test_both_costs_stated(self):
        prompt = self._prompt()
        self.assertIn("a wrong dismissal is costly", prompt)
        self.assertIn("an unnecessary escalation is costly",
                      prompt)
        self.assertIn("owner's time", prompt)
        self.assertIn("Do not shade your verdict", prompt)

    def test_harness_rules_shown_to_seat(self):
        prompt = self._prompt()
        self.assertIn("You cannot escalate", prompt)
        self.assertIn("protected class", prompt)
        self.assertIn("confidence below the harness "
                      "threshold", prompt)

    def test_verdict_schema_has_no_escalate(self):
        schema_line = [ln for ln in self._prompt().splitlines()
                       if '"verdict":' in ln]
        self.assertEqual(len(schema_line), 1)
        self.assertIn("sustain_finding", schema_line[0])
        self.assertIn("sustain_refutation", schema_line[0])
        self.assertNotIn("escalate", schema_line[0])


class StageTagTests(unittest.TestCase):
    def test_no_stage_is_enabled(self):
        self.assertEqual(techlead.ENABLED_STAGES,
                         frozenset())
        e = adjudicate(Seat([payload(), payload()]))
        self.assertFalse(e["authority_stage_enabled"])

    def test_sustain_is_stage_1(self):
        e = adjudicate(Seat([payload(), payload()]))
        self.assertEqual(e["stage"], 1)
        e2 = adjudicate(
            Seat([payload(level="minor")]),
            finding=MINOR_FINDING)
        self.assertEqual(e2["stage"], 1)

    def test_minor_dismissal_consistent_draws_stage_2(self):
        d = payload(verdict="sustain_refutation",
                    level="minor")
        e = adjudicate(Seat([d, d]), finding=MINOR_FINDING,
                       evaluation_mode=True)
        self.assertEqual(e["state"], "decided")
        self.assertEqual(e["stage"], 2)

    def test_minor_dismissal_single_draw_is_stage_3(self):
        # A single-draw minor dismissal never met stage
        # 2's evidence bar (probe support or consistent
        # double draw) — tagged stage 3, honestly.
        d = payload(verdict="sustain_refutation",
                    confidence=0.95, level="minor")
        e = adjudicate(Seat([d]), finding=MINOR_FINDING)
        self.assertEqual(e["state"], "decided")
        self.assertEqual(len(e["draws"]), 1)
        self.assertEqual(e["stage"], 3)

    def test_blocker_probe_decision_is_stage_never(self):
        seat = Seat([adequacy(True)])
        e = adjudicate(seat, finding=BLOCKER_FINDING,
                       probe_result=ProbePathTests.PASS_PROBE)
        self.assertEqual(e["state"], "decided")
        self.assertEqual(e["stage"], "never")


class SummarisePathsTests(unittest.TestCase):
    def test_paths_reported_separately(self):
        probe_entry = adjudicate(
            Seat([adequacy(True)]),
            probe_result=ProbePathTests.PASS_PROBE)
        model_entry = adjudicate(Seat([payload(),
                                       payload()]))
        esc_entry = adjudicate(Seat([payload()]),
                               protected=True)
        summary = techlead.summarise_paths(
            [probe_entry, model_entry, esc_entry])
        det = summary["deterministic_probe"]
        self.assertEqual(det["total"], 1)
        self.assertEqual(det["decided"], 1)
        self.assertEqual(
            det["decisions"], {"sustain_refutation": 1})
        self.assertEqual(
            det["probe_adequacy"]["tests_claim"], 1)
        model = summary["model"]
        self.assertEqual(model["total"], 1)
        self.assertEqual(model["decided"], 1)
        self.assertNotIn("probe_adequacy", model)
        # No blended aggregate anywhere at the top level.
        self.assertNotIn("decisions", summary)
        self.assertNotIn("escalation_rules", summary)


if __name__ == "__main__":
    unittest.main()
