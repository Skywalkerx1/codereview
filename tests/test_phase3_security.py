"""Phase 3 (external security test pass) regression tests.

Each class pins one verified Phase 3 finding's fix. The
findings were reproduced against master 53f8987 before fixing;
these tests fail on the pre-fix code and pass after.
"""

import io
import json
import os
import re
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "src"))

from codereview import cli, core  # noqa: E402

PASS_VERDICT = json.dumps({"verdict": "pass", "summary": "ok",
                           "findings": []})


def pass_provider(_prompt):
    return PASS_VERDICT


SIMPLE_PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,2 @@\n"
    " x = 1\n"
    "+y = 2\n")


def run_cli(argv, **kw):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv, **kw)
    return rc, out.getvalue(), err.getvalue()


def read_record(outdir):
    records = [f for f in os.listdir(outdir)
               if f.endswith(".json")]
    assert len(records) == 1, records
    with open(os.path.join(outdir, records[0]),
              encoding="utf-8") as fh:
        return json.load(fh)


class PolicyOriginObservabilityTests(unittest.TestCase):
    """P3-01 (observability half): a repo-discovered policy is
    applied as before, but the record states its origin, stderr
    warns, and a change that touches the gate's own config
    files is flagged on the record."""

    def _repo_with_policy(self, tmp):
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        with open(os.path.join(repo, ".codereview.toml"),
                  "w", encoding="utf-8") as fh:
            fh.write('[gate]\nprofile = "strict"\n')
        return repo

    def _patch_file(self, tmp, text=SIMPLE_PATCH):
        patch = os.path.join(tmp, "change.diff")
        with open(patch, "w", encoding="utf-8") as fh:
            fh.write(text)
        return patch

    def test_discovered_policy_records_origin_and_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo_with_policy(tmp)
            outdir = os.path.join(tmp, "out")
            rc, _out, err = run_cli(
                ["--repo", repo, "--patch",
                 self._patch_file(tmp), "--out", outdir],
                providers_override={"a": pass_provider})
            self.assertEqual(rc, 0)
            record = read_record(outdir)
            self.assertEqual(record["policy"]["origin"],
                             "discovered-in-repo")
            self.assertIn("WARNING", err)
            self.assertIn("discovered in the reviewed "
                          "repository", err)

    def test_explicit_policy_records_explicit_origin_no_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.makedirs(repo)
            policy_path = os.path.join(tmp, "operator.toml")
            with open(policy_path, "w", encoding="utf-8") as fh:
                fh.write('[gate]\nprofile = "strict"\n')
            outdir = os.path.join(tmp, "out")
            rc, _out, err = run_cli(
                ["--repo", repo, "--patch",
                 self._patch_file(tmp), "--policy", policy_path,
                 "--out", outdir],
                providers_override={"a": pass_provider})
            self.assertEqual(rc, 0)
            record = read_record(outdir)
            self.assertEqual(record["policy"]["origin"],
                             "explicit")
            self.assertNotIn("WARNING", err)

    def test_change_touching_policy_file_is_flagged(self):
        patch = (
            "diff --git a/.codereview.toml b/.codereview.toml\n"
            "--- a/.codereview.toml\n"
            "+++ b/.codereview.toml\n"
            "@@ -0,0 +1,1 @@\n"
            "+[gate]\n"
            "diff --git a/docs/AGENTS.md b/docs/AGENTS.md\n"
            "--- a/docs/AGENTS.md\n"
            "+++ b/docs/AGENTS.md\n"
            "@@ -0,0 +1,1 @@\n"
            "+# guidance\n")
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.makedirs(repo)
            outdir = os.path.join(tmp, "out")
            rc, _out, _err = run_cli(
                ["--repo", repo, "--patch",
                 self._patch_file(tmp, patch), "--out", outdir],
                providers_override={"a": pass_provider})
            self.assertEqual(rc, 0)
            record = read_record(outdir)
            self.assertEqual(
                record["policy_self_modification"],
                [".codereview.toml", "docs/AGENTS.md"])

    def test_ordinary_change_has_no_self_modification_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.makedirs(repo)
            outdir = os.path.join(tmp, "out")
            rc, _out, _err = run_cli(
                ["--repo", repo, "--patch",
                 self._patch_file(tmp), "--out", outdir],
                providers_override={"a": pass_provider})
            self.assertEqual(rc, 0)
            record = read_record(outdir)
            self.assertNotIn("policy_self_modification", record)
            self.assertNotIn("policy", record)


