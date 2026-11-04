"""Tests for the Epic A benchmark harness — scripted seats only,
no network, no provider calls."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import bench, cli  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
SHIPPED_CORPUS = os.path.join(REPO_ROOT, "bench", "corpus")


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


def _finding(sev="blocker", cat="correctness", file="billing/charge.py",
             line=5, title=None, conf=0.9):
    return {"severity": sev, "category": cat, "file": file,
            "line": line,
            "title": title or "Charge amount passed in dollars where "
                              "the gateway expects cents",
            "confidence": conf}


class ScoringTests(unittest.TestCase):
    def _case(self, expected):
        return {"id": "x", "expected": expected}

    def test_perfect_score(self):
        case = self._case(PAYMENT_EXPECTED)
        scored = bench.score_case(case, [_finding()])
        self.assertEqual(scored["matched"], 1)
        self.assertEqual(scored["escaped"], 0)
        agg = bench.aggregate_scores([scored])
        self.assertEqual(agg["recall"], 1.0)
        self.assertEqual(agg["escaped_defect_rate"], 0.0)
        self.assertEqual(agg["precision"], 1.0)

    def test_blind_scores_zero_recall_full_escape(self):
        case = self._case(PAYMENT_EXPECTED)
        scored = bench.score_case(case, [])
        agg = bench.aggregate_scores([scored])
        self.assertEqual(agg["recall"], 0.0)
        self.assertEqual(agg["escaped_defect_rate"], 1.0)

    def test_minor_mention_matches_but_still_escapes(self):
        # Seen but waved through at a non-blocking severity: recall
        # credit, but the defect escaped the gate.
        case = self._case(PAYMENT_EXPECTED)
        scored = bench.score_case(case, [_finding(sev="minor")])
        self.assertEqual(scored["matched"], 1)
        self.assertEqual(scored["escaped"], 1)

    def test_wrong_file_does_not_match(self):
        case = self._case(PAYMENT_EXPECTED)
        scored = bench.score_case(
            case, [_finding(file="billing/other.py")])
        self.assertEqual(scored["matched"], 0)
        self.assertEqual(scored["false_positives"], 1)

    def test_line_tolerance_and_token_fallback(self):
        case = self._case(PAYMENT_EXPECTED)
        near = bench.score_case(case, [_finding(line=7)])
        self.assertEqual(near["matched"], 1)
        far_same_title = bench.score_case(case, [_finding(line=99)])
        self.assertEqual(far_same_title["matched"], 1)
        far_other_title = bench.score_case(
            case, [_finding(line=99, title="Unrelated style remark",
                            cat="quality")])
        self.assertEqual(far_other_title["matched"], 0)

    def test_one_finding_cannot_match_two_defects(self):
        case = self._case(PAYMENT_EXPECTED + [dict(PAYMENT_EXPECTED[0])])
        scored = bench.score_case(case, [_finding()])
        self.assertEqual(scored["matched"], 1)
        self.assertEqual(scored["escaped"], 1)

    def test_clean_case_false_positive_accounting(self):
        case = self._case([])
        scored = bench.score_case(
            case, [_finding(file="app/util.py", cat="quality",
                            title="Possible style issue")])
        agg = bench.aggregate_scores([scored])
        self.assertEqual(agg["clean_cases"], 1)
        self.assertEqual(agg["clean_cases_with_fp"], 1)
        self.assertEqual(agg["clean_fp_rate"], 1.0)
        self.assertIsNone(agg["recall"])

    def test_percentile_nearest_rank(self):
        vals = list(range(1, 101))
        self.assertEqual(bench.percentile(vals, 50), 50)
        self.assertEqual(bench.percentile(vals, 95), 95)
        self.assertIsNone(bench.percentile([], 50))
        self.assertEqual(bench.percentile([7], 95), 7)


class CorpusLoaderTests(unittest.TestCase):
    def test_shipped_corpus_loads_and_is_balanced(self):
        cases = bench.load_corpus(SHIPPED_CORPUS)
        self.assertGreaterEqual(len(cases), 24)
        splits = {c["split"] for c in cases}
        self.assertEqual(splits, {"public", "holdout"})
        holdout = [c for c in cases if c["split"] == "holdout"]
        self.assertGreaterEqual(len(holdout), 5)
        self.assertTrue(any(not c["expected"] for c in cases),
                        "corpus needs clean control cases")
        self.assertTrue(any(c["category"] == "real" for c in cases),
                        "corpus needs cases converted from real runs")
        cats = {c["category"] for c in cases}
        for needed in ("secrets", "injection", "auth", "payments"):
            self.assertIn(needed, cats)

    def test_loader_rejects_bad_severity(self):
        with tempfile.TemporaryDirectory() as td:
            bad = [dict(PAYMENT_EXPECTED[0], severity="critical")]
            _write_case(td, "bad-case", PAYMENT_DIFF, bad)
            with self.assertRaises(ValueError):
                bench.load_corpus(td)

    def test_loader_rejects_manifest_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            _write_case(td, "only-case", CLEAN_DIFF, [])
            with open(os.path.join(td, "manifest.json"), "w") as fh:
                json.dump({"cases": [{"id": "ghost-case"}]}, fh)
            with self.assertRaises(ValueError):
                bench.load_corpus(td)


class BenchEndToEndTests(unittest.TestCase):
    """A full bench run over a tiny fixture corpus with scripted
    seats: oracle is perfect, blind escapes everything."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self.corpus = os.path.join(root, "corpus")
        os.makedirs(os.path.join(root, "configs"))
        os.makedirs(os.path.join(root, "scripts"))
        self.out = os.path.join(root, "out")
        _write_case(self.corpus, "pay-bug", PAYMENT_DIFF,
                    PAYMENT_EXPECTED, category="payments")
        _write_case(self.corpus, "holdout-bug", PAYMENT_DIFF,
                    PAYMENT_EXPECTED, split="holdout",
                    category="payments")
        _write_case(self.corpus, "clean-one", CLEAN_DIFF, [],
                    category="clean")
        oracle = {
            "pay-bug": {"verdict": "changes_requested",
                        "summary": "found it", "findings": [
                            _finding()]},
            "holdout-bug": {"verdict": "changes_requested",
                            "summary": "found it", "findings": [
                                _finding()]},
            "clean-one": {"verdict": "pass", "summary": "clean",
                          "findings": []}}
        with open(os.path.join(root, "scripts", "oracle.json"),
                  "w") as fh:
            json.dump(oracle, fh)
        with open(os.path.join(root, "scripts", "blind.json"),
                  "w") as fh:
            json.dump({"default": {"verdict": "pass",
                                   "summary": "nothing",
                                   "findings": []}}, fh)
        for name in ("oracle", "blind"):
            with open(os.path.join(root, "configs", f"{name}.json"),
                      "w") as fh:
                json.dump({"name": name,
                           "providers": [{
                               "name": name,
                               "script": f"../scripts/{name}.json"}]},
                          fh)

    def tearDown(self):
        self._tmp.cleanup()

    def test_run_and_report(self):
        results = bench.run_bench(self.corpus, ["oracle", "blind"],
                                  self.out)
        self.assertEqual(len(results["oracle"]), 3)
        report = bench.build_report(results, self.corpus)
        oracle = report["configs"]["oracle"]["metrics"]
        blind = report["configs"]["blind"]["metrics"]
        self.assertEqual(oracle["recall"], 1.0)
        self.assertEqual(oracle["escaped_defect_rate"], 0.0)
        self.assertEqual(oracle["precision"], 1.0)
        self.assertEqual(blind["recall"], 0.0)
        self.assertEqual(blind["escaped_defect_rate"], 1.0)

    def test_run_is_resumable(self):
        bench.run_bench(self.corpus, ["oracle"], self.out)
        again = bench.run_bench(self.corpus, ["oracle"], self.out)
        self.assertEqual(len(again["oracle"]), 3)
        path = os.path.join(self.out, "oracle.jsonl")
        with open(path) as fh:
            self.assertEqual(len(fh.readlines()), 3)

    def test_public_report_excludes_holdout(self):
        results = bench.run_bench(self.corpus, ["oracle"], self.out)
        report = bench.build_report(results, self.corpus,
                                    public_only=True)
        entry = report["configs"]["oracle"]
        self.assertEqual(entry["metrics"]["cases_run"], 2)
        self.assertEqual(entry["metrics"]["expected_defects"], 1)
        blob = json.dumps(report) + bench.render_markdown(report)
        self.assertNotIn("holdout-bug", blob)

    def test_cli_run_and_report(self):
        rc = cli.main(["bench", "run", "--corpus", self.corpus,
                       "--config", "oracle", "--out", self.out])
        self.assertEqual(rc, 0)
        rc = cli.main(["bench", "report", "--corpus", self.corpus,
                       "--results", self.out, "--public",
                       "--max-escaped-rate", "0.5"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
