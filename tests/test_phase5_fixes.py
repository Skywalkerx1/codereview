"""Phase 5 (external test pass, interfaces & protocol
conformance) regression pins. One class per finding; each test
names the behaviour the Phase 5 report found missing on the
0.12.1 drop and that master must now hold."""

import io
import subprocess
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import sarif  # noqa: E402


def _sarif_result(finding):
    record = {"gate": "blocked", "findings": [finding]}
    log = sarif.record_to_sarif(record)
    return log["runs"][0]["results"][0]


class TestP501Sarif(unittest.TestCase):
    BASE = {"id": "f1", "severity": "major", "title": "t",
            "category": "security"}

    def loc(self, **kw):
        f = dict(self.BASE, **kw)
        return _sarif_result(f)["locations"][0]["physicalLocation"]

    def test_uri_percent_encoded(self):
        self.assertEqual(
            self.loc(file="src/a b.py")["artifactLocation"]["uri"],
            "src/a%20b.py")
        self.assertEqual(
            self.loc(file="a#b.py")["artifactLocation"]["uri"],
            "a%23b.py")
        self.assertEqual(
            self.loc(file="src/ü.py")["artifactLocation"]["uri"],
            "src/%C3%BC.py")

    def test_uri_never_absolute_or_escaping(self):
        for hostile in ("C:/work/x.py", "C:\\work\\x.py",
                        "/etc/passwd", "//server/share.py"):
            uri = self.loc(file=hostile)["artifactLocation"]["uri"]
            self.assertFalse(uri.startswith("/"), uri)
            self.assertNotIn("..", uri.split("/"), uri)
            self.assertNotRegex(uri, r"^[A-Za-z][A-Za-z0-9+.-]*:")
        # P5-01b supersedes the drop-the-segments behaviour this
        # pin originally encoded for escaping paths: `..` now
        # RESOLVES, and a path that still escapes the root gets
        # NO location at all rather than a pointer at a
        # different file (`a/../../b.py` used to become
        # `a/b.py`). The pin's intent — never absolute, never
        # escaping — holds more strongly: there is no uri.
        for escaping in ("../outside.py", "a/../../b.py",
                         "../../etc/passwd"):
            result = _sarif_result(dict(self.BASE, file=escaping))
            self.assertNotIn("locations", result, escaping)

    def test_uri_normal_paths_unchanged(self):
        self.assertEqual(
            self.loc(file="src/app.py")["artifactLocation"]["uri"],
            "src/app.py")

    def test_start_line_clamped_to_int32(self):
        region = self.loc(file="a.py", line=10 ** 12)["region"]
        self.assertEqual(region["startLine"], 2 ** 31 - 1)

    def test_message_control_characters_stripped(self):
        r = _sarif_result(dict(self.BASE, title="a\nb\x00c\x1bd"))
        self.assertEqual(r["message"]["text"], "abcd")

    def test_determinism_kept(self):
        record = {"gate": "blocked", "findings": [
            dict(self.BASE, file="src/a b.py", line=3)]}
        one = json.dumps(sarif.record_to_sarif(record),
                         sort_keys=True)
        two = json.dumps(sarif.record_to_sarif(record),
                         sort_keys=True)
        self.assertEqual(one, two)


from codereview import cli as _cli  # noqa: E402
from codereview.github import (GitHubError, render_pr_comment,  # noqa: E402
                               review_pr)

DIFF = ("diff --git a/app.py b/app.py\n"
        "--- a/app.py\n+++ b/app.py\n"
        "@@ -1,1 +1,2 @@\n x = 1\n+run_all_the_things()\n")


class StubClient:
    """Object-level GitHubClient stand-in for review_pr."""

    def __init__(self, token="tok", fail_status=False,
                 fail_review=False):
        self.token = token
        self.fail_status = fail_status
        self.fail_review = fail_review
        self.statuses = []
        self.reviews = []

    def get_pr(self, owner, repo, number):
        return {"title": "T", "body": "", "user": {"login": "dev"},
                "head": {"sha": "abc123"}}

    def get_pr_diff(self, owner, repo, number):
        return DIFF

    def post_review(self, owner, repo, number, body, event="COMMENT"):
        if self.fail_review:
            raise GitHubError("GitHub API POST reviews: HTTP 403")
        self.reviews.append((body, event))
        return {}

    def set_status(self, owner, repo, sha, state, description,
                   target_url=None):
        if self.fail_status:
            raise GitHubError("GitHub API POST statuses: HTTP 500")
        self.statuses.append((state, description))
        return {}