def _patch_for(file, lines):
    body = "".join(f"+{line}\n" for line in lines)
    return (f"diff --git a/{file} b/{file}\n"
            f"--- a/{file}\n+++ b/{file}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n" + body)


class DeterministicScanBoundsTests(unittest.TestCase):
    """P3-02: the sql-string-build rule was cubic on long
    keyword-dense lines, and the scan had no per-line bound."""

    def _timed_scan(self, patch):
        started = time.monotonic()
        findings = core.deterministic_scan(patch)
        return findings, time.monotonic() - started

    def test_pathological_shapes_scan_fast(self):
        unit = ('var a="x",b="update",c=function(){return a+b};')
        shapes = {
            "minified-like": unit * 4000,          # ~184 KB
            "quote-plus repeats": "'x' + " * 22000,  # ~154 KB
            "keyword-dense": "delete from " * 16000,  # ~192 KB
        }
        for name, line in shapes.items():
            with self.subTest(shape=name):
                findings, elapsed = self._timed_scan(
                    _patch_for("app.min.js", [line]))
                self.assertLess(
                    elapsed, 5.0,
                    f"{name}: scan took {elapsed:.1f}s")
                self.assertIsInstance(findings, list)

    def test_legit_sql_string_builds_still_flagged(self):
        cases = [
            'cursor.execute("SELECT * FROM t WHERE id = " + uid)',
            'q = "delete from sessions where id = " + sid',
            'sql = f"UPDATE users SET name = {name}"',
            'q = "insert into logs values (%s)" % (v,)',
            'q = "select * from t where id = {}".format(uid)',
        ]
        for i, line in enumerate(cases):
            with self.subTest(line=line):
                findings = core.deterministic_scan(
                    _patch_for(f"mod{i}.py", [line]))
                rules = [f["rule"] for f in findings]
                self.assertIn("sql-string-build", rules)

    def test_scan_line_cap_keeps_head_findings(self):
        # A finding inside the first 16K chars of a huge line is
        # still reported; the scan does not walk the whole line.
        line = ('q = "SELECT * FROM t WHERE id = " + uid; '
                + "x" * 100000)
        findings, elapsed = self._timed_scan(
            _patch_for("big.py", [line]))
        self.assertIn("sql-string-build",
                      [f["rule"] for f in findings])
        self.assertLess(elapsed, 5.0)


