"""Epic K3a herdr pane-hosting tests.

The full hosted lifecycle is driven against a stub `herdr`
executable (tests/fixtures/herdr/herdr_stub.py) installed on
PATH — it implements the CLI-wrapper surface the adapter
binds and really executes pane commands in a shell, so no
test needs a real herdr (none is installed on the build
machine; the live smoke against real herdr is UNVERIFIED and
recorded as such in the changelog). Detection logic is also
unit-tested with an injected run_fn. Nothing here touches
the network or a real account.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, core, herdrhost, providers, seatstate  # noqa: E402
from codereview import userconfig  # noqa: E402

STUB = os.path.join(os.path.dirname(__file__), "fixtures",
                    "herdr", "herdr_stub.py")

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

VERDICT = json.dumps({"summary": "looks fine", "findings": []})

SCHEMA_DOC = json.dumps({
    "protocol": 22, "schema_version": 1,
    "schemas": {
        "request": {"methods": list(herdrhost.REQUIRED_METHODS)},
        "event": {"types": list(herdrhost.REQUIRED_EVENTS)},
    },
})


def _write_script(directory, name, body):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"#!{sys.executable}\n" + body)
    os.chmod(path, 0o755)
    return path


def _install_stub(tmp):
    """-> (bin_dir, state_dir): the stub herdr on a private
    PATH, its state in a private dir."""
    bin_dir = os.path.join(tmp, "bin")
    state_dir = os.path.join(tmp, "herdr-state")
    os.makedirs(bin_dir)
    os.makedirs(state_dir)
    with open(STUB, encoding="utf-8") as fh:
        body = fh.read()
    body = body.replace("#!/usr/bin/env python3",
                        f"#!{sys.executable}", 1)
    path = os.path.join(bin_dir, "herdr")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(path, 0o755)
    return bin_dir, state_dir


def _stub_env(bin_dir, state_dir, **extra):
    env = {"PATH": bin_dir + os.pathsep
           + os.environ.get("PATH", ""),
           "HERDR_STUB_DIR": state_dir}
    env.update(extra)
    return env


def _calls(state_dir):
    path = os.path.join(state_dir, "calls.log")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [ln.rstrip("\n") for ln in fh if ln.strip()]


def _seat_ok(tmp, proof_name="proof.json", sleep=0.3):
    """A seat script honouring the contract: reads the brief
    on stdin, checks $CODEREVIEW_PROMPT names the same
    content, records both to a proof file, prints a verdict."""
    proof = os.path.join(tmp, proof_name)
    body = (
        "import json, os, sys, time\n"
        f"time.sleep({sleep})\n"
        "data = sys.stdin.read()\n"
        "env_path = os.environ.get('CODEREVIEW_PROMPT')\n"
        "env_data = None\n"
        "if env_path:\n"
        "    with open(env_path, encoding='utf-8') as fh:\n"
        "        env_data = fh.read()\n"
        f"with open({proof!r}, 'w', encoding='utf-8') as fh:\n"
        "    json.dump({'stdin': data, 'env_path': env_path,\n"
        "               'env_data': env_data}, fh)\n"
        f"sys.stdout.write({VERDICT!r})\n")
    return _write_script(tmp, "seat_ok.py", body), proof


class VersionAndSchemaTests(unittest.TestCase):

    def test_parse_version(self):
        self.assertEqual(herdrhost.parse_version("herdr 0.9.5"),
                         (0, 9, 5))
        self.assertEqual(
            herdrhost.parse_version("herdr 0.10.2-preview.41"),
            (0, 10, 2))
        self.assertIsNone(herdrhost.parse_version("herdr"))
        self.assertIsNone(herdrhost.parse_version(""))

    def test_schema_names_walks_all_sections(self):
        names = herdrhost.schema_names(SCHEMA_DOC)
        for name in herdrhost.REQUIRED_METHODS:
            self.assertIn(name, names)
        for name in herdrhost.REQUIRED_EVENTS:
            self.assertIn(name, names)
        self.assertEqual(herdrhost.schema_names("not json"),
                         set())


def _fake_run(responses):
    """run_fn dispatching on the herdr subcommand words in
    argv: responses maps a key ('--version', 'schema',
    'snapshot') to (rc, out, err)."""
    def run(argv, timeout):
        joined = " ".join(argv[1:])
        for key, resp in responses.items():
            if key in joined:
                return resp
        raise AssertionError(f"unexpected herdr call {argv}")
    return run


def _good_responses(**overrides):
    responses = {
        "--version": (0, "herdr 0.9.5\n", ""),
        "schema": (0, SCHEMA_DOC, ""),
        "snapshot": (0, json.dumps(
            {"result": {"snapshot": {"panes": []}}}), ""),
    }
    responses.update(overrides)
    return responses


class DetectTests(unittest.TestCase):

    def test_absent_binary_is_inert(self):
        plan = herdrhost.detect(which_fn=lambda _n: None)
        self.assertFalse(plan["active"])
        self.assertEqual(plan["reason"],
                         "herdr not found on PATH")

    def test_version_failure_and_unparseable(self):
        plan = herdrhost.detect(
            which_fn=lambda _n: "/x/herdr",
            run_fn=_fake_run({"--version": (1, "", "boom")}))
        self.assertFalse(plan["active"])
        self.assertIn("--version failed", plan["reason"])
        plan = herdrhost.detect(
            which_fn=lambda _n: "/x/herdr",
            run_fn=_fake_run({"--version": (0, "herdr\n", "")}))
        self.assertFalse(plan["active"])
        self.assertIn("no version", plan["reason"])

    def test_too_old_is_inert_with_the_floor_named(self):
        plan = herdrhost.detect(
            which_fn=lambda _n: "/x/herdr",
            run_fn=_fake_run(_good_responses(
                **{"--version": (0, "herdr 0.8.9\n", "")})))
        self.assertFalse(plan["active"])
        self.assertIn("0.8.9", plan["reason"])
        self.assertIn("below the adapter minimum",
                      plan["reason"])

    def test_schema_mismatch_names_what_is_missing(self):
        doc = json.loads(SCHEMA_DOC)
        doc["schemas"]["request"]["methods"].remove(
            "session.snapshot")
        plan = herdrhost.detect(
            which_fn=lambda _n: "/x/herdr",
            run_fn=_fake_run(_good_responses(
                schema=(0, json.dumps(doc), ""))))
        self.assertFalse(plan["active"])
        self.assertIn("schema mismatch", plan["reason"])
        self.assertIn("session.snapshot", plan["reason"])

    def test_unreachable_session_is_inert(self):
        plan = herdrhost.detect(
            environ={},
            which_fn=lambda _n: "/x/herdr",
            run_fn=_fake_run(_good_responses(
                snapshot=(1, "", "server not running"))))
        self.assertFalse(plan["active"])
        self.assertIn("no reachable herdr session",
                      plan["reason"])
        self.assertIn("no HERDR_SOCKET_PATH set", plan["reason"])

    def test_active_plan_carries_a_host(self):
        plan = herdrhost.detect(
            which_fn=lambda _n: "/x/herdr",
            run_fn=_fake_run(_good_responses()))
        self.assertTrue(plan["active"])
        self.assertIsNone(plan["reason"])
        self.assertEqual(plan["host"].version_text, "0.9.5")
        self.assertEqual(
            herdrhost.inert_line({"reason": "why"}),
            "inert: why")

    def test_stub_too_old_and_schema_missing(self):
        # The same outcomes through the real subprocess path
        # against the stub binary.
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir, state_dir = _install_stub(tmp)
            env = _stub_env(bin_dir, state_dir,
                            HERDR_STUB_VERSION="0.8.0")
            with mock.patch.dict(os.environ, env):
                plan = herdrhost.detect()
            self.assertFalse(plan["active"])
            self.assertIn("below the adapter minimum",
                          plan["reason"])
            env = _stub_env(
                bin_dir, state_dir,
                HERDR_STUB_SCHEMA_MISSING="session.snapshot")
            with mock.patch.dict(os.environ, env):
                plan = herdrhost.detect()
            self.assertFalse(plan["active"])
            self.assertIn("session.snapshot", plan["reason"])


class HostMethodTests(unittest.TestCase):

    def _host(self, responses):
        return herdrhost.HerdrHost(
            "/x/herdr", (0, 9, 5), run_fn=_fake_run(responses))

    def test_create_workspace_reads_the_envelope(self):
        host = self._host({"workspace create": (0, json.dumps({
            "id": "cli:workspace:create",
            "result": {
                "workspace": {"workspace_id": "w1"},
                "tab": {"tab_id": "w1:t1"},
                "root_pane": {"pane_id": "w1:p1"}}}), "")})
        ws, pane = host.create_workspace(
            cwd="/tmp/x", label="codereview-seat",
            env={"CODEREVIEW_PROMPT": "/tmp/x/prompt.md"})
        self.assertEqual((ws, pane), ("w1", "w1:p1"))

    def test_create_workspace_without_ids_is_an_error(self):
        host = self._host({"workspace create": (
            0, json.dumps({"result": {}}), "")})
        with self.assertRaises(herdrhost.HerdrError):
            host.create_workspace(cwd="/tmp/x", label="l")

    def test_half_created_workspace_is_closed_not_leaked(self):
        # The create response names a workspace but no root
        # pane: the workspace exists server-side and its id is
        # the only handle — the adapter closes it before
        # raising, rather than leaking it.
        closed = []

        def run(argv, timeout):
            joined = " ".join(argv[1:])
            if "workspace create" in joined:
                return 0, json.dumps({"result": {
                    "workspace": {"workspace_id": "w7"},
                    "root_pane": {}}}), ""
            if "workspace close" in joined:
                closed.append(argv[-1])
                return 0, "{}", ""
            raise AssertionError(f"unexpected call {argv}")
        host = herdrhost.HerdrHost("/x/herdr", (0, 9, 5),
                                   run_fn=run)
        with self.assertRaises(herdrhost.HerdrError):
            host.create_workspace(cwd="/tmp/x", label="l")
        self.assertEqual(closed, ["w7"])

    def test_cli_error_carries_the_stderr_tail(self):
        host = self._host({"pane get": (1, "", "no such pane")})
        with self.assertRaises(herdrhost.HerdrError) as cm:
            host.pane_get("w1:p9")
        self.assertIn("no such pane", str(cm.exception))

    def test_snapshot_unwraps_the_result(self):
        host = self._host({"snapshot": (0, json.dumps({
            "result": {"snapshot": {"panes": [{"pane_id": "p"}]}},
        }), "")})
        self.assertEqual(host.snapshot()["panes"],
                         [{"pane_id": "p"}])


class HostingConfigTests(unittest.TestCase):

    def _env(self, tmp):
        return {"HOME": tmp,
                "CODEREVIEW_CONFIG": os.path.join(
                    tmp, "config.toml")}

    def test_hosting_table_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, self._env(tmp),
                                 clear=True):
                userconfig.save_user_config(
                    ["agent:claude:claude -p"], {},
                    hosting={"herdr": ["claude"]})
                loaded = userconfig.load_user_config()
                self.assertEqual(loaded["hosting"],
                                 {"herdr": ["claude"]})
                self.assertEqual(
                    userconfig.default_hosting_herdr_seats(),
                    ["claude"])

    def test_no_hosting_table_means_no_hosted_seats(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, self._env(tmp),
                                 clear=True):
                userconfig.save_user_config(["deepseek"], {})
                loaded = userconfig.load_user_config()
                self.assertEqual(loaded["hosting"],
                                 {"herdr": []})
                self.assertEqual(
                    userconfig.default_hosting_herdr_seats(), [])

    def test_save_without_hosting_is_byte_identical(self):
        # The pre-K3a writer's exact bytes for the same setup:
        # adding the hosting parameter must not move a byte
        # for setups that do not use it.
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

    def test_malformed_hosting_is_a_loud_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            with mock.patch.dict(os.environ, env, clear=True):
                path = env["CODEREVIEW_CONFIG"]
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write('providers = []\n\n[hosting]\n'
                             'herdr = "claude"\n')
                with self.assertRaises(ValueError) as cm:
                    userconfig.load_user_config()
                self.assertIn("hosting.herdr", str(cm.exception))
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write('providers = []\nhosting = 3\n')
                with self.assertRaises(ValueError) as cm:
                    userconfig.load_user_config()
                self.assertIn("'hosting' must be a table",
                              str(cm.exception))


class _HostedCase(unittest.TestCase):
    """Base: stub herdr installed + an active detected host."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        self.bin_dir, self.state_dir = _install_stub(self.tmp)
        self.env = _stub_env(self.bin_dir, self.state_dir)
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        plan = herdrhost.detect()
        self.assertTrue(plan["active"], plan["reason"])
        self.host = plan["host"]

    def _job_context(self):
        """Install the seat-state log + receipt box the way
        core._review_job does; returns (box, log, release)."""
        box = []
        log = seatstate.SeatStateLog()
        rtok = herdrhost.RECEIPTS.set(box)
        ltok = seatstate.CURRENT.set(log)

        def release():
            herdrhost.RECEIPTS.reset(rtok)
            seatstate.CURRENT.reset(ltok)
        return box, log, release


