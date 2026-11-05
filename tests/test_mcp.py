"""Epic L2 — MCP server for the gate.

`codereview mcp serve` exposes run_gate / get_verdict over
the Model Context Protocol (stdio, newline-delimited
JSON-RPC), implemented in-tree on the stdlib: the wire layer
(codereview.mcp_transport) and the tool layer
(codereview.mcp_tools) are separate modules.

Pinned here: the transport fails closed (a bad frame, an
oversized frame, or a crashing handler never ends the loop
and is always recorded); the handshake negotiates and lists
both tools; a verdict served over MCP equals the CLI's on
the same diff; the server holds no credentials and no
built-in panel (no setup ⇒ the CLI's own not-set-up answer);
and a real subprocess session — a minimal in-tree client
speaking the real protocol over a real stdio pipe — runs a
gate end-to-end (a brand-name client session, Claude Code /
Codex, is NOT exercised: no agent CLI on this machine is
logged in).
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from codereview import cli, mcp_tools, mcp_transport  # noqa: E402
from codereview.mcp_transport import StdioServer  # noqa: E402

PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,2 @@\n"
    " context line\n"
    "+USERS[name] = True\n")


def _pass_seat(prompt):
    return json.dumps({"verdict": "pass", "summary": "ok",
                       "findings": []})


def _rpc(method, params=None, req_id=1):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def _serve_session(messages, tools=None, max_frame_bytes=None):
    """Run serve_stdio over in-memory pipes; return
    (responses, server)."""
    raw_in = io.BytesIO(
        b"".join(m if isinstance(m, bytes)
                 else (json.dumps(m) + "\n").encode("utf-8")
                 for m in messages))
    raw_out = io.BytesIO()
    logs = []
    server = mcp_tools.serve_stdio(
        tools=tools, stdin=raw_in, stdout=raw_out,
        log=logs.append, max_frame_bytes=max_frame_bytes)
    responses = [json.loads(line) for line in
                 raw_out.getvalue().decode("utf-8").splitlines()
                 if line.strip()]
    return responses, server


class TransportTests(unittest.TestCase):
    def _dispatch(self, method, params, notification):
        if method == "boom":
            raise RuntimeError("handler exploded")
        if method == "nope":
            raise mcp_transport.JsonRpcError(
                mcp_transport.METHOD_NOT_FOUND, "no such method")
        return {"echo": method}

    def _run(self, frames, **kw):
        raw_in = io.BytesIO(b"".join(frames))
        raw_out = io.BytesIO()
        server = StdioServer(self._dispatch, stdin=raw_in,
                             stdout=raw_out, log=lambda _t: None,
                             **kw)
        server.serve_forever()
        responses = [json.loads(line) for line in
                     raw_out.getvalue().decode("utf-8")
                     .splitlines() if line.strip()]
        return responses, server

    def test_request_answered_notification_not(self):
        responses, _ = self._run([
            b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n',
            b'{"jsonrpc":"2.0","method":"ping"}\n',
            b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n'])
        self.assertEqual([r["id"] for r in responses], [1, 2])
        self.assertEqual(responses[0]["result"],
                         {"echo": "ping"})

    def test_parse_error_recorded_and_loop_continues(self):
        responses, server = self._run([
            b'this is not json\n',
            b'{"jsonrpc":"2.0","id":7,"method":"ping"}\n'])
        self.assertEqual(responses[0]["error"]["code"],
                         mcp_transport.PARSE_ERROR)
        self.assertIsNone(responses[0]["id"])
        self.assertEqual(responses[1]["id"], 7)
        self.assertEqual([e["kind"] for e in server.errors],
                         ["parse_error"])

    def test_non_object_and_batch_fail_closed(self):
        responses, server = self._run([
            b'[1,2,3]\n',
            b'"just a string"\n',
            b'{"jsonrpc":"2.0","id":3,"method":"ping"}\n'])
        self.assertEqual(
            [r["error"]["code"] for r in responses[:2]],
            [mcp_transport.INVALID_REQUEST] * 2)
        self.assertEqual(responses[2]["id"], 3)
        self.assertEqual(len(server.errors), 2)

    def test_method_error_and_handler_crash_fail_closed(self):
        responses, server = self._run([
            b'{"jsonrpc":"2.0","id":1,"method":"nope"}\n',
            b'{"jsonrpc":"2.0","id":2,"method":"boom"}\n',
            b'{"jsonrpc":"2.0","id":3,"method":"ping"}\n'])
        self.assertEqual(responses[0]["error"]["code"],
                         mcp_transport.METHOD_NOT_FOUND)
        self.assertEqual(responses[1]["error"]["code"],
                         mcp_transport.INTERNAL_ERROR)
        self.assertEqual(responses[2]["result"],
                         {"echo": "ping"})
        self.assertEqual([e["kind"] for e in server.errors],
                         ["request_error", "internal_error"])

    def test_oversized_frame_discarded_stream_stays_in_sync(self):
        big = b'{"jsonrpc":"2.0","id":1,"method":"' \
              + b'x' * 500 + b'"}\n'
        responses, server = self._run(
            [big,
             b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n'],
            max_frame_bytes=64)
        self.assertEqual(responses[0]["error"]["code"],
                         mcp_transport.INVALID_REQUEST)
        self.assertIn("size limit",
                      responses[0]["error"]["message"])
        self.assertEqual(responses[1]["id"], 2)
        self.assertEqual([e["kind"] for e in server.errors],
                         ["oversized_frame"])


class ProtocolTests(unittest.TestCase):
    def test_initialize_negotiates_and_names_the_server(self):
        responses, _ = _serve_session([
            _rpc("initialize",
                 {"protocolVersion": "2024-11-05",
                  "capabilities": {},
                  "clientInfo": {"name": "t", "version": "0"}}),
            _rpc("initialize",
                 {"protocolVersion": "1999-01-01"}, req_id=2)])
        first = responses[0]["result"]
        self.assertEqual(first["protocolVersion"], "2024-11-05")
        self.assertEqual(first["serverInfo"]["name"],
                         "codereview")
        self.assertIn("tools", first["capabilities"])
        # An unsupported version falls back to our newest.
        self.assertEqual(responses[1]["result"]
                         ["protocolVersion"], "2025-03-26")

    def test_tools_list_and_ping(self):
        responses, _ = _serve_session([
            _rpc("tools/list"),
            _rpc("ping", req_id=2)])
        tools = responses[0]["result"]["tools"]
        self.assertEqual([t["name"] for t in tools],
                         ["run_gate", "get_verdict"])
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"],
                             "object")
            self.assertFalse(tool["inputSchema"]
                             ["additionalProperties"])
        self.assertEqual(responses[1]["result"], {})

    def test_unknown_method_and_unknown_tool(self):
        responses, _ = _serve_session([
            _rpc("resources/list"),
            _rpc("tools/call", {"name": "nuke"}, req_id=2),
            _rpc("tools/call", {"arguments": {}}, req_id=3)])
        self.assertEqual(responses[0]["error"]["code"],
                         mcp_transport.METHOD_NOT_FOUND)
        self.assertEqual(responses[1]["error"]["code"],
                         mcp_transport.INVALID_PARAMS)
        self.assertIn("unknown tool",
                      responses[1]["error"]["message"])
        self.assertEqual(responses[2]["error"]["code"],
                         mcp_transport.INVALID_PARAMS)


class RunGateTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        self.out = os.path.join(self.tmp.name, "out")

    def _tools(self, seat=_pass_seat):
        return mcp_tools.GateTools(
            providers_override={"stub": seat})

    def _call(self, tools, name, arguments):
        dispatch = mcp_tools.make_dispatch(tools)
        return dispatch("tools/call",
                        {"name": name, "arguments": arguments},
                        False)

    def test_run_gate_pass_and_record_on_disk(self):
        result = self._call(self._tools(), "run_gate", {
            "repo": self.repo, "patch": PATCH, "out": self.out})
        self.assertFalse(result["isError"])
        payload = result["structuredContent"]
        self.assertEqual(payload["gate"], "pass")
        self.assertEqual(payload["exit_code"], 0)
        self.assertTrue(os.path.isfile(payload["record_path"]))
        self.assertTrue(os.path.isfile(payload["report_path"]))
        self.assertEqual(payload["counts"]["total"], 0)

    def test_mcp_verdict_equals_cli_verdict(self):
        def seat(prompt):
            if "USERS[name] = True" in prompt:
                return json.dumps({
                    "verdict": "changes_requested",
                    "summary": "one issue",
                    "findings": [{
                        "severity": "minor",
                        "category": "quality",
                        "file": "app.py", "line": 2,
                        "title": "In-place mutation of USERS",
                        "evidence": "USERS[name] = True",
                        "evidence_quote": "USERS[name] = True",
                        "recommendation": "Build a new dict.",
                        "confidence": 0.8}]})
            return json.dumps({"verdict": "pass",
                               "summary": "ok", "findings": []})

        payload = self._call(
            self._tools(seat), "run_gate",
            {"repo": self.repo, "patch": PATCH,
             "out": self.out})["structuredContent"]
        # The same change through the CLI itself.
        patch_path = os.path.join(self.tmp.name, "change.patch")
        with open(patch_path, "w", encoding="utf-8") as fh:
            fh.write(PATCH)
        cli_out = os.path.join(self.tmp.name, "cli-out")
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(stderr):
            rc = cli.main(["--repo", self.repo,
                           "--patch", patch_path,
                           "--out", cli_out],
                          providers_override={"stub": seat})
        self.assertEqual(rc, payload["exit_code"])
        with open(payload["record_path"],
                  encoding="utf-8") as fh:
            mcp_record = json.load(fh)
        cli_records = [f for f in os.listdir(cli_out)
                       if f.endswith(".json")]
        with open(os.path.join(cli_out, cli_records[0]),
                  encoding="utf-8") as fh:
            cli_record = json.load(fh)
        self.assertEqual(payload["gate"], cli_record["gate"])
        self.assertEqual(mcp_record["gate"],
                         cli_record["gate"])
        key = lambda f: (f.get("severity"), f.get("title"),  # noqa: E731
                         f.get("file"), f.get("line"))
        self.assertEqual([key(f) for f in payload["findings"]],
                         [key(f) for f in
                          cli_record["findings"]])
        self.assertEqual(payload["gate"], "pass")
        self.assertEqual(len(payload["findings"]), 1)

    def test_get_verdict_by_file_and_by_directory(self):
        tools = self._tools()
        payload = self._call(tools, "run_gate", {
            "repo": self.repo, "patch": PATCH,
            "out": self.out})["structuredContent"]
        by_file = self._call(tools, "get_verdict", {
            "record": payload["record_path"],
            "repo": self.repo})["structuredContent"]
        by_dir = self._call(tools, "get_verdict", {
            "record": self.out,
            "repo": self.repo})["structuredContent"]
        for got in (by_file, by_dir):
            self.assertEqual(got["gate"], payload["gate"])
            self.assertEqual(got["record_path"],
                             payload["record_path"])
            self.assertEqual(got["counts"],
                             payload["counts"])

    def test_get_verdict_missing_record_is_an_error_result(self):
        result = self._call(self._tools(), "get_verdict", {
            "record": os.path.join(self.tmp.name, "nope.json")})
        self.assertTrue(result["isError"])
        self.assertIn("could not read the record",
                      result["content"][0]["text"])

    def test_argument_discipline_fails_closed(self):
        tools = self._tools()
        cases = [
            {"patch": PATCH, "range": "HEAD~1..HEAD"},
            {"patch": PATCH, "bogus": "x"},
            {"patch": 123},
            {"repo": self.repo, "patch": PATCH,
             "out": self.out, "policy": 4},
        ]
        for arguments in cases:
            result = self._call(tools, "run_gate", arguments)
            self.assertTrue(result["isError"], arguments)
        missing = self._call(tools, "get_verdict", {})
        self.assertTrue(missing["isError"])
        self.assertIn("missing required argument",
                      missing["content"][0]["text"])
        # Nothing ran: no record was produced anywhere.
        self.assertFalse(os.path.exists(self.out))

    def test_no_setup_is_the_clis_own_answer(self):
        cfg = os.path.join(self.tmp.name, "codereview.toml")
        env = {"HOME": self.tmp.name,
               "PATH": os.environ.get("PATH", ""),
               "CODEREVIEW_CONFIG": cfg}
        tools = mcp_tools.GateTools()
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(cli, "_stdin_is_tty",
                                  return_value=False):
            result = self._call(tools, "run_gate", {
                "repo": self.repo, "patch": PATCH,
                "out": self.out})
        self.assertTrue(result["isError"])
        self.assertIn("not set up yet",
                      result["content"][0]["text"])
        self.assertIn("ships no default panel",
                      result["content"][0]["text"])


# -- the subprocess session: a minimal client, the real pipe ---


class _StubModelHandler(BaseHTTPRequestHandler):
    """An OpenAI-compatible stub: every chat completion is a
    clean pass review."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        body = json.dumps({
            "choices": [{"message": {"content": json.dumps({
                "verdict": "pass", "summary": "stub pass",
                "findings": []})}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _Client:
    """The minimal MCP client: newline-delimited JSON-RPC
    over the server's real stdio pipes."""

    def __init__(self, proc):
        self.proc = proc
        self._next = 0

    def send_raw(self, data):
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def read(self):
        line = self.proc.stdout.readline()
        if not line:
            raise AssertionError("server closed its stdout")
        return json.loads(line)

    def call(self, method, params=None):
        self._next += 1
        req_id = self._next
        msg = {"jsonrpc": "2.0", "id": req_id,
               "method": method}
        if params is not None:
            msg["params"] = params
        self.send_raw((json.dumps(msg) + "\n").encode("utf-8"))
        response = self.read()
        assert response.get("id") == req_id, response
        return response

    def notify(self, method):
        self.send_raw((json.dumps(
            {"jsonrpc": "2.0", "method": method})
            + "\n").encode("utf-8"))


class SubprocessSessionTests(unittest.TestCase):
    def test_full_session_over_real_stdio(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        server = HTTPServer(("127.0.0.1", 0), _StubModelHandler)
        thread = threading.Thread(target=server.serve_forever,
                                  daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        src = os.path.join(ROOT, "src")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": tmp.name,
            "PYTHONPATH": src,
            "CODEREVIEW_CONFIG": os.path.join(
                tmp.name, "codereview.toml"),
            "CODEREVIEW_PROVIDERS":
                "stub|openai-compatible|"
                f"http://127.0.0.1:{port}/v1|stub-model|"
                "STUB_KEY_ENV",
            "STUB_KEY_ENV": "stub-key",
            "NO_PROXY": "*",
        }
        proc = subprocess.Popen(
            [sys.executable, "-m", "codereview", "mcp", "serve"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, cwd=tmp.name)
        try:
            client = _Client(proc)
            hello = client.call("initialize", {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "in-tree-test",
                               "version": "0"}})
            self.assertEqual(
                hello["result"]["protocolVersion"],
                "2025-03-26")
            self.assertEqual(
                hello["result"]["serverInfo"]["name"],
                "codereview")
            client.notify("notifications/initialized")
            listing = client.call("tools/list")
            self.assertEqual(
                [t["name"] for t in
                 listing["result"]["tools"]],
                ["run_gate", "get_verdict"])
            # A malformed frame mid-session: answered, and
            # the server lives on.
            client.send_raw(b"{not json\n")
            bad = client.read()
            self.assertEqual(bad["error"]["code"],
                             mcp_transport.PARSE_ERROR)
            out_dir = os.path.join(tmp.name, "out")
            ran = client.call("tools/call", {
                "name": "run_gate",
                "arguments": {"repo": tmp.name, "patch": PATCH,
                              "out": out_dir}})
            result = ran["result"]
            self.assertFalse(result["isError"], result)
            payload = result["structuredContent"]
            self.assertIn(payload["gate"],
                          ("pass", "inconclusive", "blocked"))
            self.assertTrue(
                os.path.isfile(payload["record_path"]))
            got = client.call("tools/call", {
                "name": "get_verdict",
                "arguments": {"record": payload["record_path"],
                              "repo": tmp.name}})
            self.assertFalse(got["result"]["isError"])
            self.assertEqual(
                got["result"]["structuredContent"]["gate"],
                payload["gate"])
            # The same change through the CLI binary itself:
            # the served verdict is the CLI's verdict.
            patch_path = os.path.join(tmp.name, "change.patch")
            with open(patch_path, "w", encoding="utf-8") as fh:
                fh.write(PATCH)
            cli_out = os.path.join(tmp.name, "cli-out")
            done = subprocess.run(
                [sys.executable, "-m", "codereview",
                 "--repo", tmp.name, "--patch", patch_path,
                 "--out", cli_out],
                capture_output=True, text=True, env=env,
                cwd=tmp.name, timeout=300)
            self.assertIn(done.returncode, (0, 1, 2))
            records = [f for f in os.listdir(cli_out)
                       if f.endswith(".json")]
            with open(os.path.join(cli_out, records[0]),
                      encoding="utf-8") as fh:
                cli_record = json.load(fh)
            self.assertEqual(payload["gate"],
                             cli_record["gate"])
            self.assertEqual(
                len(payload["findings"]),
                len(cli_record["findings"]))
        finally:
            proc.stdin.close()
            proc.wait(timeout=60)
            proc.stdout.close()
            proc.stderr.close()
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
