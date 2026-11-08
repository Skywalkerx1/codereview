"""Security patch line 0.13.2 — regression tests for the CSA
mcpserver-audit fixes (A, B, C, D, F, G, I) and for the
delta fixes the tester's verification of the first build
found in the same class (V, T, the --context-literal equals
form, and the walk-every-component egress test).

Each class pins the behaviour the audit found missing:

  A  full-file context is redacted at collection, before any
     truncation, to the same standard as the diff;
  B  builder-supplied context is redacted before it reaches
     a reviewer prompt or the run record;
  C  MCP run_gate context is literal text — a leading @ is
     never a file read on the MCP path (the CLI's own @file
     expansion is unchanged);
  D  --no-records support bundles leave crash notes out too,
     as PRIVACY.md states;
  F  MCP get_verdict labels its read-back "unverified";
  G  an authenticated custom provider requires HTTPS
     (loopback HTTP excepted; keyless seats untouched);
  I  record writes use an mkstemp temp file, never the old
     predictable pid-derived name;
  V  the verification round's builder response is redacted
     at the top of run_verification, so verification prompts
     never carry it raw;
  T  test-command output is redacted at production (the CLI
     test runner), at round entry in both rounds, and in
     _test_summary — neither prompts nor the record carry it;
  =  MCP context beginning with "-" is forwarded in the
     --context-literal=VALUE equals form, so argparse never
     misreads it as a flag and the text is treated literally.

Secret-shaped values are assembled from fragments, never
written as literals — test_fixture_secret_hygiene scans every
file under tests/ with the product's own secret rules.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from codereview import agentsmd, cli, core, mcp_tools  # noqa: E402
from codereview import providers, support  # noqa: E402

FAKE_KEY = "sk-live" + "-9f8e7d6c" + "5b4a3210"

CLEAN_PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,2 @@\n"
    " X = 1\n"
    "+Y = 2\n")


def _pass_json(prompt):
    return json.dumps({"verdict": "pass", "summary": "ok",
                       "findings": []})


class _Capture:
    """A reviewer seat that records every prompt it is shown."""

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return _pass_json(prompt)


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   capture_output=True, text=True)


def _commit(repo, files, message):
    for name, text in files.items():
        with open(os.path.join(repo, name), "w",
                  encoding="utf-8") as fh:
            fh.write(text)
        _git(repo, "add", name)
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", message)


class FileContextRedactionTests(unittest.TestCase):
    """Audit A: collect_file_context redacts at collection."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q")
        _commit(self.repo, {"app.py": 'TOKEN = "' + FAKE_KEY
                            + '"\nX = 1\n'}, "base")
        with open(os.path.join(self.repo, "app.py"), "a",
                  encoding="utf-8") as fh:
            fh.write("Y = 2\n")
        self.patch = core.collect_git_patch(self.repo)

    def test_collected_context_is_redacted(self):
        fctx, entries = core.collect_file_context(
            self.repo, self.patch)
        self.assertIn("app.py", fctx)
        self.assertNotIn(FAKE_KEY, fctx["app.py"])
        self.assertIn("REDACTED", fctx["app.py"])
        # The ledger that travels with the context carries no
        # secret either.
        self.assertNotIn(FAKE_KEY, json.dumps(entries))

    def test_collected_context_prompts_are_redacted(self):
        fctx, _entries = core.collect_file_context(
            self.repo, self.patch)
        seat = _Capture()
        core.run_review(self.patch, {"a": seat, "b": seat},
                        file_context=fctx)
        self.assertTrue(seat.prompts)
        for prompt in seat.prompts:
            self.assertNotIn(FAKE_KEY, prompt)
        self.assertTrue(any("REDACTED" in p
                            for p in seat.prompts))


class BuilderContextRedactionTests(unittest.TestCase):
    """Audit B: run_review redacts the builder context once,
    at entry — prompt and record both inherit it."""

    def test_context_redacted_in_prompt_and_record(self):
        # The pasted-secret shape the redactor covers is the
        # keyword assignment — the same shapes, and only those
        # shapes, that the diff path has always redacted
        # (redact_secrets is documented pattern-based).
        seat = _Capture()
        report = core.run_review(
            CLEAN_PATCH, {"a": seat, "b": seat},
            context='staging uses API_KEY = "' + FAKE_KEY
                    + '" for now')
        self.assertTrue(seat.prompts)
        for prompt in seat.prompts:
            self.assertNotIn(FAKE_KEY, prompt)
        self.assertNotIn(FAKE_KEY, report["context"])
        self.assertIn("REDACTED", report["context"])


