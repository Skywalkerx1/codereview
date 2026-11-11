"""Phase 3 (external security test pass) regression tests.

Each class pins one verified Phase 3 finding's fix. The
findings were reproduced against master 53f8987 before fixing;
these tests fail on the pre-fix code and pass after.
"""

import io
import json
import os
import re
import shutil
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

    def test_git_mode_untracked_policy_file_is_flagged(self):
        # The external pass's scenario: the policy file is
        # part of the working-tree change but UNTRACKED, so
        # git diff never shows it as a patch section.
        import subprocess
        if not shutil.which("git"):
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.makedirs(repo)

            def git(*a):
                subprocess.run(["git", "-C", repo, *a],
                               check=True, capture_output=True)

            git("init", "-q")
            with open(os.path.join(repo, "app.py"),
                      "w") as fh:
                fh.write("import os\n")
            git("add", ".")
            git("-c", "user.email=a@b", "-c", "user.name=a",
                "commit", "-qm", "base")
            with open(os.path.join(repo, "app.py"),
                      "a") as fh:
                fh.write("VALUE = 1\n")
            with open(os.path.join(repo, ".codereview.toml"),
                      "w") as fh:
                fh.write('[gate]\nprofile = "strict"\n')
            outdir = os.path.join(tmp, "out")
            rc, _out, err = run_cli(
                ["--repo", repo, "--out", outdir],
                providers_override={"a": pass_provider})
            self.assertEqual(rc, 0)
            record = read_record(outdir)
            self.assertEqual(record["policy"]["origin"],
                             "discovered-in-repo")
            self.assertEqual(
                record["policy_self_modification"],
                [".codereview.toml"])
            self.assertIn("WARNING", err)

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


class ScanCapEvasionTests(unittest.TestCase):
    """P3-02 follow-up (tester pushback on our fix): the
    original 16K prefix cap blinded EVERY rule past 16K — a
    key planted at offset 20,000 of one line produced zero
    findings. Lines are now scanned in full up to a 1M hard
    bound; past it, the scan covers the prefix and the
    truncation is itself a minor finding. Secret-shaped
    literals are fragmented (see the fixture-hygiene note in
    RedactionCoverageTests)."""

    def test_key_planted_past_16k_is_found(self):
        key = "AK" + "IA" + "1234567890ABCDEF"
        line = "var x = '" + "a" * 20000 + "'; // " + key
        findings = core.deterministic_scan(
            _patch_for("bundle.min.js", [line]))
        self.assertIn("aws-access-key",
                      [f["rule"] for f in findings])

    def test_private_key_header_and_eval_past_16k_found(self):
        header = "-----BEGIN RSA " + "PRIVATE KEY-----"
        line1 = "b" * 20000 + header
        line2 = "c" * 20000 + "; eval(user_input)"
        findings = core.deterministic_scan(
            _patch_for("late.py", [line1, line2]))
        rules = [f["rule"] for f in findings]
        self.assertIn("private-key", rules)
        self.assertIn("eval-exec", rules)

    def test_line_past_hard_bound_reports_truncation(self):
        key = "AK" + "IA" + "1234567890ABCDEF"
        line = "d" * 1_000_001 + key
        findings = core.deterministic_scan(
            _patch_for("huge.js", [line]))
        trunc = [f for f in findings
                 if f["rule"] == "scan-line-truncated"]
        self.assertEqual(len(trunc), 1)
        self.assertEqual(trunc[0]["severity"], "minor")
        # The key sits past the bound: the scan does not
        # claim to have seen it.
        self.assertNotIn("aws-access-key",
                         [f["rule"] for f in findings])

    def test_megabyte_pathological_line_scans_fast(self):
        line = "'x' + " * 150000  # ~900 KB of quote-plus
        started = time.monotonic()
        core.deterministic_scan(_patch_for("patho.js", [line]))
        self.assertLess(time.monotonic() - started, 10.0)


