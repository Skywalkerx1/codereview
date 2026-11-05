"""Epic L3 — lifecycle hooks.

User-configured commands in the [hooks] table of
.codereview.toml fire at pre-run (before any seat call),
on-blocked (first seat in a K2 blocked class), and
post-verdict (after the record is written). They execute
through the Epic C evidence sandbox (C5 rules) and their
output is captured (sha256 + tail) into the record's `hooks`
section. Enforcement flows one way only: a hook can never
change a verdict, a finding, or a gate input — the fixtures
below pin exactly that, plus the no-[hooks] equivalence.
"""

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from codereview import cli, hooks, policy  # noqa: E402

PATCH = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,1 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""

# Assembled from fragments: test files must not contain
# secret-shaped literals (tests/test_fixture_secret_hygiene.py).
MARKER = "operator-only-" + "marker-" + "value-1234"


def _load_policy(tmp, text):
    path = os.path.join(tmp, ".codereview.toml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return policy.load_policy(path), path


class PolicyHooksSchemaTests(unittest.TestCase):
    """B1-style validation of the [hooks] table."""

    def test_commands_and_timeout_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol, _ = _load_policy(
                tmp, '[hooks]\npre_run = "echo a"\n'
                     'on_blocked = "echo b"\ntimeout = 30\n')
        self.assertEqual(pol["hooks"]["pre_run"], "echo a")
        self.assertEqual(pol["hooks"]["on_blocked"], "echo b")
        self.assertIsNone(pol["hooks"]["post_verdict"])
        self.assertEqual(pol["hooks"]["timeout"], 30)

    def test_no_hooks_table_defaults_to_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol, _ = _load_policy(tmp, "[panel]\nmin_seats = 1\n")
        self.assertEqual(pol["hooks"],
                         {"pre_run": None, "post_verdict": None,
                          "on_blocked": None, "timeout": None})

    def test_unknown_hooks_key_rejected_with_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as cm:
                _load_policy(tmp, '[hooks]\npre_rnu = "echo a"\n')
        self.assertIn(":2:", str(cm.exception))

    def test_empty_command_rejected_with_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as cm:
                _load_policy(tmp, '[hooks]\npre_run = "  "\n')
        self.assertIn(":2:", str(cm.exception))

    def test_non_string_command_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError):
                _load_policy(tmp, "[hooks]\npre_run = 42\n")

    def test_bad_timeouts_rejected(self):
        for text in ('[hooks]\ntimeout = 0\n',
                     '[hooks]\ntimeout = -5\n',
                     '[hooks]\ntimeout = "30"\n',
                     '[hooks]\ntimeout = true\n'):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(policy.PolicyError,
                                       msg=text):
                    _load_policy(tmp, text)

    def test_render_shows_hooks_only_when_configured(self):
        plain = policy.render_effective(policy.default_policy())
        self.assertNotIn("[hooks]", plain)
        with tempfile.TemporaryDirectory() as tmp:
            pol, _ = _load_policy(
                tmp, '[hooks]\npost_verdict = "echo done"\n')
        text = policy.render_effective(pol)
        self.assertIn("[hooks]", text)
        self.assertIn('post_verdict = "echo done"', text)

    def test_event_keys_pin_policy_and_hooks(self):
        self.assertEqual(
            set(hooks._EVENT_KEYS.values()),
            set(policy._HOOK_COMMAND_KEYS))


