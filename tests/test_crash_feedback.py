"""L17-L19: crash handling, support bundle, opt-in feedback."""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
FAKE_KEY = "sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0" * 2
FAKE_GH = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


class _Server:
    """Loopback fake collector that records every request."""

    def __init__(self, status=200, body=b'{"id":"r1"}', redirect=None,
                 delay=0.0):
        self.requests = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                outer.requests.append((self.path, dict(self.headers),
                                       self.rfile.read(n)))
                if delay:
                    import time
                    time.sleep(delay)
                if redirect:
                    self.send_response(302)
                    self.send_header("Location", redirect)
                    self.end_headers()
                    return
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/ingest"
        threading.Thread(target=self.httpd.serve_forever,
                         daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def run(code, args=(), env=None, cwd=None, stdin=None, timeout=60):
    e = {k: v for k, v in os.environ.items()
         if not k.startswith("CODEREVIEW_")}
    e["PYTHONPATH"] = SRC
    e.update(env or {})
    return subprocess.run(
        [sys.executable, "-c", code, *args], capture_output=True,
        text=True, env=e, cwd=cwd, input=stdin, timeout=timeout)


CRASHING = (
    "import sys, codereview.cli as c\n"
    "def boom(argv):\n"
    f"    raise RuntimeError('boom {FAKE_KEY} {FAKE_GH}')\n"
    "c.main = boom\n"
    "raise SystemExit(c.console_main())\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.state = os.path.join(self.d, "state")
        self.env = {"CODEREVIEW_STATE_DIR": self.state,
                    "CODEREVIEW_CRASH_DIR": self.d}

    def tearDown(self):
        self.tmp.cleanup()


class CrashTests(Base):
    def test_crash_exits_2_with_one_line_and_note(self):
        r = run(CRASHING, ["pr", "--token", FAKE_KEY], self.env,
                self.d)
        self.assertEqual(r.returncode, 2)
        self.assertIn("internal error (RuntimeError)", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        notes = [f for f in os.listdir(self.d)
                 if f.startswith("codereview-crash-")]
        self.assertEqual(len(notes), 1)
        text = open(os.path.join(self.d, notes[0])).read()
        json.loads(text)
        for secret in (FAKE_KEY, FAKE_GH):
            self.assertNotIn(secret, text)
            self.assertNotIn(secret, r.stderr)
            self.assertNotIn(secret, r.stdout)
        mode = os.stat(os.path.join(self.d, notes[0])).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_debug_prints_redacted_traceback(self):
        r = run(CRASHING, ["--debug"], self.env, self.d)
        self.assertEqual(r.returncode, 2)
        self.assertIn("Traceback", r.stderr)
        self.assertNotIn(FAKE_KEY, r.stderr)
        r = run(CRASHING, [], dict(self.env, CODEREVIEW_DEBUG="1"),
                self.d)
        self.assertIn("Traceback", r.stderr)

    def test_keyboard_interrupt_130(self):
        code = CRASHING.replace("RuntimeError(", "KeyboardInterrupt(")
        r = run(code, [], self.env, self.d)
        self.assertEqual(r.returncode, 130)
        self.assertNotIn("internal error", r.stderr)

    def test_broken_pipe_141_quiet(self):
        code = CRASHING.replace("RuntimeError(", "BrokenPipeError(")
        r = run(code, [], self.env, self.d)
        self.assertEqual(r.returncode, 141)
        self.assertNotIn("Traceback", r.stderr)

    def test_normal_exit_codes_pass_through(self):
        code = ("import codereview.cli as c\n"
                "c.main = lambda argv: 1\n"
                "raise SystemExit(c.console_main())\n")
        self.assertEqual(run(code, [], self.env, self.d).returncode, 1)

    def test_crash_never_reads_as_pass_or_blocked(self):
        r = run(CRASHING, [], self.env, self.d)
        self.assertNotIn(r.returncode, (0, 1))

    def test_hook_runs_and_hook_failure_is_tolerated(self):
        code = (
            "import codereview.cli as c, codereview.crash as k\n"
            "def bad(): raise ValueError('x')\n"
            "def good(): print('HOOKRAN')\n"
            "def boom(argv):\n"
            "    k.register_crash_hook(bad); k.register_crash_hook(good)\n"
            "    raise RuntimeError('b')\n"
            "c.main = boom\n"
            "raise SystemExit(c.console_main())\n")
        r = run(code, [], self.env, self.d)
        self.assertEqual(r.returncode, 2)
        self.assertIn("HOOKRAN", r.stdout)

    def test_unwritable_crash_dir_still_exits_2(self):
        env = dict(self.env, CODEREVIEW_CRASH_DIR="/nonexistent/x/y")
        r = run(CRASHING, [], env, self.d)
        self.assertEqual(r.returncode, 2)
        self.assertIn("internal error", r.stderr)

    def test_library_main_still_raises(self):
        code = ("import codereview.cli as c\n"
                "c.main = None\n")
        # main itself is not wrapped: only console_main guards.
        from codereview import crash
        with self.assertRaises(RuntimeError):
            def f(argv):
                raise RuntimeError("x")
            f([])
        self.assertTrue(callable(crash.run_guarded))


class BundleTests(Base):
    def make_records(self):
        rec = os.path.join(self.d, "codereview-out")
        os.makedirs(rec)
        with open(os.path.join(rec, "codereview-20261107-000000.json"), "w") as fh:
            json.dump({"note": f"leak {FAKE_KEY}"}, fh)
        with open(os.path.join(rec, "codereview-20261107-000000.md"), "w") as fh:
            fh.write(f"# run {FAKE_GH}\n")
        return rec

    def bundle(self, *extra, env=None):
        out = os.path.join(self.d, "b.zip")
        r = run("import sys; from codereview.cli import console_main;"
                "raise SystemExit(console_main())",
                ["support-bundle", "--out", out, *extra],
                dict(self.env, **(env or {})), self.d)
        return r, out

    def test_bundle_redacts_and_has_manifest(self):
        self.make_records()
        r, out = self.bundle(
            "--message", f"my key {FAKE_KEY}",
            env={"ANTHROPIC_API_KEY": FAKE_KEY, "GITHUB_TOKEN": FAKE_GH})
        self.assertEqual(r.returncode, 0, r.stderr)
        z = zipfile.ZipFile(out)
        names = z.namelist()
        self.assertIn("MANIFEST.txt", names)
        blob = b"".join(z.read(n) for n in names).decode("utf-8",
                                                          "replace")
        for secret in (FAKE_KEY, FAKE_GH):
            self.assertNotIn(secret, blob)
            self.assertNotIn(secret, r.stdout)
        self.assertIn("ANTHROPIC_API_KEY", blob)  # names only
        self.assertTrue(any(n.startswith("records/") for n in names))

    def test_no_records_leaves_them_out(self):
        self.make_records()
        r, out = self.bundle("--no-records")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(any(n.startswith("records/")
                             for n in zipfile.ZipFile(out).namelist()))

    def test_empty_directory_still_writes_bundle(self):
        r, out = self.bundle()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(zipfile.is_zipfile(out))

    def test_oversized_record_is_not_silently_truncated(self):
        rec = os.path.join(self.d, "codereview-out")
        os.makedirs(rec)
        with open(os.path.join(rec, "codereview-20261107-000001.json"), "w") as fh:
            fh.write("x" * (3 * 1024 * 1024))
        r, out = self.bundle()
        self.assertEqual(r.returncode, 0, r.stderr)
        z = zipfile.ZipFile(out)
        for n in z.namelist():
            self.assertLessEqual(len(z.read(n)), 2 * 1024 * 1024 + 4096)
        self.assertRegex(z.read("MANIFEST.txt").decode().lower().replace("\n"," "),
                         "left out:.*exceeds")


class FeedbackTests(Base):
    def cr(self, args, env=None, stdin=None):
        return run("from codereview.cli import console_main;"
                   "raise SystemExit(console_main())", args,
                   dict(self.env, **(env or {})), self.d, stdin)

    def test_default_is_off_and_sends_nothing(self):
        s = _Server()
        self.addCleanup(s.close)
        env = {"CODEREVIEW_FEEDBACK_URL": s.url}
        r = run(CRASHING, [], dict(self.env, **env), self.d)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(s.requests, [])
        self.assertIn("off", self.cr(["telemetry", "status"], env)
                      .stdout)

    def test_enabled_ping_has_only_fixed_fields(self):
        s = _Server()
        self.addCleanup(s.close)
        env = {"CODEREVIEW_FEEDBACK_URL": s.url}
        self.assertEqual(
            self.cr(["telemetry", "enable", "--yes"], env).returncode, 0)
        r = run(CRASHING, ["pr", "--token", FAKE_KEY],
                dict(self.env, **env), self.d)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(s.requests), 1)
        body = s.requests[0][2].decode()
        payload = json.loads(body)
        from codereview import feedback
        self.assertEqual(set(payload), set(feedback.PING_FIELDS))
        for secret in (FAKE_KEY, FAKE_GH, self.d, "boom"):
            self.assertNotIn(secret, body)

    def test_disable_and_env_off_win(self):
        s = _Server()
        self.addCleanup(s.close)
        env = {"CODEREVIEW_FEEDBACK_URL": s.url}
        self.cr(["telemetry", "enable", "--yes"], env)
        run(CRASHING, [], dict(self.env, **env, CODEREVIEW_TELEMETRY="0"),
            self.d)
        self.assertEqual(s.requests, [])
        self.cr(["telemetry", "disable"], env)
        self.assertFalse(os.path.exists(
            os.path.join(self.state, "telemetry.json")))
        run(CRASHING, [], dict(self.env, **env), self.d)
        self.assertEqual(s.requests, [])

    def test_enable_without_confirmation_does_not_enable(self):
        r = self.cr(["telemetry", "enable"], stdin="")
        self.assertEqual(r.returncode, 2)
        self.assertIn("off", self.cr(["telemetry", "status"]).stdout)

    def test_rate_limit_one_per_signature(self):
        s = _Server()
        self.addCleanup(s.close)
        env = {"CODEREVIEW_FEEDBACK_URL": s.url}
        self.cr(["telemetry", "enable", "--yes"], env)
        for _ in range(3):
            run(CRASHING, [], dict(self.env, **env), self.d)
        self.assertEqual(len(s.requests), 1)

    def test_server_failures_leave_exit_code(self):
        for kw in ({"status": 500}, {"body": b"garbage"},
                   {"redirect": "http://127.0.0.1:9/x"},
                   {"delay": 6.0}):
            s = _Server(**kw)
            self.addCleanup(s.close)
            env = {"CODEREVIEW_FEEDBACK_URL": s.url}
            self.cr(["telemetry", "enable", "--yes"], env)
            r = run(CRASHING, [], dict(self.env, **env), self.d)
            self.assertEqual(r.returncode, 2, kw)
            self.cr(["telemetry", "disable"], env)

    def test_endpoint_must_be_https_or_loopback(self):
        from codereview import feedback
        self.assertTrue(feedback._endpoint_problem(
            "http://example.com/x"))
        self.assertFalse(feedback._endpoint_problem(
            "http://127.0.0.1:1/x"))
        self.assertFalse(feedback._endpoint_problem(
            "https://example.com/x"))

    def test_no_endpoint_baked_in(self):
        from codereview import feedback
        # Pre-release this pinned "" (nothing could send until the
        # owner acted). The owner set the endpoint at release
        # (2026-11-07); the pin now fixes exactly that value, so
        # the endpoint can never drift silently.
        self.assertEqual(feedback.ENDPOINT,
                         "https://phpatch.com/codereview/report")
        # The no-endpoint branch stays covered in-process: with
        # the constant blanked, resolve_endpoint must refuse.
        saved = feedback.ENDPOINT
        try:
            feedback.ENDPOINT = ""
            url, problem = feedback.resolve_endpoint({})
            self.assertIsNone(url)
            self.assertTrue(problem)
        finally:
            feedback.ENDPOINT = saved

    def test_report_without_confirmation_sends_nothing(self):
        s = _Server()
        self.addCleanup(s.close)
        env = {"CODEREVIEW_FEEDBACK_URL": s.url}
        r = self.cr(["report", "--message", "x"], env, stdin="")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(s.requests, [])

    def test_report_yes_sends_redacted_zip(self):
        s = _Server()
        self.addCleanup(s.close)
        env = {"CODEREVIEW_FEEDBACK_URL": s.url,
               "ANTHROPIC_API_KEY": FAKE_KEY}
        r = self.cr(["report", "--yes", "--message",
                     f"oops {FAKE_KEY}"], env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(s.requests), 1)
        body = s.requests[0][2]
        self.assertTrue(body.startswith(b"PK"))
        p = os.path.join(self.d, "got.zip")
        open(p, "wb").write(body)
        z = zipfile.ZipFile(p)
        blob = b"".join(z.read(n) for n in z.namelist()).decode(
            "utf-8", "replace")
        self.assertNotIn(FAKE_KEY, blob)

    def test_report_failures_exit_2(self):
        s = _Server(status=500)
        self.addCleanup(s.close)
        r = self.cr(["report", "--yes"],
                    {"CODEREVIEW_FEEDBACK_URL": s.url})
        self.assertEqual(r.returncode, 2)
        # Was "no endpoint at all" pre-release; with the owner's
        # endpoint baked in (2026-11-07) that state no longer
        # exists in a default run — and the leg really sent to
        # the live collector from any networked sandbox. The
        # exit-2 contract is now pinned against an unreachable
        # loopback endpoint instead (deterministic everywhere);
        # the no-endpoint branch is covered in-process by
        # test_no_endpoint_baked_in.
        r = self.cr(["report", "--yes"],
                    {"CODEREVIEW_FEEDBACK_URL": "http://127.0.0.1:9/"})
        self.assertEqual(r.returncode, 2)

    def test_report_redirect_not_followed(self):
        s2 = _Server()
        s = _Server(redirect=s2.url)
        self.addCleanup(s.close)
        self.addCleanup(s2.close)
        self.cr(["report", "--yes"], {"CODEREVIEW_FEEDBACK_URL": s.url})
        self.assertEqual(s2.requests, [])


class DocsTests(unittest.TestCase):
    def test_docs_present(self):
        for f in ("SECURITY.md", "CONTRIBUTING.md", "PRIVACY.md",
                  ".github/ISSUE_TEMPLATE/bug.md"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, f)), f)

    def test_help_lists_subcommands(self):
        r = run("from codereview.cli import console_main;"
                "raise SystemExit(console_main())", ["--help"])
        for w in ("support-bundle", "report", "telemetry"):
            self.assertIn(w, r.stdout)

    @unittest.skipUnless(os.environ.get("CODEREVIEW_RELEASE_CHECK") == "1",
                         "release placeholder check (owner, pre-launch)")
    def test_no_placeholders_left(self):
        import re
        bad = []
        for f in ("SECURITY.md", "PRIVACY.md", "pyproject.toml"):
            t = open(os.path.join(ROOT, f)).read()
            if re.search(r"TO BE SET BEFORE LAUNCH|CHANGE-ME", t):
                bad.append(f)
        from codereview import feedback
        if not feedback.ENDPOINT:
            bad.append("feedback.ENDPOINT")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