class HostedSeatTests(_HostedCase):

    def test_full_lifecycle_and_the_prompt_travels_by_file(self):
        script, proof = _seat_ok(self.tmp)
        fn = providers.command_agent(
            f"{sys.executable} {script}", timeout=30, host=self.host)
        box, _log, release = self._job_context()
        try:
            text = fn("the brief")
        finally:
            release()
        self.assertEqual(text, VERDICT)
        with open(proof, encoding="utf-8") as fh:
            seen = json.load(fh)
        # Both halves of the seat contract held in the pane:
        # stdin carried the brief, and $CODEREVIEW_PROMPT
        # named a file with the same content.
        self.assertEqual(seen["stdin"], "the brief")
        self.assertEqual(seen["env_data"], "the brief")
        self.assertTrue(seen["env_path"].endswith("prompt.md"))
        # The receipt: hosting provenance for the record.
        self.assertEqual(len(box), 1)
        receipt = box[0]
        self.assertEqual(receipt["transport"], "herdr")
        self.assertEqual(receipt["herdr_version"], "0.9.5")
        self.assertIn("pane_id", receipt)
        self.assertIn("workspace_id", receipt)
        self.assertIn("terminal_id", receipt)
        statuses = [o["agent_status"]
                    for o in receipt["observations"]]
        self.assertIn("working", statuses)
        # The lifecycle ran through the CLI wrappers, and the
        # workspace was closed behind the seat.
        calls = _calls(self.state_dir)
        self.assertTrue(any(c.startswith("workspace create")
                            for c in calls))
        self.assertTrue(any(c.startswith("pane run")
                            for c in calls))
        self.assertTrue(any(c.startswith("workspace close")
                            for c in calls))

    def test_nonzero_exit_classifies_like_headless(self):
        script = _write_script(self.tmp, "boom.py",
                               "import sys\nsys.exit(3)\n")
        fn = providers.command_agent(
            f"{sys.executable} {script}", timeout=30,
            host=self.host)
        box, _log, release = self._job_context()
        try:
            with self.assertRaises(providers.ProviderError) as cm:
                fn("brief")
        finally:
            release()
        self.assertIn("agent command exited 3",
                      str(cm.exception))
        self.assertEqual(cm.exception.seat_facts["state"],
                         "failed")
        self.assertEqual(
            cm.exception.seat_facts["evidence"]["exit_code"], 3)
        # A failed attempt still leaves its hosting receipt.
        self.assertEqual(len(box), 1)
        self.assertEqual(box[0]["transport"], "herdr")

    def test_empty_output_is_the_headless_error(self):
        script = _write_script(self.tmp, "mute.py", "pass\n")
        fn = providers.command_agent(
            f"{sys.executable} {script}", timeout=30,
            host=self.host)
        _box, _log, release = self._job_context()
        try:
            with self.assertRaises(providers.ProviderError) as cm:
                fn("brief")
        finally:
            release()
        self.assertEqual(str(cm.exception),
                         "agent command produced no output")

    def test_verified_pattern_terminates_a_stuck_seat_early(self):
        # A seat binary NAMED codex (argv[0] keys the pattern
        # table) prints its verified auth failure, then hangs.
        script = _write_script(
            self.tmp, "codex",
            "import sys, time\n"
            "sys.stderr.write('HTTP error: 401 Unauthorized\\n')\n"
            "sys.stderr.flush()\n"
            "time.sleep(60)\n")
        fn = providers.command_agent(
            script, timeout=60, host=self.host,
            stall_after=60, block_grace=0.3)
        _box, _log, release = self._job_context()
        started = time.monotonic()
        try:
            with self.assertRaises(providers.ProviderError) as cm:
                fn("brief")
        finally:
            release()
        self.assertLess(time.monotonic() - started, 20)
        self.assertIn("agent command blocked (auth)",
                      str(cm.exception))
        self.assertEqual(cm.exception.seat_facts["class"],
                         "auth")

    def test_timeout_and_stalled_terminal_states(self):
        script = _write_script(self.tmp, "hang.py",
                               "import time\ntime.sleep(60)\n")
        fn = providers.command_agent(
            f"{sys.executable} {script}", timeout=1.5,
            host=self.host, stall_after=60)
        _b, _l, release = self._job_context()
        try:
            with self.assertRaises(providers.ProviderError) as cm:
                fn("brief")
        finally:
            release()
        self.assertEqual(cm.exception.seat_facts["state"],
                         "timed-out")
        fn = providers.command_agent(
            f"{sys.executable} {script}", timeout=1.5,
            host=self.host, stall_after=0.5)
        _b, _l, release = self._job_context()
        try:
            with self.assertRaises(providers.ProviderError) as cm:
                fn("brief")
        finally:
            release()
        self.assertEqual(cm.exception.seat_facts["state"],
                         "blocked")
        self.assertEqual(cm.exception.seat_facts["class"],
                         "stalled")