class _McpHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        self.out = os.path.join(self.tmp.name, "out")

    def _call(self, tools, name, arguments):
        dispatch = mcp_tools.make_dispatch(tools)
        return dispatch("tools/call",
                        {"name": name, "arguments": arguments},
                        False)


class McpContextLiteralTests(_McpHarness):
    """Audit C: on the MCP path, context is literal text."""

    def test_run_gate_context_is_never_a_file_read(self):
        victim = os.path.join(self.tmp.name, "notes.txt")
        marker = "the eagle flies at dawn"
        with open(victim, "w", encoding="utf-8") as fh:
            fh.write(marker)
        seat = _Capture()
        tools = mcp_tools.GateTools(
            providers_override={"stub": seat})
        result = self._call(tools, "run_gate", {
            "repo": self.repo, "patch": CLEAN_PATCH,
            "out": self.out, "context": "@" + victim})
        self.assertFalse(result["isError"])
        self.assertTrue(seat.prompts)
        for prompt in seat.prompts:
            # The file's contents were NOT read into the
            # prompt…
            self.assertNotIn(marker, prompt)
            # …the literal text the caller sent was.
            self.assertIn("@" + victim, prompt)

    def test_tool_schema_documents_context_as_literal(self):
        tools = mcp_tools.GateTools(
            providers_override={"stub": _pass_json})
        dispatch = mcp_tools.make_dispatch(tools)
        result = dispatch("tools/list", {}, False)
        run_gate = {t["name"]: t
                    for t in result["tools"]}["run_gate"]
        description = run_gate["inputSchema"]["properties"][
            "context"]["description"]
        self.assertIn("Literal text", description)
        self.assertIn("NOT", description)

    def test_cli_context_at_file_still_expands(self):
        # The CLI operator's own @file convenience is
        # unchanged — only the MCP path lost it. Driven
        # through a real cli.main call, the same way the MCP
        # harness drives it.
        marker = "operator supplied context"
        victim = os.path.join(self.tmp.name, "notes.txt")
        with open(victim, "w", encoding="utf-8") as fh:
            fh.write(marker)
        patch_file = os.path.join(self.tmp.name, "change.patch")
        with open(patch_file, "w", encoding="utf-8") as fh:
            fh.write(CLEAN_PATCH)
        seat = _Capture()
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(
                ["--repo", self.repo, "--out", self.out,
                 "--patch", patch_file,
                 "--context", "@" + victim],
                providers_override={"stub": seat})
        self.assertEqual(rc, 0)
        self.assertTrue(seat.prompts)
        self.assertTrue(any(marker in p for p in seat.prompts))


class NoRecordsCrashNoteTests(unittest.TestCase):
    """Audit D: --no-records excludes crash notes too."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.records = os.path.join(self.tmp.name, "records")
        os.makedirs(self.records)
        note = os.path.join(
            self.records, "codereview-crash-20261107-120000.json")
        with open(note, "w", encoding="utf-8") as fh:
            fh.write('{"kind": "crash"}\n')

    def _bundle_names(self, include_records):
        path = os.path.join(
            self.tmp.name,
            f"bundle-{include_records}.zip")
        cwd = os.getcwd()
        os.chdir(self.tmp.name)
        try:
            support.build_bundle(
                path, records_dir=self.records,
                include_records=include_records,
                environ={"HOME": self.tmp.name})
        finally:
            os.chdir(cwd)
        with zipfile.ZipFile(path) as zf:
            return zf.namelist()

    def test_no_records_excludes_crash_notes(self):
        names = self._bundle_names(False)
        self.assertFalse(
            [n for n in names if n.startswith("crash/")],
            f"crash notes leaked into a --no-records bundle: "
            f"{names}")

    def test_records_included_keeps_crash_notes(self):
        names = self._bundle_names(True)
        self.assertIn(
            "crash/codereview-crash-20261107-120000.json",
            names)


class GetVerdictLabelTests(_McpHarness):
    """Audit F: get_verdict's read-back is labelled."""

    def test_get_verdict_labels_output_unverified(self):
        tools = mcp_tools.GateTools(
            providers_override={"stub": _pass_json})
        payload = self._call(tools, "run_gate", {
            "repo": self.repo, "patch": CLEAN_PATCH,
            "out": self.out})["structuredContent"]
        got = self._call(tools, "get_verdict", {
            "record": payload["record_path"],
            "repo": self.repo})["structuredContent"]
        self.assertEqual(got["verification"], "unverified")
        self.assertEqual(got["gate"], payload["gate"])

    def test_run_gate_payload_is_not_labelled_unverified(self):
        # A fresh gate run's own payload is the run's result,
        # not a read-back — the label belongs to get_verdict.
        tools = mcp_tools.GateTools(
            providers_override={"stub": _pass_json})
        payload = self._call(tools, "run_gate", {
            "repo": self.repo, "patch": CLEAN_PATCH,
            "out": self.out})["structuredContent"]
        self.assertNotIn("verification", payload)


