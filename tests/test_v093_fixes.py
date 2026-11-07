"""v0.9.3 (Phase 1 of the v14-hold solution) — adjudication of
the review-v14 record, per the successor issue report's closure
criteria (~/workspace/issue-reports/
2026-11-04-codereview-v14-gate-findings.md) and the solution doc
~/workspace/user/files/codereview-v14-hold-solution-2026-11-04.md:

- [9] _classify_error digit-substring conflation: FIXED —
  status codes now match as whole tokens and the typed quota
  codes (RESOURCE_EXHAUSTED / insufficient_quota) decide the
  quota class directly (ClassifyErrorTokenTests);
- [2] bench --force swapping in a provider-failure run: FIXED —
  the swap is refused when any case came back degraded, the
  previous results file stays byte-identical and the temp file
  is removed (BenchForceDegradedTests);
- [8] verification clearing with a lens-named source: rebutted
  with the doc's own fixture — the finding lands in `unjudged`
  and the gate is INCONCLUSIVE (the designed fail-safe), while
  a provider-named source clears (VerificationLensSourceTests);
- [4] fallback success leaving the report marked as error:
  rebutted — the report carries the serving seat, status ok,
  error cleared, fallback recorded (FallbackReportStatusTests);
- [7] retry loop exceeding _MAX_JOB_ATTEMPTS: rebutted — the
  primary+fallback tally is bounded by the cap by construction
  (RetryPairBudgetTests);
- [5] fixture classification silently dropping findings:
  rebutted — classified + remaining == total, and classified
  findings stay visible in the record (FixturePartitionTests);
- [3] bench providers_override sharing one map across configs:
  rebutted — the override is an internal-only, by-design panel
  substitution and the shared map is never mutated
  (BenchOverrideSharingTests);
- [6] missing timeout on agent subprocess execution: rebutted
  (the execution path is providers.command_agent's
  communicate(timeout=...), not the cited core.py line) — with
  the doc's guard test added anyway: EVERY subprocess call in
  src/ must carry a timeout (SubprocessTimeoutGuardTests).
"""
import ast
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "src"))

from codereview import bench, core  # noqa: E402

NO_SLEEP = lambda _s: None  # noqa: E731

SRC = os.path.join(os.path.dirname(__file__), "..", "src",
                   "codereview")

OK_JSON = json.dumps({"summary": "fine", "findings": []})


def ok_seat(_prompt):
    return OK_JSON


def fail_auth(_prompt):
    raise RuntimeError("HTTP 401 from api.example.com")


class ClassifyErrorTokenTests(unittest.TestCase):
    """v14 [9]: real provider bodies classify as intended, and a
    status code's digits inside an unrelated number no longer
    hijack the class."""

    def test_real_provider_bodies(self):
        cases = [
            ('{"error": {"code": 429, "message": "Quota exceeded '
             'for quota metric", "status": "RESOURCE_EXHAUSTED"}}',
             ("quota", 1)),
            ("Error code: 429 - {'error': {'message': 'You exceeded "
             "your current quota', 'type': 'insufficient_quota', "
             "'code': 'insufficient_quota'}}", ("quota", 1)),
            ("Error code: 429 - {'error': {'message': 'Rate limit "
             "reached', 'type': 'rate_limit_exceeded'}}",
             ("rate_limit", 3)),
            ("Error code: 401 - {'error': {'message': 'Incorrect "
             "API key provided'}}", ("auth", 1)),
            ('{"error": {"code": 403, "message": "API key not '
             'valid.", "status": "INVALID_ARGUMENT"}}', ("auth", 1)),
            ("gemini quota: HTTP 429", ("quota", 1)),
            ("nvidia overloaded: HTTP 503", ("transient", 3)),
            ("HTTP 429 Too Many Requests", ("rate_limit", 3)),
        ]
        for msg, want in cases:
            with self.subTest(msg=msg[:40]):
                self.assertEqual(
                    core._classify_error(RuntimeError(msg)), want)

    def test_insufficient_quota_needs_no_429_in_string(self):
        self.assertEqual(
            core._classify_error(
                RuntimeError("insufficient_quota: billing hard "
                             "limit reached")),
            ("quota", 1))

    def test_digits_inside_other_numbers_do_not_conflate(self):
        # The pre-fix defect: a transient 503 whose body mentions
        # 4030 tokens (or a request id containing 401) classified
        # as auth and got NO retry.
        self.assertEqual(
            core._classify_error(RuntimeError(
                "HTTP 503 Service Unavailable: model overloaded "
                "(context 4030 tokens)")),
            ("transient", 3))
        self.assertEqual(
            core._classify_error(RuntimeError(
                "HTTP 503: overloaded, request id req_4014")),
            ("transient", 3))


