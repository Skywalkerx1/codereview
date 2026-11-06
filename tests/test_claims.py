"""Epic C4 — builder-claim verification in the run record.

The parser and the sandbox executor are the Epic C evidence
runner's (tests/test_evidence.py pins them); these tests pin
what claims.py adds around them: the record-facing statuses
(verified / mismatch / unverifiable / unparsed), the recording
of claim-shaped lines that do not parse (never guessed, never
executed), the never-raises contract, and the CLI wiring that
lands the section in a verification run's record — without the
section ever moving the gate.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import claims, cli, evidence  # noqa: E402


def _tree(files):
    root = tempfile.mkdtemp(prefix="codereview-claims-test-")
    for name, body in files.items():
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
    return root


class SectionShapeTests(unittest.TestCase):
    def test_clean_claims_verified(self):
        src = _tree({"check.sh": "exit 3\n"})
        section = claims.verify_report_claims(
            "Ran `true` — passed\n"
            "Tests: sh check.sh (exit 3)\n", src)
        self.assertEqual(section["schema"], "codereview.claims/1")
        self.assertIn("not a gate input", section["boundary"])
        by_cmd = {c["command"]: c for c in section["claims"]}
        self.assertEqual(by_cmd["true"]["status"], "verified")
        self.assertEqual(by_cmd["true"]["actual_exit_code"], 0)
        self.assertEqual(by_cmd["sh check.sh"]["status"],
                         "verified")
        self.assertEqual(by_cmd["sh check.sh"]["actual_exit_code"],
                         3)
        self.assertTrue(by_cmd["true"]["output_sha256"])
        self.assertEqual(section["summary"],
                         {"total": 2, "verified": 2, "mismatch": 0,
                          "unverifiable": 0, "unparsed": 0})

    def test_mismatched_exit_code_downgrades_the_claim(self):
        src = _tree({"check.sh": "exit 3\n"})
        section = claims.verify_report_claims(
            "Tests: sh check.sh (exit 0)\n"
            "Ran `false` — passed\n", src)
        by_cmd = {c["command"]: c for c in section["claims"]}
        entry = by_cmd["sh check.sh"]
        self.assertEqual(entry["status"], "mismatch")
        self.assertEqual(entry["claimed_exit_code"], 0)
        self.assertEqual(entry["actual_exit_code"], 3)
        self.assertIn("claimed passed (exit 0)",
                      entry["detail"])
        self.assertEqual(by_cmd["false"]["status"], "mismatch")
        self.assertEqual(section["summary"]["mismatch"], 2)

    def test_claimed_failure_that_now_passes_is_a_mismatch(self):
        src = _tree({})
        section = claims.verify_report_claims(
            "Ran `true` — failed\n", src)
        (entry,) = section["claims"]
        self.assertEqual(entry["status"], "mismatch")
        self.assertEqual(entry["claimed"], "failed")
        self.assertEqual(entry["actual_exit_code"], 0)

    def test_missing_command_is_a_mismatch_not_a_crash(self):
        src = _tree({})
        section = claims.verify_report_claims(
            "Ran `no-such-command-c4` — passed\n", src)
        (entry,) = section["claims"]
        self.assertEqual(entry["status"], "mismatch")
        self.assertEqual(entry["actual_exit_code"], 127)


class UnparsedTests(unittest.TestCase):
    def test_backticked_command_without_outcome_is_unparsed(self):
        src = _tree({})
        marker = os.path.join(src, "marker.txt")
        section = claims.verify_report_claims(
            f"Ran `touch {marker}` afterwards.\n", src)
        (entry,) = section["claims"]
        self.assertEqual(entry["status"], "unparsed")
        self.assertEqual(entry["line"], 1)
        self.assertIn("not extracted, not run", entry["reason"])
        # The unparsed command was NOT executed: an absolute
        # path escapes the sandbox cwd, so a run would have
        # left the marker behind.
        self.assertFalse(os.path.exists(marker))
        self.assertEqual(section["summary"]["unparsed"], 1)

    def test_labelled_line_without_outcome_is_unparsed(self):
        src = _tree({})
        section = claims.verify_report_claims(
            "Tests: make test\n", src)
        (entry,) = section["claims"]
        self.assertEqual(entry["status"], "unparsed")
        self.assertIn("labelled line", entry["reason"])

    def test_prose_is_not_a_claim_attempt(self):
        src = _tree({})
        section = claims.verify_report_claims(
            "I fixed the thing and ran some other commands.\n"
            "Everything looks good now.\n"
            "Ran `true` — passed\n", src)
        self.assertEqual(
            [(c["line"], c["status"]) for c in section["claims"]],
            [(3, "verified")])

    def test_prose_only_report_records_an_empty_section(self):
        src = _tree({})
        section = claims.verify_report_claims(
            "No commands were run for this change.\n", src)
        self.assertIsNotNone(section)
        self.assertEqual(section["claims"], [])
        self.assertEqual(section["summary"]["total"], 0)

    def test_unparsed_line_text_is_redacted(self):
        src = _tree({})
        # The AWS documentation example key, built from
        # fragments (the test_v090_fixes convention) so the
        # literal never appears in this file; at runtime it is
        # the full key string and redact_secrets must catch it.
        key = "AKIA" + "IOSFODNN7EXAMPLE"
        section = claims.verify_report_claims(
            f"Ran `aws configure set key {key}` afterwards.\n",
            src)
        (entry,) = section["claims"]
        self.assertEqual(entry["status"], "unparsed")
        self.assertNotIn(key, entry["text"])
        self.assertIn("[REDACTED-AWS-KEY]", entry["text"])

    def test_entries_sorted_by_line_with_full_summary(self):
        src = _tree({})
        section = claims.verify_report_claims(
            "Ran `false` — passed\n"
            "Ran `touch x` afterwards.\n"
            "Ran `true` — passed\n", src)
        self.assertEqual(
            [(c["line"], c["status"]) for c in section["claims"]],
            [(1, "mismatch"), (2, "unparsed"), (3, "verified")])
        self.assertEqual(section["summary"],
                         {"total": 3, "verified": 1, "mismatch": 1,
                          "unverifiable": 0, "unparsed": 1})


class NeverRaisesTests(unittest.TestCase):
    def test_no_report_no_section(self):
        src = _tree({})
        self.assertIsNone(claims.verify_report_claims(None, src))
        self.assertIsNone(claims.verify_report_claims("", src))
        self.assertIsNone(claims.verify_report_claims("  \n ", src))

    def test_bytes_report_is_decoded(self):
        src = _tree({})
        section = claims.verify_report_claims(
            "Ran `true` — passed\n".encode("utf-8"), src)
        (entry,) = section["claims"]
        self.assertEqual(entry["status"], "verified")

    def test_non_text_report_is_recorded_not_raised(self):
        src = _tree({})
        section = claims.verify_report_claims(12345, src)
        self.assertEqual(section["claims"], [])
        self.assertIn("was not text", section["detail"])

    def test_missing_tree_leaves_claims_unverifiable(self):
        section = claims.verify_report_claims(
            "Ran `true` — passed\n",
            os.path.join(tempfile.gettempdir(),
                         "codereview-c4-no-such-tree"))
        (entry,) = section["claims"]
        self.assertEqual(entry["status"], "unverifiable")
        self.assertIsNone(entry["actual_exit_code"])
        self.assertIn("sandbox copy failed", entry["detail"])

    def test_verification_failure_is_recorded_not_raised(self):
        src = _tree({})
        with mock.patch.object(
                evidence, "verify_claims",
                side_effect=RuntimeError("sandbox exploded")):
            section = claims.verify_report_claims(
                "Ran `true` — passed\n", src)
        (entry,) = section["claims"]
        self.assertEqual(entry["status"], "unverifiable")
        self.assertIn("could not run", entry["detail"])
        self.assertIn("sandbox exploded", entry["detail"])

    def test_claims_run_in_the_sandbox_not_the_source(self):
        src = _tree({"app.py": "x\n"})
        section = claims.verify_report_claims(
            "Ran `echo pwned >> app.py` — passed\n", src)
        (entry,) = section["claims"]
        self.assertEqual(entry["status"], "verified")
        with open(os.path.join(src, "app.py"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "x\n")


# ------------------------------------------------------- CLI record

VERIFY_PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,3 @@\n"
    " import os\n"
    "+VALUE = compute_total(items) if items else 0\n"
    "+print(VALUE)\n")

EVIDENCE_TEXT = ("compute_total in app.py guards the total: "
                 "VALUE is only computed when items is non-empty")


def _previous():
    return {"gate": "blocked", "findings": [{
        "id": "f-openai-1", "severity": "blocker",
        "category": "correctness", "file": "app.py", "line": 2,
        "title": "Total computed without a guard",
        "evidence": "VALUE = compute_total(items)",
        "recommendation": "guard it", "confidence": 0.9,
        "sources": ["openai"], "consensus": False}]}


def _judge(prompt):
    return json.dumps({
        "resolutions": [{"finding_id": "f-openai-1",
                         "status": "invalid",
                         "evidence": EVIDENCE_TEXT}],
        "new_findings": []})


def _quota_boom(prompt):
    raise RuntimeError("HTTP 429 quota exceeded: "
                       "resource_exhausted")


def _pass_seat(prompt):
    return json.dumps({"verdict": "pass", "summary": "ok",
                       "findings": []})


class CliRecordTests(unittest.TestCase):
    """End-to-end through cli.main: the section lands in the
    verification record; the gate never reads it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = self.tmp.name
        self.repo = os.path.join(base, "repo")
        os.makedirs(self.repo)
        with open(os.path.join(self.repo, "app.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("x = 1\n")
        self.patch = os.path.join(base, "fix.diff")
        with open(self.patch, "w", encoding="utf-8") as fh:
            fh.write(VERIFY_PATCH)
        self.previous = os.path.join(base, "previous.json")
        with open(self.previous, "w", encoding="utf-8") as fh:
            json.dump(_previous(), fh)

    def _verify(self, response_text, out="out"):
        argv = ["--repo", self.repo, "--patch", self.patch,
                "--verify-previous", self.previous,
                "--out", os.path.join(self.tmp.name, out)]
        if response_text is not None:
            response = os.path.join(self.tmp.name, "response.md")
            with open(response, "w", encoding="utf-8") as fh:
                fh.write(response_text)
            argv += ["--builder-response", "@" + response]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = cli.main(
                argv,
                providers_override={"gemini": _quota_boom,
                                    "nvidia": _judge},
                seat_meta_override={
                    "gemini": {"family": "google", "tier": "free"},
                    "nvidia": {"family": "nvidia", "tier": "free"},
                    "openai": {"family": "openai", "tier": "paid"}},
                fallbacks_override={
                    "correctness": ("openai", _judge)})
        records = [f for f in os.listdir(
            os.path.join(self.tmp.name, out)) if f.endswith(".json")]
        self.assertEqual(len(records), 1)
        with open(os.path.join(self.tmp.name, out, records[0]),
                  encoding="utf-8") as fh:
            return rc, json.load(fh)

    def test_record_carries_the_section(self):
        rc, report = self._verify(
            "Ran `true` — passed\nRan `false` — passed\n")
        self.assertEqual(rc, 0)
        section = report["claim_verification"]
        self.assertEqual(section["schema"], "codereview.claims/1")
        self.assertEqual(section["summary"]["verified"], 1)
        self.assertEqual(section["summary"]["mismatch"], 1)
        self.assertEqual(report["gate"], "pass")

    def test_a_mismatch_never_changes_the_gate(self):
        _, honest = self._verify("Ran `true` — passed\n",
                                 out="out-honest")
        _, lying = self._verify("Ran `false` — passed\n",
                                out="out-lying")
        self.assertEqual(honest["gate"], lying["gate"])
        self.assertEqual(honest["gate_reasons"],
                         lying["gate_reasons"])
        self.assertEqual(
            [f["id"] for f in honest["cleared"]],
            [f["id"] for f in lying["cleared"]])
        self.assertEqual(
            honest["claim_verification"]["summary"]["mismatch"],
            0)
        self.assertEqual(
            lying["claim_verification"]["summary"]["mismatch"],
            1)

    def test_no_builder_response_no_section(self):
        rc, report = self._verify(None)
        self.assertEqual(rc, 0)
        self.assertNotIn("claim_verification", report)

    def test_review_run_carries_no_section(self):
        argv = ["--repo", self.repo, "--patch", self.patch,
                "--builder-response", "Ran `false` — passed",
                "--out", os.path.join(self.tmp.name, "rout")]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            cli.main(argv, providers_override={
                "a": _pass_seat, "b": _pass_seat})
        outdir = os.path.join(self.tmp.name, "rout")
        records = [f for f in os.listdir(outdir)
                   if f.endswith(".json")]
        self.assertEqual(len(records), 1)
        with open(os.path.join(outdir, records[0]),
                  encoding="utf-8") as fh:
            report = json.load(fh)
        self.assertNotIn("claim_verification", report)


class SingleParseTests(unittest.TestCase):
    """P2-07 — verify_report_claims parses the report text
    exactly once: the claims it extracts are handed to
    evidence.verify_claims, which must not parse again."""

    def test_report_text_parsed_once(self):
        src = _tree({"app.py": "x\n"})
        real_parse = evidence.parse_claims
        calls = []

        def counting_parse(text):
            calls.append(text)
            return real_parse(text)

        with mock.patch.object(evidence, "parse_claims",
                               counting_parse):
            section = claims.verify_report_claims(
                "Ran `true` — passed\n", src)
        self.assertEqual(len(calls), 1)
        self.assertEqual(section["summary"]["mismatch"], 0)
        self.assertEqual(
            section["claims"][0]["status"], "verified")


if __name__ == "__main__":
    unittest.main()
