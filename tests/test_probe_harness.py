"""Probe harness tests (§5.2): sandboxed execution, spec
parsing, env allowlist, timeout, and the probe_fn contract.
No network, no real providers."""

import json
import os
import sys
import tempfile
import time
import unittest

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
        root = _tree({"check.py": "print('test-kind-ok')\n"})
        res = probe_mod.run_probe(
            {"kind": "test", "target": "check.py"}, root,
            timeout=30)
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


if __name__ == "__main__":
    unittest.main()
