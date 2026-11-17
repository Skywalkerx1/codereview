"""Windows startup of probe and evidence children, simulated.

Python's subprocess rejects preexec_fn on Windows with
ValueError at Popen, so a sandbox that always passed it could
never start a probe or an evidence child there; and evidence.py
imported the POSIX-only `resource` module unconditionally, so on
Windows it (and the CLI, which imports it) could not even load.

These tests run on POSIX. They simulate Windows the two ways the
code can see it: os.name == "nt" (what the guards read), and a
Popen that raises exactly what Windows' Popen raises when handed
a preexec_fn. They are a simulation, not a Windows run.
"""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from typing import ClassVar
from unittest import mock

SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, SRC)

from codereview import evidence, probe

_REAL_POPEN = subprocess.Popen
_WINDOWS_PREEXEC_ERROR = "preexec_fn is not supported on Windows platforms"


class _WindowsLikePopen(_REAL_POPEN):  # type: ignore[misc,valid-type]
    """Popen that refuses preexec_fn the way Windows' Popen does,
    and records the keyword arguments it was given."""
    calls: ClassVar[list] = []

    def __init__(self, *args, **kwargs):
        type(self).calls.append(dict(kwargs))
        if kwargs.get("preexec_fn") is not None:
            raise ValueError(_WINDOWS_PREEXEC_ERROR)
        super().__init__(*args, **kwargs)


class _RecordingPopen(_REAL_POPEN):  # type: ignore[misc,valid-type]
    calls: ClassVar[list] = []

    def __init__(self, *args, **kwargs):
        type(self).calls.append(dict(kwargs))
        super().__init__(*args, **kwargs)


@contextlib.contextmanager
def _windows(module):
    """os.name reads 'nt' and Popen behaves like Windows' Popen
    for the duration; the module's one-time notice is re-armed
    and its stderr captured."""
    _WindowsLikePopen.calls = []
    err = io.StringIO()
    with mock.patch.object(os, "name", "nt"), \
            mock.patch.object(module.subprocess, "Popen",
                              _WindowsLikePopen), \
            mock.patch.object(module, "_LIMITS_NOTICE_EMITTED",
                              False), \
            contextlib.redirect_stderr(err):
        yield err


@contextlib.contextmanager
def _no_process_groups():
    """os without killpg/getpgid, as on Windows."""
    with mock.patch.dict(os.__dict__):
        os.__dict__.pop("killpg", None)
        os.__dict__.pop("getpgid", None)
        yield


def _tree():
    root = tempfile.mkdtemp(prefix="win-start-tree-")
    with open(os.path.join(root, "mod.py"), "w",
              encoding="utf-8") as fh:
        fh.write("VALUE = 7\n")
    return root


class ProbeWindowsStartupTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX-hosted regression")
    def test_old_shape_fails_to_start_under_windows_popen(self):
        # The pre-fix failure, reproduced: limits still requested
        # (os.name posix) but Popen is Windows-like. The result
        # is an error whose detail now names why.
        _WindowsLikePopen.calls = []
        with mock.patch.object(probe.subprocess, "Popen",
                               _WindowsLikePopen):
            res = probe.run_probe(
                {"kind": "python", "code": "print('hi')"},
                _tree(), timeout=30)
        self.assertEqual(res["outcome"], "error")
        self.assertIsNone(res["exit_code"])
        self.assertIn("could not start", res["detail"])
        self.assertIn(_WINDOWS_PREEXEC_ERROR, res["detail"])

    def test_probe_starts_on_windows(self):
        with _windows(probe) as err, _no_process_groups():
            res = probe.run_probe(
                {"kind": "python",
                 "code": "import mod\nassert mod.VALUE == 7\n"
                         "print('started')"},
                _tree(), timeout=30)
        self.assertEqual(res["outcome"], "pass", res)
        self.assertIn("started", res["output"])
        self.assertTrue(_WindowsLikePopen.calls)
        self.assertNotIn("preexec_fn", _WindowsLikePopen.calls[-1])
        self.assertIn("not applied", res["sandbox"]["limits"])
        self.assertIn("POSIX-only", err.getvalue())

    def test_windows_notice_is_printed_once(self):
        with _windows(probe) as err, _no_process_groups():
            for _ in range(2):
                probe.run_probe({"kind": "python", "code": "pass"},
                                _tree(), timeout=30)
        self.assertEqual(err.getvalue().count("POSIX-only"), 1)

    def test_probe_fn_detail_names_a_start_failure(self):
        with mock.patch.object(probe.subprocess, "Popen",
                               side_effect=OSError("no such exe")):
            fn = probe.make_probe_fn(_tree(), timeout=30)
            res = fn({}, {"kind": "command", "argv": ["x"]})
        self.assertEqual(res["outcome"], "error")
        self.assertIn("could not start: no such exe", res["detail"])

    def test_windows_env_carries_startup_variables(self):
        extra = {"SYSTEMROOT": r"C:\Windows", "COMSPEC": "cmd.exe"}
        with mock.patch.dict(os.environ, extra), \
                mock.patch.object(os, "name", "nt"):
            env = probe._sandbox_env("/tmp/x", "/tmp/x/tree")
        self.assertEqual(env["SYSTEMROOT"], r"C:\Windows")
        self.assertEqual(env["COMSPEC"], "cmd.exe")

    @unittest.skipUnless(os.name == "posix", "POSIX-hosted regression")
    def test_posix_env_unchanged(self):
        extra = {"SYSTEMROOT": r"C:\Windows"}
        with mock.patch.dict(os.environ, extra):
            env = probe._sandbox_env("/tmp/x", "/tmp/x/tree")
        self.assertNotIn("SYSTEMROOT", env)

    @unittest.skipUnless(os.name == "posix", "POSIX behaviour")
    def test_posix_still_sets_preexec_fn(self):
        _RecordingPopen.calls = []
        err = io.StringIO()
        with mock.patch.object(probe.subprocess, "Popen",
                               _RecordingPopen), \
                contextlib.redirect_stderr(err):
            res = probe.run_probe({"kind": "python", "code": "pass"},
                                  _tree(), timeout=30)
        self.assertEqual(res["outcome"], "pass")
        self.assertTrue(callable(_RecordingPopen.calls[-1]
                                 .get("preexec_fn")))
        self.assertTrue(_RecordingPopen.calls[-1]
                        .get("start_new_session"))
        self.assertEqual(res["sandbox"]["limits"], "posix-rlimits")
        self.assertNotIn("POSIX-only", err.getvalue())

    @unittest.skipUnless(os.name == "posix", "POSIX behaviour")
    def test_posix_rlimits_still_bind(self):
        res = probe.run_probe(
            {"kind": "python",
             "code": "import resource\n"
                     "print(resource.getrlimit("
                     "resource.RLIMIT_FSIZE)[0])"},
            _tree(), timeout=30)
        self.assertEqual(res["outcome"], "pass")
        self.assertIn(str(probe._PROBE_FILE_SIZE_LIMIT),
                      res["output"])


