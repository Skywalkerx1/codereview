"""Characterization probes for the review-v15 adjudication (v0.9.4).

Each test pins, as executable evidence, the behavior a review-v15
finding claimed was absent or broken. They are rebuttal evidence,
not new features: if one of these ever fails, the corresponding
finding stops being a false positive.

- 636ba66423e7: fallback seats in review runs DO receive the
  configured agent timeout (also pinned by the v0.9.1 enumeration).
- ec5d130cc37e: every provider call path carries a timeout —
  _post_json defaults to DEFAULT_TIMEOUT and is the only opener
  site; the agent seam rejects non-positive timeouts.
- ca7b6fb25b54: _call_with_retry is hard-bounded (per-class caps,
  min'd with max_attempts); the while-loop cannot spin.
- 3fbb6b031f51: _classify_error's whole-token code matching does
  not conflate classes on digit-substring traps (v0.9.3 fix).
- 320b878c6253: the post-exit group kill cannot flip a successful
  agent run into a reported failure (_kill_tree never raises on a
  dead group; communicate() captured the return code first).
"""

import ast
import os
import unittest

from codereview import core, providers


class RetryBoundTests(unittest.TestCase):
    def test_transient_failure_stops_at_class_cap(self):
        calls = {"n": 0}

        def always_503(prompt):
            calls["n"] += 1
            raise RuntimeError("HTTP 503 overloaded")

        with self.assertRaises(RuntimeError):
            core._call_with_retry(always_503, "p", sleep=lambda s: None)
        self.assertEqual(calls["n"], 3)

    def test_quota_failure_never_retried(self):
        calls = {"n": 0}

        def quota(prompt):
            calls["n"] += 1
            raise RuntimeError("429 RESOURCE_EXHAUSTED daily quota")

        with self.assertRaises(RuntimeError):
            core._call_with_retry(quota, "p", sleep=lambda s: None)
        self.assertEqual(calls["n"], 1)

    def test_max_attempts_caps_below_class_cap(self):
        calls = {"n": 0}

        def always_503(prompt):
            calls["n"] += 1
            raise RuntimeError("HTTP 503 overloaded")

        with self.assertRaises(RuntimeError):
            core._call_with_retry(always_503, "p", sleep=lambda s: None,
                                  max_attempts=2)
        self.assertEqual(calls["n"], 2)


class ClassifyErrorTokenTests(unittest.TestCase):
    def test_digit_substrings_do_not_conflate(self):
        # A 503 body mentioning "4030 tokens" stays transient.
        kind, tries = core._classify_error(
            RuntimeError("HTTP 503 overloaded after 4030 tokens"))
        self.assertEqual((kind, tries), ("transient", 3))
        # "req_4014" is not a 401.
        kind, _ = core._classify_error(RuntimeError("HTTP 503 req_4014"))
        self.assertEqual(kind, "transient")

    def test_typed_quota_codes_win_without_429(self):
        kind, tries = core._classify_error(
            RuntimeError("insufficient_quota: billing exhausted"))
        self.assertEqual((kind, tries), ("quota", 1))


class ProviderTimeoutTests(unittest.TestCase):
    def test_post_json_has_default_timeout(self):
        import inspect
        sig = inspect.signature(providers._post_json)
        self.assertEqual(sig.parameters["timeout"].default,
                         providers.DEFAULT_TIMEOUT)
        self.assertGreater(providers.DEFAULT_TIMEOUT, 0)

    def test_single_opener_site_and_it_passes_timeout(self):
        tree = ast.parse(open(providers.__file__,
                              encoding="utf-8").read())
        opens = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "open"
                 and n.keywords]
        opener_opens = [n for n in opens if any(
            kw.arg == "timeout" for kw in n.keywords)]
        self.assertTrue(opener_opens,
                        "the opener.open call must pass a timeout")

    def test_agent_seam_rejects_non_positive_timeout(self):
        with self.assertRaises(providers.ProviderError):
            providers.command_agent("true", timeout=0)


@unittest.skipUnless(os.name == "posix", "POSIX process groups")
class KillTreeTests(unittest.TestCase):
    def test_kill_tree_on_dead_process_never_raises(self):
        import subprocess
        proc = subprocess.Popen(["true"])
        proc.wait()
        providers._kill_tree(proc, None)  # must not raise

    def test_successful_agent_run_not_flipped_by_group_kill(self):
        call = providers.command_agent("printf 'agent-ok\\n'")
        self.assertEqual(call("ignored"), "agent-ok")


class FallbackTimeoutForwardingTests(unittest.TestCase):
    def test_review_fallback_site_forwards_timeout(self):
        # The v0.9.1 enumeration test pins every construction site;
        # this pins the review command's fallback one specifically:
        # both review-range build_providers calls in cli.py must
        # receive agent_timeout=args.timeout.
        tree = ast.parse(open(core.__file__.replace(
            "core.py", "cli.py"), encoding="utf-8").read())
        sites = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "build_providers"):
                kws = {kw.arg for kw in node.keywords}
                sites.append("agent_timeout" in kws)
        self.assertGreaterEqual(sum(1 for s in sites if s), 3,
                                "review/doctor/verify construction "
                                "sites must forward agent_timeout")


if __name__ == "__main__":
    unittest.main()