class RedactionCoverageTests(unittest.TestCase):
    """P3-03: redact_secrets covered 7 of 32 secret shapes.
    The table mirrors the external test pass's shape list;
    the generic-encoded family (and the case-transformed
    key id) are the accepted residual — pattern-based
    best-effort, no entropy games. The bare PEM body line
    joined the covered shapes at L8 (2026-11-07): 27 of 32."""

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
                "akid-lowercase"}

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

    def test_bare_pem_body_line_shapes(self):
        # L8: a diff hunk that starts mid-key has no header
        # line; the body line is covered when it carries the
        # key's DER/OpenSSH start and stands alone on its line.
        body = "MIIEowIBAAKCAQEA" + "x7Jq" * 16
        for text in ("+" + body,
                     " " + body,
                     "    \"" + body + "\",",
                     "+" + "b3BlbnNzaC1rZXktdjEAAAAA"
                     + "x7Jq" * 10):
            with self.subTest(text=text[:24]):
                out = core.redact_secrets(text)
                self.assertIn("[REDACTED-PRIVATE-KEY]", out)
                self.assertNotIn("x7Jqx7Jq", out)

    def test_bare_pem_body_residual_edges_stay(self):
        # The boundary, pinned: later body lines of a
        # headerless fragment (no key-start prefix), generic
        # base64, and short fragments are NOT redacted —
        # encoded data is the documented residual, and the
        # shape is the key's start, not base64 itself.
        import base64
        for text in ("+" + "x7Jq" * 20,
                     "+" + base64.b64encode(
                         b"hello world, plain data").decode()
                     * 4,
                     "+MIIEowIBAAKCAQEA",
                     "the MIIEowIBAAKCAQEA value in prose"
                     " is not a body line"):
            with self.subTest(text=text[:24]):
                self.assertEqual(core.redact_secrets(text), text)

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
class ValueStopCharsEscapeTests(unittest.TestCase):
    """Rerun-2 nit (S3): `_VALUE_STOP_CHARS` spelled the
    backslash member as the invalid escape `\\[` in a
    non-raw string — a SyntaxWarning on compile under
    Python 3.12+, a SyntaxError under `-W error`, and a
    future hard error. The set itself was always correct
    (Python kept the backslash); pin both the set and a
    warning-free compile of the whole module."""

    def test_stop_char_set_is_exact(self):
        self.assertEqual(core._VALUE_STOP_CHARS, frozenset(
            " \t\r\n,'\"`(){}[]\\"))

    def test_core_module_compiles_without_syntax_warnings(
            self):
        import warnings
        path = os.path.join(os.path.dirname(
            os.path.abspath(core.__file__)), "core.py")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            compile(source, path, "exec")


class ParentEnvironHardeningTests(unittest.TestCase):
    """P3-04: in env-only sandbox mode the child's own env is
    allow-listed, but /proc/$PPID/environ exposed the gate
    process's full environment to the sandboxed command."""

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "PR_SET_DUMPABLE is Linux-only; elsewhere the call "
        "reports False — see test_non_linux_claims_no_hardening")
    def test_make_non_dumpable_idempotent(self):
        from codereview import hardening
        self.assertTrue(hardening.make_non_dumpable())
        self.assertTrue(hardening.make_non_dumpable())

    def test_non_linux_claims_no_hardening(self):
        # macOS and Windows have no prctl: the call must say
        # the protection is NOT in effect, never report True.
        from unittest import mock

        from codereview import hardening
        with mock.patch.object(hardening, "_APPLIED", False), \
                mock.patch.object(hardening.sys, "platform",
                                  "darwin"):
            self.assertFalse(hardening.make_non_dumpable())
            self.assertFalse(hardening._APPLIED)

    def test_collect_applies_hardening_at_entry(self):
        # L11: the hardening lives inside collect() itself,
        # so direct library use is protected even when no
        # item executes (the _execute backstop alone would
        # never fire on an empty config).
        from unittest import mock

        from codereview import evidence as ev
        from codereview import hardening
        with mock.patch.object(
                hardening, "make_non_dumpable",
                wraps=hardening.make_non_dumpable) as spy:
            with tempfile.TemporaryDirectory() as d:
                with open(os.path.join(d, "a"), "w") as fh:
                    fh.write("x")
                record = ev.collect({"commands": []}, d)
        self.assertEqual(record["items"], [])
        self.assertGreaterEqual(spy.call_count, 1)

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


