"""Epic K2 seat-state supervision tests.

Fixture-driven throughout: the classification tests read real
or verbatim-vendor transcripts from tests/fixtures/seatstate/
(provenance per fixture, recorded in seatstate.py's pattern
table comments); the supervised-wait tests run stub executables
NAMED like the real CLIs in a temp dir (argv[0]'s basename is
what keys the pattern table) — no test depends on a real CLI,
an account, or the network.
"""

import json
import os
import stat
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core, discovery, providers, seatstate  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures",
                        "seatstate")

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


def _fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


def pass_provider(prompt):
    return json.dumps({"summary": "looks fine", "findings": []})


def quota_provider(prompt):
    raise RuntimeError("429 RESOURCE_EXHAUSTED: daily quota gone")


def _write_cli(tmp, name, body):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!" + sys.executable + "\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class PatternTableTests(unittest.TestCase):
    """The U6 matrix, as data: each fixture is the evidence a
    pattern ships on (see seatstate.py for provenance)."""

    def test_codex_logged_out_capture_is_auth(self):
        # VERIFIED-LIVE capture: the real codex binary on the
        # build VM, logged out — full stderr, untrimmed.
        hit = seatstate.match_failure(
            "codex", _fixture("codex-loggedout.stderr.txt"))
        self.assertIsNotNone(hit)
        self.assertEqual(hit["class"], "auth")
        self.assertEqual(hit["pattern"], "codex-auth-401")

    def test_codex_quota_message_from_vendor_source(self):
        # VERIFIED-SOURCE: the vendor's own UsageLimitReached
        # string (curly apostrophe and all).
        hit = seatstate.match_failure(
            "codex", _fixture("codex-quota.txt"))
        self.assertEqual(hit["class"], "quota")
        self.assertEqual(hit["pattern"], "codex-quota-usage-limit")

    def test_claude_quota_and_auth_from_official_error_reference(self):
        hit = seatstate.match_failure(
            "claude", _fixture("claude-quota.txt"))
        self.assertEqual(hit["class"], "quota")
        self.assertEqual(hit["pattern"], "claude-quota-limit")
        hit = seatstate.match_failure(
            "claude", _fixture("claude-auth.txt"))
        self.assertEqual(hit["class"], "auth")
        self.assertEqual(hit["pattern"],
                         "claude-auth-not-logged-in")

    def test_gemini_quota_from_official_faq(self):
        hit = seatstate.match_failure(
            "gemini", _fixture("gemini-quota.txt"))
        self.assertEqual(hit["class"], "quota")
        self.assertEqual(hit["pattern"],
                         "gemini-quota-resource-exhausted")

    def test_gemini_has_no_auth_pattern_until_verified(self):
        # Gemini's unauthenticated-headless failure text is
        # UNVERIFIED in the official docs: no pattern ships, so
        # even Claude's verbatim auth text classifies nothing
        # under the gemini key.
        self.assertIsNone(seatstate.match_failure(
            "gemini", _fixture("claude-auth.txt")))

    def test_no_match_for_unrelated_text_or_unknown_cli(self):
        text = _fixture("unrelated.txt")
        for key in ("claude", "codex", "gemini", None, "echo"):
            self.assertIsNone(seatstate.match_failure(key, text),
                              key)

    def test_cli_key_for_argv(self):
        self.assertEqual(
            seatstate.cli_key_for_argv(["/usr/local/bin/codex",
                                        "exec"]), "codex")
        self.assertEqual(
            seatstate.cli_key_for_argv(["claude", "-p"]), "claude")
        self.assertIsNone(
            seatstate.cli_key_for_argv(["python3", "stub.py"]))
        self.assertIsNone(seatstate.cli_key_for_argv([]))

    def test_classify_exit_scans_stderr_then_stdout(self):
        # Claude prints in-run failures as the result on stdout.
        state, cls, ev = seatstate.classify_exit(
            "claude", 1, _fixture("claude-auth.txt"), "")
        self.assertEqual((state, cls), ("blocked", "auth"))
        self.assertEqual(ev["source"], "stdout")
        self.assertEqual(ev["exit_code"], 1)
        state, cls, ev = seatstate.classify_exit(
            "codex", 3, "", "boom: something broke")
        self.assertEqual((state, cls), ("failed", "error"))
        self.assertEqual(ev, {"exit_code": 3})