class HostedRunReviewTests(_HostedCase):

    def _providers(self, script, hosted):
        spec = f"agent:stubseat:{sys.executable} {script}"
        if hosted:
            return providers.build_providers(
                [spec], agent_timeout=30, herdr_host=self.host,
                herdr_seats=["stubseat"])
        return providers.build_providers([spec],
                                         agent_timeout=30)

    def test_hosted_headless_equivalence(self):
        script, _proof = _seat_ok(self.tmp)
        headless = core.run_review(
            CLEAN, self._providers(script, hosted=False))
        hosted = core.run_review(
            CLEAN, self._providers(script, hosted=True))
        self.assertEqual(headless["gate"], "pass")
        self.assertEqual(hosted["gate"], headless["gate"])
        self.assertEqual(hosted["findings"],
                         headless["findings"])

        def stripped(report):
            out = []
            for rec in report["reviewer_reports"]:
                rec = dict(rec)
                rec.pop("hosting", None)
                rec.pop("hosting_primary", None)
                # Timing differs run to run; not a hosting
                # field, excluded from the comparison.
                rec.pop("duration_ms", None)
                state = rec.get("seat_state") or {}
                rec["seat_state"] = {
                    "state": state.get("state"),
                    "class": state.get("class")}
                out.append(rec)
            # Reports land in job-completion order (a thread
            # pool), which is timing luck, not content.
            out.sort(key=lambda r: (r["provider"], r["lens"],
                                    r["batch"]))
            return out
        self.assertEqual(stripped(hosted), stripped(headless))
        for rec in headless["reviewer_reports"]:
            self.assertNotIn("hosting", rec)
        for rec in hosted["reviewer_reports"]:
            self.assertEqual(rec["hosting"]["transport"],
                             "herdr")
            self.assertEqual(
                rec["seat_state"]["state"], "done")

    def test_herdr_blocked_is_advisory_only(self):
        # The pane reports blocked (an input wait, by herdr's
        # vocabulary) while the seat is in fact working: the
        # episode is recorded as advisory, the seat completes,
        # and the verdict is the seat's own.
        script, _proof = _seat_ok(self.tmp, sleep=0.8)
        with mock.patch.dict(os.environ,
                             {"HERDR_STUB_STATUS": "blocked"}):
            report = core.run_review(
                CLEAN, self._providers(script, hosted=True))
        rec = report["reviewer_reports"][0]
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(report["gate"], "pass")
        self.assertEqual(rec["seat_state"]["state"], "done")
        advisory = [t for t in rec["seat_state"]["transitions"]
                    if (t.get("evidence") or {}).get("advisory")]
        self.assertTrue(any(
            t["state"] == "blocked" and t["class"] == "input"
            for t in advisory))
        statuses = [o["agent_status"]
                    for o in rec["hosting"]["observations"]]
        self.assertIn("blocked", statuses)

    def test_contradictory_pane_state_files_win(self):
        # Herdr claims the agent is done while the seat is
        # still running and no exit code exists: process truth
        # (the files) is senior — the run waits and completes.
        script, _proof = _seat_ok(self.tmp, sleep=0.8)
        with mock.patch.dict(os.environ,
                             {"HERDR_STUB_STATUS": "done"}):
            report = core.run_review(
                CLEAN, self._providers(script, hosted=True))
        rec = report["reviewer_reports"][0]
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(report["gate"], "pass")
        statuses = [o["agent_status"]
                    for o in rec["hosting"]["observations"]]
        self.assertIn("done", statuses)


