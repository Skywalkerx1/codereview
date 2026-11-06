"""Verdict record schema v1.0.0 (record_schema.py).

Pinned here: the schema definition is self-consistent; the
core validates every record at emission (CLI and MCP share
that core, so parity is structural — and still tested); the
golden fixtures (a PASS, a BLOCKED, and an INCONCLUSIVE /
degraded record, all produced by real stub-seat runs and
stored under tests/fixtures/record_schema/) validate; a
tampered record fails validation; checks that did not run are
visible; degraded behaviour names its causes on BOTH record
modes; and the locked PASS semantics travel in the record.
"""

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from codereview import cli, core, mcp_tools  # noqa: E402
from codereview import record_schema as rs  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures",
                        "record_schema")

PATCH = (
    "diff --git a/a.py b/a.py\n"
    "--- a/a.py\n"
    "+++ b/a.py\n"
    "@@ -1 +1 @@\n"
    "-x=1\n"
    "+x=2\n")


def _ok(prompt):
    return json.dumps({"summary": "ok", "findings": []})


def _bad(prompt):
    return json.dumps({
        "summary": "bad",
        "findings": [{
            "severity": "major", "category": "correctness",
            "file": "a.py", "line": 1, "title": "bug",
            "evidence": "x=2", "recommendation": "fix"}]})


def _boom(prompt):
    raise RuntimeError("quota exceeded")


def _load_fixture(name):
    with open(os.path.join(FIXTURES, name + ".json"),
              encoding="utf-8") as fh:
        return json.load(fh)


class SchemaDefinitionTests(unittest.TestCase):
    def test_schema_is_versioned_and_self_consistent(self):
        schema = rs.RECORD_SCHEMA
        self.assertEqual(schema["version"], "1.0.0")
        self.assertEqual(schema["$id"], "codereview.report/1")
        self.assertEqual(rs.SCHEMA_VERSION, "1.0.0")
        # Every required field is described in properties.
        for field in schema["required"]:
            self.assertIn(field, schema["properties"], field)
        # The record stays extensible: optional sections are
        # the product's growth mechanism, not a violation.
        self.assertTrue(schema["additionalProperties"])

    def test_verdict_vocabulary_and_exit_codes_locked(self):
        self.assertEqual(rs.VERDICT_FOR_GATE, {
            "pass": "PASS", "blocked": "BLOCKED",
            "inconclusive": "INCONCLUSIVE"})
        self.assertEqual(rs.EXIT_CODES, {
            "pass": 0, "blocked": 1, "inconclusive": 2})


class GoldenFixtureTests(unittest.TestCase):
    def test_golden_records_validate(self):
        for name, gate in (("pass", "pass"),
                           ("blocked", "blocked"),
                           ("inconclusive", "inconclusive")):
            record = _load_fixture(name)
            self.assertEqual(record["gate"], gate, name)
            self.assertEqual(record["verdict"], gate.upper())
            self.assertEqual(rs.validate_record(record), [], name)
            self.assertEqual(
                record["record_identity"]["path"], name + ".json")

    def test_golden_blocked_finding_carries_evidence_class(self):
        record = _load_fixture("blocked")
        self.assertTrue(record["findings"])
        for finding in record["findings"]:
            self.assertIn(finding["evidence_class"],
                          rs.EVIDENCE_CLASSES)

    def test_golden_inconclusive_is_degraded_and_visible(self):
        record = _load_fixture("inconclusive")
        self.assertTrue(record["degraded"])
        self.assertTrue(record["degraded_causes"])
        self.assertEqual(record["panel"]["degraded"], True)
        self.assertIn("reviewer_panel",
                      record["checks"]["unavailable"])
        self.assertNotIn("reviewer_panel", record["checks"]["run"])

    def test_golden_pass_states_what_pass_means(self):
        record = _load_fixture("pass")
        self.assertEqual(record["verdict_semantics"]["pass_means"],
                         rs.PASS_MEANS)
        self.assertIn("not a correctness guarantee",
                      record["verdict_semantics"]["pass_is_not"])
        # The checks that did not run are named, not hidden.
        self.assertIn("evidence", record["checks"]["not_run"])
        self.assertIn("policy", record["checks"]["not_run"])
        self.assertEqual(record["cost"]["status"], "not_available")
        self.assertIsNone(record["cost"]["amount_usd"])


