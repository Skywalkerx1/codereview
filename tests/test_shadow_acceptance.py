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


def _payload(decision, quote="gamma line", claim_valid=False,
             validity="valid"):
    # Default deciding quote "gamma line": distinct from the
    # refuter's quote ("beta line") — since the L06 harness
    # fix a dismissal on the refuter's own quote is
    # evidence-ineligible (tests/test_harness_fixes.py).
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

    def test_metric_set_tolerates_absent_case_ids(self):
        # 633acb885291: an explicit scorecard set naming a
        # case the corpus does not have scores over the
        # present cases — no bare KeyError.
        cases = [_case("D1", "sustain_finding")]
        seat = _Seat({"D1": [_payload("sustain_finding",
                                      quote="alpha line")]})
        with tempfile.TemporaryDirectory() as td:
            _write_corpus(td, cases, m1_set=["D1", "ZZ9"])
            result = acceptance.run_acceptance(
                td, seat, seat_family="famC",
                do_mutations=False)
        m1 = result["metrics"][
            "M1_false_dismissals_on_real_findings"]
        self.assertEqual(m1["measured"], 0)
        self.assertEqual(m1["set_size"], 1)

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


def _write_empty_corpus(root, scorecard):
    os.makedirs(os.path.join(root, "cases"))
    with open(os.path.join(root, "index.json"), "w") as fh:
        json.dump({"cases": []}, fh)
    with open(os.path.join(root, "scorecard.json"), "w") as fh:
        json.dump(scorecard, fh)
    with open(os.path.join(root, "mutations.json"), "w") as fh:
        json.dump({"mutations": []}, fh)


def _seat_must_not_be_called(prompt):
    raise AssertionError("seat called for an empty corpus")


class EmptyCorpusTests(unittest.TestCase):
    """633acb885291 regression: an empty corpus produces a
    scored run record with unlock False — never a
    ZeroDivisionError (set-less scorecard, M3) or a KeyError
    (explicit sets naming absent cases, M1)."""

    def test_empty_corpus_explicit_sets(self):
        with tempfile.TemporaryDirectory() as td:
            _write_corpus(td, [], m1_set=["L06", "L07"])
            result = acceptance.run_acceptance(
                td, _seat_must_not_be_called,
                seat_family="famC", do_mutations=True)
        self.assertEqual(result["cases"], {})
        self.assertFalse(result["unlock_all_gates_pass"])
        m = result["metrics"]
        self.assertEqual(
            m["M1_false_dismissals_on_real_findings"]
            ["set_size"], 0)
        self.assertEqual(
            m["M3_overall_accuracy"]["measured"], 0.0)
        self.assertFalse(m["M3_overall_accuracy"]["pass"])

    def test_empty_corpus_setless_scorecard(self):
        scorecard = {"metrics": [
            {"id": "M1_false_dismissals_on_real_findings",
             "threshold": {"op": "==", "value": 0}},
            {"id": "M2_probe_settled_accuracy",
             "threshold": {"op": ">=", "value": 1.0}},
            {"id": "M3_overall_accuracy",
             "threshold": {"op": ">=", "value": 0.9}},
            {"id": "M4_mutation_flip_rate",
             "threshold": {"op": "<=", "value": 0.05}},
            {"id": "M5_protected_and_insufficient_escalated",
             "threshold": {"op": ">=", "value": 1.0}},
            {"id": "M6_double_draw_agreement_on_majors",
             "threshold": {"op": ">=", "value": 0.9}}]}
        with tempfile.TemporaryDirectory() as td:
            _write_empty_corpus(td, scorecard)
            result = acceptance.run_acceptance(
                td, _seat_must_not_be_called,
                seat_family="famC", do_mutations=True)
        self.assertEqual(result["cases"], {})
        self.assertFalse(result["unlock_all_gates_pass"])
        self.assertEqual(
            result["metrics"]["M3_overall_accuracy"]
            ["measured"], 0.0)


if __name__ == "__main__":
    unittest.main()
