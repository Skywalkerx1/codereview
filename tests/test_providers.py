"""Unit tests for codereview provider seats — API presets and the
agent seats (any local agent CLI as a reviewer/solver). No network:
agent seats are exercised with shell utilities."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core, providers  # noqa: E402

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

PASS_JSON = ('{"verdict": "pass", "summary": "agent seat ok", '
             '"findings": []}')


class AgentSeatTests(unittest.TestCase):
    def test_echo_seat_roundtrips_the_prompt(self):
        seats = providers.build_providers(["agent:echo:cat"])
        self.assertEqual(list(seats), ["echo"])
        self.assertEqual(seats["echo"]("hello panel"), "hello panel")

    def test_prompt_is_available_as_a_file(self):
        seats = providers.build_providers(
            ["agent:viacat:sh -c 'cat \"$CODEREVIEW_PROMPT\"'"])
        self.assertEqual(seats["viacat"]("file contract"), "file contract")

    def test_nonzero_exit_is_a_provider_error(self):
        seats = providers.build_providers(["agent:bad:sh -c 'exit 3'"])
        with self.assertRaises(providers.ProviderError):
            seats["bad"]("anything")

    def test_missing_executable_is_a_provider_error(self):
        seats = providers.build_providers(
            ["agent:gone:no-such-binary-codereview-test"])
        with self.assertRaises(providers.ProviderError):
            seats["gone"]("anything")

    def test_empty_output_is_a_provider_error(self):
        seats = providers.build_providers(["agent:mute:true"])
        with self.assertRaises(providers.ProviderError):
            seats["mute"]("anything")

    def test_timeout_is_a_provider_error(self):
        fn = providers.command_agent("sleep 5", timeout=1)
        with self.assertRaises(providers.ProviderError):
            fn("anything")

    def test_bad_specs_are_rejected(self):
        for spec in ("agent:", "agent::cat", "agent:echo:"):
            with self.assertRaises(providers.ProviderError):
                providers.build_provider(spec)

    def test_agent_seat_can_review_end_to_end(self):
        cmd = "printf '%s' '" + PASS_JSON.replace("'", "") + "'"
        # PASS_JSON contains no single quotes; printf emits it verbatim.
        seats = providers.build_providers(["agent:bot:" + cmd])
        report = core.run_review(CLEAN, seats)
        self.assertEqual(report["gate"], "pass")
        sources = {f.get("source") for f in report.get("findings") or []}
        self.assertEqual(sources, set())

    def test_agent_seat_alongside_api_seats(self):
        seats = providers.build_providers(
            ["gemini", "agent:echo:cat", "agent:grok:cat"])
        self.assertEqual(sorted(seats), ["echo", "gemini", "grok"])
        self.assertEqual(seats["grok"]("grok seat"), "grok seat")

    def test_solver_seat_via_build_solvers(self):
        solvers = providers.build_solvers(["agent:echo:cat"])
        self.assertEqual(solvers["echo"]("plan please"), "plan please")

    def test_same_named_agent_seats_stay_distinct(self):
        # Regression (review-v7): two agent specs sharing a name run
        # DIFFERENT commands — they must be two seats, not one pool
        # where the second command only fires as a fallback.
        seats = providers.build_providers(
            ["agent:bot:printf ALPHA", "agent:bot:printf BETA"])
        self.assertEqual(sorted(seats), ["bot", "bot-2"])
        self.assertEqual(seats["bot"]("x"), "ALPHA")
        self.assertEqual(seats["bot-2"]("x"), "BETA")
        solvers = providers.build_solvers(
            ["agent:bot:printf ONE", "agent:bot:printf TWO"])
        self.assertEqual(sorted(solvers), ["bot", "bot-2"])

    def test_shell_metacharacters_are_literal(self):
        # No shell: ';' inside the command is data, never a second
        # command. If a shell ever ran this, the output would differ.
        seats = providers.build_providers(
            ["agent:lit:printf '%s' 'a;b'"])
        self.assertEqual(seats["lit"]("x"), "a;b")

    def test_unbalanced_quotes_are_a_provider_error(self):
        seats = providers.build_providers(["agent:bad:printf 'oops"])
        with self.assertRaises(providers.ProviderError):
            seats["bad"]("x")


if __name__ == "__main__":
    unittest.main()