class EmissionTests(unittest.TestCase):
    def test_live_records_validate_for_every_verdict(self):
        for providers, gate in (
                ({"a": _ok, "b": _ok}, "pass"),
                ({"a": _bad, "b": _ok}, "blocked"),
                ({"a": _boom, "b": _boom}, "inconclusive")):
            record = core.run_review(PATCH, providers)
            self.assertEqual(record["gate"], gate)
            self.assertEqual(rs.validate_record(record), [])
            self.assertEqual(record["schema_version"], "1.0.0")
            self.assertIsInstance(record["duration_ms"], int)

    def test_verify_record_validates_and_names_its_gaps(self):
        prior = core.run_review(PATCH, {"a": _bad, "b": _ok})
        record = core.run_verification(
            PATCH, {"a": _ok, "b": _ok}, prior, "fixed it")
        self.assertEqual(rs.validate_record(record), [])
        self.assertIn("degraded_causes", record)
        # Documented verify-mode gaps are visible in checks.
        for name in ("coverage", "evidence", "policy"):
            self.assertIn(name, record["checks"]["not_run"])
        self.assertEqual(record["scope"]["files"], ["a.py"])
        self.assertEqual(record["scope"]["previous_gate"],
                         "blocked")
        self.assertEqual(record["waivers"], [])

    def test_waivers_recorded_when_caller_supplies_them(self):
        waiver = {"finding_id": "abc", "reason": "accepted",
                  "date": "2026-11-05"}
        record = core.run_review(PATCH, {"a": _ok, "b": _ok},
                                 waivers=[waiver])
        self.assertEqual(record["waivers"], [waiver])
        self.assertEqual(rs.validate_record(record), [])

    def test_write_report_stamps_path_and_revalidates(self):
        record = core.run_review(PATCH, {"a": _ok, "b": _ok})
        self.assertIsNone(record["record_identity"]["path"])
        with tempfile.TemporaryDirectory() as tmp:
            jpath, _mpath = core.write_report(record, tmp,
                                              stem="rec")
            with open(jpath, encoding="utf-8") as fh:
                disk = json.load(fh)
        self.assertEqual(disk["record_identity"]["path"],
                         "rec.json")
        self.assertEqual(disk["record_identity"]["id"],
                         record["record_identity"]["id"])
        self.assertEqual(rs.validate_record(disk), [])


class NegativeTests(unittest.TestCase):
    def setUp(self):
        self.record = core.run_review(PATCH, {"a": _ok, "b": _ok})

    def test_tampered_gate_fails(self):
        tampered = copy.deepcopy(self.record)
        tampered["gate"] = "blocked"
        problems = rs.validate_record(tampered)
        self.assertTrue(any("verdict" in p for p in problems),
                        problems)

    def test_missing_schema_version_is_legacy_not_v1(self):
        legacy = copy.deepcopy(self.record)
        del legacy["schema_version"]
        problems = rs.validate_record(legacy)
        self.assertTrue(any("schema_version" in p
                            for p in problems), problems)

    def test_invented_cost_fails(self):
        tampered = copy.deepcopy(self.record)
        tampered["cost"] = {"status": "measured",
                            "amount_usd": 0.01}
        self.assertTrue(rs.validate_record(tampered))

    def test_bogus_finding_severity_fails(self):
        tampered = copy.deepcopy(self.record)
        tampered["findings"] = [{
            "id": "x", "severity": "critical", "title": "t"}]
        self.assertTrue(rs.validate_record(tampered))

    def test_overlapping_checks_fail(self):
        tampered = copy.deepcopy(self.record)
        tampered["checks"]["not_run"].append("reviewer_panel")
        self.assertTrue(rs.validate_record(tampered))

    def test_degraded_without_causes_fails(self):
        tampered = copy.deepcopy(self.record)
        tampered["degraded"] = True
        tampered["panel"]["degraded"] = True
        tampered["degraded_causes"] = []
        tampered["panel"]["degraded_causes"] = []
        self.assertTrue(rs.validate_record(tampered))


class McpParityTests(unittest.TestCase):
    def test_mcp_record_validates_identically_to_cli_record(self):
        seat = _ok
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.makedirs(repo)
            # MCP surface: run_gate through the tool layer.
            tools = mcp_tools.GateTools(
                providers_override={"stub": seat})
            dispatch = mcp_tools.make_dispatch(tools)
            mcp_out = os.path.join(tmp, "mcp-out")
            result = dispatch("tools/call", {
                "name": "run_gate",
                "arguments": {"repo": repo, "patch": PATCH,
                              "out": mcp_out}}, False)
            self.assertFalse(result["isError"])
            payload = result["structuredContent"]
            self.assertEqual(payload["exit_code"],
                             rs.EXIT_CODES[payload["gate"]])
            with open(payload["record_path"],
                      encoding="utf-8") as fh:
                mcp_record = json.load(fh)
            # CLI surface: the same patch, the same seat.
            patch_path = os.path.join(tmp, "change.patch")
            with open(patch_path, "w", encoding="utf-8") as fh:
                fh.write(PATCH)
            cli_out = os.path.join(tmp, "cli-out")
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = cli.main(["--repo", repo, "--patch",
                               patch_path, "--out", cli_out],
                              providers_override={"stub": seat})
            self.assertEqual(rc, payload["exit_code"])
            names = [f for f in os.listdir(cli_out)
                     if f.endswith(".json")]
            with open(os.path.join(cli_out, names[0]),
                      encoding="utf-8") as fh:
                cli_record = json.load(fh)
        # Identical validation outcome: both are v1 records,
        # both validate clean, with the same verdict/checks.
        self.assertEqual(rs.validate_record(mcp_record), [])
        self.assertEqual(rs.validate_record(cli_record), [])
        self.assertEqual(mcp_record["verdict"],
                         cli_record["verdict"])
        self.assertEqual(mcp_record["checks"],
                         cli_record["checks"])
        self.assertEqual(mcp_record["schema_version"],
                         cli_record["schema_version"])


if __name__ == "__main__":
    unittest.main()