class ChaosTests(_HostedCase):

    def _run_seat(self, script, scenario):
        env = _stub_env(self.bin_dir, self.state_dir, **scenario)
        fn = providers.command_agent(
            f"{sys.executable} {script}", timeout=30,
            host=self.host)
        box, _log, release = self._job_context()
        started = time.monotonic()
        try:
            with mock.patch.dict(os.environ, env):
                with self.assertRaises(
                        providers.ProviderError) as cm:
                    fn("brief")
        finally:
            release()
        return cm.exception, box, time.monotonic() - started

    def _pane_runs(self):
        return [c for c in _calls(self.state_dir)
                if c.startswith("pane run")]

    def test_herdr_dies_mid_run_seat_fails_no_resume(self):
        script = _write_script(self.tmp, "slow.py",
                               "import time\ntime.sleep(3)\n")
        exc, box, elapsed = self._run_seat(
            script, {"HERDR_STUB_DIE_AFTER_RUN": "1"})
        self.assertLess(elapsed, 2.5)
        self.assertIn("herdr hosting failed", str(exc))
        self.assertEqual(
            exc.seat_facts["evidence"]["stage"],
            "herdr-unreachable")
        self.assertEqual(len(self._pane_runs()), 1)
        self.assertEqual(box[0]["events_lost"], 1)

    def test_event_break_reconciles_and_the_run_survives(self):
        script, _proof = _seat_ok(self.tmp, sleep=0.6)
        env = _stub_env(self.bin_dir, self.state_dir,
                        HERDR_STUB_DROP_GETS="1")
        fn = providers.command_agent(
            f"{sys.executable} {script}", timeout=30,
            host=self.host)
        box, _log, release = self._job_context()
        try:
            with mock.patch.dict(os.environ, env):
                text = fn("brief")
        finally:
            release()
        self.assertEqual(text, VERDICT)
        self.assertEqual(box[0]["events_lost"], 1)
        self.assertTrue(box[0]["reconciled"])

    def test_vanished_pane_is_a_recorded_seat_failure(self):
        script = _write_script(self.tmp, "slow2.py",
                               "import time\ntime.sleep(3)\n")
        exc, _box, elapsed = self._run_seat(
            script, {"HERDR_STUB_VANISH": "1"})
        self.assertLess(elapsed, 2.5)
        self.assertEqual(
            exc.seat_facts["evidence"]["stage"], "pane-exited")
        self.assertEqual(len(self._pane_runs()), 1)

    def test_restarted_session_is_never_silently_resumed(self):
        script = _write_script(self.tmp, "slow3.py",
                               "import time\ntime.sleep(3)\n")
        exc, _box, elapsed = self._run_seat(
            script, {"HERDR_STUB_RESTART": "1"})
        self.assertLess(elapsed, 2.5)
        self.assertEqual(
            exc.seat_facts["evidence"]["stage"],
            "session-restarted")
        self.assertEqual(len(self._pane_runs()), 1)


