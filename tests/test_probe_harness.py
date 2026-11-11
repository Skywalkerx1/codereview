"""Probe harness tests (§5.2): sandboxed execution, spec
parsing, env allowlist, timeout, and the probe_fn contract.
No network, no real providers."""

import json
import os
import shutil
import signal
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import probe as probe_mod  # noqa: E402


def _tree(files):
    root = tempfile.mkdtemp(prefix="probe-test-tree-")
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return root


class ParseSpecTests(unittest.TestCase):
    def test_dict_passthrough(self):
        spec = probe_mod.parse_probe_spec(
            {"kind": "python", "code": "pass"})
        self.assertEqual(spec["kind"], "python")

    def test_json_text(self):
        spec = probe_mod.parse_probe_spec(
            '{"kind": "test", "target": "tests/test_x.py"}')
        self.assertEqual(spec["target"], "tests/test_x.py")

    def test_embedded_json_in_prose(self):
        spec = probe_mod.parse_probe_spec(
            'please run {"kind": "command", "argv": ["true"]} '
            'and check')
        self.assertEqual(spec["argv"], ["true"])

    def test_prose_only_is_none(self):
        self.assertIsNone(probe_mod.parse_probe_spec(
            "probe whether the guard exists"))

    def test_bad_shapes_are_none(self):
        self.assertIsNone(probe_mod.parse_probe_spec(
            {"kind": "python"}))
        self.assertIsNone(probe_mod.parse_probe_spec(
            {"kind": "command", "argv": []}))
        self.assertIsNone(probe_mod.parse_probe_spec(
            {"kind": "teleport", "code": "x"}))
        self.assertIsNone(probe_mod.parse_probe_spec(None))
        self.assertIsNone(probe_mod.parse_probe_spec(""))


