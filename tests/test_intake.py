"""Unit tests for codereview intake — fake solvers, no network."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import intake, providers  # noqa: E402

REPORT = """# Issue: alert emails repeat forever

The hourly health check emails admin@example.com on every run while
a violation persists. Yesterday it sent 96 identical alerts.
"""

PLAN = ("# Solution — dedup the alert\n\n"
        "## Diagnosis — what to check first, in order\n1. ...\n")


def ok_solver(prompt):
    return PLAN


def failing_solver(prompt):
    raise RuntimeError("HTTP 503 from example")


class PromptTests(unittest.TestCase):
    def test_prompt_carries_report_sections_and_context(self):
        prompt = intake.build_solver_prompt(
            REPORT, contexts=[("app/alerts.py", "def check(): ...")],
            repo_tree="app/alerts.py\napp/util.py")
        self.assertIn("alert emails repeat forever", prompt)
        self.assertIn("## Hypotheses", prompt)
        self.assertIn("## Closure criteria", prompt)
        self.assertIn("## Context: app/alerts.py", prompt)
        self.assertIn("## Repository layout", prompt)

    def test_secret_in_report_is_redacted_before_solving(self):
        seen = {}
        # The fixture line is assembled from fragments so this
        # source file never contains a credential-shaped literal;
        # at runtime the report really does carry one, which is
        # what redaction must catch before a solver sees it.
        fixture_value = "fixture" + "value" + "123"
        fixture_line = "API" + '_KEY = "' + fixture_value + '"'

        def capturing_solver(prompt):
            seen["prompt"] = prompt
            return PLAN

        report = REPORT + "\n" + fixture_line + "\n"
        result = intake.run_intake(report, {"fake": capturing_solver})
        self.assertTrue(result["ok"])
        self.assertNotIn(fixture_value, seen["prompt"])
        self.assertIn("REDACTED", seen["prompt"])

    def test_oversized_context_is_capped_and_disclosed(self):
        big = "x" * (intake.MAX_CONTEXT_FILE_CHARS + 5000)
        prompt = intake.build_solver_prompt(
            REPORT, contexts=[("big.log", big)])
        self.assertIn("truncated by codereview intake", prompt)
        result = intake.run_intake(REPORT, {"fake": ok_solver},
                                   contexts=[("big.log", big)])
        self.assertTrue(result["contexts"][0]["truncated"])


class RunIntakeTests(unittest.TestCase):
    def test_primary_is_first_successful_solver_in_order(self):
        result = intake.run_intake(
            REPORT, {"bad": failing_solver, "good": ok_solver})
        self.assertTrue(result["ok"])
        self.assertEqual(result["primary"], "good")
        by_name = {s["name"]: s for s in result["solutions"]}
        self.assertFalse(by_name["bad"]["ok"])
        self.assertIn("503", by_name["bad"]["error"])

    def test_all_solvers_failing_is_not_ok(self):
        result = intake.run_intake(REPORT, {"bad": failing_solver})
        self.assertFalse(result["ok"])
        self.assertIsNone(result["primary"])

    def test_no_solvers_is_not_ok(self):
        result = intake.run_intake(REPORT, {})
        self.assertFalse(result["ok"])

    def test_hung_solver_times_out_and_fast_solver_wins(self):
        import time as _time

        def slow_solver(prompt):
            _time.sleep(10)
            return PLAN

        started = _time.monotonic()
        result = intake.run_intake(
            REPORT, {"slow": slow_solver, "fast": ok_solver},
            timeout=1)
        elapsed = _time.monotonic() - started
        self.assertLess(elapsed, 5)
        self.assertTrue(result["ok"])
        self.assertEqual(result["primary"], "fast")
        by_name = {s["name"]: s for s in result["solutions"]}
        self.assertFalse(by_name["slow"]["ok"])
        self.assertIn("timed out", by_name["slow"]["error"])

    def test_write_intake_files(self):
        result = intake.run_intake(
            REPORT, {"alpha": ok_solver, "beta": ok_solver})
        with tempfile.TemporaryDirectory() as tmp:
            solution, manifest = intake.write_intake(
                result, tmp, report_name="issue.md")
            self.assertTrue(os.path.exists(solution))
            self.assertTrue(os.path.exists(
                os.path.join(tmp, "solution-beta.md")))
            with open(solution, encoding="utf-8") as fh:
                body = fh.read()
            self.assertIn("solver: alpha", body)
            self.assertIn("dedup the alert", body)
            with open(manifest, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["kind"], "intake")
            self.assertEqual(data["primary"], "alpha")
            self.assertEqual(data["report"]["name"], "issue.md")
            self.assertEqual(len(data["report"]["sha256"]), 64)
            self.assertNotIn("text", data["solvers"][0])


class SolverProviderTests(unittest.TestCase):
    def test_build_solvers_returns_text_mode_seats(self):
        solvers = providers.build_solvers(["gemini", "nvidia"])
        self.assertEqual(sorted(solvers), ["gemini", "nvidia"])
        for fn in solvers.values():
            self.assertTrue(callable(fn))

    def test_reviewer_build_is_unchanged(self):
        reviewers = providers.build_providers(["gemini", "nvidia"])
        self.assertEqual(sorted(reviewers), ["gemini", "nvidia"])

    def _capture_wire(self, build):
        """Run one built callable per seat against a fake transport
        and return the payloads it would have sent."""
        calls = []
        real = providers._post_json

        def fake_post(url, headers, payload):
            calls.append((url, payload))
            if "generativelanguage" in url:
                return {"candidates": [{"content": {"parts": [
                    {"text": "plan"}]}}]}
            return {"choices": [{"message": {"content": "plan"}}]}

        providers._post_json = fake_post
        old_env = dict(os.environ)
        os.environ["GEMINI_API_KEY"] = "test-key"
        os.environ["NVIDIA_API_KEY"] = "test-key"
        try:
            seats = build(["gemini", "nvidia"])
            for name in ("gemini", "nvidia"):
                self.assertEqual(seats[name]("prompt"), "plan")
        finally:
            providers._post_json = real
            os.environ.clear()
            os.environ.update(old_env)
        return {("gemini" if "generativelanguage" in url else "nvidia"):
                payload for url, payload in calls}

    def test_solver_wire_uses_solver_system_and_no_json_mode(self):
        payloads = self._capture_wire(providers.build_solvers)
        gem = payloads["gemini"]
        self.assertEqual(
            gem["systemInstruction"]["parts"][0]["text"],
            providers._SOLVER_SYSTEM)
        self.assertNotIn("responseMimeType", gem["generationConfig"])
        nvi = payloads["nvidia"]
        self.assertEqual(nvi["messages"][0]["content"],
                         providers._SOLVER_SYSTEM)

    def test_reviewer_wire_keeps_json_mode_and_reviewer_system(self):
        payloads = self._capture_wire(providers.build_providers)
        gem = payloads["gemini"]
        self.assertEqual(
            gem["systemInstruction"]["parts"][0]["text"],
            providers._SYSTEM)
        self.assertEqual(gem["generationConfig"]["responseMimeType"],
                         "application/json")
        nvi = payloads["nvidia"]
        self.assertEqual(nvi["messages"][0]["content"],
                         providers._SYSTEM)


if __name__ == "__main__":
    unittest.main()