class EvidenceWindowsStartupTests(unittest.TestCase):
    CONFIG: ClassVar[dict] = {"commands": [{"name": "tests",
                            "command": "echo evidence-ran",
                            "required": True, "timeout": 30}]}

    @unittest.skipUnless(os.name == "posix", "POSIX-hosted regression")
    def test_old_shape_fails_to_start_and_detail_names_it(self):
        _WindowsLikePopen.calls = []
        with mock.patch.object(evidence.subprocess, "Popen",
                               _WindowsLikePopen):
            record = evidence.collect(self.CONFIG, _tree())
        item = record["items"][0]
        self.assertEqual(item["status"], "error")
        self.assertIn(_WINDOWS_PREEXEC_ERROR, item["detail"])
        effect, reasons = evidence.gate_effect(record["items"])
        self.assertEqual(effect, "blocked")
        self.assertIn(_WINDOWS_PREEXEC_ERROR, reasons[0])

    @unittest.skipUnless(shutil.which("sh"), "requires sh on the host")
    def test_evidence_runs_on_windows(self):
        with _windows(evidence) as err, _no_process_groups():
            record = evidence.collect(self.CONFIG, _tree())
        item = record["items"][0]
        self.assertEqual(item["status"], "passed", item)
        self.assertIn("evidence-ran", item["output_tail"])
        self.assertNotIn("preexec_fn", _WindowsLikePopen.calls[-1])
        self.assertIn("not applied",
                      record["sandbox"]["limits"]["rlimits"])
        self.assertIn("POSIX-only", err.getvalue())

    def test_missing_shell_is_clear_and_blocked(self):
        # Real missing-executable failure under the simulated Windows
        # path, including hosts that normally have sh installed.
        with tempfile.TemporaryDirectory() as root, \
                _windows(evidence), _no_process_groups(), \
                mock.patch.object(evidence, "_unshare_ok", return_value=False), \
                mock.patch.dict(os.environ, {"PATH": ""}):
            record = evidence.collect(self.CONFIG, root)
        item = record["items"][0]
        self.assertEqual(item["status"], "error", item)
        self.assertIsNone(item["exit_code"])
        self.assertIn("could not start", item["detail"])
        effect, reasons = evidence.gate_effect(record["items"])
        self.assertEqual(effect, "blocked")
        self.assertTrue(any("could not start" in r for r in reasons))

    def test_claim_rerun_names_a_start_failure(self):
        with mock.patch.object(evidence.subprocess, "Popen",
                               side_effect=OSError("no shell")):
            out = evidence.verify_claims(
                "", _tree(), timeout=30,
                claims=[{"command": "make test", "claimed": "passed",
                         "claimed_exit_code": None, "line": 1}])
        self.assertIn("could not start: no shell",
                      out["claims"][0]["detail"])

    def test_kill_group_without_process_groups_kills_child(self):
        proc = _REAL_POPEN([sys.executable, "-c",
                            "import time; time.sleep(30)"])
        try:
            with _no_process_groups():
                evidence._kill_group(proc)
            self.assertIsNotNone(proc.wait(timeout=10))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    @unittest.skipUnless(os.name == "posix", "POSIX behaviour")
    def test_posix_still_sets_preexec_fn(self):
        _RecordingPopen.calls = []
        with mock.patch.object(evidence.subprocess, "Popen",
                               _RecordingPopen):
            record = evidence.collect(self.CONFIG, _tree())
        self.assertEqual(record["items"][0]["status"], "passed")
        self.assertEqual(record["items"][0]["detail"], "")
        self.assertTrue(callable(_RecordingPopen.calls[-1]
                                 .get("preexec_fn")))
        self.assertEqual(record["sandbox"]["limits"]["rlimits"],
                         "posix-rlimits")

    def test_modules_import_without_resource(self):
        # As on Windows, where `resource` does not exist: the
        # evidence module, and the CLI that imports it, load.
        code = ("import sys; sys.modules['resource'] = None; "
                "sys.path.insert(0, sys.argv[1]); "
                "from codereview import evidence, probe, cli; "
                "assert evidence.resource is None; "
                "assert probe.resource is None; "
                "assert not evidence._posix_limits_available(); "
                "evidence._apply_limits(5); "
                "print('imported')")
        out = subprocess.run(
            [sys.executable, "-I", "-c", code,
             os.path.abspath(SRC)],
            capture_output=True, text=True, timeout=120,
            check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("imported", out.stdout)


class WindowsNativeSmokeTests(unittest.TestCase):
    """Real Windows checks. Never counted as run on POSIX."""

    @unittest.skipUnless(os.name == "nt", "requires native Windows")
    def test_native_python_probe(self):
        with tempfile.TemporaryDirectory() as root:
            res = probe.run_probe(
                {"kind": "python", "code": "print('native-probe-ok')"},
                root, timeout=30)
        self.assertEqual(res["outcome"], "pass", res)
        self.assertIn("native-probe-ok", res["output"])
        self.assertIn("not applied", res["sandbox"]["limits"])

    @unittest.skipUnless(os.name == "nt", "requires native Windows")
    def test_native_missing_shell_is_clear_and_blocked(self):
        # Use an empty PATH even on Windows hosts with Git Bash.
        # The real OS, not a mocked Popen, must reject missing sh.
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.dict(os.environ, {"PATH": ""}):
            record = evidence.collect(
                EvidenceWindowsStartupTests.CONFIG, root)
        item = record["items"][0]
        self.assertEqual(item["status"], "error", item)
        self.assertIsNone(item["exit_code"])
        self.assertIn("could not start", item["detail"])
        effect, reasons = evidence.gate_effect(record["items"])
        self.assertEqual(effect, "blocked")
        self.assertTrue(any("could not start" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
