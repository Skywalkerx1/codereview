"""v0.7.3 — the clean-record solution's §4 items: error-class-aware
retries (4.2), fallback seat per lens (4.3), the record verifier
(4.4), the doctor preflight (4.1), seat family/tier metadata and
the free-tier policy (4.6)."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "src"))

from codereview import core  # noqa: E402

CLEAN = (
    "diff --git a/app/alerts.py b/app/alerts.py\n"
    "--- a/app/alerts.py\n"
    "+++ b/app/alerts.py\n"
    "@@ -1,2 +1,3 @@\n"
    " import os\n"
    "+TIMEOUT = 30\n"
)

NO_SLEEP = lambda _s: None  # noqa: E731


def ok_provider(_prompt):
    return json.dumps({"summary": "clean", "findings": []})


def boom(exc):
    def _fn(_prompt):
        raise exc
    return _fn


class ClassificationTests(unittest.TestCase):
    def test_quota_never_retried(self):
        self.assertEqual(
            core._classify_error(Exception("gemini quota: HTTP 429")),
            ("quota", 1))
        self.assertEqual(
            core._classify_error(Exception("RESOURCE_EXHAUSTED")),
            ("quota", 1))

    def test_per_minute_429_is_rate_limit(self):
        self.assertEqual(
            core._classify_error(Exception("HTTP 429 slow down")),
            ("rate_limit", 3))

    def test_overload_and_timeout_are_transient(self):
        self.assertEqual(
            core._classify_error(
                Exception("gemini overloaded: HTTP 503")),
            ("transient", 3))
        self.assertEqual(
            core._classify_error(TimeoutError("t")),
            ("transient", 3))

    def test_missing_key_is_auth(self):
        self.assertEqual(
            core._classify_error(
                Exception("GEMINI_API_KEY is not set")),
            ("auth", 1))

    def test_typed_flag_wins(self):
        class Typed(Exception):
            pass
        err = Typed("anything")
        err.retryable = False
        self.assertEqual(core._classify_error(err), ("provider", 1))
        err.retryable = True
        self.assertEqual(core._classify_error(err), ("provider", 3))

    def test_unknown_single_try(self):
        self.assertEqual(
            core._classify_error(Exception("weird")), ("unknown", 1))


class RetryTests(unittest.TestCase):
    def test_transient_failures_recover_and_are_counted(self):
        calls = {"n": 0}

        def flaky(_prompt):
            calls["n"] += 1
            if calls["n"] < 3:
                raise Exception("openai overloaded: HTTP 503")
            return ok_provider(_prompt)

        report = core.run_review(
            CLEAN, {"a": flaky, "b": ok_provider}, sleep=NO_SLEEP)
        rec = {r["provider"]: r for r in report["reviewer_reports"]}
        self.assertEqual(rec["a"]["status"], "ok")
        self.assertEqual(rec["a"]["attempts"], 3)
        self.assertEqual(rec["a"]["error_classes"],
                         ["transient", "transient"])
        self.assertEqual(report["gate"], "pass")
        self.assertFalse(report["degraded"])

    def test_quota_failure_is_not_retried(self):
        report = core.run_review(
            CLEAN,
            {"a": boom(Exception("gemini quota: HTTP 429")),
             "b": ok_provider},
            sleep=NO_SLEEP)
        rec = {r["provider"]: r for r in report["reviewer_reports"]}
        self.assertEqual(rec["a"]["attempts"], 1)
        self.assertEqual(rec["a"]["status"], "error")
        self.assertEqual(report["gate"], "inconclusive")

    def test_transient_exhaustion_records_every_attempt(self):
        report = core.run_review(
            CLEAN,
            {"a": boom(Exception("HTTP 503")), "b": ok_provider},
            sleep=NO_SLEEP)
        rec = {r["provider"]: r for r in report["reviewer_reports"]}
        self.assertEqual(rec["a"]["attempts"], 3)
        self.assertEqual(rec["a"]["error_classes"],
                         ["transient"] * 3)


class FallbackTests(unittest.TestCase):
    META = {"gem": {"family": "google", "tier": "free"},
            "nvi": {"family": "nvidia", "tier": "free"},
            "oai": {"family": "openai", "tier": "paid"}}

    def test_fallback_serves_the_lens_and_is_flagged(self):
        report = core.run_review(
            CLEAN,
            {"gem": boom(Exception("gemini quota: HTTP 429")),
             "nvi": ok_provider},
            seat_meta=self.META,
            fallbacks={"correctness": ("oai", ok_provider)},
            sleep=NO_SLEEP)
        self.assertEqual(report["gate"], "pass")
        self.assertFalse(report["degraded"])
        rec = {r["lens"]: r for r in report["reviewer_reports"]}
        self.assertEqual(rec["correctness"]["provider"], "oai")
        self.assertEqual(rec["correctness"]["fallback_for"], "gem")
        self.assertEqual(rec["correctness"]["family"], "openai")
        self.assertIn("fallback",
                      " ".join(report["gate_reasons"]))

    def test_fallback_failure_keeps_the_round_honest(self):
        report = core.run_review(
            CLEAN,
            {"gem": boom(Exception("gemini quota: HTTP 429")),
             "nvi": ok_provider},
            fallbacks={"correctness": ("oai", boom(
                Exception("openai overloaded: HTTP 503")))},
            sleep=NO_SLEEP)
        self.assertEqual(report["gate"], "inconclusive")
        self.assertTrue(report["degraded"])
        rec = {r["lens"]: r for r in report["reviewer_reports"]}
        self.assertEqual(rec["correctness"]["status"], "error")
        self.assertIn("fallback", rec["correctness"]["error"])


class SeatMetaTests(unittest.TestCase):
    def test_meta_lands_on_reports(self):
        report = core.run_review(
            CLEAN, {"a": ok_provider, "b": ok_provider},
            seat_meta={"a": {"family": "google", "tier": "paid"}},
            sleep=NO_SLEEP)
        rec = {r["provider"]: r for r in report["reviewer_reports"]}
        self.assertEqual(rec["a"]["family"], "google")
        self.assertEqual(rec["a"]["tier"], "paid")
        self.assertEqual(rec["b"]["family"], "unknown")


class DoctorTests(unittest.TestCase):
    def test_doctor_reports_per_seat_health(self):
        result = core.run_doctor(
            {"good": ok_provider,
             "bad": boom(Exception("HTTP 503"))})
        self.assertFalse(result["ok"])
        seats = {s["name"]: s for s in result["seats"]}
        self.assertTrue(seats["good"]["ok"])
        self.assertFalse(seats["bad"]["ok"])
        self.assertEqual(seats["bad"]["error_class"], "transient")

    def test_doctor_all_healthy(self):
        result = core.run_doctor({"a": ok_provider})
        self.assertTrue(result["ok"])


class TierPolicyTests(unittest.TestCase):
    def test_free_tier_blocked_only_for_private(self):
        meta = {"gem": {"family": "google", "tier": "free"}}
        self.assertEqual(len(core.check_tier_policy(
            meta, private=True)), 1)
        self.assertEqual(core.check_tier_policy(
            meta, private=False), [])
        self.assertEqual(core.check_tier_policy(
            {"oai": {"family": "openai", "tier": "paid"}},
            private=True), [])


class _RepoFixture(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        env = dict(os.environ, HOME="/home/hatch")
        self.env = env

        def git(*args):
            return subprocess.run(
                ["git", "-C", self.td, "-c", "user.email=t@t",
                 "-c", "user.name=t", *args],
                capture_output=True, text=True, env=env,
                check=True).stdout.strip()

        self.git = git
        git("init", "-q")
        with open(os.path.join(self.td, "a.txt"), "w") as fh:
            fh.write("one\n")
        git("add", "-A")
        git("commit", "-qm", "c1")
        self.c1 = git("rev-parse", "HEAD")
        with open(os.path.join(self.td, "a.txt"), "w") as fh:
            fh.write("one\ntwo\n")
        git("add", "-A")
        git("commit", "-qm", "c2")
        self.c2 = git("rev-parse", "HEAD")
        self.range = f"{self.c1}..{self.c2}"
        patch = core.collect_git_patch(self.td, range_spec=self.range)
        self.record = {
            # The pre-stamp declarations every real record
            # of the era carried (P6-12b: a hash-less record
            # with NO declarations no longer reads legacy).
            "version": "0.7.3",
            "created_at": "2026-10-28T00:00:00+00:00",
            "gate": "pass", "degraded": False,
            "test_results": [{"command": "t", "ok": True}],
            "reviewer_reports": [
                {"provider": "gemini", "lens": "correctness",
                 "status": "ok", "family": "google"},
                {"provider": "nvidia", "lens": "operations",
                 "status": "ok", "family": "nvidia"}],
            "range": self.range, "head": self.c2,
            "patch_sha256": hashlib.sha256(
                patch.encode("utf-8")).hexdigest()}


class VerifyRecordTests(_RepoFixture):
    def verify(self, record=None, record_dir="review-x"):
        return core.verify_record(record or self.record,
                                  repo=self.td,
                                  record_dir=record_dir)

    def test_eligible_record_passes(self):
        result = self.verify()
        self.assertTrue(result["eligible"], result["checks"])

    def test_degraded_record_fails(self):
        self.record["degraded"] = True
        result = self.verify()
        self.assertFalse(result["eligible"])
        failed = {c["name"] for c in result["checks"] if not c["ok"]}
        self.assertIn("not_degraded", failed)

    def test_same_family_panel_fails(self):
        self.record["reviewer_reports"][1]["family"] = "google"
        result = self.verify()
        self.assertFalse(result["eligible"])
        failed = {c["name"] for c in result["checks"] if not c["ok"]}
        self.assertIn("two_families", failed)

    def test_missing_lens_fails(self):
        self.record["reviewer_reports"] = \
            self.record["reviewer_reports"][:1]
        result = self.verify()
        self.assertFalse(result["eligible"])
        failed = {c["name"] for c in result["checks"] if not c["ok"]}
        self.assertIn("lens_coverage", failed)

    def test_pre_range_record_cannot_prove_currency(self):
        del self.record["range"], self.record["head"]
        result = self.verify()
        self.assertFalse(result["eligible"])
        failed = {c["name"] for c in result["checks"] if not c["ok"]}
        self.assertIn("range_recorded", failed)

    def test_tampered_patch_hash_fails(self):
        self.record["patch_sha256"] = "0" * 64
        result = self.verify()
        self.assertFalse(result["eligible"])
        failed = {c["name"] for c in result["checks"] if not c["ok"]}
        self.assertIn("patch_matches_range", failed)

    def test_later_code_commit_breaks_currency(self):
        with open(os.path.join(self.td, "a.txt"), "a") as fh:
            fh.write("three\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "c3")
        result = self.verify()
        self.assertFalse(result["eligible"])
        failed = {c["name"] for c in result["checks"] if not c["ok"]}
        self.assertIn("head_current", failed)

    def test_record_only_commit_keeps_currency(self):
        os.makedirs(os.path.join(self.td, "review-x"))
        with open(os.path.join(self.td, "review-x", "r.json"),
                  "w") as fh:
            fh.write("{}")
        self.git("add", "-A")
        self.git("commit", "-qm", "file the record")
        result = self.verify()
        self.assertTrue(result["eligible"], result["checks"])


class RecordVerifyCliTests(_RepoFixture):
    def test_cli_exit_codes(self):
        out_dir = os.path.join(self.td, "review-x")
        os.makedirs(out_dir)
        with open(os.path.join(out_dir, "rec.json"), "w") as fh:
            json.dump(self.record, fh)
        env = dict(os.environ, HOME="/home/hatch",
                   PYTHONPATH=os.path.join(
                       os.path.dirname(__file__), "..", "src"))
        proc = subprocess.run(
            [sys.executable, "-m", "codereview.cli", "record-verify",
             out_dir, "--repo", self.td],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ELIGIBLE", proc.stdout)
        self.record["gate"] = "inconclusive"
        with open(os.path.join(out_dir, "rec.json"), "w") as fh:
            json.dump(self.record, fh)
        proc = subprocess.run(
            [sys.executable, "-m", "codereview.cli", "record-verify",
             out_dir, "--repo", self.td],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
