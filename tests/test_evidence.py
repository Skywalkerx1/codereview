"""Epic C — evidence runner (tickets C1–C5).

C1: configured commands run in a sandboxed working copy; the
record carries exit code, output hash, and duration.
C2: adapters (gitleaks, semgrep, dependency audit) skip cleanly
as `unavailable` when their tool is absent; a policy `require`
list turns an absent tool into a `missing` record.
C3: the gate rule — required evidence failed/timeout/error/
missing blocks; required-but-unavailable is inconclusive —
tested as a pure function over every state, and end-to-end
through run_review.
C4: builder claims are parsed from a work report, re-run in the
sandbox, and downgraded when the re-run contradicts them.
C5: sandbox safety — the child environment is allow-listed
(operator secrets never cross), HOME/TMPDIR point inside the
sandbox, commands run in a throwaway copy (never the reviewed
tree), the copy is deleted, and a runaway command is killed at
its timeout.

Fake adapter tools are tiny shell scripts placed on a test PATH;
no real scanner is needed and none is installed on this machine.
"""

import hashlib
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core, evidence  # noqa: E402


def _tree(files):
    """A temp working tree with the given {relpath: content}."""
    root = tempfile.mkdtemp(prefix="evidence-src-")
    for rel, content in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    return root


def _fake_tool(bindir, name, script):
    path = os.path.join(bindir, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n" + script)
    os.chmod(path, 0o755)
    return path


def _env_with_path(bindir):
    return {"PATH": bindir + os.pathsep + os.environ["PATH"]}


class CollectCommandTests(unittest.TestCase):
    """C1 — commands, records, hashes, timeouts."""

    def test_passing_command_recorded_with_hash_and_duration(self):
        src = _tree({"app.py": "print('hi')\n"})
        record = evidence.collect(
            {"commands": [{"name": "greet",
                           "command": "echo hello-evidence"}]},
            src)
        (item,) = record["items"]
        self.assertEqual(item["status"], "passed")
        self.assertEqual(item["exit_code"], 0)
        self.assertEqual(
            item["output_sha256"],
            hashlib.sha256(b"hello-evidence\n").hexdigest())
        self.assertGreaterEqual(item["duration_s"], 0)
        self.assertTrue(item["required"])  # commands default required
        self.assertEqual(record["schema"], "codereview.evidence/1")
        self.assertEqual(record["sandbox"]["kind"].split()[0],
                         "temp-copy")

    def test_failing_command_is_failed_not_raised(self):
        src = _tree({"app.py": "x\n"})
        record = evidence.collect(
            {"commands": [{"name": "boom", "command": "exit 3"}]},
            src)
        (item,) = record["items"]
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["exit_code"], 3)

    def test_timeout_is_enforced_and_recorded(self):
        src = _tree({"app.py": "x\n"})
        started = time.monotonic()
        record = evidence.collect(
            {"commands": [{"name": "slow", "command": "sleep 30",
                           "timeout": 1}]},
            src)
        self.assertLess(time.monotonic() - started, 20)
        (item,) = record["items"]
        self.assertEqual(item["status"], "timeout")
        self.assertIsNone(item["exit_code"])

    def test_commands_run_in_the_copy_not_the_source(self):
        src = _tree({"app.py": "x\n"})
        record = evidence.collect(
            {"commands": [{"name": "mutate",
                           "command": "echo changed >> app.py "
                                      "&& echo done > made.txt"}]},
            src)
        (item,) = record["items"]
        self.assertEqual(item["status"], "passed")
        with open(os.path.join(src, "app.py"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "x\n")  # source untouched
        self.assertFalse(os.path.exists(os.path.join(src,
                                                     "made.txt")))

    def test_git_dir_is_not_copied(self):
        src = _tree({".git/HEAD": "ref: refs/heads/main\n",
                     "app.py": "x\n"})
        record = evidence.collect(
            {"commands": [{"name": "probe",
                           "command": "test ! -e .git && echo clean"}]},
            src)
        (item,) = record["items"]
        self.assertEqual(item["status"], "passed")
        self.assertIn("clean", item["output_tail"])

    def test_missing_source_tree_records_error_items(self):
        record = evidence.collect(
            {"commands": [{"name": "t", "command": "true"}]},
            "/nonexistent/path/that/does/not/exist")
        (item,) = record["items"]
        self.assertEqual(item["status"], "error")
        self.assertIn("sandbox copy failed", item["detail"])


class SandboxSafetyTests(unittest.TestCase):
    """C5 — environment scrubbing and sandbox placement."""

    def test_operator_secrets_never_reach_the_child(self):
        src = _tree({"app.py": "x\n"})
        marker = "s3" + "cr" + "et" + "-marker-value"
        environ = {"PATH": os.environ["PATH"],
                   "OPERATOR_ONLY_MARKER": marker}
        record = evidence.collect(
            {"commands": [{
                "name": "envprobe",
                "command": "echo MARKER=${OPERATOR_ONLY_MARKER:-"
                           "ABSENT}; echo HOME=$HOME; "
                           "echo TMP=$TMPDIR"}]},
            src, environ=environ)
        (item,) = record["items"]
        self.assertIn("MARKER=ABSENT", item["output_tail"])
        self.assertNotIn(marker, item["output_tail"])
        home_line = [ln for ln in item["output_tail"].splitlines()
                     if ln.startswith("HOME=")][0]
        self.assertIn("codereview-evidence-", home_line)
        self.assertNotEqual(
            home_line, "HOME=" + os.path.expanduser("~"))

    def test_no_network_default_is_recorded_honestly(self):
        src = _tree({"app.py": "x\n"})
        record = evidence.collect(
            {"commands": [{"name": "t", "command": "true"}]}, src)
        (item,) = record["items"]
        # The mode must be one of the honest values: a namespace
        # where unshare works, env-only restriction where not —
        # never a bare claim of "off" with no mechanism.
        self.assertIn(item["network_mode"],
                      ("namespace", "env-only"))
        self.assertEqual(record["sandbox"]["network"],
                         item["network_mode"])

    def test_allow_network_opt_in_is_recorded(self):
        src = _tree({"app.py": "x\n"})
        record = evidence.collect(
            {"commands": [{"name": "t", "command": "true",
                           "allow_network": True}]}, src)
        (item,) = record["items"]
        self.assertEqual(item["network_mode"], "allowed")


class AdapterTests(unittest.TestCase):
    """C2 — adapters skip cleanly; policy can require presence."""

    def setUp(self):
        self.bindir = tempfile.mkdtemp(prefix="evidence-bin-")
        self.src = _tree({"app.py": "x\n"})

    def test_absent_adapter_is_unavailable_never_a_crash(self):
        record = evidence.collect(
            {"adapters": [{"name": "gitleaks", "required": True}]},
            self.src, environ={"PATH": self.bindir})
        (item,) = record["items"]
        self.assertEqual(item["status"], "unavailable")
        self.assertIn("not found on PATH", item["detail"])
        self.assertIsNone(item["exit_code"])

    def test_present_adapter_runs_and_passes(self):
        _fake_tool(self.bindir, "gitleaks", "echo no-leaks; exit 0\n")
        record = evidence.collect(
            {"adapters": [{"name": "gitleaks"}]},
            self.src, environ=_env_with_path(self.bindir))
        (item,) = record["items"]
        self.assertEqual(item["status"], "passed")
        self.assertIn("no-leaks", item["output_tail"])
        self.assertFalse(item["required"])  # adapters default optional

    def test_adapter_findings_exit_nonzero_is_failed(self):
        _fake_tool(self.bindir, "gitleaks",
                   "echo leak-found; exit 1\n")
        record = evidence.collect(
            {"adapters": [{"name": "gitleaks", "required": True}]},
            self.src, environ=_env_with_path(self.bindir))
        (item,) = record["items"]
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["exit_code"], 1)

    def test_semgrep_adapter_with_fake_tool(self):
        _fake_tool(self.bindir, "semgrep", "echo scanned; exit 0\n")
        record = evidence.collect(
            {"adapters": [{"name": "semgrep"}]},
            self.src, environ=_env_with_path(self.bindir))
        (item,) = record["items"]
        self.assertEqual(item["status"], "passed")

    def test_dependency_audit_unavailable_without_tools(self):
        record = evidence.collect(
            {"adapters": [{"name": "dependency-audit"}]},
            self.src, environ={"PATH": self.bindir})
        (item,) = record["items"]
        self.assertEqual(item["status"], "unavailable")
        self.assertIn("osv-scanner", item["detail"])

    def test_dependency_audit_uses_npm_when_package_json(self):
        _fake_tool(self.bindir, "npm",
                   "echo '{\"vulnerabilities\":{}}'; exit 0\n")
        src = _tree({"package.json": "{}\n"})
        record = evidence.collect(
            {"adapters": [{"name": "dependency-audit"}]},
            src, environ=_env_with_path(self.bindir))
        (item,) = record["items"]
        self.assertEqual(item["status"], "passed")

    def test_policy_require_of_unconfigured_name_is_missing(self):
        record = evidence.collect(
            {"commands": [{"name": "tests", "command": "true"}],
             "require": ["gitleaks"]},
            self.src)
        missing = [i for i in record["items"]
                   if i["status"] == "missing"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["name"], "gitleaks")
        self.assertTrue(missing[0]["required"])

    def test_unknown_adapter_rejected_at_load(self):
        with self.assertRaises(ValueError):
            evidence.validate_config(
                {"adapters": [{"name": "not-a-tool"}]})