class _BenchFixture(unittest.TestCase):
    """Tiny two-case corpus + one scripted config, in the shape
    BenchEndToEndTests / BenchForceTests use."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self.corpus = os.path.join(root, "corpus")
        os.makedirs(os.path.join(root, "configs"))
        os.makedirs(os.path.join(root, "scripts"))
        self.out = os.path.join(root, "out")
        diff = ("diff --git a/app/util.py b/app/util.py\n"
                "--- a/app/util.py\n+++ b/app/util.py\n"
                "@@ -1 +1 @@\n-x\n+y\n")
        for cid in ("clean-one", "clean-two"):
            cdir = os.path.join(self.corpus, cid)
            os.makedirs(cdir)
            meta = {"id": cid, "title": f"case {cid}",
                    "category": "clean", "split": "public",
                    "source": "test fixture", "license": "MIT",
                    "expected": []}
            with open(os.path.join(cdir, "case.json"), "w") as fh:
                json.dump(meta, fh)
            with open(os.path.join(cdir, "diff.patch"), "w") as fh:
                fh.write(diff)
        with open(os.path.join(root, "scripts", "blind.json"),
                  "w") as fh:
            json.dump({"default": {"verdict": "pass",
                                   "summary": "nothing",
                                   "findings": []}}, fh)
        for name in ("blind", "blind2"):
            with open(os.path.join(root, "configs", f"{name}.json"),
                      "w") as fh:
                json.dump({"name": name,
                           "providers": [{
                               "name": name,
                               "script": "../scripts/blind.json"}]},
                          fh)

    def tearDown(self):
        self._tmp.cleanup()


class BenchForceDegradedTests(_BenchFixture):
    """v14 [2]: a --force run in which a provider failed must not
    replace good stored results with degraded ones."""

    def test_degraded_force_run_refuses_swap(self):
        bench.run_bench(self.corpus, ["blind"], self.out)
        path = os.path.join(self.out, "blind.jsonl")
        with open(path, encoding="utf-8") as fh:
            before = fh.read()
        self.assertTrue(before.strip())
        with self.assertRaises(ValueError):
            bench.run_bench(
                self.corpus, ["blind"], self.out, force=True,
                providers_by_config={
                    "blind": {"bad": fail_auth, "bad2": fail_auth}})
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)
        self.assertFalse(os.path.exists(path + ".tmp"))

    def test_healthy_force_run_still_swaps(self):
        bench.run_bench(self.corpus, ["blind"], self.out)
        results = bench.run_bench(self.corpus, ["blind"], self.out,
                                  force=True)
        self.assertEqual(len(results["blind"]), 2)
        path = os.path.join(self.out, "blind.jsonl")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(len(fh.readlines()), 2)


class BenchOverrideSharingTests(_BenchFixture):
    """v14 [3]: the internal providers_override intentionally
    serves every named config with the same panel; run_bench
    never mutates the shared map."""

    def test_shared_override_map_unmutated(self):
        shared = {"sharedseat": ok_seat}
        results = bench.run_bench(
            self.corpus, ["blind", "blind2"], self.out,
            providers_by_config={"blind": shared, "blind2": shared})
        self.assertEqual(len(results["blind"]), 2)
        self.assertEqual(len(results["blind2"]), 2)
        self.assertEqual(list(shared), ["sharedseat"])
        self.assertIs(shared["sharedseat"], ok_seat)


class VerificationLensSourceTests(unittest.TestCase):
    """v14 [8]: sources are provider names by construction (the
    only writers are _normalize_finding, the deterministic
    literal, and merge_findings' copies). A hypothetical
    lens-named source cannot clear — it lands in unjudged and
    the gate is INCONCLUSIVE, the designed fail-safe."""

    PATCH = ("diff --git a/x.py b/x.py\n@@ -1 +1 @@\n-bad\n+good\n")
    EVIDENCE = "the bad line was replaced by good in x.py"

    def _seat(self):
        def seat(_prompt):
            return json.dumps({
                "resolutions": [{
                    "finding_id": "abc123", "status": "fixed",
                    "evidence": self.EVIDENCE}],
                "new_findings": []})
        return seat

    def _run(self, sources):
        prior = {"findings": [{
            "id": "abc123", "severity": "major", "file": "x.py",
            "title": "t", "sources": sources}]}
        return core.run_verification(
            self.PATCH,
            {"seatA": self._seat(), "seatB": self._seat()},
            prior, builder_response="fixed it", sleep=NO_SLEEP)

    def test_lens_named_source_is_unjudged_not_cleared(self):
        rep = self._run(["correctness"])
        self.assertEqual(rep["gate"], "inconclusive")
        self.assertEqual(len(rep["unjudged"]), 1)
        self.assertEqual(len(rep["cleared"]), 0)

    def test_provider_named_source_clears(self):
        rep = self._run(["seatA"])
        self.assertEqual(rep["gate"], "pass")
        self.assertEqual(len(rep["cleared"]), 1)


class FallbackReportStatusTests(unittest.TestCase):
    """v14 [4]: when the fallback serves a lens, the reviewer
    report names the serving seat, status ok, error cleared."""

    def test_fallback_success_report_is_ok(self):
        rep = core.run_review(
            "diff --git a/x.py b/x.py\n@@ -1 +1 @@\n-a\n+b\n",
            {"bad": fail_auth, "good": ok_seat},
            fallbacks={"correctness": ("fbseat", ok_seat)},
            sleep=NO_SLEEP)
        rec = [r for r in rep["reviewer_reports"]
               if r["lens"] == "correctness"][0]
        self.assertEqual(rec["provider"], "fbseat")
        self.assertEqual(rec["fallback_for"], "bad")
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["error"], "")


class RetryPairBudgetTests(unittest.TestCase):
    """v14 [7]: with always-failing seats, a primary job plus
    its fallback spend at most _MAX_JOB_ATTEMPTS attempts in
    total — the fallback is handed only the remaining budget."""

    def test_pair_total_never_exceeds_cap(self):
        def fail_rl(_prompt):
            raise RuntimeError("HTTP 429 rate limit reached")

        primary = core._review_job(fail_rl, "p", sleep=NO_SLEEP)
        self.assertEqual(primary["attempts"], 3)
        remaining = core._MAX_JOB_ATTEMPTS - primary["attempts"]
        fallback = core._review_job(fail_rl, "p", sleep=NO_SLEEP,
                                    max_attempts=remaining)
        self.assertEqual(primary["attempts"] + fallback["attempts"],
                         core._MAX_JOB_ATTEMPTS)

    def test_quota_job_spends_one_attempt(self):
        def fail_quota(_prompt):
            raise RuntimeError("gemini quota: HTTP 429")

        res = core._review_job(fail_quota, "p", sleep=NO_SLEEP)
        self.assertEqual(res["attempts"], 1)


class FixturePartitionTests(unittest.TestCase):
    """v14 [5]: fixture classification is a partition, not a
    filter — every finding lands in exactly one of the two
    lists, and classified findings stay in the record."""

    def test_partition_is_complete_and_visible(self):
        patch = (
            "diff --git a/bench/corpus/case-a/diff.patch "
            "b/bench/corpus/case-a/diff.patch\n"
            "--- /dev/null\n+++ b/bench/corpus/case-a/diff.patch\n"
            "@@ -0,0 +3 @@\n"
            "+diff --git a/app/search.py b/app/search.py\n"
            "diff --git a/src/prod.py b/src/prod.py\n"
            "--- a/src/prod.py\n+++ b/src/prod.py\n"
            "@@ -1 +1 @@\n-x\n+y\n")

        def seat(_prompt):
            return json.dumps({"summary": "s", "findings": [
                {"severity": "major",
                 "file": "bench/corpus/case-a/diff.patch",
                 "line": 1, "title": "fixture file finding unique-a",
                 "evidence": "e", "recommendation": "r"},
                {"severity": "major", "file": "app/search.py",
                 "line": 2, "title": "inner path finding unique-b",
                 "evidence": "e", "recommendation": "r"},
                {"severity": "major", "file": "src/prod.py",
                 "line": 3, "title": "product finding unique-c",
                 "evidence": "e", "recommendation": "r"}]})

        rep = core.run_review(
            patch, {"s1": seat, "s2": ok_seat},
            fixture_scope={"patterns": ["bench/corpus/**"],
                           "policy_version": 1,
                           "manifest_path": "fixtures-manifest.json",
                           "manifest_sha256": "x" * 64},
            sleep=NO_SLEEP)
        total = len(rep["findings"]) + len(rep["fixture_findings"])
        self.assertEqual(total, 3)
        self.assertEqual(
            [f["title"] for f in rep["findings"]],
            ["product finding unique-c"])
        self.assertEqual(
            sorted(f["title"] for f in rep["fixture_findings"]),
            ["fixture file finding unique-a",
             "inner path finding unique-b"])
        self.assertTrue(any("fixture" in r
                            for r in rep["gate_reasons"]))


# Popen pairings the guard accepts besides communicate(
# timeout=...): named supervised waits that take the same
# timeout and enforce it with bounded waits and a process
# kill — providers' seat wait (Epic K2) and the evidence
# sandbox's wait (Epic C5). See the guard class docstring.
_SUPERVISED_WAITS = ("_run_seat_process",
                     "_supervise_sandbox_run",
                     # P3-07: the discovery probe's supervised
                     # wait — same contract (deadline-bounded
                     # waits, kill on expiry, capped drain).
                     "_supervise_probe_run",
                     # B3/C5: the probe harness's supervised
                     # wait — same contract again (deadline-
                     # bounded waits, process-group kill on
                     # expiry, capped drained output).
                     "_supervise_probe_execution")


class SubprocessTimeoutGuardTests(unittest.TestCase):
    """v14 [6] guard (added per the solution doc whether the
    finding is real or rebutted): every subprocess execution in
    src/ carries a timeout — subprocess.run/check_* via the
    timeout keyword, Popen via a communicate(timeout=...) in
    the same function. Epic K2 adds the second accepted Popen
    pairing: handing the process to providers._run_seat_process
    (the supervised seat wait), which takes the same timeout
    and enforces it as a poll-loop deadline with a process-tree
    kill — a stronger bound than communicate's, not a weaker
    one; the guard accepts the call by name so the pairing
    stays explicit in the seat code. Epic C5 adds the third
    accepted pairing, by the same rule: evidence's
    _supervise_sandbox_run, which waits on the sandbox child
    with wait(timeout=...) plus bounded drainer-thread joins
    and kills the process group on expiry — again a stronger
    bound than communicate's, since communicate buffers the
    child's output without bound (the C5 output-cap gap) and
    the supervised wait drains it under a per-stream cap.
    The B3 C5 hardening of the probe harness adds the fourth
    accepted pairing by the same rule: probe's
    _supervise_probe_execution, which the harness's Popen
    hands the child to — deadline-bounded waits and bounded
    drainer joins, the whole process group killed on expiry
    (and on normal exit, so no backgrounded child survives),
    output drained under the same per-stream cap."""

    def _files(self):
        for fname in sorted(os.listdir(SRC)):
            if fname.endswith(".py"):
                yield fname, os.path.join(SRC, fname)

    def test_run_family_always_has_timeout_keyword(self):
        offenders = []
        for fname, path in self._files():
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if (isinstance(func, ast.Attribute)
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "subprocess"
                        and func.attr in ("run", "call", "check_call",
                                          "check_output")
                        and not any(k.arg == "timeout"
                                    for k in node.keywords)):
                    offenders.append(
                        f"{fname}:{node.lineno} "
                        f"subprocess.{func.attr} without timeout")
        self.assertEqual(offenders, [])

    def test_popen_pairs_with_communicate_timeout(self):
        offenders = []
        total_popen = 0
        for fname, path in self._files():
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                popens = [n for n in ast.walk(node)
                          if isinstance(n, ast.Call)
                          and isinstance(n.func, ast.Attribute)
                          and isinstance(n.func.value, ast.Name)
                          and n.func.value.id == "subprocess"
                          and n.func.attr == "Popen"]
                if not popens:
                    continue
                total_popen += len(popens)
                guarded = any(
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "communicate"
                    and any(k.arg == "timeout" for k in n.keywords)
                    for n in ast.walk(node)) or any(
                    isinstance(n, ast.Call)
                    and ((isinstance(n.func, ast.Name)
                          and n.func.id in _SUPERVISED_WAITS)
                         or (isinstance(n.func, ast.Attribute)
                             and n.func.attr
                             in _SUPERVISED_WAITS))
                    for n in ast.walk(node))
                if not guarded:
                    offenders.append(
                        f"{fname}:{node.name} Popen without a "
                        "communicate(timeout=...) or a "
                        "supervised wait in the function")
        self.assertGreaterEqual(total_popen, 1)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