class SupervisedWaitTests(unittest.TestCase):
    """providers.command_agent under supervision, driven by
    stub executables named like the real CLIs."""

    def _agent(self, tmp, name, body, **kw):
        path = _write_cli(tmp, name, body)
        return providers.command_agent(path, **kw)

    def test_auth_failure_exit_is_blocked_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = (
                "import sys\n"
                f"sys.stderr.write(open("
                f"{os.path.join(FIXTURES, 'codex-loggedout.stderr.txt')!r}"
                ").read())\n"
                "sys.exit(1)\n")
            fn = self._agent(tmp, "codex", body, timeout=30)
            with self.assertRaises(providers.ProviderError) as cm:
                fn("brief")
        self.assertTrue(str(cm.exception).startswith(
            "agent command exited 1"))
        facts = cm.exception.seat_facts
        self.assertEqual(facts["state"], "blocked")
        self.assertEqual(facts["class"], "auth")
        self.assertEqual(facts["evidence"]["pattern"],
                         "codex-auth-401")
        self.assertEqual(facts["evidence"]["source"], "stderr")

    def test_quota_pattern_terminates_a_stuck_seat_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = (
                "import sys, time\n"
                f"sys.stderr.write(open("
                f"{os.path.join(FIXTURES, 'codex-quota.txt')!r}"
                ").read())\n"
                "sys.stderr.flush()\n"
                "time.sleep(30)\n")
            fn = self._agent(tmp, "codex", body, timeout=30,
                             stall_after=60.0, block_grace=0.3)
            started = time.monotonic()
            with self.assertRaises(providers.ProviderError) as cm:
                fn("brief")
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 15)
        self.assertIn("blocked (quota)", str(cm.exception))
        facts = cm.exception.seat_facts
        self.assertEqual(facts["state"], "blocked")
        self.assertEqual(facts["class"], "quota")
        self.assertTrue(facts["evidence"]["early_terminated"])

    def test_silent_seat_times_out_blocked_stalled(self):
        with tempfile.TemporaryDirectory() as tmp:
            fn = self._agent(tmp, "codex",
                             "import time\ntime.sleep(30)\n",
                             timeout=1.0, stall_after=0.3,
                             block_grace=30.0)
            log = seatstate.SeatStateLog()
            token = seatstate.CURRENT.set(log)
            try:
                with self.assertRaises(
                        providers.ProviderError) as cm:
                    fn("brief")
            finally:
                seatstate.CURRENT.reset(token)
        self.assertEqual(str(cm.exception),
                         "agent command timed out after 1.0s")
        facts = cm.exception.seat_facts
        self.assertEqual(facts["state"], "blocked")
        self.assertEqual(facts["class"], "stalled")
        episodes = [t for t in log.summary()["transitions"]
                    if t["state"] == "blocked"
                    and t["class"] == "stalled"]
        self.assertTrue(episodes)
        self.assertTrue(episodes[0]["evidence"]["transient"])

    def test_active_seat_times_out_as_timed_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = ("import sys, time\n"
                    "for i in range(400):\n"
                    "    sys.stderr.write('working %d\\n' % i)\n"
                    "    sys.stderr.flush()\n"
                    "    time.sleep(0.05)\n")
            fn = self._agent(tmp, "codex", body, timeout=0.8,
                             stall_after=5.0, block_grace=5.0)
            with self.assertRaises(providers.ProviderError) as cm:
                fn("brief")
        self.assertEqual(str(cm.exception),
                         "agent command timed out after 0.8s")
        facts = cm.exception.seat_facts
        self.assertEqual(facts["state"], "timed-out")
        self.assertIsNone(facts["class"])

    def test_stall_episode_then_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = ("import sys, time\n"
                    "time.sleep(0.7)\n"
                    "sys.stdout.write('{\"summary\": \"ok\", "
                    "\"findings\": []}')\n")
            fn = self._agent(tmp, "claude", body, timeout=10,
                             stall_after=0.25, block_grace=5.0)
            log = seatstate.SeatStateLog()
            token = seatstate.CURRENT.set(log)
            try:
                text = fn("brief")
            finally:
                seatstate.CURRENT.reset(token)
        self.assertIn('"summary": "ok"', text)
        states = [(t["state"], t["class"])
                  for t in log.summary()["transitions"]]
        self.assertIn(("blocked", "stalled"), states)
        # Output resuming returns the seat to working.
        self.assertGreater(states.index(("working", None)),
                           states.index(("blocked", "stalled")))

    def test_plain_failure_is_failed_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            fn = self._agent(
                tmp, "codex",
                "import sys\n"
                "sys.stderr.write('boom: something broke')\n"
                "sys.exit(3)\n", timeout=30)
            with self.assertRaises(providers.ProviderError) as cm:
                fn("brief")
        self.assertTrue(str(cm.exception).startswith(
            "agent command exited 3"))
        facts = cm.exception.seat_facts
        self.assertEqual(facts["state"], "failed")
        self.assertEqual(facts["class"], "error")
        self.assertEqual(facts["evidence"], {"exit_code": 3})

    def test_no_output_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fn = self._agent(tmp, "codex", "pass\n", timeout=30)
            with self.assertRaises(providers.ProviderError) as cm:
                fn("brief")
        self.assertEqual(str(cm.exception),
                         "agent command produced no output")
        self.assertEqual(cm.exception.seat_facts["state"],
                         "failed")