class GateEffectTests(unittest.TestCase):
    """C3 — every state of the gate rule, as a pure function."""

    def _item(self, status, required=True):
        return {"name": "ev", "required": required,
                "status": status, "detail": ""}

    def test_passed_required_evidence_does_not_move_gate(self):
        self.assertEqual(
            evidence.gate_effect([self._item("passed")]),
            (None, []))

    def test_failed_required_blocks(self):
        effect, reasons = evidence.gate_effect(
            [self._item("failed")])
        self.assertEqual(effect, "blocked")
        self.assertIn("failed", reasons[0])

    def test_timeout_and_error_and_missing_block(self):
        for status in ("timeout", "error", "missing"):
            effect, _ = evidence.gate_effect(
                [self._item(status)])
            self.assertEqual(effect, "blocked", status)

    def test_unavailable_required_is_inconclusive(self):
        effect, reasons = evidence.gate_effect(
            [self._item("unavailable")])
        self.assertEqual(effect, "inconclusive")
        self.assertIn("unavailable", reasons[0])

    def test_optional_items_never_move_the_gate(self):
        for status in evidence.STATUSES:
            effect, _ = evidence.gate_effect(
                [self._item(status, required=False)])
            self.assertIsNone(effect, status)

    def test_blocked_wins_over_inconclusive(self):
        effect, reasons = evidence.gate_effect(
            [self._item("unavailable"), self._item("failed")])
        self.assertEqual(effect, "blocked")
        self.assertEqual(len(reasons), 2)