class RedactionCoverageTests(unittest.TestCase):
    """P3-03: redact_secrets covered 7 of 32 secret shapes.
    The table mirrors the external test pass's shape list;
    the generic-encoded family (and a markerless PEM body
    line, and the case-transformed key id) are the accepted
    residual — pattern-based best-effort, no entropy games."""

    J = staticmethod("".join)
    AKID = J(["AKIA", "IOSFODNN7", "EXAMPLE"])

    def _cases(self):
        J = self.J
        akid = self.AKID
        import base64
        import urllib.parse
        return {
            "aws-akid": (akid, akid),
            "aws-temp-ASIA": (J(["ASIA", "IOSFODNN7", "EXAMPLE"]),
                              J(["ASIA", "IOSFODNN7", "EXAMPLE"])),
            "aws-secret-unquoted": (
                "aws_secret_access_key = "
                + J(["wJalrXUtnFEMI/K7MDENG",
                     "/bPxRfiCYEXAMPLEKEY"]),
                J(["wJalrXUtnFEMI/K7MDENG",
                   "/bPxRfiCYEXAMPLEKEY"])),
            "github-pat": (
                J(["gh", "p_",
                   "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"]),
                J(["gh", "p_",
                   "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"])),
            "github-fine": (
                J(["github_", "pat_",
                   "11ABCDEFG0abcdefghijkl_",
                   "abcdefghijklmnopqrstuvwxyz0123456789"
                   "ABCDEFGHIJKLMNOPQRST"]),
                J(["github_", "pat_",
                   "11ABCDEFG0abcdefghijkl_",
                   "abcdefghijklmnopqrstuvwxyz0123456789"
                   "ABCDEFGHIJKLMNOPQRST"])),
            "openai-sk": (
                J(["s", "k-", "proj-",
                   "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"]),
                J(["s", "k-", "proj-",
                   "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"])),
            "anthropic": (
                J(["sk-", "ant-", "api03-",
                   "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
                   "O5p6Q7r8S9t0"]),
                J(["sk-", "ant-", "api03-",
                   "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
                   "O5p6Q7r8S9t0"])),
            "slack-bot": (
                J(["xo", "xb-", "123456789012-",
                   "123456789012-",
                   "AbCdEfGhIjKlMnOpQrStUvWx"]),
                J(["xo", "xb-", "123456789012-",
                   "123456789012-",
                   "AbCdEfGhIjKlMnOpQrStUvWx"])),
            "stripe-live": (
                J(["sk_", "live_",
                   "51HabcdEFGH1234567890abcdef"]),
                J(["sk_", "live_",
                   "51HabcdEFGH1234567890abcdef"])),
            "google-api": (
                J(["AI", "za",
                   "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"]),
                J(["AI", "za",
                   "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"])),
            "jwt": (
                J(["eyJhbGciOiJIUzI1NiJ9.",
                   "eyJzdWIiOiIxMjM0NTY3ODkwIn0.",
                   "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJ"
                   "V_adQssw5c"]),
                J(["eyJhbGciOiJIUzI1NiJ9.",
                   "eyJzdWIiOiIxMjM0NTY3ODkwIn0.",
                   "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJ"
                   "V_adQssw5c"])),
            "db-url-password": (
                "postgres://admin:" + J(["Sup3r", "S3cretPw"])
                + "@db.internal:5432/app",
                J(["Sup3r", "S3cretPw"])),
            "yaml-password-unquoted": (
                "password: " + J(["Sup3r", "S3cretPw"]),
                J(["Sup3r", "S3cretPw"])),
            "env-style-unquoted": (
                "API_KEY=" + J(["abcd1234", "efgh5678"]),
                J(["abcd1234", "efgh5678"])),
            "env-style-quoted": (
                "API_KEY='" + J(["abcd1234", "efgh5678"]) + "'",
                J(["abcd1234", "efgh5678"])),
            "json-quoted-key": (
                '"password": "' + J(["Sup3r", "S3cretPw"]) + '"',
                J(["Sup3r", "S3cretPw"])),
            "basic-auth-header": (
                "Authorization: Basic "
                + base64.b64encode(
                    b"admin:Sup3rS3cretPw").decode(),
                base64.b64encode(
                    b"admin:Sup3rS3cretPw").decode()),
            "bearer": (
                "Authorization: Bearer "
                + J(["abcdEFGH1234", "ijklMNOP5678"]),
                J(["abcdEFGH1234", "ijklMNOP5678"])),
            "pem-header": ("-----BEGIN RSA " "PRIVATE KEY-----",
                           "-----BEGIN RSA " "PRIVATE KEY-----"),
            "pem-body-line": (
                "MIIEowIBAAKCAQEA" + "x7Jq" * 16,
                "MIIEowIBAAKCAQEA" + "x7Jq" * 16),
            "openssh-header": (
                "-----BEGIN OPENSSH " "PRIVATE KEY-----",
                "-----BEGIN OPENSSH " "PRIVATE KEY-----"),
            "akid-base64": (
                base64.b64encode(akid.encode()).decode(),
                base64.b64encode(akid.encode()).decode()),
            "akid-urlencoded-split": (
                urllib.parse.quote(akid[:10]) + "%0A" + akid[10:],
                urllib.parse.quote(akid[:10]) + "%0A"
                + akid[10:]),
            "akid-linewrapped": (
                akid[:8] + "\\\n" + akid[8:],
                akid[:8] + "\\\n" + akid[8:]),
            "akid-in-hex": (akid.encode().hex(),
                            akid.encode().hex()),
            "akid-lowercase": (akid.lower(), akid.lower()),
            "private_key_assign": (
                'private_key = "' + J(["abcdefghij", "klmnop"])
                + '"',
                J(["abcdefghij", "klmnop"])),
            "token-with-spaces-assign": (
                "token = '" + J(["abc", "def", "ghi"]) + "'",
                J(["abc", "def", "ghi"])),
            "passwd-single-char-key": (
                'PASSWORD="short"', "short"),
            "secret-ts-template": (
                "const secret = `" + J(["abcdEFGH1234",
                                        "ijklMNOP"]) + "`",
                J(["abcdEFGH1234", "ijklMNOP"])),
            "secret-fstring": (
                "secret = f\"" + J(["abcdEFGH1234",
                                    "ijklMNOP"]) + "\"",
                J(["abcdEFGH1234", "ijklMNOP"])),
            "secret-triple-quote": (
                'secret = """' + J(["abcdEFGH1234",
                                    "ijklMNOP"]) + '"""',
                J(["abcdEFGH1234", "ijklMNOP"])),
        }

    # The accepted residual: transformed forms of a key carry
    # no pattern a linear regex can honestly match.
    RESIDUAL = {"akid-base64", "akid-urlencoded-split",
                "akid-linewrapped", "akid-in-hex",
                "akid-lowercase", "pem-body-line"}

    def test_shape_table(self):
        for name, (text, payload) in self._cases().items():
            with self.subTest(shape=name):
                out = core.redact_secrets("+" + text)
                if name in self.RESIDUAL:
                    self.assertIn(payload, out,
                                  "residual shape changed — "
                                  "update the residual list")
                else:
                    self.assertNotIn(payload, out)

    def test_full_pem_block_redacted_wholesale(self):
        body = "MIIEowIBAAKCAQEA" + "x7Jq" * 16
        text = ("-----BEGIN RSA " "PRIVATE KEY-----\n" + body
                + "\n-----END RSA " "PRIVATE KEY-----\n")
        out = core.redact_secrets(text)
        self.assertNotIn(body, out)
        self.assertNotIn("MIIEowIBAAKCAQEA", out)
        self.assertIn("[REDACTED-PRIVATE-KEY]", out)

    def test_redaction_is_linear_on_pathological_text(self):
        # A long word-run with no keyword and no separator must
        # not send the assignment patterns quadratic (the
        # unbounded-lazy-prefix failure mode).
        text = ('var a="x",b="update",c=function(){return a+b};'
                * 2000 + "z" * 100000)
        started = time.monotonic()
        core.redact_secrets(text)
        self.assertLess(time.monotonic() - started, 5.0)

    def test_call_targets_are_not_redacted(self):
        # An unquoted value that is a call target is code, not
        # a secret literal.
        self.assertEqual(
            core.redact_secrets("token = compute_total(items)"),
            "token = compute_total(items)")
        self.assertIn(
            "os.environ.get",
            core.redact_secrets('password = os.environ.get("P")'))

    def test_scanner_flags_provider_token_prefixes(self):
        shapes = [
            ("ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
             "provider-token"),
            ("sk_live_51HabcdEFGH1234567890abcdef",
             "provider-token"),
            ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkw"
             "In0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
             "provider-token"),
            ("ASIA" + "IOSFODNN7" + "EXAMPLE", "aws-access-key"),
            ("xoxb-123456789012-123456789012-AbCdEfGhIjKl",
             "provider-token"),
        ]
        for i, (token, rule) in enumerate(shapes):
            with self.subTest(rule=rule, token=token[:12]):
                findings = core.deterministic_scan(
                    _patch_for(f"tok{i}.py",
                               [f'value = "{token}"']))
                self.assertIn(rule,
                              [f["rule"] for f in findings])


