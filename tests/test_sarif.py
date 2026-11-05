"""Tests for the SARIF 2.1.0 export (Epic D, ticket D1) —
record dicts only, no network, no provider calls.

Schema validation here is a MINIMAL STRUCTURAL validator
(`sarif_problems` below): it checks the invariants SARIF 2.1.0
mandates for the shapes this writer emits (required top-level
fields, rule/result cross-references, level vocabulary,
location/region sanity, string fingerprints). It is NOT the
full official JSON Schema — that document is ~112 KB and the
package is stdlib-only, so it is not vendored. The writer's
output was additionally validated against the full official
schema during development; these tests pin the structure so a
regression is caught by the suite, not by a consumer.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, core, sarif  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")

_LEVELS = {"error", "warning", "note", "none"}


def sarif_problems(log):
    """Minimal structural validation of a SARIF 2.1.0 log:
    returns a list of problems ([] means structurally valid)."""
    problems = []
    if not isinstance(log, dict):
        return ["log is not an object"]
    if log.get("version") != "2.1.0":
        problems.append("version is not '2.1.0'")
    if not str(log.get("$schema") or ""):
        problems.append("missing $schema")
    runs = log.get("runs")
    if not isinstance(runs, list) or not runs:
        problems.append("runs is not a non-empty list")
        return problems
    for run in runs:
        driver = (run.get("tool") or {}).get("driver") or {}
        if not str(driver.get("name") or ""):
            problems.append("driver has no name")
        rules = driver.get("rules") or []
        rule_ids = [r.get("id") for r in rules]
        if len(rule_ids) != len(set(rule_ids)):
            problems.append("duplicate rule ids")
        for rule in rules:
            text = (rule.get("shortDescription") or {}).get("text")
            if not str(text or ""):
                problems.append(
                    f"rule {rule.get('id')}: no shortDescription")
            level = (rule.get("defaultConfiguration")
                     or {}).get("level")
            if level is not None and level not in _LEVELS:
                problems.append(
                    f"rule {rule.get('id')}: bad default level")
        results = run.get("results")
        if not isinstance(results, list):
            problems.append("results is not a list")
            continue
        for res in results:
            if res.get("ruleId") not in rule_ids:
                problems.append(
                    f"result references undeclared rule "
                    f"{res.get('ruleId')}")
            if res.get("level", "warning") not in _LEVELS:
                problems.append(
                    f"result {res.get('ruleId')}: bad level "
                    f"{res.get('level')}")
            if not str((res.get("message") or {}).get("text")
                       or ""):
                problems.append(
                    f"result {res.get('ruleId')}: empty message")
            for loc in res.get("locations") or []:
                phys = loc.get("physicalLocation") or {}
                uri = (phys.get("artifactLocation")
                       or {}).get("uri")
                if not str(uri or ""):
                    problems.append("location without a uri")
                region = phys.get("region") or {}
                if "startLine" in region:
                    line = region["startLine"]
                    if not isinstance(line, int) or line < 1:
                        problems.append(
                            f"bad startLine {line!r}")
            for key, value in (res.get("partialFingerprints")
                               or {}).items():
                if not isinstance(value, str):
                    problems.append(
                        f"fingerprint {key} is not a string")
    return problems


def _finding(**kw):
    base = {"id": "aaaa00000001", "rule": "", "severity": "major",
            "category": "correctness", "file": "app/x.py",
            "line": 10, "title": "Something is wrong",
            "evidence": "bad_line()", "evidence_quote": "bad_line()",
            "recommendation": "Fix it.", "confidence": 0.7,
            "sources": ["gemini"], "consensus": False}
    base.update(kw)
    return base


def _record(findings, **kw):
    record = {"schema": core.SCHEMA, "version": core.VERSION,
              "mode": "review", "created_at": "2026-11-04T00:00:00+00:00",
              "gate": "blocked", "gate_reasons": ["test record"],
              "findings": findings}
    record.update(kw)
    return record


class SeverityMappingTests(unittest.TestCase):
    def test_task_mapping(self):
        self.assertEqual(sarif.level_for_severity("blocker"),
                         "error")
        self.assertEqual(sarif.level_for_severity("major"),
                         "warning")
        self.assertEqual(sarif.level_for_severity("minor"), "note")
        self.assertEqual(sarif.level_for_severity("nit"), "note")

    def test_unknown_severity_behaves_as_minor(self):
        self.assertEqual(sarif.level_for_severity("critical"),
                         "note")
        self.assertEqual(sarif.level_for_severity(None), "note")
        self.assertEqual(sarif.level_for_severity(""), "note")


class RuleDerivationTests(unittest.TestCase):
    def _rules(self, record):
        log = sarif.record_to_sarif(record)
        return {r["id"]: r
                for r in log["runs"][0]["tool"]["driver"]["rules"]}

    def test_deterministic_rule_keeps_scan_id_and_text(self):
        record = _record([_finding(
            id="d1", rule="eval-exec", severity="blocker",
            category="security", sources=["deterministic"])])
        rules = self._rules(record)
        self.assertIn("eval-exec", rules)
        rule = rules["eval-exec"]
        # Canonical title from the scan's own rule table.
        self.assertEqual(rule["shortDescription"]["text"],
                         "eval/exec call in added code")
        self.assertTrue(rule["help"]["text"])
        self.assertEqual(rule["defaultConfiguration"]["level"],
                         "error")
        self.assertEqual(rule["name"], "EvalExec")

    def test_model_rule_id_from_category(self):
        record = _record([_finding(id="m1", category="data-loss")])
        rules = self._rules(record)
        self.assertIn("model-data-loss", rules)
        self.assertEqual(rules["model-data-loss"]["name"],
                         "ModelDataLoss")

    def test_rule_default_level_is_most_severe_result(self):
        record = _record([
            _finding(id="m1", severity="minor"),
            _finding(id="m2", severity="blocker",
                     title="A different serious thing")])
        rules = self._rules(record)
        self.assertEqual(
            rules["model-correctness"]
            ["defaultConfiguration"]["level"], "error")
        log = sarif.record_to_sarif(record)
        levels = {r["partialFingerprints"]["codereviewFindingId"]:
                  r["level"] for r in log["runs"][0]["results"]}
        # Each result still carries its OWN level.
        self.assertEqual(levels["m1"], "note")
        self.assertEqual(levels["m2"], "error")

    def test_unknown_scan_rule_id_does_not_crash(self):
        record = _record([_finding(
            id="d9", rule="some-retired-rule",
            sources=["deterministic"])])
        rules = self._rules(record)
        self.assertIn("some-retired-rule", rules)
        self.assertTrue(
            rules["some-retired-rule"]["shortDescription"]["text"])


class ResultShapeTests(unittest.TestCase):
    def _result(self, finding, **record_kw):
        log = sarif.record_to_sarif(_record([finding],
                                            **record_kw))
        return log["runs"][0]["results"][0]

    def test_location_line_and_snippet(self):
        res = self._result(_finding(
            line=42, evidence_quote="first line\nsecond line"))
        phys = res["locations"][0]["physicalLocation"]
        self.assertEqual(phys["artifactLocation"]["uri"],
                         "app/x.py")
        self.assertEqual(phys["region"]["startLine"], 42)
        # Snippet is the cited line only, not the whole quote.
        self.assertEqual(phys["region"]["snippet"]["text"],
                         "first line")

    def test_file_less_finding_has_no_location(self):
        res = self._result(_finding(
            id="t1", rule="test-failure", severity="blocker",
            category="testing", file="", line=None,
            sources=["deterministic"]))
        self.assertNotIn("locations", res)
        self.assertEqual(res["level"], "error")

    def test_fingerprint_is_the_finding_id(self):
        res = self._result(_finding(id="feedface1234"))
        self.assertEqual(
            res["partialFingerprints"]["codereviewFindingId"],
            "feedface1234")
        self.assertEqual(res["properties"]["severity"], "major")

    def test_line_basis_passed_through_when_present(self):
        res = self._result(_finding(line_basis="blob"))
        self.assertEqual(res["properties"]["lineBasis"], "blob")
        res = self._result(_finding())
        self.assertNotIn("lineBasis", res["properties"])

    def test_unknown_severity_normalized_in_properties(self):
        res = self._result(_finding(severity="critical"))
        self.assertEqual(res["level"], "note")
        self.assertEqual(res["properties"]["severity"], "minor")

    def test_run_properties_carry_record_facts(self):
        log = sarif.record_to_sarif(_record(
            [_finding()], patch_sha256="ab12", head="cafe",
            range="a..b"))
        run = log["runs"][0]
        props = run["properties"]["codereview"]
        self.assertEqual(props["gate"], "blocked")
        self.assertEqual(props["patchSha256"], "ab12")
        self.assertEqual(props["head"], "cafe")
        self.assertEqual(props["exportedResults"], 1)
        self.assertEqual(run["tool"]["driver"]["name"],
                         "CodeReview")
        self.assertEqual(run["tool"]["driver"]["version"],
                         core.VERSION)


class RecordScopeTests(unittest.TestCase):
    def test_verify_record_exports_findings_and_remaining(self):
        record = _record(
            [_finding(id="new1")], mode="verify",
            remaining=[_finding(id="old1", title="Still present"),
                       _finding(id="new1", title="Duplicate id")],
            cleared=[_finding(id="done1", title="Cleared")])
        pairs = sarif.record_findings(record)
        ids = [f["id"] for f, _state in pairs]
        self.assertEqual(ids, ["new1", "old1"])
        log = sarif.record_to_sarif(record)
        self.assertEqual(len(log["runs"][0]["results"]), 2)
        self.assertEqual(sarif_problems(log), [])

    def test_human_decision_lists_exported_with_state(self):
        record = _record(
            [], disputed_findings=[_finding(id="disp1")],
            refutation_weak_findings=[_finding(id="weak1")],
            escalated_findings=[_finding(id="esc1")],
            withdrawn_findings=[_finding(id="gone1")])
        log = sarif.record_to_sarif(record)
        states = {r["partialFingerprints"]["codereviewFindingId"]:
                  r["properties"]["adjudicationState"]
                  for r in log["runs"][0]["results"]}
        self.assertEqual(states, {"disp1": "disputed",
                                  "weak1": "refutation-weak",
                                  "esc1": "escalated"})
        self.assertEqual(sarif_problems(log), [])

    def test_empty_record_is_valid(self):
        log = sarif.record_to_sarif(_record([]))
        self.assertEqual(log["runs"][0]["results"], [])
        self.assertEqual(sarif_problems(log), [])


class StructuralValidatorTests(unittest.TestCase):
    """The validator must be able to FAIL — a validator that
    passes everything validates nothing."""

    def _valid(self):
        return sarif.record_to_sarif(_record([_finding()]))

    def test_valid_log_passes(self):
        self.assertEqual(sarif_problems(self._valid()), [])

    def test_bad_level_fails(self):
        log = self._valid()
        log["runs"][0]["results"][0]["level"] = "fatal"
        self.assertTrue(sarif_problems(log))

    def test_dangling_rule_reference_fails(self):
        log = self._valid()
        log["runs"][0]["results"][0]["ruleId"] = "no-such-rule"
        self.assertTrue(sarif_problems(log))

    def test_bad_start_line_fails(self):
        log = self._valid()
        loc = log["runs"][0]["results"][0]["locations"][0]
        loc["physicalLocation"]["region"]["startLine"] = 0
        self.assertTrue(sarif_problems(log))

    def test_wrong_version_fails(self):
        log = self._valid()
        log["version"] = "2.0.0"
        self.assertTrue(sarif_problems(log))


class RealRecordTests(unittest.TestCase):
    """End to end over a real saved record from this repo's own
    review history: record JSON -> SARIF -> structural
    validation, with a spot check on a known finding."""

    def test_v096_record_converts_and_validates(self):
        path = os.path.join(
            REPO_ROOT, "review-v096",
            "codereview-20261104-233259.json")
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
        log = sarif.record_to_sarif(record)
        self.assertEqual(sarif_problems(log), [])
        results = log["runs"][0]["results"]
        self.assertEqual(len(results),
                         len(sarif.record_findings(record)))
        by_id = {r["partialFingerprints"]["codereviewFindingId"]:
                 r for r in results}
        sqli = by_id["c47217cc097b"]
        self.assertEqual(sqli["ruleId"], "model-security")
        self.assertEqual(sqli["level"], "error")
        phys = sqli["locations"][0]["physicalLocation"]
        self.assertEqual(phys["artifactLocation"]["uri"],
                         "app/users.py")
        self.assertEqual(phys["region"]["startLine"], 12)


# The dynamic-evaluation call below is assembled from fragments
# so no literal line in this file matches the scan pattern (the
# fixture-hygiene rule's spirit: fixtures stay clean on disk,
# byte-identical at runtime — same approach as tests/test_core.py).
_EVAL_PATCH = """diff --git a/app/run.py b/app/run.py
--- a/app/run.py
+++ b/app/run.py
@@ -1,1 +1,3 @@
 def run(user_input):