class ProviderHttpsTests(unittest.TestCase):
    """Audit G: authenticated providers require HTTPS."""

    def test_keyed_http_remote_is_refused(self):
        with self.assertRaises(providers.ProviderError) as cm:
            providers.openai_compatible(
                "http://llm.example.com/v1", "m",
                "EXAMPLE_KEY_ENV")
        self.assertIn("https", str(cm.exception))

    def test_keyed_https_builds(self):
        fn = providers.openai_compatible(
            "https://llm.example.com/v1", "m", "EXAMPLE_KEY_ENV")
        self.assertTrue(callable(fn))

    def test_keyed_loopback_http_still_builds(self):
        for base in ("http://127.0.0.1:11434/v1",
                     "http://localhost:8080/v1",
                     "http://[::1]:8080/v1"):
            fn = providers.openai_compatible(
                base, "m", "EXAMPLE_KEY_ENV")
            self.assertTrue(callable(fn), base)

    def test_keyless_http_is_untouched(self):
        fn = providers.openai_compatible(
            "http://192.0.2.10:8080/v1", "m", None)
        self.assertTrue(callable(fn))

    def test_custom_spec_http_refused_https_builds(self):
        with self.assertRaises(providers.ProviderError):
            providers.build_provider(
                "openai-compatible:http://llm.example.com/v1"
                "|m|EXAMPLE_KEY_ENV")
        _name, fn, _label = providers.build_provider(
            "openai-compatible:https://llm.example.com/v1"
            "|m|EXAMPLE_KEY_ENV")
        self.assertTrue(callable(fn))