class RunReviewSeatStateTests(unittest.TestCase):

    def _rec(self, report, provider):
        return next(r for r in report["reviewer_reports"]
                    if r["provider"] == provider)

    def test_blocked_seat_degrades_and_record_agrees_with_live(
            self):
        events = []
        report = core.run_review(
            CLEAN, {"a": pass_provider, "b": quota_provider},
            progress=events.append)
        self.assertEqual(report["gate"], "inconclusive")
        self.assertTrue(report["degraded"])
        rec = self._rec(report, "b")
        self.assertEqual(rec["status"], "error")
        self.assertEqual(rec["seat_state"]["state"], "blocked")
        self.assertEqual(rec["seat_state"]["class"], "quota")
        # §4.3 agreement: the live stream and the record are the
        # same transitions, in the same order.
        live = [(e["state"], e["class"]) for e in events
                if e["seat"] == "b"]
        recorded = [(t["state"], t["class"])
                    for t in rec["seat_state"]["transitions"]]
        self.assertEqual(live, recorded)
        self.assertEqual(recorded[0][0], "pending")
        self.assertEqual(recorded[-1], ("blocked", "quota"))
        ok_rec = self._rec(report, "a")
        self.assertEqual(ok_rec["seat_state"]["state"], "done")

    def test_fallback_serves_and_primary_state_is_kept(self):
        fallbacks = {"correctness": ("aux", pass_provider),
                     "operations": ("aux", pass_provider)}
        report = core.run_review(
            CLEAN, {"main": quota_provider, "aux": pass_provider},
            fallbacks=fallbacks)
        rec = next(r for r in report["reviewer_reports"]
                   if r.get("fallback_for") == "main")
        self.assertEqual(rec["provider"], "aux")
        self.assertEqual(rec["seat_state"]["state"], "done")
        self.assertEqual(
            rec["seat_state_primary"]["state"], "blocked")
        self.assertEqual(
            rec["seat_state_primary"]["class"], "quota")

    def test_state_never_changes_the_verdict(self):
        clean = core.run_review(CLEAN, {"a": pass_provider})
        with_blocked = core.run_review(
            CLEAN, {"a": pass_provider, "b": quota_provider})
        self.assertEqual(clean["findings"],
                         with_blocked["findings"])
        self.assertEqual(clean["gate"], "pass")
        # The only difference the blocked seat may make is the
        # existing degraded -> INCONCLUSIVE discipline.
        self.assertEqual(with_blocked["gate"], "inconclusive")

    def test_agent_seat_end_to_end_blocked_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = (
                "import sys\n"
                f"sys.stderr.write(open("
                f"{os.path.join(FIXTURES, 'codex-loggedout.stderr.txt')!r}"
                ").read())\n"
                "sys.exit(1)\n")
            path = _write_cli(tmp, "codex", body)
            agent_fn = providers.command_agent(path, timeout=30)
            report = core.run_review(
                CLEAN, {"api": pass_provider, "cx": agent_fn})
        rec = self._rec(report, "cx")
        self.assertEqual(rec["status"], "error")
        self.assertEqual(rec["seat_state"]["state"], "blocked")
        self.assertEqual(rec["seat_state"]["class"], "auth")
        self.assertEqual(
            rec["seat_state"]["evidence"]["pattern"],
            "codex-auth-401")
        self.assertEqual(report["gate"], "inconclusive")

    def test_verification_job_marks_carry_seat_state(self):
        previous = {"gate": "blocked", "findings": [{
            "id": "abc123", "severity": "major",
            "category": "reliability", "file": "app/alerts.py",
            "line": 6, "title": "Alert has no dedup",
            "evidence": "", "recommendation": "",
            "confidence": 0.8, "sources": ["a"],
            "consensus": False}]}

        def fixed(prompt):
            return json.dumps({
                "resolutions": [{
                    "finding_id": "abc123", "status": "fixed",
                    "evidence": "return a + b and return a - b "
                                "are the only helpers left in "
                                "app/util.py and the sendmail "
                                "alert is removed"}],
                "new_findings": []})

        report = core.run_verification(
            CLEAN, {"a": fixed, "b": quota_provider},
            previous, "fixed it")
        rec = self._rec(report, "b")
        self.assertTrue(rec["jobs"])
        for mark in rec["jobs"]:
            self.assertEqual(mark["seat_state"]["state"],
                             "blocked")
            self.assertEqual(mark["seat_state"]["class"],
                             "quota")

    def test_report_entry_presence_copies_seat_state(self):
        summary = {"state": "blocked", "class": "quota",
                   "evidence": {"error_class": "quota"},
                   "transitions": []}
        entry = core.reviewer_report_entry({
            "provider": "x", "lens": "correctness",
            "status": "error", "attempts": 1, "error": "e",
            "error_classes": ["quota"], "duration_ms": 5,
            "prompt_chars": 10, "seat_state": summary})
        self.assertEqual(entry["seat_state"], summary)
        legacy = core.reviewer_report_entry({
            "provider": "x", "lens": "correctness",
            "status": "ok", "attempts": 1})
        self.assertNotIn("seat_state", legacy)


class DiscoveryWiringTests(unittest.TestCase):
    """Deliverable 3: every CLI the U6 matrix verified is
    offerable; the commands carry the verified forms."""

    def test_all_known_clis_are_offerable(self):
        for entry in discovery.KNOWN_CLIS:
            self.assertTrue(entry["command"], entry["name"])
            spec = discovery.seat_spec(entry)
            self.assertTrue(spec.startswith(
                f"agent:{entry['name']}:"), spec)

    def test_codex_command_is_the_verified_exec_form(self):
        entry = next(e for e in discovery.KNOWN_CLIS
                     if e["name"] == "codex")
        self.assertTrue(entry["command"].startswith(
            "codex exec"))
        self.assertIn("-s read-only", entry["command"])
        self.assertIn("--skip-git-repo-check", entry["command"])
        self.assertTrue(entry["command"].endswith(" -"))

    def test_gemini_command_is_the_docs_verified_form(self):
        entry = next(e for e in discovery.KNOWN_CLIS
                     if e["name"] == "gemini")
        self.assertTrue(entry["command"].startswith(
            'gemini -p "'))


if __name__ == "__main__":
    unittest.main()
