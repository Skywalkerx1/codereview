"""B2 confirmation machinery (pre-registration-b2-2026-11-05
§8): the generation-v3 scorer extension, the registered
runner's set loader, and the attempt-record adapter's stratum /
unverified-majors carriage.

Validation discipline (registration §7): SYNTHETIC fixtures
only — no generation-v3 case is read here; the synthetic corpus
is built in a temp dir with the sealed sets' shape (case.json +
diff.patch + stratum) and throwaway labels.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "bench"))
sys.path.insert(0, os.path.join(ROOT, "bench", "scripts"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sc2 = _load("score_confirmation_v2",
            "bench/scripts/score_confirmation_v2.py")
try:
    runner = _load("run_confirmation_b2",
                   "bench/scripts/run_confirmation_b2.py")
except ModuleNotFoundError as exc:  # env dependent
    # run_confirmation_b2 drives run_generation_v2, which
    # imports the swarm environment's llm_chain from a path
    # outside this repo. A clean checkout must report this
    # module as SKIPPED, not as an import error (Phase 4
    # rerun, suite portability) — the same guard
    # test_generation_driver.py and
    # test_deepseek_connector_switch.py already carry.
    if exc.name != "llm_chain":
        raise
    raise unittest.SkipTest(
        "bench/scripts/run_confirmation_b2.py needs the swarm "
        "environment's llm_chain module, which is not importable")
import generation as gen  # noqa: E402


def _write_case(corpus, cid, stratum, expected):
    d = os.path.join(corpus, cid)
    os.makedirs(d)
    meta = {"id": cid, "title": f"synthetic case {cid}",
            "category": "correctness", "source": "synthetic-test",
            "license": "test", "split": "holdout",
            "stratum": stratum, "expected": expected,
            "context": ""}
    with open(os.path.join(d, "case.json"), "w",
              encoding="utf-8") as fh:
        json.dump(meta, fh)
    with open(os.path.join(d, "diff.patch"), "w",
              encoding="utf-8") as fh:
        fh.write(f"--- a/{cid}.py\n+++ b/{cid}.py\n"
                 f"@@ -1,1 +1,1 @@\n-old\n+new {cid}\n")


def _finding(fid, file, line, title, severity, sources=None):
    return {"id": fid, "file": file, "line": line,
            "title": title, "category": "correctness",
            "severity": severity,
            "sources": sources or ["openai"],
            "evidence_class": "E1",
            "quote": "charge(req.key)",
            "trigger": "retry the same request with the "
                       "same idempotency key"}


def _record(cid, gate, findings, degraded=False, causes=None,
            unverified=None):
    return {"schema": "codereview.benchresult/1",
            "run": "b2-confirmation", "case_id": cid,
            "split": "holdout", "gate": gate,
            "degraded": degraded, "degraded_causes": causes,
            "gate_profile": {"profile": "corroborated"},
            "findings": findings,
            "unverified_majors": unverified or [],
            "reviewer_reports": []}


def _patch_bootstrap(testcase):
    """Point metrics and verdicts are asserted, not intervals —
    shrink the bootstrap so the suite stays fast."""
    orig = sc2.bootstrap
    sc2.bootstrap = lambda fn, items, **kw: orig(  # noqa: E731
        fn, items, resamples=100)
    testcase.addCleanup(setattr, sc2, "bootstrap", orig)


def _write_records(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


DEFECT_1 = [{"severity": "major", "category": "correctness",
             "file": "app.py", "line": 10,
             "title": "double charge on retry",
             "keywords": ["double", "charge"]}]
DEFECT_2 = [{"severity": "major", "category": "correctness",
             "file": "web.py", "line": 5,
             "title": "missing auth check on admin route",
             "keywords": ["auth", "admin"]}]
CORROB_CAUSE = ("corroboration unavailable for 1 unverified "
                "major(s) under gate profile 'corroborated' "
                "(policy B2 degraded mode)")


class MixedViewTest(unittest.TestCase):
    def setUp(self):
        _patch_bootstrap(self)
        self.tmp = tempfile.mkdtemp()
        self.corpus = os.path.join(self.tmp, "corpus")
        os.makedirs(self.corpus)
        _write_case(self.corpus, "syn-clean-1", "clean-authored",
                    [])
        _write_case(self.corpus, "syn-clean-2", "clean-realworld",
                    [])
        _write_case(self.corpus, "syn-clean-3", "clean-authored",
                    [])
        _write_case(self.corpus, "syn-defect-1",
                    "defect-injected", DEFECT_1)
        _write_case(self.corpus, "syn-defect-2",
                    "defect-realworld", DEFECT_2)
        unv = _finding("f-unv", "x.py", 1, "possible issue",
                       "major", ["deepseek"])
        records = [
            _record("syn-clean-1", "pass", []),
            _record("syn-clean-2", "blocked", [unv],
                    degraded=True, causes=[CORROB_CAUSE],
                    unverified=[unv]),
            _record("syn-defect-1", "blocked", [
                _finding("f-d1", "app.py", 10,
                         "double charge on retry", "major")]),
            _record("syn-defect-2", "pass", [
                _finding("f-d2", "web.py", 5,
                         "missing auth check", "minor",
                         ["deepseek"])]),
        ]
        self.records_path = os.path.join(self.tmp, "rec.jsonl")
        _write_records(self.records_path, records)
        self.out = sc2.score_attempt_v3(
            self.records_path, gen3_dir=self.corpus)

    def test_cap_accounting(self):
        self.assertEqual(self.out["unscored_cases"],
                         ["syn-clean-3"])
        self.assertEqual(
            self.out["corroboration_unavailable_cases"],
            ["syn-clean-2"])
        self.assertEqual(self.out["cap_used"], 2)
        self.assertFalse(self.out["void"])

    def test_views(self):
        scored = self.out["views"]["scored_only"]
        self.assertEqual(scored["clean"]["cases"], 2)
        self.assertEqual(scored["clean"]["blocked"], 1)
        self.assertEqual(scored["clean"]["rate"], 0.5)
        self.assertEqual(
            scored["defects"]["recall_any_severity"], 1.0)
        self.assertEqual(
            scored["defects"]["recall_blocking_tier"], 0.5)
        self.assertEqual(
            scored["defects"]["merged_blocking_precision"], 1.0)
        pess = self.out["views"]["pessimistic"]
        self.assertEqual(pess["clean"]["cases"], 3)
        self.assertEqual(pess["clean"]["blocked"], 2)
        self.assertAlmostEqual(pess["clean"]["rate"], 2 / 3)

    def test_thresholds_and_verdict(self):
        th = self.out["views"]["scored_only"]["thresholds"]
        self.assertTrue(th["recall_any_severity_floor"])
        self.assertFalse(th["recall_blocking_tier_primary"])
        self.assertTrue(th["merged_blocking_precision"])
        self.assertFalse(th["clean_blocked_point"])
        self.assertEqual(self.out["verdict"], "FAIL")

    def test_baselines_present_and_live_row(self):
        live = self.out["baselines"]["live_corroborated"]
        self.assertEqual(live["clean_blocked_rate"], 0.5)
        self.assertEqual(live["recall_any_severity"], 1.0)
        det = self.out["baselines"]["deterministic_only"]
        self.assertEqual(det["recall_any_severity"], 0.0)
        self.assertIn("strict_paired", self.out["baselines"])
        self.assertIn("corroborated_paired",
                      self.out["baselines"])


class VoidTest(unittest.TestCase):
    def setUp(self):
        _patch_bootstrap(self)

    def test_cap_exceeded_is_void(self):
        tmp = tempfile.mkdtemp()
        corpus = os.path.join(tmp, "corpus")
        os.makedirs(corpus)
        for i in range(6):
            _write_case(corpus, f"syn-clean-{i}",
                        "clean-authored", [])
        path = os.path.join(tmp, "rec.jsonl")
        _write_records(path, [_record("syn-clean-0", "pass", [])])
        out = sc2.score_attempt_v3(path, gen3_dir=corpus)
        self.assertEqual(out["cap_used"], 5)
        self.assertTrue(out["void"])
        self.assertEqual(out["verdict"], "VOID")


class PassTest(unittest.TestCase):
    def setUp(self):
        _patch_bootstrap(self)

    def test_clean_pass(self):
        tmp = tempfile.mkdtemp()
        corpus = os.path.join(tmp, "corpus")
        os.makedirs(corpus)
        records = []
        for i in range(13):
            cid = f"syn-clean-{i:02d}"
            _write_case(corpus, cid, "clean-authored", [])
            records.append(_record(cid, "pass", []))
        _write_case(corpus, "syn-defect-1", "defect-injected",
                    DEFECT_1)
        _write_case(corpus, "syn-defect-2", "defect-realworld",
                    DEFECT_2)
        records.append(_record("syn-defect-1", "blocked", [
            _finding("f-d1", "app.py", 10,
                     "double charge on retry", "major")]))
        records.append(_record("syn-defect-2", "blocked", [
            _finding("f-d2", "web.py", 5,
                     "missing auth check", "major", ["deepseek"])]))
        path = os.path.join(tmp, "rec.jsonl")
        _write_records(path, records)
        out = sc2.score_attempt_v3(path, gen3_dir=corpus)
        self.assertEqual(out["verdict"], "PASS")
        for view in out["views"].values():
            self.assertTrue(view["thresholds_all"])


class RunnerLoaderTest(unittest.TestCase):
    def _build_full_corpus(self, tmp):
        corpus = os.path.join(tmp, "gen3")
        os.makedirs(corpus)
        plan = (("clean-authored", 56, "ca"),
                ("clean-realworld", 8, "cr"),
                ("defect-injected", 14, "di"),
                ("defect-realworld", 10, "dr"))
        for stratum, n, tag in plan:
            for i in range(n):
                exp = [] if stratum.startswith("clean") \
                    else DEFECT_1
                _write_case(corpus, f"syn-{tag}-{i:02d}",
                            stratum, exp)
        return corpus

    def test_loads_88_with_strata(self):
        tmp = tempfile.mkdtemp()
        corpus = self._build_full_corpus(tmp)
        with mock.patch.object(runner, "GEN3", corpus):
            cases = runner.load_gen3_cases()
        self.assertEqual(len(cases), 88)
        self.assertTrue(all(c.get("stratum") for c in cases))

    def test_missing_stratum_is_loud(self):
        tmp = tempfile.mkdtemp()
        corpus = self._build_full_corpus(tmp)
        victim = os.path.join(corpus, "syn-ca-00", "case.json")
        with open(victim, encoding="utf-8") as fh:
            meta = json.load(fh)
        del meta["stratum"]
        with open(victim, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        with mock.patch.object(runner, "GEN3", corpus):
            with self.assertRaises(ValueError):
                runner.load_gen3_cases()


class AttemptRecordAdapterTest(unittest.TestCase):
    def test_stratum_and_unverified_carried(self):
        case = {"id": "syn-x", "split": "holdout",
                "category": "correctness", "stratum": "clean-"
                "authored"}
        report = {"gate": "pass", "degraded": False,
                  "degraded_causes": None,
                  "gate_profile": {"profile": "corroborated"},
                  "patch_sha256": "x", "findings": [],
                  "reviewer_reports": [], "seat_lenses": None,
                  "unverified_majors": [{"id": "f1"}]}
        rec = gen.to_attempt_record(
            case, report, "cfg", "sha", 1, "b2-confirmation",
            0.0, 5, "2026-11-06T00:00:00Z")
        self.assertEqual(rec["stratum"], "clean-authored")
        self.assertEqual(rec["unverified_majors"], [{"id": "f1"}])


if __name__ == "__main__":
    unittest.main()