class FireHookTests(unittest.TestCase):
    """fire_hook through the real evidence sandbox."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.src)
        with open(os.path.join(self.src, "code.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("x = 1\n")

    def test_event_and_record_reach_the_hook(self):
        record = os.path.join(self.tmp.name, "record.json")
        with open(record, "w", encoding="utf-8") as fh:
            fh.write("RECORD-MARKER")
        entry = hooks.fire_hook(
            'echo "ev=$1 rec=$2 var=$CODEREVIEW_HOOK_EVENT"; '
            'cat "$CODEREVIEW_HOOK_RECORD"',
            "post-verdict", self.src, record_path=record)
        self.assertEqual(entry["status"], "passed")
        self.assertEqual(entry["exit_code"], 0)
        self.assertIn("ev=post-verdict", entry["output_tail"])
        self.assertIn(f"rec={record}", entry["output_tail"])
        self.assertIn("var=post-verdict", entry["output_tail"])
        self.assertIn("RECORD-MARKER", entry["output_tail"])
        self.assertEqual(entry["record_path"], record)

    def test_output_sha256_is_the_full_output_hash(self):
        entry = hooks.fire_hook("printf 'hook-output'",
                                "pre-run", self.src)
        self.assertEqual(entry["status"], "passed")
        self.assertEqual(entry["output_tail"], "hook-output")
        self.assertEqual(
            entry["output_sha256"],
            hashlib.sha256(b"hook-output").hexdigest())

    def test_failing_hook_is_recorded_not_raised(self):
        entry = hooks.fire_hook("echo hook-failed-marker; exit 3",
                                "pre-run", self.src)
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(entry["exit_code"], 3)
        self.assertIn("hook-failed-marker", entry["output_tail"])

    def test_missing_command_is_recorded(self):
        entry = hooks.fire_hook(
            "no-such-command-codereview-l3", "pre-run", self.src)
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(entry["exit_code"], 127)

    def test_timeout_is_recorded(self):
        entry = hooks.fire_hook("sleep 5", "pre-run", self.src,
                                timeout=1)
        self.assertEqual(entry["status"], "timeout")
        self.assertIsNone(entry["exit_code"])

    def test_environment_is_allow_listed(self):
        # C5 marker discipline, as in the evidence tests: an
        # operator-only variable planted in the environment the
        # runner is handed must not reach the hook, while the
        # hook's own CODEREVIEW_HOOK_* variables do.
        environ = {"PATH": os.environ["PATH"],
                   "OPERATOR_ONLY_MARKER": MARKER}
        entry = hooks.fire_hook(
            "printenv OPERATOR_ONLY_MARKER; "
            "printenv CODEREVIEW_HOOK_EVENT; echo end",
            "pre-run", self.src, environ=environ)
        self.assertNotIn(MARKER, entry["output_tail"])
        self.assertIn("pre-run", entry["output_tail"])
        self.assertIn("end", entry["output_tail"])

    def test_hook_runs_in_a_throwaway_copy(self):
        # The hook's cwd is a sandbox copy: a file it creates
        # lands in the copy, never in the reviewed tree.
        entry = hooks.fire_hook("touch hook-was-here; pwd",
                                "pre-run", self.src)
        self.assertEqual(entry["status"], "passed")
        self.assertFalse(os.path.exists(
            os.path.join(self.src, "hook-was-here")))
        self.assertNotIn(self.src, entry["output_tail"])


class RunnerAndTriggerTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.src)

    def test_each_event_fires_exactly_once(self):
        runner = hooks.HookRunner(
            {"pre_run": "true"}, self.src)
        first = runner.fire("pre-run")
        self.assertIsNotNone(first)
        self.assertIsNone(runner.fire("pre-run"))
        self.assertEqual(len(runner.results), 1)
        self.assertIsNone(runner.fire("post-verdict"))
        self.assertEqual(runner.section()["results"], [first])

    def test_section_is_none_without_config(self):
        self.assertIsNone(hooks.HookRunner({}, self.src).section())
        self.assertIsNone(hooks.hooks_from_policy(None))
        self.assertIsNone(hooks.hooks_from_policy(
            {"hooks": {"pre_run": None, "timeout": 30}}))

    def test_hooks_from_policy_picks_commands_and_timeout(self):
        config = hooks.hooks_from_policy(
            {"hooks": {"pre_run": "echo a", "post_verdict": None,
                       "on_blocked": None, "timeout": 12}})
        self.assertEqual(config, {"pre_run": "echo a",
                                  "timeout": 12})

    def test_first_blocked_trigger_reads_both_state_slots(self):
        reports = [
            {"provider": "a", "lens": "correctness",
             "seat_state": {"state": "done", "class": None}},
            {"provider": "b", "lens": "operations",
             "seat_state": {"state": "done", "class": None},
             "seat_state_primary": {"state": "blocked",
                                    "class": "quota"}},
            {"provider": "c", "lens": "operations",
             "seat_state": {"state": "blocked", "class": "auth"}},
        ]
        trigger = hooks.first_blocked_trigger(reports)
        self.assertEqual(trigger["seat"], "b")
        self.assertEqual(trigger["class"], "quota")
        self.assertEqual(trigger["state_source"],
                         "seat_state_primary")

    def test_no_blocked_seat_no_trigger(self):
        self.assertIsNone(hooks.first_blocked_trigger([
            {"provider": "a",
             "seat_state": {"state": "failed", "class": "error"}},
            {"provider": "b",
             "seat_state": {"state": "done", "class": None}},
            "not-a-dict", None]))
        self.assertIsNone(hooks.first_blocked_trigger([]))
        self.assertIsNone(hooks.first_blocked_trigger(None))


def _toml_str(value):
    """A TOML basic string carrying `value` verbatim."""
    return '"' + value.replace("\\", "\\\\").replace(
        '"', '\\"') + '"'


def _pass_seat(log=None):
    def seat(prompt):
        if log:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write("seat:good\n")
        return json.dumps({"verdict": "pass", "summary": "ok",
                           "findings": []})
    return seat


def _quota_seat(log=None):
    def seat(prompt):
        if log:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write("seat:bad\n")
        raise RuntimeError("429 RESOURCE_EXHAUSTED: quota gone")
    return seat


class CliLifecycleTests(unittest.TestCase):
    """End-to-end through cli.main with stub seats."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = self.tmp.name
        self.repo = os.path.join(base, "repo")
        os.makedirs(self.repo)
        with open(os.path.join(self.repo, "code.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("x = 1\n")
        self.patch = os.path.join(base, "change.diff")
        with open(self.patch, "w", encoding="utf-8") as fh:
            fh.write(PATCH)
        self.log = os.path.join(base, "order.log")

    def _policy(self, text):
        path = os.path.join(self.tmp.name, ".codereview.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _run(self, providers, policy_path=None, out="out"):
        argv = ["--repo", self.repo, "--patch", self.patch,
                "--out", os.path.join(self.tmp.name, out)]
        if policy_path:
            argv += ["--policy", policy_path]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = cli.main(argv, providers_override=providers)
        records = [f for f in os.listdir(
            os.path.join(self.tmp.name, out)) if f.endswith(".json")]
        self.assertEqual(len(records), 1)
        jpath = os.path.join(self.tmp.name, out, records[0])
        with open(jpath, encoding="utf-8") as fh:
            return rc, json.load(fh), jpath

    def _order(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as fh:
            return [line.strip() for line in fh if line.strip()]

    def _all_hooks_policy(self, pre=None, blocked=None, post=None):
        log = self.log
        pre = pre or f"echo hook:pre-run >> {log}"
        blocked = blocked or f"echo hook:on-blocked >> {log}"
        # The post-verdict hook reads the record it was handed
        # ($2) and lifts its gate line into the order log. The
        # anchored pattern '"gate": "' cannot match the hook's
        # own command as echoed (backslash-escaped) inside the
        # record's hooks section.
        post = post or (
            f"grep -m1 '\"gate\": \"' \"$2\" >> {log} && "
            f"echo hook:post-verdict >> {log}")
        return self._policy(
            "[hooks]\n"
            f"pre_run = {_toml_str(pre)}\n"
            f"on_blocked = {_toml_str(blocked)}\n"
            f"post_verdict = {_toml_str(post)}\n")

    def test_all_events_fire_once_in_order(self):
        policy_path = self._all_hooks_policy()
        providers = {"good": _pass_seat(self.log),
                     "bad": _quota_seat(self.log)}
        rc, record, jpath = self._run(providers, policy_path)
        self.assertEqual(rc, 2)  # inconclusive: a seat blocked
        self.assertEqual(record["gate"], "inconclusive")

        section = record["hooks"]
        self.assertEqual(
            [e["event"] for e in section["events"]],
            ["pre-run", "on-blocked", "post-verdict"])
        results = section["results"]
        self.assertEqual([r["event"] for r in results],
                         ["pre-run", "on-blocked", "post-verdict"])
        for entry in results:
            self.assertEqual(entry["status"], "passed")
            self.assertEqual(len(entry["output_sha256"]), 64)
        self.assertIsNone(results[0]["record_path"])
        self.assertEqual(results[1]["record_path"], jpath)
        self.assertEqual(results[2]["record_path"], jpath)
        trigger = section["blocked_trigger"]
        self.assertEqual(trigger["seat"], "bad")
        self.assertEqual(trigger["class"], "quota")
        self.assertEqual(results[1]["trigger"]["seat"], "bad")

        order = self._order()
        self.assertEqual(order[0], "hook:pre-run")
        self.assertEqual(order.count("hook:pre-run"), 1)
        self.assertEqual(order.count("hook:on-blocked"), 1)
        self.assertEqual(order.count("hook:post-verdict"), 1)
        self.assertIn("seat:good", order)
        self.assertIn("seat:bad", order)
        # Every seat call sits between pre-run and on-blocked;
        # the post-verdict hook read the written record and saw
        # its gate before its own line landed.
        seat_idx = [i for i, line in enumerate(order)
                    if line.startswith("seat:")]
        self.assertLess(order.index("hook:pre-run"), min(seat_idx))
        self.assertLess(max(seat_idx),
                        order.index("hook:on-blocked"))
        self.assertLess(order.index("hook:on-blocked"),
                        order.index("hook:post-verdict"))
        gate_line = next(i for i, line in enumerate(order)
                         if '"gate": "inconclusive"' in line)
        self.assertLess(gate_line, order.index("hook:post-verdict"))

    def test_on_blocked_skipped_when_no_seat_blocks(self):
        policy_path = self._all_hooks_policy()
        rc, record, _ = self._run(
            {"good": _pass_seat(self.log)}, policy_path)
        self.assertEqual(rc, 0)
        self.assertEqual(
            [r["event"] for r in record["hooks"]["results"]],
            ["pre-run", "post-verdict"])
        self.assertIsNone(record["hooks"]["blocked_trigger"])
        self.assertNotIn("hook:on-blocked", self._order())

    def test_failing_hooks_never_change_the_verdict(self):
        fail = "echo hook-ran; exit 1"
        policy_path = self._all_hooks_policy(
            pre=fail, blocked=fail, post=fail)
        providers = {"good": _pass_seat(), "bad": _quota_seat()}
        rc, hooked, _ = self._run(providers, policy_path,
                                  out="hooked")
        rc2, control, _ = self._run(providers, None, out="control")
        self.assertEqual(rc, rc2)
        self.assertEqual(hooked["gate"], control["gate"])
        self.assertEqual(hooked["findings"], control["findings"])
        self.assertEqual(
            [(r["provider"], r["status"])
             for r in hooked["reviewer_reports"]],
            [(r["provider"], r["status"])
             for r in control["reviewer_reports"]])
        self.assertNotIn("hooks", control)
        self.assertEqual(
            [r["status"] for r in hooked["hooks"]["results"]],
            ["failed", "failed", "failed"])

    def test_policy_without_hooks_table_is_equivalent(self):
        policy_path = self._policy("[panel]\nmin_seats = 0\n")
        providers = {"good": _pass_seat()}
        rc, record, _ = self._run(providers, policy_path)
        self.assertEqual(rc, 0)
        self.assertNotIn("hooks", record)

    def test_missing_hook_command_recorded_run_continues(self):
        policy_path = self._all_hooks_policy(
            pre="no-such-command-codereview-l3")
        rc, record, _ = self._run({"good": _pass_seat()},
                                  policy_path)
        self.assertEqual(rc, 0)
        self.assertEqual(record["gate"], "pass")
        pre = record["hooks"]["results"][0]
        self.assertEqual(pre["event"], "pre-run")
        self.assertEqual(pre["status"], "failed")
        self.assertEqual(pre["exit_code"], 127)


if __name__ == "__main__":
    unittest.main()
