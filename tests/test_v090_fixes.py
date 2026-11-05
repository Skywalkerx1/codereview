"""v0.9.0 — adjudication of the review-v11 record, per the
owner's clean-gate solution: the versioned fixture manifest and
its record-verify validation (§3), review-shaped doctor probes
with fallback probing and timeout forwarding (§4), the bounded
primary+fallback attempt budget (§4), fallback attempt accounting,
bench resume/config staleness validation, case-canonical seat
collision checks, and agent seat kind tagging for default seat
metadata."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "src"))

from codereview import bench, cli, core, providers  # noqa: E402

NO_SLEEP = lambda _s: None  # noqa: E731

REPO_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), ".."))

SECRET_LINE = 'aws_key = "AKIA' + "TEST" * 4 + '"'

FIXTURE_AND_PRODUCT = (
    "diff --git a/bench/corpus/some-case/diff.patch "
    "b/bench/corpus/some-case/diff.patch\n"
    "--- a/bench/corpus/some-case/diff.patch\n"
    "+++ b/bench/corpus/some-case/diff.patch\n"
    "@@ -0,0 +1,1 @@\n"
    f"+{SECRET_LINE}\n"
    "diff --git a/src/app.py b/src/app.py\n"
    "--- a/src/app.py\n"
    "+++ b/src/app.py\n"
    "@@ -0,0 +1,1 @@\n"
    f"+{SECRET_LINE}\n"
)

FIXTURE_ONLY = (
    "diff --git a/bench/corpus/some-case/diff.patch "
    "b/bench/corpus/some-case/diff.patch\n"
    "--- a/bench/corpus/some-case/diff.patch\n"
    "+++ b/bench/corpus/some-case/diff.patch\n"
    "@@ -0,0 +1,1 @@\n"
    f"+{SECRET_LINE}\n"
)

# A fixture section whose nested diff adds app/search.py in the
# case's own little world.
FIXTURE_NESTED = (
    "diff --git a/bench/corpus/sql-case/diff.patch "
    "b/bench/corpus/sql-case/diff.patch\n"
    "--- a/bench/corpus/sql-case/diff.patch\n"
    "+++ b/bench/corpus/sql-case/diff.patch\n"
    "@@ -0,0 +1,4 @@\n"
    "+diff --git a/app/search.py b/app/search.py\n"
    "+--- a/app/search.py\n"
    "++++ b/app/search.py\n"
    f"++{SECRET_LINE}\n"
)

CLEAN = (
    "diff --git a/app/alerts.py b/app/alerts.py\n"
    "--- a/app/alerts.py\n"
    "+++ b/app/alerts.py\n"
    "@@ -1,2 +1,3 @@\n"
    " import os\n"
    "+TIMEOUT = 30\n"
)

SCOPE = {"manifest_path": "fixtures-manifest.json",
         "manifest_sha256": "a" * 64, "policy_version": 1,
         "patterns": ["bench/corpus/**", "bench/scripts/**"]}


def ok_provider(_prompt):
    return json.dumps({"summary": "clean", "findings": []})


def boom(exc):
    def _fn(_prompt):
        raise exc
    return _fn


def finding_provider(file, title="planted defect"):
    def _fn(_prompt):
        return json.dumps({
            "verdict": "changes_requested", "summary": "found one",
            "findings": [{
                "severity": "blocker", "category": "security",
                "file": file, "line": 1, "title": title,
                "evidence": "the added line", "recommendation":
                "fix it", "confidence": 0.9}]})
    return _fn


class PathMatchTests(unittest.TestCase):
    def test_directory_glob(self):
        pats = ["bench/corpus/**"]
        self.assertTrue(core.path_matches(
            "bench/corpus/x/diff.patch", pats))
        self.assertTrue(core.path_matches("bench/corpus", pats))
        self.assertFalse(core.path_matches(
            "src/codereview/bench.py", pats))
        self.assertFalse(core.path_matches(
            "bench/corpusx/diff.patch", pats))

    def test_plain_path_and_glob_forms(self):
        self.assertTrue(core.path_matches(
            "bench/scripts/oracle.json", ["bench/scripts"]))
        self.assertTrue(core.path_matches(
            "a/b/case.json", ["a/*/case.json"]))
        self.assertFalse(core.path_matches(
            "a/b/other.json", ["a/*/case.json"]))


class ShippedManifestTests(unittest.TestCase):
    def test_manifest_enumerates_every_case_and_only_data(self):
        scope = cli._load_fixture_scope(
            "fixtures-manifest.json", repo=REPO_ROOT)
        self.assertEqual(scope["policy_version"], 1)
        self.assertEqual(len(scope["patterns"]), 39)
        corpus = os.path.join(REPO_ROOT, "bench", "corpus")
        for cid in os.listdir(corpus):
            if os.path.isdir(os.path.join(corpus, cid)):
                self.assertTrue(core.path_matches(
                    f"bench/corpus/{cid}/diff.patch",
                    scope["patterns"]), cid)
        for product_path in (
                "src/codereview/bench.py", "src/codereview/core.py",
                "src/codereview/cli.py", "tests/test_bench.py",
                "bench/README.md", "bench/configs/oracle.json",
                "fixtures-manifest.json"):
            self.assertFalse(core.path_matches(
                product_path, scope["patterns"]), product_path)


class FixtureClassificationTests(unittest.TestCase):
    def test_fixture_findings_classified_product_still_blocks(self):
        report = core.run_review(
            FIXTURE_AND_PRODUCT,
            {"a": ok_provider, "b": ok_provider},
            fixture_scope=SCOPE, sleep=NO_SLEEP)
        self.assertEqual(report["gate"], "blocked")
        self.assertEqual(
            {f["file"] for f in report["findings"]}, {"src/app.py"})
        self.assertEqual(
            {f["file"] for f in report["fixture_findings"]},
            {"bench/corpus/some-case/diff.patch"})
        # Evidence is preserved, not suppressed.
        self.assertTrue(report["fixture_findings"][0]["evidence"])
        self.assertEqual(
            report["fixture_scope"]["fixture_finding_count"], 1)
        self.assertIn("expected fixture finding",
                      " ".join(report["gate_reasons"]))

    def test_fixture_only_patch_passes_with_scope(self):
        report = core.run_review(
            FIXTURE_ONLY, {"a": ok_provider, "b": ok_provider},
            fixture_scope=SCOPE, sleep=NO_SLEEP)
        self.assertEqual(report["gate"], "pass")
        self.assertEqual(len(report["fixture_findings"]), 1)
        self.assertEqual(report["findings"], [])

    def test_without_scope_fixtures_block_as_usual(self):
        report = core.run_review(
            FIXTURE_ONLY, {"a": ok_provider, "b": ok_provider},
            sleep=NO_SLEEP)
        self.assertEqual(report["gate"], "blocked")
        self.assertNotIn("fixture_findings", report)

    def test_inner_path_finding_belongs_to_the_fixture(self):
        report = core.run_review(
            FIXTURE_NESTED,
            {"a": finding_provider("app/search.py"),
             "b": ok_provider},
            fixture_scope=SCOPE, sleep=NO_SLEEP)
        fixture_files = {f["file"]
                         for f in report["fixture_findings"]}
        self.assertIn("app/search.py", fixture_files)
        self.assertEqual(
            {f["file"] for f in report["findings"]}, set())

    def test_inner_path_shared_with_product_stays_blocking(self):
        patch = FIXTURE_NESTED + (
            "diff --git a/app/search.py b/app/search.py\n"
            "--- a/app/search.py\n"
            "+++ b/app/search.py\n"
            "@@ -0,0 +1,1 @@\n"
            "+x = 1\n")
        report = core.run_review(
            patch,
            {"a": finding_provider("app/search.py"),
             "b": ok_provider},
            fixture_scope=SCOPE, sleep=NO_SLEEP)
        self.assertIn("app/search.py",
                      {f["file"] for f in report["findings"]})


class FixtureScopeVerifyTests(unittest.TestCase):
    MANIFEST = {
        "schema": core.FIXTURE_MANIFEST_SCHEMA,
        "policy_version": 1,
        "fixtures": [{"path": "bench/corpus/**",
                      "reason": "test data",
                      "expected_categories": ["security"]}]}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.td = self._tmp.name

        def git(*args):
            return subprocess.run(
                ["git", "-C", self.td, "-c", "user.email=t@t",
                 "-c", "user.name=t", *args],
                capture_output=True, text=True, check=True).stdout
        self.git = git
        git("init", "-q")
        with open(os.path.join(self.td, "app.py"), "w") as fh:
            fh.write("x = 1\n")
        git("add", "-A")
        git("commit", "-qm", "c1")
        self.manifest_bytes = (
            json.dumps(self.MANIFEST, indent=2) + "\n").encode()
        with open(os.path.join(self.td, "fixtures-manifest.json"),
                  "wb") as fh:
            fh.write(self.manifest_bytes)
        os.makedirs(os.path.join(self.td, "bench", "corpus", "fx"))
        with open(os.path.join(self.td, "bench", "corpus", "fx",
                               "diff.patch"), "w") as fh:
            fh.write(SECRET_LINE + "\n")
        with open(os.path.join(self.td, "app.py"), "w") as fh:
            fh.write("x = 2\n")
        git("add", "-A")
        git("commit", "-qm", "c2")
        self.head = git("rev-parse", "HEAD").strip()

    def tearDown(self):
        self._tmp.cleanup()

    def _record(self):
        patch = core.collect_git_patch(
            self.td, range_spec="HEAD~1..HEAD")
        scope = {"manifest_path": "fixtures-manifest.json",
                 "manifest_sha256": hashlib.sha256(
                     self.manifest_bytes).hexdigest(),
                 "policy_version": 1,
                 "patterns": ["bench/corpus/**"]}
        return core.run_review(
            patch, {"a": ok_provider, "b": ok_provider},
            test_results=[{"command": "true", "ok": True,
                           "exit_code": 0, "output": ""}],
            seat_meta={"a": {"family": "openai", "tier": "paid"},
                       "b": {"family": "nvidia", "tier": "free"}},
            fixture_scope=scope,
            record_extra={"range": "HEAD~1..HEAD",
                          "head": self.head},
            sleep=NO_SLEEP)

    def _checks(self, record):
        result = core.verify_record(record, repo=self.td,
                                    record_dir="review-x")
        return {c["name"]: c["ok"] for c in result["checks"]}, \
            result["eligible"]

    def test_valid_scope_verifies(self):
        record = self._record()
        self.assertEqual(record["gate"], "pass")
        self.assertEqual(len(record["fixture_findings"]), 1)
        checks, eligible = self._checks(record)
        self.assertTrue(checks["fixture_scope_valid"], checks)
        self.assertTrue(eligible, checks)

    def test_stale_manifest_hash_fails(self):
        record = self._record()
        record["fixture_scope"]["manifest_sha256"] = "0" * 64
        checks, eligible = self._checks(record)
        self.assertFalse(checks["fixture_scope_valid"])
        self.assertFalse(eligible)

    def test_classified_paths_differing_from_manifest_fail(self):
        record = self._record()
        record["fixture_scope"]["classified_paths"] = [
            "bench/corpus/**", "src/**"]
        checks, _eligible = self._checks(record)
        self.assertFalse(checks["fixture_scope_valid"])

    def test_uncovered_fixture_finding_fails(self):
        record = self._record()
        record["fixture_findings"].append({
            "file": "src/app.py", "severity": "blocker",
            "category": "security", "title": "smuggled"})
        record["fixture_scope"]["fixture_finding_count"] = 2
        checks, _eligible = self._checks(record)
        self.assertFalse(checks["fixture_scope_valid"])

    def test_fixture_findings_without_scope_fail(self):
        record = self._record()
        del record["fixture_scope"]
        checks, _eligible = self._checks(record)
        self.assertFalse(checks["fixture_scope_valid"])

    def test_scope_missing_manifest_path_fails_named(self):
        record = self._record()
        del record["fixture_scope"]["manifest_path"]
        result = core.verify_record(record, repo=self.td,
                                    record_dir="review-x")
        check = [c for c in result["checks"]
                 if c["name"] == "fixture_scope_valid"][0]
        self.assertFalse(check["ok"])
        self.assertIn("manifest_path", check["detail"])


class FixtureManifestLoaderTests(unittest.TestCase):
    def test_manifest_outside_the_repo_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            os.makedirs(repo)
            outside = os.path.join(td, "manifest.json")
            with open(outside, "w") as fh:
                json.dump({"policy_version": 1, "fixtures": [
                    {"path": "x/**"}]}, fh)
            with self.assertRaises(ValueError):
                cli._load_fixture_scope("../manifest.json",
                                        repo=repo)
            with self.assertRaises(ValueError):
                cli._load_fixture_scope(outside, repo=repo)

    def test_manifest_path_is_recorded_repo_relative(self):
        with tempfile.TemporaryDirectory() as td:
            sub = os.path.join(td, "docs")
            os.makedirs(sub)
            with open(os.path.join(sub, "m.json"), "w") as fh:
                json.dump({"schema": core.FIXTURE_MANIFEST_SCHEMA,
                           "policy_version": 1, "fixtures": [
                               {"path": "x/**"}]}, fh)
            scope = cli._load_fixture_scope("docs/m.json", repo=td)
            self.assertEqual(scope["manifest_path"], "docs/m.json")
            self.assertEqual(scope["policy_version"], 1)

    def test_malformed_manifests_are_rejected(self):
        bad_manifests = [
            {"policy_version": 1, "fixtures": [{"path": "x/**"}]},
            {"schema": core.FIXTURE_MANIFEST_SCHEMA,
             "policy_version": 99, "fixtures": [{"path": "x/**"}]},
            {"schema": core.FIXTURE_MANIFEST_SCHEMA,
             "policy_version": 1, "fixtures": []},
            {"schema": core.FIXTURE_MANIFEST_SCHEMA,
             "policy_version": 1, "fixtures": [{"reason": "x"}]},
            {"schema": core.FIXTURE_MANIFEST_SCHEMA,
             "policy_version": 1, "fixtures": "bench/**"},
        ]
        with tempfile.TemporaryDirectory() as td:
            for i, bad in enumerate(bad_manifests):
                path = os.path.join(td, f"bad{i}.json")
                with open(path, "w") as fh:
                    json.dump(bad, fh)
                with self.assertRaises(ValueError, msg=f"case {i}"):
                    cli._load_fixture_scope(path, repo=td)


class DoctorShapeTests(unittest.TestCase):
    def test_probe_uses_review_request_shape(self):
        def shape_sensitive(prompt):
            if "json" not in prompt.lower() \
                    or "findings" not in prompt:
                raise Exception(
                    "400: messages must contain 'json' for "
                    "response_format json_object")
            return json.dumps({"summary": "ok", "findings": []})
        result = core.run_doctor({"strict": shape_sensitive})
        self.assertTrue(result["ok"], result)

    def test_fallback_seats_are_probed_and_labelled(self):
        result = core.run_doctor(
            {"main": ok_provider},
            fallbacks={"correctness": ("fb", ok_provider)})
        roles = {(s["name"], s["role"]) for s in result["seats"]}
        self.assertIn(("main", "primary"), roles)
        self.assertIn(("fb", "fallback"), roles)
        self.assertTrue(result["ok"])

    def test_failing_fallback_fails_preflight_with_class(self):
        result = core.run_doctor(
            {"main": ok_provider},
            fallbacks={"correctness": ("fb", boom(
                Exception("gemini quota: HTTP 429")))})
        self.assertFalse(result["ok"])
        fb = [s for s in result["seats"]
              if s["role"] == "fallback"][0]
        self.assertEqual(fb["error_class"], "quota")

    def test_seat_probed_once_when_primary_and_fallback(self):
        calls = {"n": 0}

        def counting(_prompt):
            calls["n"] += 1
            return json.dumps({"summary": "ok", "findings": []})
        result = core.run_doctor(
            {"main": counting},
            fallbacks={"correctness": ("main", counting)})
        self.assertEqual(calls["n"], 1)
        roles = {(s["name"], s["role"]) for s in result["seats"]}
        self.assertEqual(roles, {("main", "primary"),
                                 ("main", "fallback")})
        self.assertTrue(result["ok"])

    def test_error_classes_distinguish_auth_from_transient(self):
        result = core.run_doctor({
            "no_key": boom(Exception("api_key not set")),
            "busy": boom(Exception("HTTP 503 overloaded"))})
        classes = {s["name"]: s["error_class"]
                   for s in result["seats"]}
        self.assertEqual(classes["no_key"], "auth")
        self.assertEqual(classes["busy"], "transient")

    def test_doctor_forwards_timeout_to_construction(self):
        captured = {}

        def fake_build(specs, agent_timeout=None, **kw):
            captured["agent_timeout"] = agent_timeout
            return {"x": ok_provider}
        original = cli.build_providers
        cli.build_providers = fake_build
        try:
            # An explicit --provider: since the first-run-setup
            # amendment the doctor no longer falls back to a
            # built-in panel when nothing is configured.
            rc = cli._doctor_main(["--timeout", "7", "--provider",
                                   "gemini"])
        finally:
            cli.build_providers = original
        self.assertEqual(rc, 0)
        self.assertEqual(captured["agent_timeout"], 7)


class DoctorTimeoutTests(unittest.TestCase):
    """Finding 3bbe648d8bfc (v0.11.0 review, standing major):
    the doctor's probe calls ran unbounded — a seat whose
    callable hung blocked the preflight forever. Every probe
    now runs under the review path's bounded-call pattern
    (_probe_call_bounded) with the same default semantics."""

    def test_hanging_seat_is_bounded_and_reported(self):
        never = threading.Event()

        def hanging(_prompt):
            never.wait(30)
            return "too late"
        started = time.monotonic()
        result = core.run_doctor({"hang": hanging}, timeout=1)
        elapsed = time.monotonic() - started
        self.assertFalse(result["ok"])
        seat = result["seats"][0]
        self.assertFalse(seat["ok"])
        self.assertEqual(seat["error_class"], "transient")
        self.assertIn("timed out", seat["error"])
        # The bound is a WAIT bound: the preflight returns in
        # ~timeout seconds, not when the seat eventually answers.
        self.assertLess(elapsed, 10)

    def test_fast_seat_still_probes_ok_under_a_bound(self):
        result = core.run_doctor({"main": ok_provider}, timeout=5)
        self.assertTrue(result["ok"], result)

    def test_default_timeout_is_the_review_call_ceiling(self):
        # No explicit timeout: the default semantics are the
        # review path's per-call ceiling, not a doctor-only
        # number — a merely slow seat still answers fine.
        def slow(_prompt):
            time.sleep(0.2)
            return json.dumps({"summary": "ok", "findings": []})
        result = core.run_doctor({"slow": slow})
        self.assertTrue(result["ok"], result)

    def test_non_positive_timeout_is_a_caller_error(self):
        with self.assertRaises(ValueError):
            core.run_doctor({"main": ok_provider}, timeout=0)

    def test_doctor_main_wires_timeout_to_the_probe(self):
        never = threading.Event()

        def hanging(_prompt):
            never.wait(30)
            return "too late"
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        started = time.monotonic()
        with redirect_stdout(out):
            rc = cli._doctor_main(
                ["--timeout", "1"],
                providers_override={"hang": hanging})
        elapsed = time.monotonic() - started
        self.assertEqual(rc, 2)
        self.assertLess(elapsed, 10)
        result = json.loads(out.getvalue())
        self.assertFalse(result["ok"])
        self.assertIn("timed out",
                      result["seats"][0]["error"])


class FallbackAttemptsTests(unittest.TestCase):
    def test_attempts_count_primary_plus_fallback(self):
        report = core.run_review(
            CLEAN,
            {"gem": boom(Exception("gemini quota: HTTP 429")),
             "nvi": ok_provider},
            fallbacks={"correctness": ("oai", ok_provider)},
            sleep=NO_SLEEP)
        rec = {r["lens"]: r for r in report["reviewer_reports"]}
        self.assertEqual(rec["correctness"]["provider"], "oai")
        # 1 (primary, quota — never retried) + 1 (fallback).
        self.assertEqual(rec["correctness"]["attempts"], 2)

    def test_attempts_count_both_when_fallback_also_fails(self):
        report = core.run_review(
            CLEAN,
            {"gem": boom(Exception("gemini quota: HTTP 429")),
             "nvi": ok_provider},
            fallbacks={"correctness": ("oai", boom(
                Exception("unauthorized: 401")))},
            sleep=NO_SLEEP)
        rec = {r["lens"]: r for r in report["reviewer_reports"]}
        self.assertEqual(rec["correctness"]["status"], "error")
        self.assertEqual(rec["correctness"]["attempts"], 2)

    def test_job_attempts_are_capped_in_the_worst_case(self):
        calls = {"primary": 0, "fallback": 0}

        def transient(key):
            def _fn(_prompt):
                calls[key] += 1
                raise Exception("HTTP 503 overloaded")
            return _fn
        report = core.run_review(
            CLEAN,
            {"gem": transient("primary"), "nvi": ok_provider},
            fallbacks={"correctness": ("oai",
                                       transient("fallback"))},
            sleep=NO_SLEEP)
        rec = {r["lens"]: r for r in report["reviewer_reports"]}
        self.assertEqual(calls, {"primary": 3, "fallback": 3})
        self.assertEqual(rec["correctness"]["attempts"],
                         core._MAX_JOB_ATTEMPTS)

    def test_budget_exhausted_fallback_is_not_attempted(self):
        calls = {"fallback": 0}

        def fb(_prompt):
            calls["fallback"] += 1
            return json.dumps({"summary": "ok", "findings": []})
        original = core._MAX_JOB_ATTEMPTS
        core._MAX_JOB_ATTEMPTS = 1
        try:
            report = core.run_review(
                CLEAN,
                {"gem": boom(Exception("gemini quota: HTTP 429")),
                 "nvi": ok_provider},
                fallbacks={"correctness": ("oai", fb)},
                sleep=NO_SLEEP)
        finally:
            core._MAX_JOB_ATTEMPTS = original
        self.assertEqual(calls["fallback"], 0)
        rec = {r["lens"]: r for r in report["reviewer_reports"]}
        self.assertEqual(rec["correctness"]["status"], "error")
        self.assertIn("not attempted",
                      " ".join(report["gate_reasons"]))


class SeatCollisionCaseTests(unittest.TestCase):
    CUSTOM = "Bot|openai-compatible|https://example.invalid|m|NOPE"

    def test_case_variant_cross_kind_collision_raises(self):
        with self.assertRaises(providers.ProviderError):
            providers.build_providers(
                [self.CUSTOM, "agent:bot:echo hi"])

    def test_case_variant_reversed_raises(self):
        with self.assertRaises(providers.ProviderError):
            providers.build_providers(
                ["agent:Bot:echo hi",
                 "bot|openai-compatible|https://example.invalid|m|N"])

    def test_same_name_same_kind_still_builds(self):
        seats = providers.build_providers(
            ["agent:bot:echo hi", "agent:bot:echo ho"])
        self.assertEqual(sorted(seats), ["bot", "bot-2"])

    def test_case_variant_agent_names_stay_unique(self):
        seats = providers.build_providers(
            ["agent:Bot:echo hi", "agent:bot:echo ho"])
        self.assertEqual(sorted(seats), ["Bot", "bot-2"])


class DefaultSeatMetaTests(unittest.TestCase):
    def test_agent_seats_get_agent_family(self):
        seats = providers.build_providers(["agent:bot:echo hi"])
        meta = cli._default_seat_meta(seats)
        self.assertEqual(meta["bot"]["family"], "agent")

    def test_suffixed_agent_seats_get_agent_family(self):
        seats = providers.build_providers(
            ["agent:bot:echo hi", "agent:bot:echo ho"])
        meta = cli._default_seat_meta(seats)
        self.assertEqual(meta["bot"]["family"], "agent")
        self.assertEqual(meta["bot-2"]["family"], "agent")

    def test_agent_named_like_preset_is_not_the_preset_family(self):
        seats = providers.build_providers(["agent:gemini:echo hi"])
        meta = cli._default_seat_meta(seats)
        self.assertEqual(meta["gemini"]["family"], "agent")

    def test_preset_family_unchanged(self):
        seats = providers.build_providers(["gemini"])
        meta = cli._default_seat_meta(seats)
        self.assertEqual(meta["gemini"]["family"], "google")


DIFF_V1 = """diff --git a/billing/charge.py b/billing/charge.py
--- a/billing/charge.py
+++ b/billing/charge.py
@@ -3,4 +3,4 @@ def checkout(order, card):
-    return charge(order.total_cents)
+    return charge(order.total_dollars)
"""

DIFF_V2 = """diff --git a/billing/charge.py b/billing/charge.py
--- a/billing/charge.py
+++ b/billing/charge.py
@@ -3,4 +3,4 @@ def checkout(order, card):
-    return charge(order.total_cents)
+    return charge(order.total_dollars + 1)
"""

EXPECTED = [{"severity": "blocker", "category": "correctness",
             "file": "billing/charge.py", "line": 4,
             "title": "dollars charged as cents",
             "keywords": ["dollars", "cents"]}]


def _write_case(root, cid, diff, expected):
    cdir = os.path.join(root, cid)
    os.makedirs(cdir, exist_ok=True)
    meta = {"id": cid, "title": f"case {cid}",
            "category": "payments", "split": "public",
            "source": "test fixture", "license": "MIT",
            "expected": expected}
    with open(os.path.join(cdir, "case.json"), "w") as fh:
        json.dump(meta, fh)
    with open(os.path.join(cdir, "diff.patch"), "w") as fh:
        fh.write(diff)


class BenchStalenessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self.corpus = os.path.join(root, "corpus")
        self.out = os.path.join(root, "out")
        os.makedirs(os.path.join(root, "configs"))
        os.makedirs(os.path.join(root, "scripts"))
        _write_case(self.corpus, "pay-bug", DIFF_V1, EXPECTED)
        script = {"pay-bug": {
            "verdict": "changes_requested", "summary": "found it",
            "findings": [{"severity": "blocker",
                          "category": "correctness",
                          "file": "billing/charge.py", "line": 4,
                          "title": "dollars charged as cents",
                          "evidence": "x", "recommendation": "y",
                          "confidence": 0.9}]}}
        with open(os.path.join(root, "scripts", "oracle.json"),
                  "w") as fh:
            json.dump(script, fh)
        self.config_path = os.path.join(root, "configs",
                                        "oracle.json")
        self._write_config(0)

    def _write_config(self, cost):
        with open(self.config_path, "w") as fh:
            json.dump({"name": "oracle",
                       "providers": [{"name": "oracle",
                                      "script": "../scripts/"
                                                "oracle.json"}],
                       "cost_per_call_usd": cost}, fh)

    def tearDown(self):
        self._tmp.cleanup()

    def test_changed_case_is_rerun_not_trusted(self):
        first = bench.run_bench(self.corpus, ["oracle"], self.out)
        sha_v1 = first["oracle"][0]["patch_sha256"]
        _write_case(self.corpus, "pay-bug", DIFF_V2, EXPECTED)
        second = bench.run_bench(self.corpus, ["oracle"], self.out)
        self.assertEqual(len(second["oracle"]), 1)
        self.assertNotEqual(second["oracle"][0]["patch_sha256"],
                            sha_v1)
        path = os.path.join(self.out, "oracle.jsonl")
        with open(path) as fh:
            self.assertEqual(len(fh.readlines()), 1)

    def test_changed_config_is_rerun_not_trusted(self):
        bench.run_bench(self.corpus, ["oracle"], self.out)
        self._write_config(5)
        again = bench.run_bench(self.corpus, ["oracle"], self.out)
        self.assertEqual(len(again["oracle"]), 1)
        self.assertGreater(again["oracle"][0]["cost_usd"], 0)

    def test_unchanged_resume_still_skips(self):
        bench.run_bench(self.corpus, ["oracle"], self.out)
        again = bench.run_bench(self.corpus, ["oracle"], self.out)
        self.assertEqual(len(again["oracle"]), 1)
        path = os.path.join(self.out, "oracle.jsonl")
        with open(path) as fh:
            self.assertEqual(len(fh.readlines()), 1)

    def test_report_drops_hash_mismatched_records(self):
        results = bench.run_bench(self.corpus, ["oracle"], self.out)
        results["oracle"][0]["patch_sha256"] = "0" * 64
        report = bench.build_report(results, self.corpus)
        self.assertEqual(report["stale_records_dropped"], 1)
        self.assertEqual(
            report["configs"]["oracle"]["metrics"]["cases_run"], 0)

    def test_report_drops_config_mismatched_records(self):
        bench.run_bench(self.corpus, ["oracle"], self.out)
        self._write_config(9)
        report = bench.build_report(
            bench.load_results(self.out), self.corpus)
        self.assertEqual(report["stale_records_dropped"], 1)
        self.assertEqual(
            report["configs"]["oracle"]["metrics"]["cases_run"], 0)


class DoctorFallbackGuardTests(unittest.TestCase):
    def test_doctor_rejects_fallback_duplicating_primary(self):
        # 764e1d15a218 (doctor half): the review path refuses
        # a fallback seat that duplicates a primary; the
        # doctor path applies the same guard.
        import io
        from contextlib import redirect_stdout
        spec = ("dup|openai-compatible|https://example.invalid"
                "/v1|m|NOPE_KEY_ENV")
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli._doctor_main(
                ["--fallback", f"correctness={spec}"],
                providers_override={"dup": lambda p: "{}"})
        self.assertEqual(rc, 2)
        self.assertIn("already a primary seat", out.getvalue())


if __name__ == "__main__":
    unittest.main()