class RunReviewEvidenceTests(unittest.TestCase):
    """C3 end-to-end: the record lands in the run JSON and the
    gate moves — and only ever in the blocking direction."""

    PATCH = ("diff --git a/app.py b/app.py\n"
             "--- a/app.py\n"
             "+++ b/app.py\n"
             "@@ -1,1 +1,1 @@\n"
             "-x = 1\n"
             "+x = 2\n")

    def _run(self, evidence_record):
        def ok_provider(_prompt):
            return json.dumps({"verdict": "pass", "summary": "fine",
                               "findings": []})
        return core.run_review(
            self.PATCH,
            {"a": ok_provider, "b": ok_provider},
            evidence=evidence_record)

    def _record(self, status, required=True):
        return {"schema": "codereview.evidence/1",
                "items": [{"name": "tests", "kind": "command",
                           "required": required, "status": status,
                           "exit_code": 0, "duration_s": 0.1,
                           "output_sha256": "0" * 64,
                           "output_tail": "", "detail": "",
                           "command": "true",
                           "network_mode": "env-only"}]}

    def test_no_evidence_no_evidence_key(self):
        report = self._run(None)
        self.assertNotIn("evidence", report)
        self.assertEqual(report["gate"], "pass")

    def test_passing_evidence_recorded_gate_unchanged(self):
        report = self._run(self._record("passed"))
        self.assertEqual(report["gate"], "pass")
        self.assertEqual(report["evidence"]["items"][0]["status"],
                         "passed")

    def test_failed_required_evidence_blocks_a_passing_panel(self):
        report = self._run(self._record("failed"))
        self.assertEqual(report["gate"], "blocked")
        self.assertTrue(any("required evidence" in r
                            for r in report["gate_reasons"]))

    def test_unavailable_required_evidence_is_inconclusive(self):
        report = self._run(self._record("unavailable"))
        self.assertEqual(report["gate"], "inconclusive")

    def test_missing_required_evidence_blocks(self):
        report = self._run(self._record("missing"))
        self.assertEqual(report["gate"], "blocked")