class RunProbeTests(unittest.TestCase):
    def test_python_probe_sees_tree_copy_and_passes(self):
        root = _tree({"mod.py": "VALUE = 41\n"})
        res = probe_mod.run_probe(
            {"kind": "python",
             "code": "import mod\n"
                     "assert mod.VALUE == 41, mod.VALUE\n"
                     "print('value-ok')"},
            root, timeout=30)
        self.assertEqual(res["outcome"], "pass")
        self.assertIn("value-ok", res["output"])
        self.assertTrue(res["can_rebut"])
        self.assertFalse(res["can_support"])
        self.assertEqual(res["sandbox"]["cwd"], "temp-copy")

    def test_python_probe_failure_is_fail_not_crash(self):
        root = _tree({})
        res = probe_mod.run_probe(
            {"kind": "python", "code": "raise SystemExit(3)"},
            root, timeout=30)
        self.assertEqual(res["outcome"], "fail")
        self.assertEqual(res["exit_code"], 3)

    def test_environment_is_allowlist_no_secrets(self):
        root = _tree({})
        sentinel = "CODEREVIEW_PROBE_TEST_SECRET_SENTINEL"
        os.environ[sentinel] = "must-not-leak"
        try:
            res = probe_mod.run_probe(
                {"kind": "python",
                 "code": "import os\n"
                         f"print('leaked' if os.environ.get("
                         f"'{sentinel}') else 'clean')"},
                root, timeout=30)
        finally:
            del os.environ[sentinel]
        self.assertEqual(res["outcome"], "pass")
        self.assertIn("clean", res["output"])
        self.assertNotIn("must-not-leak", res["output"])

    def test_probe_cannot_mutate_real_tree(self):
        root = _tree({"mod.py": "VALUE = 1\n"})
        res = probe_mod.run_probe(
            {"kind": "python",
             "code": "open('mod.py', 'w').write('VALUE = 2\\n')"},
            root, timeout=30)
        self.assertEqual(res["outcome"], "pass")
        with open(os.path.join(root, "mod.py"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "VALUE = 1\n")

    def test_timeout_bounds_the_probe(self):
        root = _tree({})
        started = time.monotonic()
        res = probe_mod.run_probe(
            {"kind": "python",
             "code": "import time\ntime.sleep(30)"},
            root, timeout=2)
        self.assertEqual(res["outcome"], "timeout")
        self.assertLess(time.monotonic() - started, 15)

    def test_command_and_test_kinds(self):
        # The test kind targets a real unittest file and runs
        # it through the runner (4cf81c69d7cf — it used to
        # execute the target as a plain script, which is the
        # defective contract this test previously encoded).
        root = _tree({"tests/test_check.py":
                      "import unittest\n\n\n"
                      "class CheckTest(unittest.TestCase):\n"
                      "    def test_ok(self):\n"
                      "        print('test-kind-ok')\n"
                      "        self.assertTrue(True)\n"})
        res = probe_mod.run_probe(
            {"kind": "test", "target": "tests/test_check.py"},
            root, timeout=30)
        self.assertEqual(res["outcome"], "pass")
        self.assertIn("test-kind-ok", res["output"])
        res = probe_mod.run_probe(
            {"kind": "command", "argv": [sys.executable, "-c",
                                          "print('cmd-ok')"]},
            root, timeout=30)
        self.assertEqual(res["outcome"], "pass")
        self.assertIn("cmd-ok", res["output"])

    def test_output_is_hashed(self):
        root = _tree({})
        res = probe_mod.run_probe(
            {"kind": "python", "code": "print('x')"}, root,
            timeout=30)
        self.assertEqual(len(res["output_sha256"]), 64)


_FAILING_TEST = ("import unittest\n\n\n"
                 "class DemoTest(unittest.TestCase):\n"
                 "    def test_arithmetic(self):\n"
                 "        self.assertEqual(1, 2)\n")
_MAIN_GUARD = ('\n\nif __name__ == "__main__":\n'
               "    unittest.main()\n")


class ProbeTreeCopyTests(unittest.TestCase):
    """L6 F1/F2: the probe's tree copy must preserve symlinks
    (never dereference them into the sandbox copy — parity with
    evidence._copy_tree), and a copy failure must surface as an
    `error` OUTCOME, never as an exception escaping run_probe
    (its contract: probe failures are outcomes, not crashes)."""

    def _outside_file(self, text="TOPSECRET-OUTSIDE"):
        fd, path = tempfile.mkstemp(prefix="probe-outside-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.unlink, path)
        return path

    def test_symlink_to_outside_file_is_copied_as_link(self):
        outside = self._outside_file()
        root = _tree({"real.txt": "hello\n"})
        self.addCleanup(shutil.rmtree, root, True)
        os.symlink(outside, os.path.join(root, "link.txt"))
        res = probe_mod.run_probe(
            {"kind": "python",
             "code": "import os; print(os.path.islink('link.txt'))"},
            root, timeout=30)
        self.assertEqual(res["outcome"], "pass")
        self.assertIn("True", res["output"])

    def test_dangling_symlink_does_not_escape_run_probe(self):
        root = _tree({"real.txt": "hello\n"})
        self.addCleanup(shutil.rmtree, root, True)
        os.symlink("/nonexistent/definitely-missing",
                   os.path.join(root, "link.txt"))
        res = probe_mod.run_probe(
            {"kind": "python",
             "code": "import os; print(os.path.islink('link.txt'))"},
            root, timeout=30)
        # No exception; the link arrives in the copy as a link.
        self.assertEqual(res["outcome"], "pass")
        self.assertIn("True", res["output"])

    def test_special_file_symlink_is_not_streamed_into_copy(self):
        if not os.path.exists("/dev/zero"):
            self.skipTest("no /dev/zero on this platform")
        root = _tree({"real.txt": "hello\n"})
        self.addCleanup(shutil.rmtree, root, True)
        os.symlink("/dev/zero", os.path.join(root, "zero"))
        res = probe_mod.run_probe(
            {"kind": "python",
             "code": "import os; print(os.path.islink('zero'))"},
            root, timeout=30)
        self.assertEqual(res["outcome"], "pass")
        self.assertIn("True", res["output"])

    def test_copy_failure_is_an_error_outcome(self):
        root = _tree({"real.txt": "hello\n"})
        self.addCleanup(shutil.rmtree, root, True)
        with mock.patch("shutil.copytree",
                        side_effect=shutil.Error("boom")):
            res = probe_mod.run_probe(
                {"kind": "python", "code": "print('x')"}, root,
                timeout=30)
        self.assertEqual(res["outcome"], "error")
        self.assertIn("copy", res["detail"])


class TestKindRunnerTests(unittest.TestCase):
    """4cf81c69d7cf regression: kind-'test' probes execute
    through the test runner, so a target's verdict no longer
    depends on a __main__ guard the contract never required,
    and a zero-test run is never a pass."""

    def test_guarded_and_unguarded_failing_test_agree(self):
        # The packet's two-way repro: the SAME failing
        # unittest, with and without the guard, must produce
        # the same probe verdict.
        for body in (_FAILING_TEST, _FAILING_TEST + _MAIN_GUARD):
            root = _tree({"tests/test_demo.py": body})
            res = probe_mod.run_probe(
                {"kind": "test",
                 "target": "tests/test_demo.py"}, root,
                timeout=30)
            self.assertEqual(res["outcome"], "fail")
            self.assertEqual(res["exit_code"], 1)
            self.assertIn("Ran 1 test", res["output"])

    def test_unguarded_passing_test_passes_via_runner(self):
        body = _FAILING_TEST.replace("self.assertEqual(1, 2)",
                                     "self.assertEqual(1, 1)")
        root = _tree({"tests/test_demo.py": body})
        res = probe_mod.run_probe(
            {"kind": "test", "target": "tests/test_demo.py"},
            root, timeout=30)
        self.assertEqual(res["outcome"], "pass")
        self.assertIn("Ran 1 test", res["output"])

    def test_zero_test_target_is_not_a_pass(self):
        root = _tree({"tests/test_empty.py":
                      "import unittest\n\n\nVALUE = 1\n"})
        res = probe_mod.run_probe(
            {"kind": "test", "target": "tests/test_empty.py"},
            root, timeout=30)
        self.assertEqual(res["outcome"], "error")
        self.assertIn("zero tests", res["output"])


class ProbeFnContractTests(unittest.TestCase):
    def test_unexecutable_request_is_inconclusive(self):
        fn = probe_mod.make_probe_fn(_tree({}))
        out = fn({"id": "x"}, "check the guard somehow")
        self.assertEqual(out["outcome"], "inconclusive")
        self.assertIn("machine-executable", out["detail"])

    def test_executable_request_runs(self):
        fn = probe_mod.make_probe_fn(_tree({}))
        out = fn({"id": "x"},
                 {"kind": "python", "code": "print('ran')"})
        self.assertEqual(out["outcome"], "pass")
        self.assertEqual(out["evidence_quote"], "ran")
        self.assertIn("sha256", out["detail"])
        self.assertFalse(out["can_support"])


def _pid_alive(pid):
    """True when `pid` names a live process. A zombie is
    dead for our purposes: it runs nothing and holds no
    resources but its exit status."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as fh:
            state = fh.read().rsplit(")", 1)[-1].split()[0]
    except OSError:
        return True  # kill() said it exists; cannot refine
    return state != "Z"


def _wait_until_dead(pid, budget_s=10.0):
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.1)
    return not _pid_alive(pid)


@unittest.skipUnless(
    os.name == "posix" and probe_mod.resource is not None,
    "C5 sandbox discipline is POSIX-rlimit based")
class SandboxHardeningTests(unittest.TestCase):
    """The C5 pins: the probe runs in its own session under
    rlimits, expiry or exit kills its whole process group,
    and output is drained under a cap. A probe that forks,
    spins, or allocates past its budget is terminated and
    lands in the harness's long-standing outcome vocabulary
    (pass/fail/timeout/error) — never a new category."""

    def test_limits_applied_inside_probe(self):
        # A compliant probe runs normally and can observe
        # the exact limits the sandbox promised: CPU is the
        # wall timeout plus the C5 slack, the rest are the
        # module's named constants.
        root = _tree({})
        res = probe_mod.run_probe(
            {"kind": "python",
             "code": "import resource\n"
                     "print('cpu', resource.getrlimit("
                     "resource.RLIMIT_CPU)[0])\n"
                     "print('as', resource.getrlimit("
                     "resource.RLIMIT_AS)[0])\n"
                     "print('fsize', resource.getrlimit("
                     "resource.RLIMIT_FSIZE)[0])\n"
                     "print('nofile', resource.getrlimit("
                     "resource.RLIMIT_NOFILE)[0])\n"},
            root, timeout=30)
        self.assertEqual(res["outcome"], "pass")
        self.assertIn(f"cpu {30 + probe_mod._CPU_SLACK_S}",
                      res["output"])
        if probe_mod._memory_cap_enforced():
            self.assertIn(f"as {probe_mod._PROBE_MEMORY_LIMIT}",
                          res["output"])
            self.assertEqual(
                res["sandbox"]["memory_cap"],
                f"RLIMIT_AS {probe_mod._PROBE_MEMORY_LIMIT} bytes")
        else:
            # macOS does not enforce RLIMIT_AS: the result must
            # say the cap is absent instead of claiming it.
            self.assertIn("not enforced",
                          res["sandbox"]["memory_cap"])
        self.assertIn(
            f"fsize {probe_mod._PROBE_FILE_SIZE_LIMIT}",
            res["output"])
        self.assertIn(
            f"nofile {probe_mod._PROBE_OPEN_FILES_LIMIT}",
            res["output"])

    def test_timeout_kills_forked_child(self):
        # The pre-C5 harness killed only the direct child on
        # timeout: this forked sleeper would have survived
        # it. The group kill must reap it too.
        marker_dir = tempfile.mkdtemp(prefix="probe-marker-")
        marker = os.path.join(marker_dir, "child.pid")
        root = _tree({})
        started = time.monotonic()
        res = probe_mod.run_probe(
            {"kind": "python",
             "code": "import os, time\n"
                     f"MARKER = {marker!r}\n"
                     "pid = os.fork()\n"
                     "if pid == 0:\n"
                     "    with open(MARKER, 'w') as fh:\n"
                     "        fh.write(str(os.getpid()))\n"
                     "    time.sleep(120)\n"
                     "    os._exit(0)\n"
                     "time.sleep(120)\n"},
            root, timeout=2)
        self.assertEqual(res["outcome"], "timeout")
        self.assertLess(time.monotonic() - started, 20)
        with open(marker, encoding="ascii") as fh:
            child_pid = int(fh.read().strip())
        self.assertTrue(
            _wait_until_dead(child_pid),
            f"forked probe child {child_pid} survived the "
            f"timeout kill")

    def test_clean_exit_leaves_no_background_child(self):
        # The P3-06 shape: the probe backgrounds a child
        # with redirected stdio (so it holds no harness
        # pipe) and exits 0 at once. The run passes — and
        # the group kill on the normal path must still reap
        # the child, or it would sleep on for 120 s.
        marker_dir = tempfile.mkdtemp(prefix="probe-marker-")
        marker = os.path.join(marker_dir, "child.pid")
        sink = os.path.join(marker_dir, "sink.txt")
        root = _tree({})
        res = probe_mod.run_probe(
            {"kind": "python",
             "code": "import os, time\n"
                     f"MARKER = {marker!r}\n"
                     f"SINK = {sink!r}\n"
                     "pid = os.fork()\n"
                     "if pid == 0:\n"
                     "    fd = os.open(SINK, os.O_WRONLY | "
                     "os.O_CREAT | os.O_TRUNC)\n"
                     "    os.dup2(fd, 1)\n"
                     "    os.dup2(fd, 2)\n"
                     "    with open(MARKER, 'w') as fh:\n"
                     "        fh.write(str(os.getpid()))\n"
                     "    time.sleep(120)\n"
                     "    os._exit(0)\n"
                     "print('parent-done')\n"},
            root, timeout=30)
        self.assertEqual(res["outcome"], "pass")
        self.assertIn("parent-done", res["output"])
        with open(marker, encoding="ascii") as fh:
            child_pid = int(fh.read().strip())
        self.assertTrue(
            _wait_until_dead(child_pid),
            f"backgrounded probe child {child_pid} survived "
            f"a passed run")

    def test_cpu_limit_kills_spinning_probe(self):
        # The CPU budget is timeout + _CPU_SLACK_S (the C5
        # convention): with the shipped slack a CPU kill can
        # only beat the wall clock for a probe burning
        # several cores at once, so this pin narrows the
        # slack to bring the budget inside the run and
        # verifies the mechanism end to end — the child is
        # rlimited, the kernel kills it at the budget
        # (SIGXCPU), and the harness reports the signal
        # death as an ordinary "fail" whose exit code is
        # the negative signal number. The shipped budget
        # arithmetic itself is pinned unpatched by
        # test_limits_applied_inside_probe.
        root = _tree({})
        real_slack = probe_mod._CPU_SLACK_S
        probe_mod._CPU_SLACK_S = -25  # budget: 30 - 25 = 5 s
        try:
            started = time.monotonic()
            res = probe_mod.run_probe(
                {"kind": "python",
                 "code": "while True:\n    pass\n"},
                root, timeout=30)
            elapsed = time.monotonic() - started
        finally:
            probe_mod._CPU_SLACK_S = real_slack
        self.assertEqual(res["outcome"], "fail")
        expected = {-int(signal.SIGKILL)}
        if hasattr(signal, "SIGXCPU"):
            expected.add(-int(signal.SIGXCPU))
        self.assertIn(res["exit_code"], expected)
        # Killed at its 5 CPU-second budget, nowhere near
        # the 30 s wall timeout.
        self.assertGreater(elapsed, 3)
        self.assertLess(elapsed, 20)

    @unittest.skipUnless(
        probe_mod._memory_cap_enforced(),
        "this platform does not enforce RLIMIT_AS (macOS); the "
        "probe reports its memory as uncapped instead — see "
        "test_macos_reports_memory_cap_not_enforced")
    def test_memory_limit_bounds_allocation(self):
        # The probe reserves anonymous address space in
        # 256 MiB chunks (reservation alone does not touch
        # RSS). With no AS limit this box would let it
        # reserve the full 10 GiB demand; the sandbox
        # ceiling must stop it at the named limit, and the
        # probe dies at the ceiling — an ordinary "fail".
        root = _tree({})
        res = probe_mod.run_probe(
            {"kind": "python",
             "code": "import mmap, resource\n"
                     "limit = resource.getrlimit("
                     "resource.RLIMIT_AS)[0]\n"
                     "print('as-limit', limit)\n"
                     "chunk = 256 * 1024 * 1024\n"
                     "chunks = []\n"
                     "try:\n"
                     "    for _ in range(40):\n"
                     "        chunks.append("
                     "mmap.mmap(-1, chunk))\n"
                     "    print('no-ceiling')\n"
                     "    raise SystemExit(0)\n"
                     "except (OSError, MemoryError):\n"
                     "    print('ceiling-hit reserved', "
                     "len(chunks) * chunk)\n"
                     "    raise SystemExit(1)\n"},
            root, timeout=30)
        self.assertEqual(res["outcome"], "fail")
        self.assertEqual(res["exit_code"], 1)
        self.assertIn(
            f"as-limit {probe_mod._PROBE_MEMORY_LIMIT}",
            res["output"])
        self.assertIn("ceiling-hit", res["output"])
        self.assertNotIn("no-ceiling", res["output"])
        reserved = int(res["output"].split(
            "ceiling-hit reserved ")[1].split()[0])
        self.assertLessEqual(reserved,
                             probe_mod._PROBE_MEMORY_LIMIT)
        self.assertGreater(reserved,
                           probe_mod._PROBE_MEMORY_LIMIT
                           * 3 // 4)

    def test_macos_reports_memory_cap_not_enforced(self):
        # Runs on every POSIX host: with the platform reported
        # as macOS, the result and the probe_fn detail must
        # both say the memory cap is not enforced — never the
        # 2 GiB figure the platform would silently ignore.
        with mock.patch.object(probe_mod.sys, "platform",
                               "darwin"):
            self.assertFalse(probe_mod._memory_cap_enforced())
        root = _tree({})
        with mock.patch.object(probe_mod, "_memory_cap_enforced",
                               return_value=False):
            res = probe_mod.make_probe_fn(root, timeout=30)(
                {}, {"kind": "python", "code": "print('ok')"})
        self.assertEqual(res["outcome"], "pass")
        self.assertIn("not enforced",
                      res["sandbox"]["memory_cap"])
        self.assertNotIn(str(probe_mod._PROBE_MEMORY_LIMIT),
                         res["sandbox"]["memory_cap"])
        self.assertIn("memory cap not enforced", res["detail"])

    def test_file_size_limit_blocks_oversize_write(self):
        # A write that would extend a file past
        # RLIMIT_FSIZE fails (EFBIG) instead of landing:
        # the probe dies on the traceback — an ordinary
        # "fail" — and no oversize file exists.
        root = _tree({})
        res = probe_mod.run_probe(
            {"kind": "python",
             "code": "import os\n"
                     "fd = os.open('big.bin', os.O_WRONLY | "
                     "os.O_CREAT)\n"
                     "os.lseek(fd, "
                     f"{probe_mod._PROBE_FILE_SIZE_LIMIT} + "
                     "1024 * 1024, os.SEEK_SET)\n"
                     "os.write(fd, b'x')\n"
                     "print('write-survived')\n"},
            root, timeout=30)
        self.assertEqual(res["outcome"], "fail")
        self.assertIn("File too large", res["output"])
        self.assertNotIn("write-survived", res["output"])

    def test_spewing_probe_output_is_drained_and_capped(self):
        # 9 MiB of stdout exceeds the per-stream capture
        # cap: the drainer must keep pulling (the probe
        # never blocks on a full pipe, the harness's memory
        # never holds more than the cap), and the stored
        # output keeps the harness's long-standing
        # _OUTPUT_CAP truncation.
        root = _tree({})
        res = probe_mod.run_probe(
            {"kind": "python",
             "code": "import sys\n"
                     "sys.stdout.write('x' * (9 * 1024 * 1024)"
                     ")\n"},
            root, timeout=30)
        self.assertEqual(res["outcome"], "pass")
        self.assertEqual(len(res["output"]),
                         probe_mod._OUTPUT_CAP)
        self.assertEqual(set(res["output"]), {"x"})


if __name__ == "__main__":
    unittest.main()