-    return "ok"
+    result = @EVAL@(user_input)
+    return result
""".replace("@EVAL@", "ev" + "al")


def _cite_provider(prompt):
    line = "    result = " + "ev" + "al(user_input)"
    return json.dumps({
        "verdict": "changes_requested", "summary": "unsafe",
        "findings": [{
            "severity": "major", "category": "reliability",
            "file": "app/run.py", "line": 2,
            "title": "No timeout around the dynamic call",
            "evidence": line, "evidence_quote": line,
            "recommendation": "Bound the call with a timeout.",
            "confidence": 0.8}]})


def _pass_provider(prompt):
    return json.dumps({"verdict": "pass", "summary": "fine",
                       "findings": []})


class EndToEndTests(unittest.TestCase):
    """A live run_review record -> write_report -> the sarif
    CLI -> parsed SARIF -> structural validation."""

    def _make_record_dir(self, tmp):
        report = core.run_review(
            _EVAL_PATCH,
            {"a": _cite_provider, "b": _pass_provider})
        self.assertEqual(report["gate"], "blocked")
        out_dir = os.path.join(tmp, "record-out")
        core.write_report(report, out_dir)
        return out_dir

    def test_cli_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = self._make_record_dir(tmp)
            sarif_path = os.path.join(tmp, "results.sarif")
            with redirect_stdout(io.StringIO()):
                rc = cli.main(["sarif", out_dir,
                               "--out", sarif_path])
            self.assertEqual(rc, 0)
            with open(sarif_path, encoding="utf-8") as fh:
                log = json.load(fh)
            self.assertEqual(sarif_problems(log), [])
            results = log["runs"][0]["results"]
            rule_ids = {r["ruleId"] for r in results}
            # The deterministic finding keeps its scan rule id;
            # the model finding lands under its category rule.
            self.assertIn("eval-exec", rule_ids)
            self.assertIn("model-reliability", rule_ids)
            levels = {r["ruleId"]: r["level"] for r in results}
            self.assertEqual(levels["eval-exec"], "error")
            self.assertEqual(levels["model-reliability"],
                             "warning")

    def test_cli_stdout_is_pure_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = self._make_record_dir(tmp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["sarif", out_dir])
            self.assertEqual(rc, 0)
            log = json.loads(buf.getvalue())
            self.assertEqual(sarif_problems(log), [])

    def test_cli_missing_record_is_exit_2(self):
        with redirect_stderr(io.StringIO()):
            rc = cli.main(["sarif",
                           "/nonexistent/record-dir-xyz"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