def _ok_reviewer(prompt):
    return json.dumps({"findings": [], "summary": "s", "usage": {}})


class TestP502PostTokenFailFast(unittest.TestCase):
    def test_review_pr_refuses_before_any_review_call(self):
        calls = []

        def counting(prompt):
            calls.append(1)
            return _ok_reviewer(prompt)

        client = StubClient(token="")
        with self.assertRaises(GitHubError):
            review_pr(client, "o", "r", 7, {"fake": counting},
                      post=True)
        self.assertEqual(calls, [])  # zero provider calls

    def test_cli_post_without_token_exits_2_no_calls(self):
        calls = []

        def counting(prompt):
            calls.append(1)
            return _ok_reviewer(prompt)

        env = {k: v for k, v in os.environ.items()
               if k != "GITHUB_TOKEN"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("sys.stderr", io.StringIO()):
            rc = _cli._pr_main(
                ["--pr", "https://github.com/o/r/pull/7", "--post"],
                providers_override={"fake": counting})
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])


class TestP503PostFailureKeepsReport(unittest.TestCase):
    def test_status_500_records_posting_and_returns_report(self):
        client = StubClient(fail_status=True)
        report, actions = review_pr(
            client, "o", "r", 7, {"fake": _ok_reviewer}, post=True)
        self.assertEqual(report["gate"], "pass")
        self.assertEqual(actions,
                         ["review comment posted (event=COMMENT)"])
        self.assertEqual(report["posting"]["posted"], actions)
        self.assertIn("500", report["posting"]["error"])

    def test_review_post_failure_records_empty_posted(self):
        client = StubClient(fail_review=True)
        report, actions = review_pr(
            client, "o", "r", 7, {"fake": _ok_reviewer}, post=True)
        self.assertEqual(actions, [])
        self.assertEqual(report["posting"]["posted"], [])
        self.assertIn("403", report["posting"]["error"])

    def test_successful_post_records_no_posting_block(self):
        client = StubClient()
        report, actions = review_pr(
            client, "o", "r", 7, {"fake": _ok_reviewer}, post=True)
        self.assertEqual(len(actions), 2)
        self.assertNotIn("posting", report)


class TestP504CommentNeutralisation(unittest.TestCase):
    def test_hostile_finding_text_is_inert(self):
        report = {
            "gate": "blocked",
            "gate_reasons": ["see @everyone-team and "
                             "<img src=http://evil.example/x>"],
            "findings": [{
                "severity": "major", "file": "a.py",
                "title": "@octocat @org/security-team please look "
                         "![beacon](http://evil.example/p.png) "
                         "[click](javascript:alert(1)) </details>",
                "sources": ["@reviewer"]}],
            "version": "0", "patch_sha256": "x" * 12}
        body = render_pr_comment(report, "o", "r", 7)
        self.assertNotIn("@octocat", body)
        self.assertNotIn("@everyone-team", body)
        self.assertNotIn("![beacon](http", body)
        self.assertNotIn("](javascript:", body)
        self.assertNotIn("<img", body)
        self.assertNotIn("</details>", body)
        # Structural markdown survives.
        self.assertIn("## ", body)
        self.assertIn("| Severity | File | Finding | Reviewer(s) |",
                      body)


class TestP511InconclusiveStatus(unittest.TestCase):
    def test_inconclusive_pending_with_explicit_description(self):
        def dead(prompt):
            raise RuntimeError("seat down")

        client = StubClient()
        report, _actions = review_pr(
            client, "o", "r", 7, {"fake": dead}, post=True)
        self.assertEqual(report["gate"], "inconclusive")
        self.assertEqual(len(client.statuses), 1)
        state, desc = client.statuses[0]
        self.assertEqual(state, "pending")
        self.assertIn("inconclusive", desc)


from codereview import mcp_transport  # noqa: E402