class EnvOnlyKeyExposureWarningTests(unittest.TestCase):
    """P3-04 follow-up: env-only mode has no pid namespace,
    so a sandboxed child can read a SIBLING same-uid
    process's environ via /proc (THREAT-MODEL residual 7) —
    not ours to close for processes we do not own. When the
    gate environment carries key-shaped variable names, the
    run surfaces the exposure: once on stderr, and as a
    warning in the evidence record's sandbox section."""

    def setUp(self):
        from codereview import evidence as ev
        ev._ENV_ONLY_WARNING_EMITTED = False
        self.addCleanup(setattr, ev,
                        "_ENV_ONLY_WARNING_EMITTED", False)

    def _collect(self):
        from codereview import evidence as ev
        cfg = {"commands": [{"name": "c", "timeout": 20,
                             "command": "true"}]}
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a"), "w") as fh:
                fh.write("x")
            err = io.StringIO()
            with redirect_stderr(err):
                record = ev.collect(cfg, d)
        return record, err.getvalue()

    def test_env_only_with_key_names_warns_and_records(self):
        from unittest import mock

        from codereview import evidence as ev
        with mock.patch.object(ev, "_UNSHARE_OK", False):
            with mock.patch.dict(
                    os.environ,
                    {"CODEREVIEW_TEST_API_KEY": "fake-value"}):
                record, err = self._collect()
        self.assertEqual(record["sandbox"]["network"],
                         "env-only")
        warning = record["sandbox"].get("warning")
        self.assertIsNotNone(warning)
        self.assertIn("CODEREVIEW_TEST_API_KEY", warning)
        self.assertIn("env-only", err)
        self.assertIn("CODEREVIEW_TEST_API_KEY", err)
        # Names only — values are never surfaced.
        self.assertNotIn("fake-value", warning)
        self.assertNotIn("fake-value", err)

    def test_env_only_without_key_names_is_silent(self):
        from unittest import mock

        from codereview import evidence as ev
        clean = {k: v for k, v in os.environ.items()
                 if not ev._KEY_SHAPED_NAME_RE.search(k)
                 and not k.endswith("_KEY")}
        with mock.patch.object(ev, "_UNSHARE_OK", False):
            with mock.patch.dict(os.environ, clean,
                                 clear=True):
                record, err = self._collect()
        self.assertEqual(record["sandbox"]["network"],
                         "env-only")
        self.assertNotIn("warning", record["sandbox"])
        self.assertEqual(err, "")

    def test_namespace_mode_with_key_names_is_silent(self):
        from unittest import mock

        from codereview import evidence as ev
        if not ev._unshare_ok():
            self.skipTest("user namespaces unavailable here")
        with mock.patch.dict(
                os.environ,
                {"CODEREVIEW_TEST_API_KEY": "fake-value"}):
            record, err = self._collect()
        self.assertEqual(record["sandbox"]["network"],
                         "namespace")
        self.assertNotIn("warning", record["sandbox"])
        self.assertEqual(err, "")


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

    def _serve(self, *frames):
        from codereview import mcp_tools
        stdin = io.BytesIO(b"".join(f + b"\n" for f in frames))
        stdout = io.BytesIO()
        server = mcp_tools.serve_stdio(
            mcp_tools.GateTools(
                providers_override={"a": lambda _p: PASS_VERDICT}),
            stdin=stdin, stdout=stdout, log=lambda _t: None)
        return [json.loads(line) for line in
                stdout.getvalue().decode().splitlines()
                if line.strip()], server

    def _ping(self, params):
        return (b'{"jsonrpc":"2.0","method":"ping","id":1,'
                b'"params":' + params + b"}")

    def test_depth_cap_is_explicit_not_interpreter_dependent(self):
        # One level past the cap is refused on every Python,
        # far below any interpreter recursion limit — the
        # refusal no longer depends on json.loads raising
        # RecursionError (which Python 3.14 on macOS does not).
        from codereview import mcp_transport
        limit = mcp_transport.MAX_NESTING_DEPTH
        # The ping object itself is one level, so this frame
        # nests limit + 1 deep.
        over = self._ping(b"[" * limit + b"]" * limit)
        out, server = self._serve(over)
        self.assertEqual(out[0]["error"]["code"],
                         mcp_transport.PARSE_ERROR)
        self.assertIsNone(out[0]["id"])
        self.assertIn("parse_error",
                      [e["kind"] for e in server.errors])

    def test_frame_at_the_depth_cap_is_served(self):
        from codereview import mcp_transport
        depth = mcp_transport.MAX_NESTING_DEPTH - 1
        out, server = self._serve(
            self._ping(b"[" * depth + b"]" * depth))
        self.assertEqual(out[0]["id"], 1)
        self.assertNotIn("error", out[0])
        self.assertEqual(server.errors, [])

    def test_brackets_inside_strings_do_not_count(self):
        from codereview import mcp_transport
        depth = mcp_transport.MAX_NESTING_DEPTH * 4
        text = ('"\\"' + "[" * depth + '{"').encode()
        out, server = self._serve(
            self._ping(b'{"note":' + text + b"}"))
        self.assertEqual(out[0]["id"], 1)
        self.assertNotIn("error", out[0])
        self.assertEqual(server.errors, [])


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


