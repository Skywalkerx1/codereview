"""Acceptance wiring for adjudication protocol v2
(honest-negatives solution §3.4, Part A): the redesigned
adjudicator (techlead.adjudicate) scored through the SAME
scorer and metric computation as the v1 runner, with the
two paths reported separately. Scripted seats over a
synthetic mini-corpus; the live dev-set search is an
execution step, not a unit test."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import acceptance, techlead  # noqa: E402

REGION = ("alpha line\n"
          "beta line\n"
          "gamma_value = compute_total(items)\n"
          "delta line\n")
QUOTE = "gamma_value = compute_total(items)"


def _case(cid, decision, scoring="exact", sev="major",
          case_class="synthetic", reasoning=None, probe=None,
          extra=None):
    c = {"case_id": cid, "case_class": case_class,
         "title": cid,
         "finding": {"claim": f"claim {cid}",
                     "evidence": f"evidence {cid}: gamma_value "
                                 "is used unbounded",
                     "evidence_quote": "alpha line",
                     "severity_as_raised": sev,
                     "file": "x.py", "line": 3,
                     "raised_by_family": "famA",
                     "record_finding_id": cid},
         "refutation": {"by_family": "famB",
                        "quote": "beta line",
                        "reason": "the claim is wrong"},
         "code_region": {"path": "x.py", "start_line": 1,
                         "end_line": 4, "text": REGION},
         "probe": probe,
         "expected": {"decision": decision,
                      "severity_after": None,
                      "scoring": scoring}}
    if reasoning:
        c["expected"]["reasoning_validity"] = reasoning
    if extra:
        c.update(extra)
    return c


def _write_corpus(root, cases, m1_set, m2_set, m5_set):
    os.makedirs(os.path.join(root, "cases"))
    index = {"cases": [{"case_id": c["case_id"]} for c in cases]}
    with open(os.path.join(root, "index.json"), "w") as fh:
        json.dump(index, fh)
    for c in cases:
        with open(os.path.join(
                root, "cases", c["case_id"] + ".json"),
                "w") as fh:
            json.dump(c, fh)
    scorecard = {"metrics": [
        {"id": "M1_false_dismissals_on_real_findings",
         "set": m1_set, "threshold": {"op": "==", "value": 0}},
        {"id": "M2_probe_settled_accuracy", "set": m2_set,
         "threshold": {"op": ">=", "value": 1.0}},
        {"id": "M3_overall_accuracy", "set": "all",
         "threshold": {"op": ">=", "value": 0.9}},
        {"id": "M4_mutation_flip_rate", "set": "all",
         "threshold": {"op": "<=", "value": 0.05}},
        {"id": "M5_protected_and_insufficient_escalated",
         "set": m5_set, "threshold": {"op": ">=", "value": 1.0}},
        {"id": "M6_double_draw_agreement_on_majors",
         "set": "majors",
         "threshold": {"op": ">=", "value": 0.9}}]}
    with open(os.path.join(root, "scorecard.json"), "w") as fh:
        json.dump(scorecard, fh)
    with open(os.path.join(root, "mutations.json"), "w") as fh:
        json.dump({"mutations": [{"id": "position_swap"}]}, fh)


def _verdict(verdict, confidence=0.95, claim_valid=True,
             validity="valid", level="major"):
    return {"verdict": verdict, "confidence": confidence,
            "deciding_quote": QUOTE,
            "severity_after_rubric": {"level": level,
                                      "rubric_clause": None},
            "claim_restated": "restated",
            "position_a_addresses_claim": {"value": True,
                                           "why": "w"},
            "position_b_addresses_claim": {"value": True,
                                           "why": "w"},
            "reasoning_assessment": {
                "claim_valid": claim_valid,
                "refutation_validity": validity},
            "rationale": "r"}


class _Seat:
    """Dispatches on the case marker in the prompt; adequacy
    prompts get the adequacy payload. Records every prompt."""

    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if prompt.startswith("You are grading ONE thing"):
            return json.dumps(
                {"tests_claim": True, "confidence": 0.95,
                 "why": "the probe exercises the cited call"})
        for cid, payloads in self.verdicts.items():
            if f"claim {cid}" in prompt:
                p = payloads.pop(0) if len(payloads) > 1 \
                    else payloads[0]
                return json.dumps(p)
        raise AssertionError(f"unscripted prompt: {prompt[:80]}")


def _mini_corpus(root):
    cases = [
        # Deterministic path: the corpus probe settles the
        # claim; the seat only grades adequacy.
        _case("D1", "sustain_refutation",
              probe={"id": "P1", "result": "PASS",
                     "summary": "the prediction fails on the "
                                "as-raised code"}),
        # Real finding, model path: the seat dismisses a
        # major with no probe support — the harness must
        # escalate, so this is NOT a false dismissal.
        _case("R1", "sustain_finding"),
        # Model path: agreed sustain on a major.
        _case("F1", "sustain_finding"),
        # Machinery two-field on a minor: the dismissal
        # stands on a consistent double draw and is scored
        # on the seat's own reasoning assessment.
        _case("G1", "sustain_refutation",
              scoring="machinery_two_field", sev="minor",
              reasoning={"claim": "false",
                         "refutation": "weak_self_quote"}),
        # Protected class: routed by the harness; the seat
        # must never be called for this case.
        _case("X1", "escalate", case_class="protected_class",
              extra={"protected_class":
                     "confidentiality_and_policy"}),
        # Draws disagree: harness escalation.
        _case("W1", "sustain_finding"),
    ]
    _write_corpus(root, cases, m1_set=["R1"], m2_set=["D1"],
                  m5_set=["X1"])
    seat = _Seat({
        "R1": [_verdict("sustain_refutation")],
        "F1": [_verdict("sustain_finding")],
        "G1": [_verdict("sustain_refutation", claim_valid=False,
                        validity="weak_self_quote",
                        level="minor")],
        "W1": [_verdict("sustain_finding"),
               _verdict("sustain_refutation")],
    })
    return seat


class RunAcceptanceV2Tests(unittest.TestCase):

    def _run(self, root):
        seat = _mini_corpus(root)
        result = acceptance.run_acceptance_v2(
            root, seat, seat_family="famC",
            seat_name="scripted-v2", timeout=30)
        return seat, result

    def test_paths_reported_separately(self):
        with tempfile.TemporaryDirectory() as root:
            _seat, result = self._run(root)
            paths = result["paths"]
            self.assertEqual(
                paths["deterministic_probe"]["cases"], ["D1"])
            self.assertEqual(
                paths["deterministic_probe"]["correct"], 1)
            self.assertEqual(
                sorted(paths["model"]["cases"]),
                ["F1", "G1", "R1", "W1"])
            self.assertEqual(
                paths["routing_or_unavailable"]["cases"],
                ["X1"])
            total = sum(paths[k]["total"] for k in (
                "deterministic_probe", "model",
                "routing_or_unavailable"))
            self.assertEqual(total, 6)
            # No blended aggregate anywhere in the record.
            self.assertNotIn("combined", json.dumps(
                result["paths"]["summary"]))

    def test_probe_path_entry_shape(self):
        with tempfile.TemporaryDirectory() as root:
            _seat, result = self._run(root)
            entry = result["cases"]["D1"]["entry"]
            self.assertEqual(entry["path"],
                             "deterministic_probe")
            self.assertEqual(entry["decision"],
                             "sustain_refutation")
            self.assertEqual(entry["draws"], [])
            self.assertIsNone(entry["draws_agree"])
            self.assertTrue(
                result["cases"]["D1"]["score"]["correct"])

    def test_major_dismissal_without_probe_is_not_m1(self):
        with tempfile.TemporaryDirectory() as root:
            _seat, result = self._run(root)
            entry = result["cases"]["R1"]["entry"]
            self.assertEqual(entry["escalation_rule"],
                             "major_dismissal_without_probe")
            self.assertEqual(
                result["metrics"]
                ["M1_false_dismissals_on_real_findings"]
                ["measured"], 0)
            self.assertEqual(
                result["paths"]["model"]
                ["false_dismissals_on_m1_set"], 0)

    def test_machinery_two_field_uses_seat_assessment(self):
        with tempfile.TemporaryDirectory() as root:
            _seat, result = self._run(root)
            score = result["cases"]["G1"]["score"]
            self.assertTrue(score["correct"])
            self.assertEqual(score["reasoning_match"],
                             {"claim": True, "refutation": True})
            entry = result["cases"]["G1"]["entry"]
            self.assertEqual(
                entry["reasoning_assessment"],
                {"claim_valid": False,
                 "refutation_validity": "weak_self_quote"})

    def test_protected_case_consumes_no_seat_call(self):
        with tempfile.TemporaryDirectory() as root:
            seat, result = self._run(root)
            self.assertFalse(any(
                "claim X1" in p for p in seat.prompts))
            self.assertTrue(
                result["cases"]["X1"]["score"]["correct"])
            self.assertEqual(
                result["metrics"]
                ["M5_protected_and_insufficient_escalated"]
                ["measured"], 1.0)

    def test_draws_disagree_escalates_and_counts_in_m6(self):
        with tempfile.TemporaryDirectory() as root:
            _seat, result = self._run(root)
            entry = result["cases"]["W1"]["entry"]
            self.assertEqual(entry["escalation_rule"],
                             "draws_disagree")
            self.assertIs(entry["draws_agree"], False)
            m6 = result["metrics"][
                "M6_double_draw_agreement_on_majors"]
            # Majors: D1 (no draws — deterministic path),
            # R1/F1 agree, W1 disagrees, X1 no draws.
            self.assertEqual(m6["majors"], 5)
            self.assertEqual(m6["measured_cases"], 3)
            self.assertEqual(m6["agreed_cases"], 2)

    def test_record_states_protocol_and_counting_rules(self):
        with tempfile.TemporaryDirectory() as root:
            _seat, result = self._run(root)
            self.assertEqual(result["protocol"], "v2")
            self.assertEqual(result["protocol_version"],
                             techlead.TL_PROTOCOL_VERSION)
            self.assertIn("false_dismissal",
                          result["counting_rules_note"])
            m4 = result["metrics"]["M4_mutation_flip_rate"]
            self.assertIsNone(m4["measured"])
            self.assertFalse(m4["pass"])
            self.assertFalse(result["unlock_all_gates_pass"])
            m2 = result["metrics"]["M2_probe_settled_accuracy"]
            self.assertEqual(m2["measured"], 1.0)


class AdaptV2EntryTests(unittest.TestCase):

    def test_full_entry_passes_through(self):
        entry = {"decision": "sustain_finding",
                 "severity_after_rubric": {
                     "level": "minor", "rubric_clause": None},
                 "deciding_evidence": {"quote": "q"},
                 "draws_agree": True,
                 "reasoning_assessment": {
                     "claim_valid": True,
                     "refutation_validity": "contradicted"},
                 "path": "model"}
        out = acceptance.adapt_v2_entry(entry)
        self.assertEqual(out["decision"], "sustain_finding")
        self.assertEqual(
            out["severity_after_rubric"]["level"], "minor")
        self.assertEqual(out["deciding_evidence"],
                         {"quote": "q"})
        self.assertIs(out["draws_agree"], True)
        self.assertEqual(out["reasoning_assessment"],
                         {"claim_valid": True,
                          "refutation_validity": "contradicted"})
        self.assertEqual(out["path"], "model")

    def test_missing_assessment_is_reported_not_invented(self):
        out = acceptance.adapt_v2_entry(
            {"decision": None, "path": "deterministic_probe"})
        self.assertEqual(
            out["reasoning_assessment"],
            {"claim_valid": False, "refutation_validity": None})
        self.assertEqual(acceptance.scored_decision(out),
                         "escalate")
        self.assertEqual(out["deciding_evidence"],
                         {"quote": ""})


class ReasoningAssessmentDrawTests(unittest.TestCase):
    """The v2 draw records the seat's two-field assessment;
    a seat that omits it gets the v1 defaults, not an
    invented grade."""

    def _entry(self, payload):
        payload = dict(payload)
        payload["severity_after_rubric"] = {
            "level": "minor", "rubric_clause": None}
        seat = lambda prompt: json.dumps(payload)  # noqa: E731
        finding = {"id": "fx", "file": "x.py", "line": 3,
                   "severity": "minor", "title": "t",
                   "evidence": "gamma_value is used unbounded",
                   "evidence_quote": "alpha line"}
        dispute = {"by": "seatB", "family": "famB",
                   "raiser_family": "famA",
                   "evidence_quote": "beta line",
                   "reason": "the claim is wrong"}
        return techlead.adjudicate(
            seat, finding, REGION, dispute,
            seat_name="tl", seat_family="famC",
            evaluation_mode=True, timeout=30)

    def test_assessment_recorded_from_draw(self):
        entry = self._entry(_verdict(
            "sustain_finding", claim_valid=True,
            validity="contradicted"))
        self.assertEqual(entry["reasoning_assessment"],
                         {"claim_valid": True,
                          "refutation_validity": "contradicted"})

    def test_omitted_assessment_defaults_like_v1(self):
        payload = _verdict("sustain_finding")
        del payload["reasoning_assessment"]
        entry = self._entry(payload)
        self.assertEqual(entry["reasoning_assessment"],
                         {"claim_valid": False,
                          "refutation_validity": "valid"})

    def test_out_of_vocabulary_validity_normalised(self):
        entry = self._entry(_verdict(
            "sustain_finding", validity="mostly_valid"))
        self.assertEqual(
            entry["reasoning_assessment"]
            ["refutation_validity"], "valid")


if __name__ == "__main__":
    unittest.main()
