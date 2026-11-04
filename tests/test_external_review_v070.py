"""Regression tests for the v0.7.0 external review findings
(2026-11-04): env leak to agent seats, one-reviewer verification
"consensus", agent cwd, cross-kind seat-name collisions, intake
deadline/process lifetime, noisy agent output. No network."""

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core, intake, providers  # noqa: E402

CLEAN = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,1 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""


def verdict_provider(resolutions=None, verdict="pass"):
    def fn(prompt):
        return json.dumps({
            "verdict": verdict, "summary": "s", "findings": [],
            "resolutions": resolutions or [], "new_findings": []})
    return fn


def failing_provider(prompt):
    raise providers.ProviderError("HTTP 503", retryable=True)


def prior_report(sources=("finder",)):
    return {"gate": "blocked", "findings": [{
        "id": "f1", "severity": "major", "title": "Bug",
        "file": "app/x.py", "sources": list(sources)}]}


FIXED = [{"finding_id": "f1", "status": "fixed",
          "evidence": "the new diff util sub add functions are "
                      "present and correct"}]


class AgentEnvTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(os.environ)
        os.environ["OPENAI_API_KEY"] = "sk-test-SECRET"
        os.environ["GITHUB_TOKEN"] = "ghp-test-SECRET"
        os.environ.pop("CODEREVIEW_AGENT_ENV", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def test_agent_seat_cannot_see_provider_keys(self):
        seats = providers.build_providers(["agent:e:env"])
        out = seats["e"]("x")
        self.assertNotIn("sk-test-SECRET", out)
        self.assertNotIn("ghp-test-SECRET", out)
        self.assertNotIn("OPENAI_API_KEY", out)
        self.assertIn("CODEREVIEW_PROMPT=", out)
        self.assertIn("PATH=", out)

    def test_agent_env_opt_in_passes_named_variable(self):
        os.environ["CODEREVIEW_AGENT_ENV"] = "OPENAI_API_KEY"
        seats = providers.build_providers(["agent:e:env"])
        out = seats["e"]("x")
        self.assertIn("sk-test-SECRET", out)
        self.assertNotIn("ghp-test-SECRET", out)


class AgentCwdTests(unittest.TestCase):
    def test_agent_runs_in_scratch_dir_with_only_the_prompt(self):
        seats = providers.build_providers(["agent:ls:ls -A"])
        out = seats["ls"]("the brief")
        self.assertEqual(out.strip().splitlines(), ["prompt.md"])

    def test_prompt_file_is_readable_via_env_path(self):
        seats = providers.build_providers(
            ["agent:c:sh -c 'cat \"$CODEREVIEW_PROMPT\"'"])
        self.assertEqual(seats["c"]("scratch brief"), "scratch brief")


class SeatNamespaceTests(unittest.TestCase):
    def test_cross_kind_collision_raises_in_either_order(self):
        for specs in (["agent:gemini:printf A", "gemini"],
                      ["gemini", "agent:gemini:printf A"]):
            with self.assertRaises(providers.ProviderError):
                providers.build_providers(specs)

    def test_cross_kind_collision_with_custom_spec(self):
        with self.assertRaises(providers.ProviderError):
            providers.build_providers(
                ["agent:bot:printf A",
                 "bot|openai-compatible|https://x/v1|m|K"])

    def test_agent_seat_named_like_preset_without_the_preset_is_fine(self):
        seats = providers.build_providers(["agent:gemini:printf A"])
        self.assertEqual(seats["gemini"]("x"), "A")


class AgentLifetimeTests(unittest.TestCase):
    def test_hung_agent_solver_dies_with_the_intake_deadline(self):
        marker_dir = tempfile.mkdtemp(prefix="codereview-test-")
        marker = os.path.join(marker_dir, "survived")
        solvers = providers.build_solvers(
            [f"agent:slow:sh -c 'sleep 3; touch {marker}'"],
            agent_timeout=1)
        start = time.monotonic()
        result = intake.run_intake("an issue report", solvers,
                                   timeout=1)
        elapsed = time.monotonic() - start
        self.assertFalse(result["solutions"][0]["ok"])
        self.assertLess(elapsed, 4)
        time.sleep(3.4)  # past the point a survivor would touch it
        self.assertFalse(os.path.exists(marker))

    def test_agent_error_is_not_retryable(self):
        seats = providers.build_providers(["agent:bad:false"])
        try:
            seats["bad"]("x")
            self.fail("expected ProviderError")
        except providers.ProviderError as exc:
            self.assertFalse(providers.is_retryable(exc))


class NoisyAgentOutputTests(unittest.TestCase):
    def test_banner_fences_and_trailing_text_still_parse(self):
        payload = ('{"verdict": "pass", "summary": "ok", '
                   '"findings": [], "resolutions": [], '
                   '"new_findings": []}')
        noisy = ("AGENT BANNER v2\nworking...\n```json\n" + payload
                 + "\n```\ndone in 3s")
        report = core.run_review(CLEAN, {"bot": lambda p: noisy})
        self.assertEqual(report["gate"], "pass")


class VerificationQuorumTests(unittest.TestCase):
    def test_one_surviving_reviewer_cannot_pass_verification(self):
        report = core.run_verification(
            CLEAN, {"finder": verdict_provider(FIXED),
                    "other": failing_provider},
            prior_report(), "fixed it")
        self.assertEqual(report["gate"], "inconclusive")
        self.assertIn("quorum", " ".join(report["gate_reasons"]))

    def test_finder_must_confirm_its_own_finding(self):
        # The finder errors; two other reviewers say fixed. The
        # finding is unjudged, not cleared: INCONCLUSIVE.
        report = core.run_verification(
            CLEAN, {"finder": failing_provider,
                    "other": verdict_provider(FIXED),
                    "third": verdict_provider(FIXED)},
            prior_report(), "fixed it")
        self.assertEqual(report["gate"], "inconclusive")
        self.assertEqual(len(report["unjudged"]), 1)
        self.assertEqual(report["cleared"], [])

    def test_finder_plus_quorum_passes_and_labels_counts(self):
        report = core.run_verification(
            CLEAN, {"finder": verdict_provider(FIXED),
                    "other": verdict_provider(FIXED)},
            prior_report(), "fixed it")
        self.assertEqual(report["gate"], "pass")
        self.assertIn("2 of 2", report["gate_reasons"][0])

    def test_degraded_pass_is_labelled_in_markdown(self):
        # Quorum met by finder + other; a third seat errored.
        report = core.run_verification(
            CLEAN, {"finder": verdict_provider(FIXED),
                    "other": verdict_provider(FIXED),
                    "third": failing_provider},
            prior_report(), "fixed it")
        self.assertEqual(report["gate"], "pass")
        self.assertTrue(report["degraded"])
        md = core.render_markdown(report)
        self.assertIn("DEGRADED", md)
        self.assertIn("2 of 3", md)

    def test_shipped_v070_record_would_not_pass_today(self):
        # The actual v0.7.0 verification shape: one ok reviewer,
        # one errored, one deterministic + one gemini finding.
        prev = {"gate": "blocked", "findings": [
            {"id": "d1", "severity": "major", "title": "Shell exec",
             "file": "src/x.py", "sources": ["deterministic"]},
            {"id": "f1", "severity": "major", "title": "Bug",
             "file": "src/x.py", "sources": ["gemini"]}]}
        res = [{"finding_id": "d1", "status": "fixed",
                "evidence": "shell false shlex split argv list"},
               {"finding_id": "f1", "status": "fixed",
                "evidence": "occurrence suffix seat names distinct"}]
        report = core.run_verification(
            CLEAN, {"nvidia": verdict_provider(res),
                    "gemini": failing_provider},
            prev, "fixed both")
        self.assertNotEqual(report["gate"], "pass")


if __name__ == "__main__":
    unittest.main()