class MissingRepoValidationTests(unittest.TestCase):
    """P3-09 (test_missing_repo_is_an_error): no existence
    check existed anywhere — a nonexistent --repo was
    accepted in patch mode too, silently skipping policy /
    AGENTS.md / evidence context, and repo="" became the
    CWD."""

    def _patch_file(self, tmp):
        patch = os.path.join(tmp, "change.diff")
        with open(patch, "w", encoding="utf-8") as fh:
            fh.write(SIMPLE_PATCH)
        return patch

    def test_cli_nonexistent_repo_patch_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "no-such-dir")
            rc, _out, err = run_cli(
                ["--patch", self._patch_file(tmp),
                 "--repo", missing,
                 "--out", os.path.join(tmp, "out")],
                providers_override={"a": pass_provider})
            self.assertEqual(rc, 2)
            self.assertIn(missing, err)

    def test_cli_nonexistent_repo_git_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "no-such-dir")
            rc, _out, err = run_cli(
                ["--repo", missing,
                 "--out", os.path.join(tmp, "out")],
                providers_override={"a": pass_provider})
            self.assertEqual(rc, 2)
            self.assertIn(missing, err)

    def test_cli_empty_repo_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, _out, err = run_cli(
                ["--patch", self._patch_file(tmp),
                 "--repo", "",
                 "--out", os.path.join(tmp, "out")],
                providers_override={"a": pass_provider})
            self.assertEqual(rc, 2)
            self.assertIn("--repo", err)

    def test_mcp_nonexistent_repo_is_tool_error(self):
        from codereview import mcp_tools
        tools = mcp_tools.GateTools(
            providers_override={"a": pass_provider})
        with self.assertRaises(mcp_tools.ToolError):
            tools.run_gate({"repo": "/nonexistent/zzz",
                            "patch": SIMPLE_PATCH})
        with self.assertRaises(mcp_tools.ToolError):
            tools.run_gate({"repo": "", "patch": SIMPLE_PATCH})