class ClaimTests(unittest.TestCase):
    """C4 — parse, re-run, compare; mismatch downgrades."""

    def test_parse_documented_forms(self):
        text = ("Ran `make test` — passed\n"
                "Tests: make lint (exit 0)\n"
                "- Command: make build — failed\n"
                "I ran some other commands too.\n")
        claims = evidence.parse_claims(text)
        self.assertEqual(
            [(c["command"], c["claimed"]) for c in claims],
            [("make test", "passed"), ("make lint", "passed"),
             ("make build", "failed")])
        self.assertEqual(claims[1]["claimed_exit_code"], 0)
        self.assertEqual(claims[0]["line"], 1)

    def test_command_without_outcome_is_not_a_claim(self):
        self.assertEqual(
            evidence.parse_claims("Ran `make test` afterwards.\n"),
            [])

    def test_outcome_word_inside_command_is_not_a_claim(self):
        # 'error' is part of the command, not a claimed outcome.
        claims = evidence.parse_claims(
            "Command: grep error app.log — passed\n")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["claimed"], "passed")
        self.assertEqual(claims[0]["command"],
                         "grep error app.log")

    def test_true_claim_confirmed_false_claim_downgraded(self):
        src = _tree({"app.py": "x\n", "check.sh": "exit 3\n"})
        text = ("Ran `true` — passed\n"
                "Ran `false` — passed\n"
                "Tests: sh check.sh (exit 3)\n")
        result = evidence.verify_claims(text, src)
        by_cmd = {c["command"]: c for c in result["claims"]}
        self.assertEqual(by_cmd["true"]["status"], "confirmed")
        self.assertEqual(by_cmd["false"]["status"], "downgraded")
        self.assertIn("re-run exited 1",
                      by_cmd["false"]["detail"])
        self.assertEqual(by_cmd["sh check.sh"]["status"],
                         "confirmed")
        self.assertEqual(by_cmd["sh check.sh"]["actual_exit_code"],
                         3)
        self.assertEqual(result["summary"],
                         {"total": 3, "confirmed": 2,
                          "downgraded": 1, "error": 0})

    def test_claimed_failure_that_now_passes_is_downgraded(self):
        src = _tree({"app.py": "x\n"})
        result = evidence.verify_claims("Ran `true` — failed\n",
                                        src)
        (claim,) = result["claims"]
        self.assertEqual(claim["status"], "downgraded")

    def test_claims_run_in_sandbox_not_source(self):
        src = _tree({"app.py": "x\n"})
        result = evidence.verify_claims(
            "Ran `echo pwned >> app.py` — passed\n", src)
        (claim,) = result["claims"]
        self.assertEqual(claim["status"], "confirmed")
        with open(os.path.join(src, "app.py"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "x\n")


class ClaimedOutcomeReadingTests(unittest.TestCase):
    """P2-06 — counts and negation are read before the bare
    word search: "12 passed, 0 failed" is a pass claim, "did
    not fail" is a pass claim, "0 errors" is a pass claim."""

    def outcome(self, text):
        result = evidence._claimed_outcome(text)
        return result[0] if result else None

    def test_counts_with_zero_failures_pass(self):
        self.assertEqual(self.outcome("12 passed, 0 failed"),
                         "passed")

    def test_negated_failure_passes(self):
        self.assertEqual(self.outcome("did not fail"), "passed")
        self.assertEqual(self.outcome("no failures"), "passed")
        self.assertEqual(self.outcome("never failed"), "passed")

    def test_zero_errors_is_a_pass_claim(self):
        self.assertEqual(self.outcome("0 errors"), "passed")

    def test_controls_stay(self):
        self.assertEqual(self.outcome("3 failed"), "failed")
        self.assertEqual(self.outcome("all passed"), "passed")
        self.assertEqual(self.outcome("2 passed, 1 failed"),
                         "failed")
        self.assertEqual(self.outcome("5 errors"), "failed")
        self.assertEqual(self.outcome("(exit 0)"), "passed")

    def test_parse_level_zero_errors_claim_exists(self):
        claims = evidence.parse_claims(
            "Ran `make test` — 0 errors\n")
        self.assertEqual(
            [(c["command"], c["claimed"]) for c in claims],
            [("make test", "passed")])


class TrailingOutcomePerformanceTests(unittest.TestCase):
    """P2-07 — a labelled line ending in a long separator run
    must parse in linear time (the old separator-run regex
    backtracked quadratically: ~12s at 12KB)."""

    def test_long_separator_run_parses_fast(self):
        import time
        line = "Ran: make test" + " - " * 4000 + "passed\n"
        start = time.perf_counter()
        claims = evidence.parse_claims(line)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 2.0)
        self.assertEqual(
            [(c["command"], c["claimed"]) for c in claims],
            [("make test", "passed")])