class TestP505McpEnvelope(unittest.TestCase):
    def _run(self, frames):
        raw_in = io.BytesIO(b"".join(frames))
        raw_out = io.BytesIO()
        server = mcp_transport.StdioServer(
            lambda method, params, notification: {"echo": method},
            stdin=raw_in, stdout=raw_out, log=lambda _t: None)
        server.serve_forever()
        return [json.loads(line) for line in
                raw_out.getvalue().decode("utf-8").splitlines()
                if line.strip()]

    def test_invalid_ids_get_invalid_request(self):
        for bad in ("true", "1.5", "null", '{"a": 1}', "[1]"):
            frame = ('{"jsonrpc": "2.0", "id": %s, '
                     '"method": "ping"}\n' % bad).encode()
            responses = self._run([frame])
            self.assertEqual(len(responses), 1, bad)
            self.assertEqual(responses[0]["error"]["code"], -32600,
                             bad)
            self.assertIsNone(responses[0]["id"], bad)

    def test_valid_ids_still_answered(self):
        responses = self._run([
            b'{"jsonrpc": "2.0", "id": "abc", "method": "ping"}\n',
            b'{"jsonrpc": "2.0", "id": 0, "method": "ping"}\n',
            b'{"jsonrpc": "2.0", "id": 1180591620717411303424, '
            b'"method": "ping"}\n'])
        self.assertEqual([r["id"] for r in responses],
                         ["abc", 0, 1180591620717411303424])
        self.assertTrue(all("result" in r for r in responses))

    def test_nonfinite_float_id_keeps_p310_sanitisation(self):
        # Boundary with the Phase 3 pin: NaN cannot be emitted
        # in strict JSON, so it is echoed as null and SERVED
        # (P3-10); finite floats are refused (P5-05, above).
        responses = self._run([
            b'{"jsonrpc": "2.0", "id": NaN, "method": "ping"}\n'])
        self.assertEqual(len(responses), 1)
        self.assertIsNone(responses[0]["id"])
        self.assertEqual(responses[0]["result"], {"echo": "ping"})

    def test_absent_id_is_a_silent_notification(self):
        responses = self._run([
            b'{"jsonrpc": "2.0", "method": "ping"}\n',
            b'{"jsonrpc": "2.0", "id": 9, "method": "ping"}\n'])
        self.assertEqual([r["id"] for r in responses], [9])

    def test_wrong_jsonrpc_still_invalid_request(self):
        responses = self._run([
            b'{"id": 1, "method": "ping"}\n',
            b'{"jsonrpc": "1.0", "id": 2, "method": "ping"}\n',
            b'{"jsonrpc": "2.0", "id": 3, "method": "ping"}\n'])
        self.assertEqual(
            [r["error"]["code"] for r in responses[:2]],
            [-32600, -32600])
        self.assertEqual(responses[2]["id"], 3)  # still alive

    def test_duplicate_ids_still_answered(self):
        responses = self._run([
            b'{"jsonrpc": "2.0", "id": 5, "method": "ping"}\n',
            b'{"jsonrpc": "2.0", "id": 5, "method": "ping"}\n'])
        self.assertEqual([r["id"] for r in responses], [5, 5])


from codereview import setup_wizard  # noqa: E402