@unittest.skipUnless(sys.platform.startswith("linux"),
                     "PR_SET_DUMPABLE / /proc semantics are "
                     "Linux-only")
class ParentEnvironHardeningTests(unittest.TestCase):
    """P3-04: in env-only sandbox mode the child's own env is
    allow-listed, but /proc/$PPID/environ exposed the gate
    process's full environment to the sandboxed command."""

    def test_make_non_dumpable_idempotent(self):
        from codereview import hardening
        self.assertTrue(hardening.make_non_dumpable())
        self.assertTrue(hardening.make_non_dumpable())

    def test_env_only_child_cannot_read_parent_environ(self):
        from unittest import mock

        from codereview import evidence as ev
        sentinel = "CODEREVIEW_P3_SENTINEL"
        cfg = {"commands": [{
            "name": "c", "timeout": 20,
            "command":
                'echo "count=$(tr "\\0" "\\n" '
                '< /proc/$PPID/environ 2>/dev/null '
                f'| grep -c {sentinel})"'}]}
        with mock.patch.dict(os.environ,
                             {sentinel: "s3cr3t-value"}):
            with mock.patch.object(ev, "_UNSHARE_OK", False):
                with tempfile.TemporaryDirectory() as d:
                    with open(os.path.join(d, "a"),
                              "w") as fh:
                        fh.write("x")
                    item = ev.collect(cfg, d)["items"][0]
        self.assertEqual(item["status"], "passed")
        self.assertIn("count=0", item["output_tail"])
        self.assertNotIn("s3cr3t-value", item["output_tail"])


