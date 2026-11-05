"""Step-3 error persistence (void forensics recommendation 3).

The voided Baseline-v2 confirmation attempts were unrecoverable
forensically because the bench record writer trimmed reviewer
reports to provider/lens/status/attempts — the seat error string
was dropped. These tests pin the fix: every record-writing path
persists, for an errored report, the full error string, the HTTP
status it carries (or None), the failure classes, the call's
wall-clock duration and the prompt size; and legacy records
without the new fields still load.
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import generation as gen  # noqa: E402
from codereview import bench, core  # noqa: E402
from codereview.providers import ProviderError  # noqa: E402

DIFF = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,2 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""

GOOD = json.dumps({"summary": "fine", "findings": []})
USAGE = {"prompt_tokens": 100, "completion_tokens": 50}
ERR = "HTTP 402 from api.deepseek.com"


def _raising(prompt):
    raise ProviderError(ERR)


class HttpStatusTests(unittest.TestCase):
    def test_message_embedded_status(self):
        self.assertEqual(core._http_status_of(
            ProviderError(ERR)), 402)
        self.assertEqual(core._http_status_of(
            "ProviderError: deepseek http: HTTP 402"), 402)
        self.assertEqual(core._http_status_of(
            Exception("HTTP 503 Service Unavailable")), 503)

    def test_structured_status_attribute(self):
        class FakeHTTPError(Exception):
            code = 429
        self.assertEqual(core._http_status_of(
            FakeHTTPError("slow down")), 429)

        class Structured(Exception):
            status = 500
        self.assertEqual(core._http_status_of(
            Structured("boom")), 500)

    def test_no_status_is_none_never_invented(self):
        self.assertIsNone(core._http_status_of(
            ProviderError("network error: timed out")))
        self.assertIsNone(core._http_status_of(
            Exception("seat used 5000 tokens in req_4014")))
        self.assertIsNone(core._http_status_of(None))


class RunReviewErrorDetailTests(unittest.TestCase):
    def test_errored_report_persists_full_detail(self):
        report = core.run_review(
            DIFF, {"deepseek": _raising}, sleep=lambda _s: None)
        reps = report["reviewer_reports"]
        self.assertTrue(reps)
        for rep in reps:
            self.assertEqual(rep["status"], "error")
            detail = rep["error_detail"]
            self.assertEqual(detail["error"], ERR)
            self.assertEqual(detail["http_status"], 402)
            self.assertIn("unknown", detail["error_classes"])
            self.assertIsInstance(rep["duration_ms"], int)
            self.assertGreaterEqual(rep["duration_ms"], 0)
            self.assertGreater(rep["prompt_chars"], 0)
            entry = core.reviewer_report_entry(rep)
            self.assertEqual(entry["error_detail"], detail)
            self.assertEqual(entry["duration_ms"],
                             rep["duration_ms"])
            self.assertEqual(entry["prompt_chars"],
                             rep["prompt_chars"])

    def test_fallback_recovery_still_persists_primary_detail(self):
        def good(prompt):
            return GOOD
        report = core.run_review(
            DIFF, {"deepseek": _raising},
            fallbacks={"correctness": ("relief", good),
                       "operations": ("relief", good)},
            sleep=lambda _s: None)
        reps = [r for r in report["reviewer_reports"]
                if r.get("fallback_for")]
        self.assertTrue(reps)
        for rep in reps:
            self.assertEqual(rep["status"], "ok")
            detail = rep["error_detail"]
            self.assertEqual(detail["error"], ERR)
            self.assertEqual(detail["http_status"], 402)

    def test_entry_copies_error_detail_by_presence(self):
        # Verification-round regression: the persisted form must
        # copy error_detail whenever the report CARRIES the key,
        # even when the block is falsy or holds only a
        # fallback_error — truthiness would silently drop it.
        base = {"provider": "p", "lens": "correctness",
                "status": "error", "attempts": 1}
        only_fb = dict(base, error_detail={
            "fallback_error": "HTTP 503 from api.example.com"})
        self.assertEqual(
            core.reviewer_report_entry(only_fb)["error_detail"],
            only_fb["error_detail"])
        empty = dict(base, error_detail={})
        self.assertEqual(
            core.reviewer_report_entry(empty)["error_detail"], {})
        absent = core.reviewer_report_entry(base)
        self.assertNotIn("error_detail", absent)

    def test_clean_report_has_no_error_detail(self):
        def good(prompt):
            return GOOD
        report = core.run_review(
            DIFF, {"a": good}, sleep=lambda _s: None)
        for rep in report["reviewer_reports"]:
            self.assertEqual(rep["status"], "ok")
            self.assertNotIn("error_detail", rep)
            entry = core.reviewer_report_entry(rep)
            self.assertNotIn("error_detail", entry)
            self.assertGreater(rep["prompt_chars"], 0)


def _write_case(root, cid):
    cdir = os.path.join(root, cid)
    os.makedirs(cdir)
    meta = {"id": cid, "title": f"case {cid}",
            "category": "correctness", "split": "public",
            "source": "test fixture", "license": "MIT",
            "expected": []}
    with open(os.path.join(cdir, "case.json"), "w") as fh:
        json.dump(meta, fh)
    with open(os.path.join(cdir, "diff.patch"), "w") as fh:
        fh.write(DIFF)


class BenchRecordTests(unittest.TestCase):
    def test_bench_record_persists_error_detail(self):
        with tempfile.TemporaryDirectory() as root:
            corpus = os.path.join(root, "corpus")
            os.makedirs(os.path.join(root, "configs"))
            os.makedirs(os.path.join(root, "scripts"))
            _write_case(corpus, "clean-one")
            with open(os.path.join(root, "scripts", "x.json"),
                      "w") as fh:
                json.dump({"default": {"verdict": "pass",
                                       "summary": "n",
                                       "findings": []}}, fh)
            with open(os.path.join(root, "configs", "bad.json"),
                      "w") as fh:
                json.dump({"name": "bad", "providers": [
                    {"name": "bad", "script": "../scripts/x.json"}]},
                    fh)
            out = os.path.join(root, "out")
            results = bench.run_bench(
                corpus, ["bad"], out,
                providers_by_config={"bad": {"bad": _raising}})
            rec = results["bad"][0]
            rep = rec["reviewer_reports"][0]
            self.assertEqual(rep["status"], "error")
            self.assertEqual(rep["error_detail"]["error"], ERR)
            self.assertEqual(rep["error_detail"]["http_status"],
                             402)
            self.assertIsInstance(rep["duration_ms"], int)
            self.assertGreater(rep["prompt_chars"], 0)
            with open(os.path.join(out, "bad.jsonl"),
                      encoding="utf-8") as fh:
                disk = json.loads(fh.readline())
            self.assertEqual(
                disk["reviewer_reports"][0]["error_detail"],
                rep["error_detail"])

    def test_legacy_records_still_load(self):
        # The shipped v1 baseline results are real pre-change
        # records: their reviewer_reports carry only the four
        # historical fields. Loading must treat the missing
        # error_detail as legacy, never as corruption.
        shipped = os.path.join(
            ROOT, "bench", "baseline-2026-11-04-results.jsonl")
        with tempfile.TemporaryDirectory() as td:
            with open(shipped, encoding="utf-8") as fh:
                data = fh.read()
            with open(os.path.join(
                    td, "baseline-2026-11-04.jsonl"), "w",
                    encoding="utf-8") as fh:
                fh.write(data)
            loaded = bench.load_results(td)
            self.assertTrue(loaded)
            rec = next(iter(loaded.values()))[0]
            rep = rec["reviewer_reports"][0]
            self.assertNotIn("error_detail", rep)
            entry = core.reviewer_report_entry(rep)
            self.assertNotIn("error_detail", entry)
            self.assertIsNone(entry["duration_ms"])


def _seat(name, transport, **kw):
    kw.setdefault("sleep", lambda _s: None)
    kw.setdefault("rng", lambda: 0.5)
    return gen.GenerationSeat(name, "deepseek-chat", transport,
                              **kw)


class GenerationErrorDetailTests(unittest.TestCase):
    def test_generation_record_persists_error_detail(self):
        seen = {}

        def dead(prompt):
            seen["prompt"] = prompt
            raise ProviderError(ERR)

        def good(prompt):
            return GOOD, USAGE

        cases = bench.load_corpus(os.path.join(
            ROOT, "bench", "corpus"))
        pub = [c for c in cases if c["split"] == "public"]
        pub.sort(key=lambda c: len(c["diff"]))
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "out")
            gen.run_generation(
                pub[:1], {"a": _seat("a", good),
                          "b": _seat("b", dead)},
                {"a": ["correctness"], "b": ["operations"]},
                cache_dir=os.path.join(td, "cache"), out_dir=out,
                config_name="testcfg", config_sha256="sha-x",
                log=lambda _m: None)
            with open(os.path.join(
                    out, "generation-attempt-1.jsonl"),
                    encoding="utf-8") as fh:
                recs = [json.loads(l) for l in fh if l.strip()]
            rec = [r for r in recs if r["seat"] == "b"][0]
            self.assertEqual(rec["status"], "unscored_infra")
            detail = rec["error_detail"][0]
            self.assertEqual(detail["error"], ERR)
            self.assertEqual(detail["http_status"], 402)
            self.assertEqual(detail["error_class"], "unknown")
            self.assertIsInstance(detail["duration_ms"], int)
            self.assertEqual(detail["prompt_chars"],
                             len(seen["prompt"]))

    def test_attempt_record_persists_error_detail(self):
        # With a declared fallback the case completes despite
        # the primary's 402, an attempt record is written, and
        # its reviewer_reports carry the primary's error_detail.
        def dead(prompt):
            raise ProviderError(ERR)

        def good(prompt):
            return GOOD, USAGE

        cases = bench.load_corpus(os.path.join(
            ROOT, "bench", "corpus"))
        pub = [c for c in cases if c["split"] == "public"]
        pub.sort(key=lambda c: len(c["diff"]))
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "out")
            summary = gen.run_generation(
                pub[:1], {"a": _seat("a", good),
                          "b": _seat("b", dead)},
                {"a": ["correctness"], "b": ["operations"]},
                cache_dir=os.path.join(td, "cache"), out_dir=out,
                config_name="testcfg", config_sha256="sha-x",
                fallbacks={"operations": "a"},
                log=lambda _m: None)
            self.assertEqual(summary["incomplete"], {})
            with open(os.path.join(out, "attempt-1.jsonl"),
                      encoding="utf-8") as fh:
                att = [json.loads(l) for l in fh if l.strip()]
            reps = [r for r in att[0]["reviewer_reports"]
                    if r.get("fallback_for") == "b"]
            self.assertTrue(reps)
            detail = reps[0]["error_detail"]
            self.assertEqual(detail["error"], ERR)
            self.assertEqual(detail["http_status"], 402)
            self.assertIsInstance(reps[0]["duration_ms"], int)
            self.assertGreater(reps[0]["prompt_chars"], 0)


if __name__ == "__main__":
    unittest.main()