class AtomicWriteTests(unittest.TestCase):
    """Audit I: _atomic_write_text uses mkstemp."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_write_roundtrip_and_no_temp_leftovers(self):
        path = os.path.join(self.tmp.name, "record.json")
        core._atomic_write_text(path, "hello\n")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "hello\n")
        self.assertEqual(os.listdir(self.tmp.name),
                         ["record.json"])

    def test_planted_symlink_at_old_temp_name_not_followed(self):
        victim = os.path.join(self.tmp.name, "victim.txt")
        with open(victim, "w", encoding="utf-8") as fh:
            fh.write("original")
        path = os.path.join(self.tmp.name, "record.json")
        planted = f"{path}.tmp-{os.getpid()}"
        os.symlink(victim, planted)
        core._atomic_write_text(path, "new content")
        with open(victim, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "original")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "new content")
        self.assertTrue(os.path.islink(planted))


# ------------------------------------------------------------------
# Delta fixes (tester verification of a7adf9e): V, T, equals form.

SECRET_PATCH = "sk-live" + "-a11ce001" + "b0b5ec01"
SECRET_FILECTX = "sk-live" + "-a11ce002" + "b0b5ec02"
SECRET_CONTEXT = "sk-live" + "-a11ce003" + "b0b5ec03"
SECRET_RESPONSE = "sk-live" + "-a11ce004" + "b0b5ec04"
SECRET_TESTOUT = "sk-live" + "-a11ce005" + "b0b5ec05"
SECRET_AGENTS = "sk-live" + "-a11ce006" + "b0b5ec06"
ALL_COMPONENT_SECRETS = (
    SECRET_PATCH, SECRET_FILECTX, SECRET_CONTEXT,
    SECRET_RESPONSE, SECRET_TESTOUT, SECRET_AGENTS)


def _previous_report():
    return {"gate": "blocked", "findings": [{
        "id": "abc123", "severity": "major",
        "category": "reliability", "file": "app/alerts.py",
        "line": 6, "title": "Alert has no dedup",
        "evidence": "", "recommendation": "", "confidence": 0.8,
        "sources": ["a"], "consensus": False}]}


class _VerifyCapture:
    """A verification seat that records every prompt it is
    shown and clears the prior finding with grounded
    evidence."""

    _EVIDENCE = ("return a + b and return a - b are the only "
                 "helpers left in app/util.py and the sendmail "
                 "alert is removed")

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return json.dumps({
            "resolutions": [{"finding_id": "abc123",
                             "status": "fixed",
                             "evidence": self._EVIDENCE}],
            "new_findings": []})


class BuilderResponseRedactionTests(unittest.TestCase):
    """Audit V: run_verification redacts builder_response at
    the top, so verification-round prompts never carry it
    raw."""

    def test_builder_response_redacted_in_prompts(self):
        seat = _VerifyCapture()
        report = core.run_verification(
            CLEAN_PATCH, {"a": seat, "b": seat},
            _previous_report(),
            'fixed it; staging RESPONSE_API_KEY = "'
            + SECRET_RESPONSE + '" for now')
        self.assertTrue(seat.prompts)
        for prompt in seat.prompts:
            self.assertNotIn(SECRET_RESPONSE, prompt)
        # Non-vacuity: the response section reached the panel,
        # in redacted form.
        self.assertTrue(any("REDACTED" in p
                            for p in seat.prompts))
        self.assertNotIn(SECRET_RESPONSE, json.dumps(report))


class TestOutputRedactionTests(unittest.TestCase):
    """Audit T: test-command output is redacted at production
    (the CLI test runner), at round entry in both rounds, and
    in _test_summary — so prompts and the serialized record
    stay clean even when a caller hands a round raw results,
    as the legacy --test-command path produced them."""

    def _raw_results(self):
        return [{"command": "pytest -q", "ok": False,
                 "exit_code": 1,
                 "output_tail": 'assert failed\nTEST_API_KEY = "'
                                + SECRET_TESTOUT + '"\n'}]

    def test_cli_runner_redacts_at_production(self):
        cmd = ("printf 'TEST_API_KEY = \"%s\"\\n' '"
               + SECRET_TESTOUT + "'; exit 1")
        results = cli._run_tests([cmd], ".")
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertNotIn(SECRET_TESTOUT,
                         results[0]["output_tail"])
        self.assertIn("REDACTED", results[0]["output_tail"])

    def test_test_summary_redacts(self):
        summary = core._test_summary(self._raw_results())
        self.assertNotIn(SECRET_TESTOUT, summary)
        self.assertIn("REDACTED", summary)

    def test_run_review_redacts_raw_results(self):
        raw = self._raw_results()
        seat = _Capture()
        report = core.run_review(
            CLEAN_PATCH, {"a": seat, "b": seat},
            test_results=raw)
        self.assertTrue(seat.prompts)
        for prompt in seat.prompts:
            self.assertNotIn(SECRET_TESTOUT, prompt)
        # Non-vacuity: the failing test's summary really is
        # part of the reviewer prompt.
        self.assertTrue(any("output tail" in p
                            for p in seat.prompts))
        self.assertNotIn(SECRET_TESTOUT, json.dumps(report))
        self.assertNotIn(SECRET_TESTOUT,
                         report["test_results"][0]["output_tail"])
        # The caller's dicts were not mutated.
        self.assertIn(SECRET_TESTOUT, raw[0]["output_tail"])

    def test_run_verification_redacts_raw_results(self):
        seat = _VerifyCapture()
        report = core.run_verification(
            CLEAN_PATCH, {"a": seat, "b": seat},
            _previous_report(), "fixed it",
            test_results=self._raw_results())
        self.assertTrue(seat.prompts)
        for prompt in seat.prompts:
            self.assertNotIn(SECRET_TESTOUT, prompt)
        self.assertTrue(any("output tail" in p
                            for p in seat.prompts))
        self.assertNotIn(SECRET_TESTOUT, json.dumps(report))


class McpDashContextTests(_McpHarness):
    """Delta: MCP context beginning with "-" (e.g. --out=/x)
    is literal text, not an argparse error — mcp_tools
    forwards it in the --context-literal=VALUE equals form,
    which argparse cannot misread as a flag."""

    def test_run_gate_dash_leading_context_is_literal(self):
        seat = _Capture()
        tools = mcp_tools.GateTools(
            providers_override={"stub": seat})
        result = self._call(tools, "run_gate", {
            "repo": self.repo, "patch": CLEAN_PATCH,
            "out": self.out, "context": "--out=/x"})
        self.assertFalse(result["isError"])
        self.assertTrue(seat.prompts)
        self.assertTrue(any("--out=/x" in p
                            for p in seat.prompts))
        # The value was NOT reinterpreted as the --out flag:
        # the record landed in the requested output directory
        # and nothing was created at the pointed-to path.
        record_path = result["structuredContent"]["record_path"]
        self.assertTrue(record_path.startswith(self.out))
        self.assertFalse(os.path.exists("/x"))

    def test_cli_context_literal_equals_form(self):
        patch_file = os.path.join(self.tmp.name, "change.patch")
        with open(patch_file, "w", encoding="utf-8") as fh:
            fh.write(CLEAN_PATCH)
        seat = _Capture()
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(
                ["--repo", self.repo, "--out", self.out,
                 "--patch", patch_file,
                 "--context-literal=--out=/x"],
                providers_override={"stub": seat})
        self.assertEqual(rc, 0)
        self.assertTrue(any("--out=/x" in p
                            for p in seat.prompts))


class PromptEgressWalkTests(unittest.TestCase):
    """The audit's "one egress boundary" in test form: one
    synthetic secret per prompt component — patch, file
    context, builder context, builder response, test output,
    AGENTS.md content — and no secret may reach any captured
    prompt or the serialized record, in either round."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q")
        # The secret line is a comment: git's hunk-header
        # function context backtracks to the last line that
        # starts with a word character, so a code-shaped first
        # line would be copied into the patch header itself
        # and the isolation below could not hold.
        base = ('# config: FILECTX_API_KEY = "' + SECRET_FILECTX
                + '"\n'
                + "".join(f"# filler {i}\n" for i in range(20))
                + "X = 1\n")
        _commit(self.repo, {
            "app.py": base,
            "AGENTS.md": '# Guidance\nAGENTS_API_KEY = "'
                         + SECRET_AGENTS + '"\n'}, "base")
        with open(os.path.join(self.repo, "app.py"), "a",
                  encoding="utf-8") as fh:
            fh.write('PATCH_API_KEY = "' + SECRET_PATCH + '"\n')
        self.patch = core.collect_git_patch(self.repo)
        # Isolation: the file-context secret sits far above
        # the diff hunk, so in this test it can only arrive
        # via the file context, never via the patch text.
        self.assertNotIn(SECRET_FILECTX, self.patch)
        self.assertIn(SECRET_PATCH, self.patch)

    def _assert_clean(self, prompts, report):
        self.assertTrue(prompts)
        blob = json.dumps(report)
        for secret in ALL_COMPONENT_SECRETS:
            for prompt in prompts:
                self.assertNotIn(secret, prompt)
            self.assertNotIn(secret, blob)
        # Non-vacuity: components really were attached — the
        # redaction marker reached the panel.
        self.assertTrue(any("REDACTED" in p for p in prompts))

    def test_review_round_walks_every_component(self):
        fctx, _entries = core.collect_file_context(
            self.repo, self.patch)
        agents_payload, _a = agentsmd.collect_agents_context(
            self.repo, self.patch)
        self.assertIsNotNone(agents_payload)
        seat = _Capture()
        report = core.run_review(
            self.patch, {"a": seat, "b": seat},
            context='change notes: CONTEXT_API_KEY = "'
                    + SECRET_CONTEXT + '"',
            test_results=[{
                "command": "pytest -q", "ok": False,
                "exit_code": 1,
                "output_tail": 'TEST_API_KEY = "'
                               + SECRET_TESTOUT + '"'}],
            file_context=fctx, agents_context=agents_payload)
        self._assert_clean(seat.prompts, report)

    def test_verification_round_walks_response_and_tests(self):
        seat = _VerifyCapture()
        report = core.run_verification(
            CLEAN_PATCH, {"a": seat, "b": seat},
            _previous_report(),
            'fixed; RESPONSE_API_KEY = "' + SECRET_RESPONSE
            + '"',
            test_results=[{
                "command": "pytest -q", "ok": False,
                "exit_code": 1,
                "output_tail": 'TEST_API_KEY = "'
                               + SECRET_TESTOUT + '"'}])
        self._assert_clean(seat.prompts, report)


if __name__ == "__main__":
    unittest.main()