class TestP506P513WizardInterrupts(unittest.TestCase):
    def _environ(self, tmp):
        return {"PATH": "", "HOME": tmp,
                "CODEREVIEW_CONFIG": os.path.join(tmp, "c.toml")}

    def test_wizard_eof_prints_abort_exactly_once(self):
        tmp = tempfile.mkdtemp()
        lines = []

        def eof_input(prompt):
            raise EOFError("EOF when reading a line")

        with self.assertRaises(EOFError):
            setup_wizard.run_wizard(
                input_fn=eof_input, print_fn=lines.append,
                environ=self._environ(tmp),
                discover_fn=lambda: [])
        aborts = [l for l in lines if "setup aborted" in l]
        self.assertEqual(len(aborts), 1)
        self.assertFalse(os.path.exists(
            os.path.join(tmp, "c.toml")))

    def test_wizard_ctrl_c_propagates_and_saves_nothing(self):
        tmp = tempfile.mkdtemp()

        def int_input(prompt):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            setup_wizard.run_wizard(
                input_fn=int_input, print_fn=lambda _l: None,
                environ=self._environ(tmp),
                discover_fn=lambda: [])
        self.assertFalse(os.path.exists(
            os.path.join(tmp, "c.toml")))

    def test_setup_main_ctrl_c_is_130_no_traceback(self):
        err = io.StringIO()
        with mock.patch.object(
                _cli, "_run_setup_wizard",
                side_effect=KeyboardInterrupt), \
                mock.patch("sys.stderr", err):
            rc = _cli._setup_main([])
        self.assertEqual(rc, 130)
        self.assertIn("cancelled — nothing saved.", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_setup_main_eof_does_not_duplicate_message(self):
        out, err = io.StringIO(), io.StringIO()

        def fake_wizard():
            print("setup aborted — nothing saved.")
            raise EOFError("EOF when reading a line")

        with mock.patch.object(_cli, "_run_setup_wizard",
                               side_effect=fake_wizard), \
                mock.patch("sys.stdout", out), \
                mock.patch("sys.stderr", err):
            rc = _cli._setup_main([])
        self.assertEqual(rc, 2)
        combined = out.getvalue() + err.getvalue()
        self.assertEqual(combined.count("setup aborted"), 1)
        self.assertNotIn("EOF when reading a line", combined)


class TestP507OutCheckedUpFront(unittest.TestCase):
    def test_problem_detection(self):
        self.assertIsNotNone(_cli._out_dir_problem("/proc/nope"))
        self.assertIsNone(_cli._out_dir_problem(None))
        tmp = tempfile.mkdtemp()
        self.assertIsNone(_cli._out_dir_problem(tmp))
        self.assertIsNone(_cli._out_dir_problem(
            os.path.join(tmp, "new", "nested")))
        f = os.path.join(tmp, "afile")
        open(f, "w").close()
        self.assertIn("not a directory",
                      _cli._out_dir_problem(f))

    def test_problem_detection_simulated_unwritable(self):
        # P5-07b (3): the unwritable case is SIMULATED, not read
        # off /proc semantics — os.access says yes and directory
        # creation fails, which is exactly the root-in-CI shape
        # the original check missed. Identical for every user.
        tmp = tempfile.mkdtemp()
        target = os.path.join(tmp, "new", "nested")
        with mock.patch("os.access", return_value=True), \
                mock.patch("os.makedirs",
                           side_effect=PermissionError(
                               13, "Permission denied")):
            self.assertIsNotNone(_cli._out_dir_problem(target))

    def test_main_unwritable_out_exits_2_zero_provider_calls(self):
        calls = []

        def counting(prompt):
            calls.append(1)
            return _ok_reviewer(prompt)

        tmp = tempfile.mkdtemp()
        patch = os.path.join(tmp, "p.diff")
        with open(patch, "w") as fh:
            fh.write(DIFF)
        out = os.path.join(tmp, "nope")
        real_makedirs = os.makedirs

        def makedirs_spy(path, *a, **kw):
            if os.path.abspath(str(path)) == out:
                raise PermissionError(13, "Permission denied")
            return real_makedirs(path, *a, **kw)

        # P5-07b (3): was driven by `--out /proc/nope`, whose
        # refusal depended on /proc semantics that differ for
        # root (the rerun's two failing tests). The failure is
        # now simulated at os.makedirs — the probe's create —
        # so the pin holds identically for root and non-root.
        err = io.StringIO()
        with mock.patch("os.makedirs", side_effect=makedirs_spy), \
                mock.patch("sys.stderr", err):
            rc = _cli.main(["--patch", patch, "--out", out],
                           providers_override={"fake": counting})
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])  # zero provider calls
        self.assertNotIn("Traceback", err.getvalue())
        self.assertIn("--out", err.getvalue())

    def test_main_unwritable_out_proc_exits_2_zero_calls(self):
        # The rerun's original repro, kept as a pin: with the
        # real probe (P5-07b (1)) the refusal no longer depends
        # on what os.access claims — creating /proc/nope fails
        # for root exactly as for anyone else.
        calls = []

        def counting(prompt):
            calls.append(1)
            return _ok_reviewer(prompt)

        tmp = tempfile.mkdtemp()
        patch = os.path.join(tmp, "p.diff")
        with open(patch, "w") as fh:
            fh.write(DIFF)
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            rc = _cli.main(["--patch", patch, "--out", "/proc/nope"],
                           providers_override={"fake": counting})
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])
        self.assertIn("--out", err.getvalue())