class McpProtocolStrictnessTests(unittest.TestCase):
    """P3-10: _handle never read the jsonrpc field (a "1.0"
    or versionless frame was served as 2.0), and a NaN id was
    echoed through json.dumps' default allow_nan=True,
    emitting invalid JSON."""

    def _serve(self, frames):
        from codereview import mcp_transport

        def dispatch(method, _params, _notification):
            return {"echo": method}

        raw_in = io.BytesIO(b"".join(frames))
        raw_out = io.BytesIO()
        server = mcp_transport.StdioServer(
            dispatch, stdin=raw_in, stdout=raw_out,
            log=lambda _t: None)
        server.serve_forever()
        return raw_out.getvalue(), server

    def test_wrong_or_missing_jsonrpc_rejected(self):
        from codereview import mcp_transport
        for frame in (
                b'{"jsonrpc":"1.0","method":"ping","id":1}\n',
                b'{"method":"ping","id":1}\n'):
            with self.subTest(frame=frame):
                raw, server = self._serve(
                    [frame,
                     b'{"jsonrpc":"2.0","method":"ping",'
                     b'"id":2}\n'])
                responses = [json.loads(line) for line in
                             raw.decode().splitlines()]
                self.assertEqual(
                    responses[0]["error"]["code"],
                    mcp_transport.INVALID_REQUEST)
                self.assertEqual(responses[1]["id"], 2)
                self.assertEqual(
                    responses[1]["result"], {"echo": "ping"})

    def test_bad_version_notification_gets_no_response(self):
        raw, server = self._serve(
            [b'{"jsonrpc":"1.0","method":"ping"}\n',
             b'{"jsonrpc":"2.0","method":"ping","id":2}\n'])
        responses = [json.loads(line) for line in
                     raw.decode().splitlines()]
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], 2)
        self.assertEqual([e["kind"] for e in server.errors],
                         ["invalid_request"])

    def test_nan_id_echoed_as_null_strict_json(self):
        raw, _server = self._serve(
            [b'{"jsonrpc":"2.0","method":"ping","id":NaN}\n'])

        def no_constants(value):
            raise ValueError(value)

        parsed = json.loads(raw.decode(),
                            parse_constant=no_constants)
        self.assertIsNone(parsed["id"])
        self.assertEqual(parsed["result"], {"echo": "ping"})


class SharedContainmentHelperTests(unittest.TestCase):
    """P3-11: cli._is_within was the shared fail-closed
    helper, but agentsmd and core's file-context collector
    called os.path.commonpath directly (agentsmd's site did
    not even catch the cross-drive ValueError locally). One
    implementation now lives in core."""

    def test_all_sites_use_the_one_implementation(self):
        from codereview import agentsmd, cli
        self.assertIs(cli._is_within, core._is_within)
        self.assertIs(agentsmd._is_within, core._is_within)

    def test_helper_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            inner = os.path.join(tmp, "a", "b.txt")
            self.assertTrue(core._is_within(inner, tmp))
            self.assertTrue(core._is_within(tmp, tmp))
            self.assertFalse(
                core._is_within(os.path.join(tmp, "..", "x"),
                                tmp))

    def test_commonpath_value_error_fails_closed(self):
        from unittest import mock
        with mock.patch("os.path.commonpath",
                        side_effect=ValueError("mixed drives")):
            self.assertFalse(core._is_within("/a/b", "/a"))


class NotifierSummaryHygieneTests(unittest.TestCase):
    """P3-12: _one_line collapsed whitespace only — ESC/BEL/
    OSC escape bytes and unbounded strings reached both the
    notifier argv and the recorded outcome verbatim."""

    def _fire(self, summary):
        from codereview import notify
        captured = []

        def runner(argv, _timeout):
            captured.append(argv)
            return 0

        notifier = notify.Notifier(["notify-cmd"], runner=runner)
        outcome = notifier.fire("verdict", summary)
        return captured[0], outcome

    def test_escape_bytes_never_reach_argv_or_record(self):
        hostile = ["\x1b[2J", "\x1b]0;pwn\x07evil",
                   "\x1b]8;;https://x\x1b\\click\x07",
                   "bell\x07here", "del\x7fhere"]
        for text in hostile:
            with self.subTest(text=text):
                argv, outcome = self._fire("seat " + text)
                self.assertNotIn("\x1b", argv[2])
                self.assertNotIn("\x07", argv[2])
                self.assertNotIn("\x7f", argv[2])
                self.assertEqual(outcome["summary"], argv[2])

    def test_summary_capped_at_500_with_marker(self):
        _argv, outcome = self._fire("x" * 100000)
        self.assertEqual(len(outcome["summary"]), 500)
        self.assertTrue(outcome["summary"].endswith("…"))

    def test_ordinary_summary_unchanged(self):
        _argv, outcome = self._fire("gate blocked: 3 findings")
        self.assertEqual(outcome["summary"],
                         "gate blocked: 3 findings")


if __name__ == "__main__":
    unittest.main()