class CliHostingTests(unittest.TestCase):

    def _write_config(self, tmp, script, hosting):
        cfg = os.path.join(tmp, "config.toml")
        spec = f"agent:stubseat:{sys.executable} {script}"
        userconfig.save_user_config(
            [spec], {}, environ={"CODEREVIEW_CONFIG": cfg},
            hosting=hosting)
        return cfg

    def _run_gate(self, tmp, cfg, path_value, extra_env=None):
        patch = os.path.join(tmp, "change.diff")
        with open(patch, "w", encoding="utf-8") as fh:
            fh.write(CLEAN)
        outdir = os.path.join(tmp, "out")
        env = {"PATH": path_value, "HOME": tmp,
               "CODEREVIEW_CONFIG": cfg}
        env.update(extra_env or {})
        err = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(cli, "_stdin_is_tty",
                                  lambda: False), \
                redirect_stderr(err):
            rc = cli.main(["--patch", patch, "--out", outdir])
        records = []
        if os.path.isdir(outdir):
            import glob
            records = glob.glob(
                os.path.join(outdir, "codereview-*.json"))
        self.assertEqual(len(records), 1, err.getvalue())
        with open(records[0], encoding="utf-8") as fh:
            return rc, json.load(fh)

    def test_inert_adapter_one_recorded_line_headless_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            script, _proof = _seat_ok(tmp)
            cfg = self._write_config(
                tmp, script, {"herdr": ["stubseat"]})
            empty_bin = os.path.join(tmp, "empty-bin")
            os.mkdir(empty_bin)
            rc, record = self._run_gate(tmp, cfg, empty_bin)
            self.assertEqual(rc, 0)
            # Exactly one recorded line, and the seat still
            # served — headless, with no hosting receipt.
            self.assertEqual(record["herdr_hosting"],
                             "inert: herdr not found on PATH")
            rec = record["reviewer_reports"][0]
            self.assertEqual(rec["status"], "ok")
            self.assertNotIn("hosting", rec)
            self.assertEqual(record["gate"], "pass")

    def test_active_adapter_hosts_the_config_marked_seat(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir, state_dir = _install_stub(tmp)
            script, _proof = _seat_ok(tmp)
            cfg = self._write_config(
                tmp, script, {"herdr": ["stubseat"]})
            path_value = bin_dir + os.pathsep + os.environ.get(
                "PATH", "")
            rc, record = self._run_gate(
                tmp, cfg, path_value,
                extra_env={"HERDR_STUB_DIR": state_dir})
            self.assertEqual(rc, 0)
            self.assertNotIn("herdr_hosting", record)
            rec = record["reviewer_reports"][0]
            self.assertEqual(rec["hosting"]["transport"],
                             "herdr")
            self.assertEqual(rec["hosting"]["herdr_version"],
                             "0.9.5")
            self.assertEqual(record["gate"], "pass")


if __name__ == "__main__":
    unittest.main()