class McpNestedFrameTests(unittest.TestCase):
    """P3-05: a JSON frame nested deeper than the interpreter
    limit raised RecursionError out of json.loads, killing
    serve_forever with no PARSE_ERROR and no ledger entry."""

    def test_deeply_nested_frame_gets_parse_error(self):
        from codereview import mcp_tools, mcp_transport

        def good(_prompt):
            return PASS_VERDICT

        depth = 50000
        raw = (b'{"jsonrpc":"2.0","method":"ping","id":1,'
               b'"params":' + b"[" * depth + b"]" * depth
               + b"}\n")
        valid = (b'{"jsonrpc":"2.0","method":"ping",'
                 b'"id":"after"}\n')
        stdin = io.BytesIO(raw + valid)
        stdout = io.BytesIO()
        logs = []
        tools = mcp_tools.GateTools(
            providers_override={"a": good})
        server = mcp_tools.serve_stdio(
            tools, stdin=stdin, stdout=stdout,
            log=logs.append)
        out = [json.loads(line) for line in
               stdout.getvalue().decode().splitlines()
               if line.strip()]
        self.assertEqual(out[0]["error"]["code"],
                         mcp_transport.PARSE_ERROR)
        self.assertIsNone(out[0]["id"])
        self.assertEqual(out[1]["id"], "after")
        self.assertIn("parse_error",
                      [e["kind"] for e in server.errors])


class SandboxGroupKillTests(unittest.TestCase):
    """P3-06: _kill_group ran only on the timeout path; a
    backgrounded child with redirected stdio survived a
    passed run."""

    def test_background_child_killed_on_normal_exit(self):
        from codereview import evidence as ev
        cfg = {"commands": [{
            "name": "c", "timeout": 20,
            "command": "sleep 60 >/dev/null 2>&1 & "
                       "echo bgpid=$!; echo done"}]}
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a"), "w") as fh:
                fh.write("x")
            item = ev.collect(cfg, d)["items"][0]
        self.assertEqual(item["status"], "passed")
        match = re.search(r"bgpid=(\d+)", item["output_tail"])
        self.assertIsNotNone(match, item["output_tail"])
        pid = int(match.group(1))

        def dead():
            try:
                with open(f"/proc/{pid}/stat") as fh:
                    return fh.read().rsplit(")", 1)[1] \
                        .split()[0] == "Z"
            except FileNotFoundError:
                return True
            except OSError:
                return False

        try:
            deadline = time.monotonic() + 5
            while not dead() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(
                dead(), f"background pid {pid} survived the run")
        finally:
            try:
                os.kill(pid, 9)
            except OSError:
                pass


