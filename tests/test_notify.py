"""Epic L4 attention-notification tests.

The contract under test (Playbook v2 §11, Epic L row L4):

  * on a seat entering a blocked state (K2 classes) and on
    gate verdict, the operator-configured local command runs
    exactly once per event, argv = configured argv + event
    name + one-line summary;
  * the command is configured in the USER SETUP ([notify] in
    the saved config) — the project policy cannot set one;
  * unset means zero behaviour change: no invocations, no
    `notifications` section, prompts and verdict untouched;
  * a failing or hanging notifier is bounded, recorded, and
    never changes the verdict.

Fixtures are stub runners / stub scripts throughout — no
test depends on a real notification service, an account, or
the network.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, core, notify, policy, userconfig  # noqa: E402

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


def pass_provider(prompt):
    return json.dumps({"summary": "looks fine", "findings": []})


def quota_provider(prompt):
    raise RuntimeError("429 RESOURCE_EXHAUSTED: daily quota gone")


class RecordingRunner:
    """A notify runner that records argv and answers with a
    scripted exit code (or raises a scripted exception)."""

    def __init__(self, exit_code=0, exc=None):
        self.calls = []
        self.exit_code = exit_code
        self.exc = exc

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        if self.exc is not None:
            raise self.exc
        return self.exit_code


def _strip_volatile(report):
    """The fields that legitimately differ between two runs
    of the same review (timestamps, durations) — everything
    else about two reports on the same inputs must agree."""
    out = dict(report)
    out.pop("created_at", None)
    out.pop("notifications", None)
    reps = []
    for rec in report["reviewer_reports"]:
        rec = dict(rec)
        rec.pop("duration_ms", None)
        reps.append(rec)
    out["reviewer_reports"] = reps
    return out


class NotifierTests(unittest.TestCase):

    def test_fire_appends_event_and_summary_to_argv(self):
        runner = RecordingRunner()
        n = notify.Notifier(["my-notify", "--flag"], runner=runner)
        outcome = n.fire("verdict", "gate pass: 0 finding(s)")
        self.assertEqual(
            runner.calls,
            [["my-notify", "--flag", "verdict",
              "gate pass: 0 finding(s)"]])
        self.assertEqual(outcome["event"], "verdict")
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["exit_code"], 0)
        self.assertEqual(n.outcomes, [outcome])

    def test_nonzero_exit_is_recorded_failed_never_raised(self):
        runner = RecordingRunner(exit_code=3)
        n = notify.Notifier(["nope"], runner=runner)
        outcome = n.fire("verdict", "gate blocked: 1 finding(s)")
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["exit_code"], 3)

    def test_timeout_is_recorded_timeout(self):
        runner = RecordingRunner(
            exc=subprocess.TimeoutExpired(["slow"], 5.0))
        n = notify.Notifier(["slow"], runner=runner)
        outcome = n.fire("verdict", "gate pass: 0 finding(s)")
        self.assertEqual(outcome["status"], "timeout")
        self.assertIsNone(outcome["exit_code"])

    def test_unstartable_command_is_recorded_error(self):
        runner = RecordingRunner(
            exc=FileNotFoundError("no such file"))
        n = notify.Notifier(["missing"], runner=runner)
        outcome = n.fire("seat_blocked", "seat a blocked:quota")
        self.assertEqual(outcome["status"], "error")
        self.assertIn("no such file", outcome["detail"])

    def test_seat_blocked_dedupes_per_seat_and_class(self):
        runner = RecordingRunner()
        n = notify.Notifier(["bell"], runner=runner)
        self.assertIsNotNone(n.seat_blocked("cx", "quota"))
        # Same seat, same class: one fact, one ping.
        self.assertIsNone(n.seat_blocked("cx", "quota"))
        # A different class or a different seat is a new fact.
        self.assertIsNotNone(n.seat_blocked("cx", "auth"))
        self.assertIsNotNone(n.seat_blocked("gm", "quota"))
        self.assertEqual(
            [c[1:] for c in runner.calls],
            [["seat_blocked", "seat cx blocked:quota"],
             ["seat_blocked", "seat cx blocked:auth"],
             ["seat_blocked", "seat gm blocked:quota"]])

    def test_verdict_fires_once(self):
        runner = RecordingRunner()
        n = notify.Notifier(["bell"], runner=runner)
        self.assertIsNotNone(n.verdict("gate pass: 0 finding(s)"))
        self.assertIsNone(n.verdict("gate pass: 0 finding(s)"))
        self.assertEqual(len(runner.calls), 1)

    def test_summary_is_collapsed_to_one_line(self):
        runner = RecordingRunner()
        n = notify.Notifier(["bell"], runner=runner)
        n.fire("verdict", "gate pass:\n  0 finding(s)\r\n")
        self.assertEqual(runner.calls[0][2],
                         "gate pass: 0 finding(s)")

    def test_notifier_for_unset_command_is_none(self):
        self.assertIsNone(notify.notifier_for(None))
        self.assertIsNone(notify.notifier_for([]))
        self.assertIsInstance(notify.notifier_for(["bell"]),
                              notify.Notifier)


class RealRunnerTests(unittest.TestCase):
    """The default runner against real subprocesses: a stub
    script on disk, the way an operator's command really
    runs."""

    def _write_stub(self, tmp, body):
        path = os.path.join(tmp, "notify_stub.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path

    def test_real_command_receives_event_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "calls.jsonl")
            stub = self._write_stub(
                tmp,
                "import json, sys\n"
                f"with open({log!r}, 'a', encoding='utf-8') as fh:\n"
                "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n")
            n = notify.Notifier([sys.executable, stub])
            outcome = n.verdict("gate pass: 0 finding(s)")
            self.assertEqual(outcome["status"], "ok")
            with open(log, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
            self.assertEqual(
                [json.loads(line) for line in lines],
                [["verdict", "gate pass: 0 finding(s)"]])

    def test_hanging_command_is_bounded_by_the_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = self._write_stub(
                tmp, "import time\ntime.sleep(30)\n")
            n = notify.Notifier([sys.executable, stub],
                                timeout=0.3)
            started = time.monotonic()
            outcome = n.verdict("gate pass: 0 finding(s)")
            elapsed = time.monotonic() - started
            self.assertEqual(outcome["status"], "timeout")
            self.assertLess(elapsed, 10)

    def test_missing_executable_is_an_error_outcome(self):
        n = notify.Notifier(["/nonexistent/notify-cmd-xyz"])
        outcome = n.verdict("gate pass: 0 finding(s)")
        self.assertEqual(outcome["status"], "error")
        self.assertIsNone(outcome["exit_code"])


class UserConfigNotifyTests(unittest.TestCase):
    """The [notify] table lives in the user setup and follows
    the [hosting] table's rules: round-trips when set, absent
    (byte-identical file) when not, loud ValueError when
    malformed."""

    def _env(self, tmp):
        return {"HOME": tmp, "CODEREVIEW_CONFIG":
                os.path.join(tmp, "config.toml")}

    def test_notify_table_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, self._env(tmp),
                                 clear=True):
                userconfig.save_user_config(
                    ["deepseek"], {},
                    notify={"command": ["my-notify", "--loud"]})
                loaded = userconfig.load_user_config()
                self.assertEqual(
                    loaded["notify"],
                    {"command": ["my-notify", "--loud"]})
                self.assertEqual(
                    userconfig.default_notify_command(),
                    ["my-notify", "--loud"])

    def test_no_notify_table_means_no_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, self._env(tmp),
                                 clear=True):
                userconfig.save_user_config(["deepseek"], {})
                loaded = userconfig.load_user_config()
                self.assertEqual(loaded["notify"],
                                 {"command": []})
                self.assertEqual(
                    userconfig.default_notify_command(), [])

    def test_save_without_notify_is_byte_identical(self):
        # The pre-L4 writer's exact bytes for the same setup:
        # adding the notify parameter must not move a byte for
        # setups that do not use it.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, self._env(tmp),
                                 clear=True):
                path = userconfig.save_user_config(
                    ["deepseek"], {"tech-lead": "deepseek"})
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
        self.assertEqual(
            text,
            "# CodeReview user setup — created by "
            "`codereview setup`.\n"
            "# Provider specs and role assignments only: keys "
            "live in\n"
            "# the environment variables the specs name, never "
            "here.\n"
            'providers = ["deepseek"]\n'
            "\n"
            "[roles]\n"
            'tech-lead = "deepseek"\n')

    def test_malformed_notify_is_a_loud_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            with mock.patch.dict(os.environ, env, clear=True):
                path = env["CODEREVIEW_CONFIG"]
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write('providers = []\n\n[notify]\n'
                             'command = "my-notify"\n')
                with self.assertRaises(ValueError) as cm:
                    userconfig.load_user_config()
                self.assertIn("notify.command", str(cm.exception))
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write('providers = []\nnotify = 3\n')
                with self.assertRaises(ValueError) as cm:
                    userconfig.load_user_config()
                self.assertIn("'notify' must be a table",
                              str(cm.exception))


class PolicyCannotSetNotifyTests(unittest.TestCase):

    def test_project_policy_rejects_a_notify_table(self):
        # Notifications are operator preference, not project
        # contract: the policy schema has no notify table, so
        # a project that tries to set one is refused loudly
        # rather than obeyed.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".codereview.toml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('[notify]\ncommand = ["evil"]\n')
            with self.assertRaises(policy.PolicyError) as cm:
                policy.load_policy(path)
            self.assertIn("notify", str(cm.exception))


class RunReviewNotifyTests(unittest.TestCase):

    def _notifier(self, runner=None, **kw):
        return notify.Notifier(["notify-stub"],
                               runner=runner or RecordingRunner(),
                               **kw)

    def test_blocked_seat_and_verdict_each_fire_once(self):
        runner = RecordingRunner()
        events = []
        report = core.run_review(
            CLEAN, {"a": pass_provider, "b": quota_provider},
            progress=events.append, notify=self._notifier(runner))
        self.assertEqual(report["gate"], "inconclusive")
        blocked = [c for c in runner.calls if c[1] == "seat_blocked"]
        verdicts = [c for c in runner.calls if c[1] == "verdict"]
        # Seat b may serve several jobs — the (seat, class)
        # dedupe keeps it to exactly one invocation.
        self.assertEqual(
            blocked,
            [["notify-stub", "seat_blocked",
              "seat b blocked:quota"]])
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0][:2], ["notify-stub", "verdict"])
        self.assertTrue(
            verdicts[0][2].startswith("gate inconclusive"),
            verdicts[0][2])
        # Both outcomes are on the record, in firing order.
        notes = report["notifications"]
        self.assertEqual([n["event"] for n in notes],
                         ["seat_blocked", "verdict"])
        self.assertTrue(all(n["status"] == "ok" for n in notes))
        # The caller's own progress sink still saw the stream.
        self.assertTrue(any(e.get("seat") == "b"
                            and e.get("state") == "blocked"
                            for e in events))

    def test_notifications_fire_without_a_progress_sink(self):
        runner = RecordingRunner()
        report = core.run_review(
            CLEAN, {"a": pass_provider, "b": quota_provider},
            notify=self._notifier(runner))
        self.assertEqual(
            [c[1] for c in runner.calls],
            ["seat_blocked", "verdict"])
        self.assertIn("notifications", report)

    def test_verdict_only_for_a_clean_panel(self):
        runner = RecordingRunner()
        report = core.run_review(
            CLEAN, {"a": pass_provider},
            notify=self._notifier(runner))
        self.assertEqual(report["gate"], "pass")
        self.assertEqual(
            runner.calls,
            [["notify-stub", "verdict",
              "gate pass: 0 finding(s)"]])
        self.assertEqual(len(report["notifications"]), 1)

    def test_unset_notifier_leaves_no_trace(self):
        control = core.run_review(
            CLEAN, {"a": pass_provider, "b": quota_provider})
        self.assertNotIn("notifications", control)

    def test_notifier_never_changes_the_outcome(self):
        # Configured vs unconfigured on identical inputs: the
        # gate, findings, and reviewer reports agree field for
        # field (minus volatile timing); the ONLY record
        # difference is the added `notifications` section.
        control = core.run_review(
            CLEAN, {"a": pass_provider, "b": quota_provider})
        runner = RecordingRunner()
        wired = core.run_review(
            CLEAN, {"a": pass_provider, "b": quota_provider},
            notify=self._notifier(runner))
        self.assertEqual(_strip_volatile(control),
                         _strip_volatile(wired))
        self.assertEqual(
            set(wired) - set(control), {"notifications"})

    def test_prompts_are_identical_with_and_without_notify(self):
        seen = []

        def recording(prompt):
            seen.append(prompt)
            return pass_provider(prompt)

        core.run_review(CLEAN, {"a": recording})
        plain = sorted(seen)
        seen.clear()
        core.run_review(CLEAN, {"a": recording},
                        notify=self._notifier())
        self.assertEqual(plain, sorted(seen))

    def test_failing_notifier_is_recorded_verdict_unaffected(self):
        runner = RecordingRunner(exit_code=3)
        wired = core.run_review(
            CLEAN, {"a": pass_provider, "b": quota_provider},
            notify=self._notifier(runner))
        control = core.run_review(
            CLEAN, {"a": pass_provider, "b": quota_provider})
        self.assertEqual(wired["gate"], control["gate"])
        self.assertEqual(wired["findings"], control["findings"])
        self.assertTrue(wired["notifications"])
        self.assertTrue(all(n["status"] == "failed"
                            for n in wired["notifications"]))

    def test_hanging_notifier_is_bounded_verdict_unaffected(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = os.path.join(tmp, "hang.py")
            with open(stub, "w", encoding="utf-8") as fh:
                fh.write("import time\ntime.sleep(30)\n")
            n = notify.Notifier([sys.executable, stub],
                                timeout=0.3)
            started = time.monotonic()
            wired = core.run_review(
                CLEAN, {"a": pass_provider, "b": quota_provider},
                notify=n)
            elapsed = time.monotonic() - started
        self.assertEqual(wired["gate"], "inconclusive")
        self.assertLess(elapsed, 15)
        self.assertTrue(wired["notifications"])
        self.assertTrue(all(nt["status"] == "timeout"
                            for nt in wired["notifications"]))


class RunVerificationNotifyTests(unittest.TestCase):

    PREVIOUS = {"gate": "blocked", "findings": [{
        "id": "abc123", "severity": "major",
        "category": "reliability", "file": "app/alerts.py",
        "line": 6, "title": "Alert has no dedup",
        "evidence": "", "recommendation": "",
        "confidence": 0.8, "sources": ["a"],
        "consensus": False}]}

    @staticmethod
    def _fixed(prompt):
        return json.dumps({
            "resolutions": [{
                "finding_id": "abc123", "status": "fixed",
                "evidence": "return a + b and return a - b "
                            "are the only helpers left in "
                            "app/util.py and the sendmail "
                            "alert is removed"}],
            "new_findings": []})

    def test_verification_verdict_and_blocked_seat_fire(self):
        runner = RecordingRunner()
        n = notify.Notifier(["notify-stub"], runner=runner)
        core.run_verification(
            CLEAN, {"a": self._fixed, "b": quota_provider},
            self.PREVIOUS, "fixed it", notify=n)
        events = [c[1] for c in runner.calls]
        self.assertIn("seat_blocked", events)
        self.assertEqual(events.count("verdict"), 1)
        blocked = next(c for c in runner.calls
                       if c[1] == "seat_blocked")
        self.assertEqual(blocked[2], "seat b blocked:quota")

    def test_verification_without_notify_has_no_section(self):
        report = core.run_verification(
            CLEAN, {"a": self._fixed, "b": quota_provider},
            self.PREVIOUS, "fixed it")
        self.assertNotIn("notifications", report)


class CliNotifyWiringTests(unittest.TestCase):
    """The full seam: [notify] in the user setup reaches the
    run through the CLI and lands in the record on disk."""

    def _setup(self, tmp, with_notify):
        log = os.path.join(tmp, "calls.jsonl")
        stub = os.path.join(tmp, "notify_stub.py")
        with open(stub, "w", encoding="utf-8") as fh:
            fh.write(
                "import json, sys\n"
                f"with open({log!r}, 'a', encoding='utf-8') as fh:\n"
                "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n")
        cfg = os.path.join(tmp, "config.toml")
        environ = {"CODEREVIEW_CONFIG": cfg}
        with mock.patch.dict(os.environ, environ, clear=False):
            if with_notify:
                userconfig.save_user_config(
                    ["deepseek"], {},
                    notify={"command": [sys.executable, stub]})
            else:
                userconfig.save_user_config(["deepseek"], {})
        patch = os.path.join(tmp, "change.diff")
        with open(patch, "w", encoding="utf-8") as fh:
            fh.write(CLEAN)
        return log, cfg, patch

    def _run_cli(self, tmp, cfg, patch):
        outdir = os.path.join(tmp, "out")
        err = io.StringIO()
        with mock.patch.dict(os.environ,
                             {"CODEREVIEW_CONFIG": cfg},
                             clear=False), \
                redirect_stderr(err):
            rc = cli.main(
                ["--patch", patch, "--out", outdir],
                providers_override={"a": pass_provider,
                                    "b": pass_provider})
        records = [f for f in os.listdir(outdir)
                   if f.endswith(".json")]
        self.assertEqual(len(records), 1)
        with open(os.path.join(outdir, records[0]),
                  encoding="utf-8") as fh:
            return rc, json.load(fh)

    def test_cli_run_notifies_verdict_and_records_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, cfg, patch = self._setup(tmp, with_notify=True)
            rc, record = self._run_cli(tmp, cfg, patch)
            self.assertEqual(rc, 0)
            with open(log, encoding="utf-8") as fh:
                calls = [json.loads(line)
                         for line in fh.read().splitlines()]
            self.assertEqual(
                calls, [["verdict", "gate pass: 0 finding(s)"]])
            self.assertEqual(len(record["notifications"]), 1)
            self.assertEqual(
                record["notifications"][0]["status"], "ok")

    def test_cli_run_without_notify_config_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, cfg, patch = self._setup(tmp, with_notify=False)
            rc, record = self._run_cli(tmp, cfg, patch)
            self.assertEqual(rc, 0)
            self.assertFalse(os.path.exists(log))
            self.assertNotIn("notifications", record)


if __name__ == "__main__":
    unittest.main()
