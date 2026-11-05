"""Acceptance runner mechanics (scoring rules, mutation
accounting, metric computation) over a synthetic mini-corpus
with scripted seats. The live-corpus run is an execution
step, not a unit test."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import acceptance  # noqa: E402

REGION = "alpha line\nbeta line\ngamma line\n"


def _case(cid, decision, scoring="exact", sev="major",
          reasoning=None, real=False):
    c = {"case_id": cid, "case_class": "synthetic",
         "title": cid,
         "finding": {"claim": f"claim {cid}",
                     "evidence": "alpha line",
                     "evidence_quote": "alpha line",
                     "severity_as_raised": sev,
                     "file": "x.py", "line": 1,
                     "raised_by_family": "famA",
                     "record_finding_id": cid},
         "refutation": {"by_family": "famB",
                        "quote": "beta line",
                        "reason": "the claim is wrong"},
         "code_region": {"path": "x.py", "start_line": 1,
                         "end_line": 3, "text": REGION},
         "probe": None,
         "expected": {"decision": decision,
                      "severity_after": None,
                      "scoring": scoring}}
    if reasoning:
        c["expected"]["reasoning_validity"] = reasoning
    return c


def _write_corpus(root, cases, m1_set):
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
        {"id": "M2_probe_settled_accuracy", "set": [],
         "threshold": {"op": ">=", "value": 1.0}},
        {"id": "M3_overall_accuracy", "set": "all",
         "threshold": {"op": ">=", "value": 0.9}},
        {"id": "M4_mutation_flip_rate", "set": "all",
         "threshold": {"op": "<=", "value": 0.05}},
        {"id": "M5_protected_and_insufficient_escalated",
         "set": [], "threshold": {"op": ">=", "value": 1.0}},
        {"id": "M6_double_draw_agreement_on_majors",
         "set": "majors",
         "threshold": {"op": ">=", "value": 0.9}}]}
    with open(os.path.join(root, "scorecard.json"), "w") as fh:
        json.dump(scorecard, fh)
    mutations = {"mutations": [{"id": "position_swap"},
                               {"id": "family_swap"},
                               {"id": "vendor_strip"},
                               {"id": "reason_paraphrase"}]}
    with open(os.path.join(root, "mutations.json"), "w") as fh:
        json.dump(mutations, fh)


def _payload(decision, quote="beta line", claim_valid=False,
             validity="valid"):
    return {"claim_restated": "restated",
            "claim_falsifiable": True,
            "position_a_addresses_claim": {"value": True,
                                           "why": "w"},
            "position_b_addresses_claim": {"value": True,
                                           "why": "w"},
            "reasoning_assessment": {
                "claim_valid": claim_valid,
                "refutation_validity": validity},
            "deciding_evidence": {"quote": quote},
            "probe_request": None,
            "decision": decision,
            "severity_after_rubric": {"level": "major",
                                      "rubric_clause": None},
            "confidence": "high", "rationale": "r"}


class _Seat:
    """Answers shadow prompts by the claim id in the prompt;
    paraphrase prompts get a word-shuffled echo."""

    def __init__(self, decisions):
        self.decisions = decisions

    def __call__(self, prompt):
        if prompt.startswith("Paraphrase the following text"):
            return "paraphrased prose here"
        for cid, payloads in self.decisions.items():
            if f"claim {cid}" in prompt:
                p = payloads.pop(0) if len(payloads) > 1 \
                    else payloads[0]
                return json.dumps(p)
        return json.dumps(_payload("escalate"))


class AcceptanceRunnerTests(unittest.TestCase):
    def test_scoring_and_metrics(self):
        cases = [
            _case("A1", "sustain_refutation"),
            _case("A2", "sustain_finding"),
            _case("A3", "escalate",
                  scoring="dismissal_evidence_rule"),
            _case("A4", "sustain_refutation",
                  scoring="machinery_two_field",
                  reasoning={"claim": "false",
                             "refutation": "weak_self_quote"}),
        ]
        seat = _Seat({
            "A1": [_payload("sustain_refutation")],
            "A2": [_payload("sustain_finding",
                            quote="alpha line")],
            "A3": [_payload("escalate")],
            "A4": [_payload("sustain_refutation",
                            validity="weak_self_quote")],
        })
        with tempfile.TemporaryDirectory() as td:
            _write_corpus(td, cases, m1_set=["A2"])
            result = acceptance.run_acceptance(
                td, seat, seat_family="famC",
                do_mutations=False)
        self.assertTrue(
            all(result["cases"][c]["score"]["correct"]
                for c in ("A1", "A2", "A3", "A4")))
        m = result["metrics"]
        self.assertEqual(
            m["M1_false_dismissals_on_real_findings"]
            ["measured"], 0)
        self.assertEqual(m["M3_overall_accuracy"]["measured"],
                         1.0)
        self.assertEqual(
            m["M6_double_draw_agreement_on_majors"]
            ["measured"], 1.0)
        self.assertFalse(result["unlock_all_gates_pass"])  # M2/M5 empty sets

    def test_false_dismissal_counted(self):
        cases = [_case("B1", "sustain_finding")]
        seat = _Seat({"B1": [_payload("sustain_refutation")]})
        with tempfile.TemporaryDirectory() as td:
            _write_corpus(td, cases, m1_set=["B1"])
            result = acceptance.run_acceptance(
                td, seat, seat_family="famC",
                do_mutations=False)
        self.assertEqual(
            result["metrics"]
            ["M1_false_dismissals_on_real_findings"]
            ["measured"], 1)
        self.assertFalse(result["cases"]["B1"]["score"]
                         ["correct"])

    def test_dismissal_evidence_rule_rejects_self_quote(self):
        entry = {"decision": "sustain_refutation",
                 "deciding_evidence": {"quote": "beta line"},
                 "severity_after_rubric": {"level": "major"}}
        case = _case("C1", "escalate",
                     scoring="dismissal_evidence_rule")
        score = acceptance.score_case(case, entry)
        self.assertFalse(score["correct"])
        entry["deciding_evidence"]["quote"] = "gamma line"
        score = acceptance.score_case(case, entry)
        self.assertTrue(score["correct"])


if __name__ == "__main__":
    unittest.main()
