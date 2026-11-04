"""v0.9.1 — adjudication of the review-v12 record, per the
issue report's closure criteria
(~/workspace/issue-reports/2026-11-04-codereview-v12-gate-findings.md):

- the enumeration test: EVERY seat-construction entry point in
  cli.py / bench.py / providers.py is accounted for — a path
  either forwards the configured agent timeout or belongs to a
  command that exposes no timeout option at all, so a missed
  construction path fails loudly here instead of hiding until a
  gate panel finds it (the v12 [3]/[4] failure mode);
- functional forwarding tests for the two flagged paths (review
  primaries + fallbacks, doctor fallbacks);
- the bench --force replacement fix (v12 [1]);
- _fixture_inner_paths enforcing the top-level subtraction
  itself (v12 [8]);
- executable evidence for the rebutted budget claims (v12
  [6]/[7]) and the subprocess kill/status ordering (v12 [0]).
"""
import ast
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "src"))

from codereview import bench, cli, core, providers  # noqa: E402

NO_SLEEP = lambda _s: None  # noqa: E731

SRC = os.path.join(os.path.dirname(__file__), "..", "src",
                   "codereview")

CLEAN_DIFF = (
    "diff --git a/app/util.py b/app/util.py\n"
    "--- a/app/util.py\n"
    "+++ b/app/util.py\n"
    "@@ -1,2 +1,3 @@\n"
    " def add(a, b):\n"
    "     return a + b\n"
    "+TIMEOUT = 30\n")


def ok_provider(_prompt):
    return json.dumps({"summary": "clean", "findings": []})


def boom(exc):
    def _fn(_prompt):
        raise exc
    return _fn


# ------------------------------------------------------------------
# The enumeration test (closure criterion for v12 [3]/[4])
#
# Construction entry points that expose NO timeout option: their
# parsers define no --timeout, so there is no configured value to
# forward and every seat they build — primaries; these commands
# have no fallback seats — gets build_providers' uniform default.
# The day any of them grows a --timeout flag, this test fails
# until the forwarding is wired, which is the point.
NO_TIMEOUT_OPTION = {
    ("cli.py", "_loop_main"),
    ("cli.py", "_workflow_main"),
    ("cli.py", "_pr_main"),
    ("bench.py", "build_config_providers"),
}

CONSTRUCTION_FUNCS = ("build_providers", "build_solvers")


def _construction_sites(fname):
    """All build_providers/build_solvers call sites in a source
    file: [(enclosing_function, lineno, passes_agent_timeout)]."""
    path = os.path.join(SRC, fname)
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    sites = []

    def visit(node, func):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef,
                                  ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call):
                callee = child.func
                name = None
                if isinstance(callee, ast.Name):
                    name = callee.id
                elif isinstance(callee, ast.Attribute):
                    name = callee.attr
                if name in CONSTRUCTION_FUNCS:
                    passes = any(kw.arg == "agent_timeout"
                                 for kw in child.keywords)
                    sites.append((func, child.lineno, passes))
            visit(child, func)

    visit(tree, "<module>")
    return src, sites