class DiscoveryProbeCapTests(unittest.TestCase):
    """P3-07: default_probe buffered a --version probe's
    output without bound (subprocess.run capture) and only
    OSError/TimeoutExpired were caught, so a spewing binary
    could raise MemoryError out of discover_clis despite the
    never-raises docstring."""

    def _bindir(self, tmp, name, body):
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir, exist_ok=True)
        path = os.path.join(bindir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.chmod(path, 0o755)
        return bindir

    def test_spewing_binary_probe_is_capped_and_calm(self):
        from codereview import discovery
        body = ("#!/usr/bin/env python3\n"
                "import sys\n"
                "sys.stdout.write('claude 1.0\\n' "
                "+ 'A' * 5000000)\n"
                "sys.stdout.flush()\n")
        with tempfile.TemporaryDirectory() as tmp:
            bindir = self._bindir(tmp, "claude", body)
            started = time.monotonic()
            found = discovery.discover_clis(path_value=bindir)
            elapsed = time.monotonic() - started
        self.assertEqual([f["name"] for f in found], ["claude"])
        self.assertFalse(found[0]["probe_ok"])
        self.assertLess(elapsed, 10)

    def test_probe_exception_becomes_failed_probe(self):
        from codereview import discovery

        def bad_probe(_path):
            raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmp:
            bindir = self._bindir(
                tmp, "claude", "#!/bin/sh\necho 'claude 1.0'\n")
            found = discovery.discover_clis(
                path_value=bindir, probe_fn=bad_probe)
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0]["probe_ok"])
        self.assertIn("boom", found[0]["probe_detail"])

    def test_well_behaved_binary_still_probes_ok(self):
        from codereview import discovery
        with tempfile.TemporaryDirectory() as tmp:
            bindir = self._bindir(
                tmp, "claude", "#!/bin/sh\necho 'claude 1.2.3'\n")
            found = discovery.discover_clis(path_value=bindir)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["probe_ok"])
        self.assertEqual(found[0]["probe_detail"],
                         "claude 1.2.3")


class HerdrMalformedOutputTests(unittest.TestCase):
    """P3-08: herdrhost._cli_json caught only ValueError and
    returned non-dict documents as-is; snapshot() then died
    with AttributeError (null / list) or RecursionError
    (deep nesting) instead of detect() going inert."""

    def _detect(self, snap_out):
        from codereview import herdrhost

        def run_fn(argv, _timeout):
            if "--version" in argv:
                return 0, "herdr 0.9.5\n", ""
            if "schema" in argv:
                return 0, json.dumps({
                    "methods": list(herdrhost.REQUIRED_METHODS),
                    "events": list(herdrhost.REQUIRED_EVENTS)}), ""
            return 0, snap_out, ""

        return herdrhost.detect(
            environ={}, which_fn=lambda _n: "/bin/herdr",
            run_fn=run_fn)

    def test_malformed_snapshots_go_inert(self):
        for label, snap in [("null", "null"),
                            ("array", "[1,2,3]"),
                            ("deep-nested", "[" * 100000)]:
            with self.subTest(shape=label):
                plan = self._detect(snap)
                self.assertFalse(plan["active"])
                self.assertTrue(plan["reason"])

    def test_error_object_still_goes_inert(self):
        plan = self._detect('{"error":"boom"}')
        self.assertFalse(plan["active"])
        self.assertIn("boom", plan["reason"])

    def test_valid_snapshot_still_detects(self):
        plan = self._detect('{"snapshot":{"workspaces":[]}}')
        self.assertTrue(plan["active"])
        self.assertIsNotNone(plan["host"])


if __name__ == "__main__":
    unittest.main()