class TestP510HookPositionalArgs(unittest.TestCase):
    """P5-10 (docs + pin): $1/$2 are the hook COMMAND STRING's
    positional parameters. A bare script path receives no
    arguments (it reads the CODEREVIEW_HOOK_* env vars); a
    shell string that forwards "$1" "$2" delivers them."""

    def _run_with_hook(self, command):
        tmp = tempfile.mkdtemp()
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)

        def git(*a):
            subprocess.run(["git", *a], cwd=repo, check=True,
                           capture_output=True)

        git("init", "-q")
        git("config", "user.email", "a@b")
        git("config", "user.name", "t")
        with open(os.path.join(repo, "app.py"), "w") as fh:
            fh.write("import os\n")
        git("add", ".")
        git("commit", "-qm", "i")
        with open(os.path.join(repo, "app.py"), "w") as fh:
            fh.write("import os\nx = os.getcwd()\n")
        hook = os.path.join(tmp, "hook.sh")
        with open(hook, "w") as fh:
            fh.write('#!/bin/sh\necho "A1=[$1] A2=[$2] '
                     'EV=$CODEREVIEW_HOOK_EVENT"\n')
        os.chmod(hook, 0o755)
        pol = os.path.join(tmp, "pol.toml")
        with open(pol, "w") as fh:
            fh.write('[hooks]\npost_verdict = %s\n'
                     % json.dumps(command.replace("HOOK", hook)))
        out = os.path.join(tmp, "out")
        with mock.patch("sys.stderr", io.StringIO()), \
                mock.patch("sys.stdout", io.StringIO()):
            rc = _cli.main(
                ["--repo", repo, "--policy", pol, "--out", out],
                providers_override={"a": _ok_reviewer,
                                    "b": _ok_reviewer})
        self.assertEqual(rc, 0)
        records = [f for f in os.listdir(out) if f.endswith(".json")]
        record = json.load(open(os.path.join(out, records[0])))
        results = (record.get("hooks") or {}).get("results") or []
        self.assertEqual(len(results), 1)
        return results[0].get("output_tail") or ""

    def test_bare_path_gets_no_positional_args(self):
        tail = self._run_with_hook("HOOK")
        self.assertIn("A1=[] A2=[]", tail)
        self.assertIn("EV=post-verdict", tail)  # env vars arrive

    def test_shell_string_forwards_positional_args(self):
        tail = self._run_with_hook('HOOK "$1" "$2"')
        self.assertIn("A1=[post-verdict]", tail)
        self.assertIn("A2=[", tail)


class TestP514LauncherWording(unittest.TestCase):
    def test_file_path_says_not_a_directory(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..",
            "herdr-plugin-codereview"))
        import codereview_launch as launch

        tmp = tempfile.mkdtemp()
        f = os.path.join(tmp, "afile")
        open(f, "w").close()
        err = io.StringIO()
        env = {"PATH": os.path.dirname(sys.executable),
               "HOME": tmp}
        # A `codereview` must exist on PATH for the launcher to
        # get past its first check; point PATH at the interpreter
        # dir plus a shim.
        shim = os.path.join(tmp, "bin")
        os.makedirs(shim)
        shimfile = os.path.join(shim, "codereview")
        open(shimfile, "w").write("#!/bin/sh\nexit 0\n")
        os.chmod(shimfile, 0o755)
        env["PATH"] = shim
        with mock.patch("sys.stderr", err):
            rc = launch.main(["--repo", f], environ=env)
        self.assertEqual(rc, 2)
        self.assertIn("is not a directory", err.getvalue())
        self.assertNotIn("does not exist", err.getvalue())

    def test_missing_path_says_does_not_exist(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..",
            "herdr-plugin-codereview"))
        import codereview_launch as launch

        tmp = tempfile.mkdtemp()
        shim = os.path.join(tmp, "bin")
        os.makedirs(shim)
        shimfile = os.path.join(shim, "codereview")
        open(shimfile, "w").write("#!/bin/sh\nexit 0\n")
        os.chmod(shimfile, 0o755)
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            rc = launch.main(
                ["--repo", os.path.join(tmp, "nope")],
                environ={"PATH": shim, "HOME": tmp})
        self.assertEqual(rc, 2)
        self.assertIn("does not exist", err.getvalue())


class TestP509HelpExitCodes(unittest.TestCase):
    """P5-09 was already fixed on master (82efd38, D-004/D-005:
    --help exits 0 for policy/bench/mcp); this pins every
    subcommand's help at exit 0 against regression."""

    SUBS = ("setup", "evidence", "acceptance", "doctor",
            "record-verify", "policy", "sarif", "disputes",
            "locate", "bench", "pr", "workflow", "intake",
            "loop", "mcp")

    def test_every_subcommand_help_exits_0(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        env = dict(os.environ, PYTHONPATH=os.path.abspath(src),
                   HOME=tempfile.mkdtemp())
        for sub in (None,) + self.SUBS:
            argv = [sys.executable, "-m", "codereview"]
            if sub:
                argv.append(sub)
            argv.append("--help")
            p = subprocess.run(argv, env=env, capture_output=True,
                               text=True, timeout=60)
            self.assertEqual(p.returncode, 0,
                             f"{sub or 'main'} --help: {p.stderr[:120]}")


if __name__ == "__main__":
    unittest.main()