class TimeoutEnumerationTests(unittest.TestCase):
    def test_every_construction_site_is_accounted_for(self):
        seen = set()
        for fname in ("cli.py", "bench.py", "providers.py"):
            _src, sites = _construction_sites(fname)
            self.assertTrue(sites, f"no construction sites in "
                                   f"{fname} — enumeration is stale")
            for func, lineno, passes in sites:
                key = (fname, func)
                seen.add(key)
                if passes:
                    continue
                self.assertIn(
                    key, NO_TIMEOUT_OPTION,
                    f"{fname}:{lineno} in {func} constructs seats "
                    f"without forwarding agent_timeout and is not "
                    f"a known no-timeout-option entry point — wire "
                    f"the forwarding (and remove it from the "
                    f"allowlist if it gained a --timeout option)")
        # The allowlist must not rot: every entry still names a
        # real construction site found above.
        self.assertEqual(seen & NO_TIMEOUT_OPTION, NO_TIMEOUT_OPTION)

    def test_allowlisted_commands_really_have_no_timeout_option(self):
        with open(os.path.join(SRC, "cli.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        funcs = {n.name: n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)}
        for fname, func in sorted(NO_TIMEOUT_OPTION):
            if fname != "cli.py":
                continue
            node = funcs[func]
            segment = ast.get_source_segment(
                open(os.path.join(SRC, fname),
                     encoding="utf-8").read(), node) or ""
            self.assertNotIn(
                '"--timeout"', segment,
                f"{func} defines --timeout but does not forward "
                f"it — remove it from NO_TIMEOUT_OPTION and wire "
                f"agent_timeout through its constructions")

    def test_terminal_agent_construction_uses_the_timeout(self):
        # providers.build_provider is where agent seats are
        # actually built: the command_agent call's timeout must
        # derive from the agent_timeout parameter (with the
        # AGENT_TIMEOUT default behind it), and build_solvers
        # must forward its own agent_timeout into build_providers.
        _src, sites = _construction_sites("providers.py")
        self.assertTrue(
            any(func == "build_solvers" and passes
                for func, _ln, passes in sites),
            "build_solvers no longer forwards agent_timeout")
        with open(os.path.join(SRC, "providers.py"),
                  encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(
                    node.func, ast.Name) \
                    and node.func.id == "command_agent":
                kw = {k.arg: k.value for k in node.keywords}
                self.assertIn("timeout", kw)
                self.assertIn("agent_timeout",
                              ast.dump(kw["timeout"]))
                break
        else:  # pragma: no cover — the call must exist
            self.fail("command_agent construction not found")


class TimeoutForwardingFunctionalTests(unittest.TestCase):
    """Spy on cli.build_providers (the v0.9.0 doctor test's style)
    and drive the real entry points with --timeout set."""

    def _spy(self):
        calls = []

        def fake_build(specs, agent_timeout=None, **kw):
            calls.append(agent_timeout)
            name = "prim" if len(calls) == 1 else "fb"
            return {name: ok_provider}

        original = cli.build_providers
        cli.build_providers = fake_build
        self.addCleanup(setattr, cli, "build_providers", original)
        return calls

    def test_review_main_forwards_timeout_to_primaries_and_fallback(
            self):
        calls = self._spy()
        with tempfile.TemporaryDirectory() as tmp:
            patch = os.path.join(tmp, "change.diff")
            with open(patch, "w", encoding="utf-8") as fh:
                fh.write(CLEAN_DIFF)
            rc = cli.main(["--patch", patch, "--out",
                           os.path.join(tmp, "out"),
                           "--provider", "gemini",
                           "--fallback", "correctness=openai",
                           "--timeout", "7"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [7, 7])

    def test_review_main_default_timeout_is_uniform(self):
        calls = self._spy()
        with tempfile.TemporaryDirectory() as tmp:
            patch = os.path.join(tmp, "change.diff")
            with open(patch, "w", encoding="utf-8") as fh:
                fh.write(CLEAN_DIFF)
            rc = cli.main(["--patch", patch, "--out",
                           os.path.join(tmp, "out"),
                           "--provider", "gemini",
                           "--fallback", "correctness=openai"])
        self.assertEqual(rc, 0)
        # No --timeout: both constructions receive the same
        # "unset" value and build_providers applies its one
        # default — primaries and fallbacks cannot diverge.
        self.assertEqual(calls, [None, None])

    def test_doctor_forwards_timeout_to_fallback_construction(self):
        calls = self._spy()
        rc = cli._doctor_main(["--timeout", "7", "--provider",
                               "gemini", "--fallback",
                               "correctness=openai"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [7, 7])


class BenchForceTests(unittest.TestCase):
    """v12 [1]: a --force rerun replaces the stored records for
    a config instead of appending duplicates."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self.corpus = os.path.join(root, "corpus")
        os.makedirs(os.path.join(root, "configs"))
        os.makedirs(os.path.join(root, "scripts"))
        self.out = os.path.join(root, "out")
        for cid, diff in (("clean-one", CLEAN_DIFF),
                          ("clean-two", CLEAN_DIFF)):
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
        with open(os.path.join(root, "configs", "blind.json"),
                  "w") as fh:
            json.dump({"name": "blind",
                       "providers": [{"name": "blind",
                                      "script":
                                      "../scripts/blind.json"}]},
                      fh)

    def tearDown(self):
        self._tmp.cleanup()

    def _lines(self):
        with open(os.path.join(self.out, "blind.jsonl")) as fh:
            return len(fh.readlines())

    def test_force_rerun_replaces_records(self):
        bench.run_bench(self.corpus, ["blind"], self.out)
        self.assertEqual(self._lines(), 2)
        bench.run_bench(self.corpus, ["blind"], self.out,
                        force=True)
        self.assertEqual(self._lines(), 2)
        again = bench.run_bench(self.corpus, ["blind"], self.out)
        self.assertEqual(len(again["blind"]), 2)
        self.assertEqual(self._lines(), 2)

    def test_failed_force_run_keeps_previous_results(self):
        # The fix diff's own internal review: replacing must be
        # atomic — a force run that dies mid-way leaves the
        # previous results file byte-identical, never a
        # truncated stub.
        bench.run_bench(self.corpus, ["blind"], self.out)
        path = os.path.join(self.out, "blind.jsonl")
        with open(path, encoding="utf-8") as fh:
            before = fh.read()

        def boom(*a, **kw):
            raise RuntimeError("simulated mid-run failure")

        original = bench.core.run_review
        bench.core.run_review = boom
        self.addCleanup(setattr, bench.core, "run_review",
                        original)
        with self.assertRaises(RuntimeError):
            bench.run_bench(self.corpus, ["blind"], self.out,
                            force=True)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)


class TimeoutValidationTests(unittest.TestCase):
    """Non-positive --timeout values are rejected at the CLI
    boundary (the fix diff's own internal review): a zero or
    negative value would otherwise reach subprocess
    communicate() and surface as a confusing seat error. Every
    command that accepts --timeout validates it."""

    def test_review_rejects_non_positive_timeout(self):
        for bad in ("0", "-3"):
            self.assertEqual(
                cli.main(["--patch", "+x", "--timeout", bad]), 2)

    def test_doctor_rejects_non_positive_timeout(self):
        self.assertEqual(cli._doctor_main(["--timeout", "0"]), 2)

    def test_intake_rejects_non_positive_timeout(self):
        self.assertEqual(cli._intake_main(
            ["no-such-report.md", "--timeout", "0"]), 2)


FIXTURE_NESTED = (
    "diff --git a/bench/corpus/sql-case/diff.patch "
    "b/bench/corpus/sql-case/diff.patch\n"
    "--- a/bench/corpus/sql-case/diff.patch\n"
    "+++ b/bench/corpus/sql-case/diff.patch\n"
    "@@ -0,0 +1,4 @@\n"
    "+diff --git a/app/search.py b/app/search.py\n"
    "+--- a/app/search.py\n"
    "++++ b/app/search.py\n"
    "++x = 1\n")

PRODUCT_SECTION = (
    "diff --git a/app/search.py b/app/search.py\n"
    "--- a/app/search.py\n"
    "+++ b/app/search.py\n"
    "@@ -0,0 +1,1 @@\n"
    "+x = 1\n")


class FixtureInnerPathsTests(unittest.TestCase):
    """v12 [8]: the top-level subtraction is enforced inside
    _fixture_inner_paths itself, not only by caller discipline."""

    def test_inner_name_colliding_with_top_level_is_excluded(self):
        sections = core.split_patch_sections(
            FIXTURE_NESTED + PRODUCT_SECTION)
        inner = core._fixture_inner_paths(
            sections, ["bench/corpus/**"])
        self.assertNotIn("app/search.py", inner)

    def test_inner_name_without_collision_still_collected(self):
        sections = core.split_patch_sections(FIXTURE_NESTED)
        inner = core._fixture_inner_paths(
            sections, ["bench/corpus/**"])
        self.assertIn("app/search.py", inner)


class AttemptBudgetEvidenceTests(unittest.TestCase):
    """Executable evidence for the v12 [6]/[7] rebuttals: a lone
    seat's job is bounded by the error-class cap (at most 3),
    which is below the primary+fallback pair budget (6) — the
    pair budget exists for the pair; no path lets one job past
    it. The pair worst case itself is covered by
    test_v090_fixes.test_job_attempts_are_capped_in_the_worst_case.
    """

    def test_lone_seat_attempts_capped_by_error_class(self):
        cases = [
            (Exception("HTTP 429 quota exceeded (daily)"), 1),
            (Exception("api_key not set"), 1),
            (Exception("HTTP 503 overloaded"), 3),
        ]
        for exc, want in cases:
            res = core._review_job(boom(exc), "prompt",
                                   sleep=NO_SLEEP)
            self.assertFalse(res["ok"])
            self.assertEqual(res["attempts"], want)
            self.assertLessEqual(res["attempts"],
                                 core._MAX_JOB_ATTEMPTS)

    def test_verification_voter_attempts_are_bounded_too(self):
        previous = {
            "gate": "blocked",
            "findings": [{
                "id": "f1", "severity": "blocker",
                "category": "correctness", "file": "app/util.py",
                "line": 1, "title": "planted", "evidence": "e",
                "recommendation": "r", "confidence": 0.9,
                "sources": ["busy"]}]}
        voter = boom(Exception("HTTP 503 overloaded"))
        fixer = lambda _p: json.dumps({  # noqa: E731
            "resolutions": [{"finding_id": "f1",
                             "status": "fixed",
                             "evidence": "TIMEOUT = 30 added in "
                                         "app/util.py"}],
            "new_findings": []})
        report = core.run_verification(
            CLEAN_DIFF, {"busy": voter, "fixer": fixer}, previous,
            "fixed it", sleep=NO_SLEEP)
        rec = {r["provider"]: r
               for r in report["reviewer_reports"]}
        self.assertEqual(rec["busy"]["attempts"], 3)
        self.assertLessEqual(rec["busy"]["attempts"],
                             core._MAX_JOB_ATTEMPTS)


@unittest.skipUnless(os.name == "posix", "process groups are POSIX")
class SubprocessOrderEvidenceTests(unittest.TestCase):
    """v12 [0]: in command_agent, communicate() captures the
    exit status BEFORE the finally-block group kill runs. If the
    kill preceded (or corrupted) the status check, a slow exit-0
    agent would report SIGKILL (-9) instead of returning its
    output, and an exit-7 agent would not report 7."""

    def test_exit_status_survives_the_group_kill(self):
        fn = providers.command_agent(
            "sh -c 'sleep 0.3; echo hello'", timeout=30)
        self.assertEqual(fn("prompt"), "hello")

    def test_nonzero_exit_status_is_the_one_reported(self):
        fn = providers.command_agent(
            "sh -c 'echo out; exit 7'", timeout=30)
        with self.assertRaises(providers.ProviderError) as cm:
            fn("prompt")
        self.assertIn("exited 7", str(cm.exception))
        self.assertNotIn("-9", str(cm.exception))

    def test_background_child_killed_after_status_captured(self):
        # The seat exits 0 with work still running in its group;
        # the call returns the seat's output (status honored) and
        # the child is dead before it can fire — the kill's whole
        # purpose (v0.7.2 finding 3.2), exercised here against a
        # marker the child would create 2s after the seat exited.
        marker_dir = tempfile.mkdtemp(prefix="codereview-test-")
        marker = os.path.join(marker_dir, "survived")
        fn = providers.command_agent(
            "sh -c '(sleep 2; touch " + marker + ") & echo hi'",
            timeout=30)
        self.assertEqual(fn("prompt"), "hi")
        time.sleep(2.6)
        self.assertFalse(os.path.exists(marker))


if __name__ == "__main__":
    unittest.main()