class ConfigLoadTests(unittest.TestCase):
    def test_load_config_roundtrip_and_errors(self):
        path = os.path.join(_tree({}), "cfg.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"commands": [{"command": "true"}]}, fh)
        self.assertEqual(evidence.load_config(path)["commands"],
                         [{"command": "true"}])
        with self.assertRaises(ValueError):
            evidence.load_config(path + ".missing")
        bad = path + ".bad"
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        with self.assertRaises(ValueError):
            evidence.load_config(bad)
        with self.assertRaises(ValueError):
            evidence.validate_config(
                {"commands": [{"name": "no-command"}]})


class EvidenceMainTests(unittest.TestCase):
    def test_collect_failure_returns_2_not_traceback(self):
        # 934fab88a12e: a config value that passes validation
        # and fails inside collect (a numeric-string timeout
        # reaches Popen as a str) is a subcommand error —
        # exit 2, never an exception out of _evidence_main.
        import contextlib
        import io
        from codereview import cli
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "evidence.json")
            with open(cfg, "w", encoding="utf-8") as fh:
                json.dump({"commands": [{"name": "t",
                                         "command": "true",
                                         "timeout": "10"}]}, fh)
            with contextlib.redirect_stderr(io.StringIO()):
                rc = cli._evidence_main(
                    ["--repo", td, "--config", cfg,
                     "--out", os.path.join(td, "out")])
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
