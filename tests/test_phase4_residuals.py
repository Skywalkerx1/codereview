"""Regression tests for the Phase 4 rerun findings (P4-08b, P4-01b, P4-06b/c)."""
import json, os, sys, tempfile, threading, unittest, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "bench"))
from codereview import providers, seatstate  # noqa: E402
import generation as gen  # noqa: E402


class TornTail(unittest.TestCase):
    def _file(self, content):
        d = tempfile.mkdtemp(); p = os.path.join(d, "x.jsonl")
        with open(p, "w") as fh: fh.write(content)
        return p

    def test_torn_tail_removed_then_append_is_clean(self):
        p = self._file('{"a":1}\n{"a":2}\n{"a":3, "b')
        self.assertTrue(gen._repair_jsonl_tail(p))
        with open(p, "a") as fh: fh.write('{"a":4}\n')
        self.assertEqual([r["a"] for r in gen._read_jsonl(p)], [1, 2, 4])

    def test_complete_final_line_without_newline_is_kept(self):
        p = self._file('{"a":1}\n{"a":2}')
        gen._repair_jsonl_tail(p)
        with open(p, "a") as fh: fh.write('{"a":3}\n')
        self.assertEqual([r["a"] for r in gen._read_jsonl(p)], [1, 2, 3])

    def test_clean_file_untouched(self):
        p = self._file('{"a":1}\n')
        self.assertFalse(gen._repair_jsonl_tail(p))

    def test_mid_file_corruption_not_hidden(self):
        p = self._file('{"a":1}\nGARBAGE\n{"a":3}\n')
        self.assertFalse(gen._repair_jsonl_tail(p))
        with self.assertRaises(json.JSONDecodeError):
            gen._read_jsonl(p)

    def test_corrupt_then_torn_keeps_corrupt_visible(self):
        p = self._file('{"a":1}\nGARBAGE\n{"a":3, "b')
        gen._repair_jsonl_tail(p)
        with self.assertRaises(json.JSONDecodeError):
            gen._read_jsonl(p)

    def test_missing_and_empty(self):
        self.assertFalse(gen._repair_jsonl_tail("/nonexistent/zz"))
        self.assertFalse(gen._repair_jsonl_tail(self._file("")))

    def test_only_torn_line(self):
        p = self._file('{"a":')
        gen._repair_jsonl_tail(p)
        self.assertEqual(gen._read_jsonl(p), [])


class ErrorBodyRedaction(unittest.TestCase):
    SECRET = "sk-" + "proj-" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ" + "0123456789abcd"

    def _serve(self, body):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0)); self.rfile.read(n)
                self.send_response(401); self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H); srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close); self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}/v1"

    def test_secret_in_error_body_is_redacted(self):
        url = self._serve(json.dumps({"error": {"message": "Incorrect API key provided: " + self.SECRET}}).encode())
        with self.assertRaises(providers.ProviderError) as cm:
            providers._post_json(url, {}, {}, 5)
        self.assertNotIn(self.SECRET, str(cm.exception))
        self.assertIn("401", str(cm.exception))

    def test_class_deciding_text_survives_redaction(self):
        url = self._serve(b'{"error":{"code":"insufficient_quota","message":"You exceeded your current quota"}}')
        with self.assertRaises(providers.ProviderError) as cm:
            providers._post_json(url, {}, {}, 5)
        self.assertIn("insufficient_quota", str(cm.exception))


class LeadIn(unittest.TestCase):
    def m(self, text): return seatstate.match_failure("claude", text)

    def test_json_wrapped_result_matches(self):
        self.assertEqual(self.m('{"type":"result","is_error":true,"result":"Not logged in · Please run /login"}')["class"], "auth")
        self.assertEqual(self.m('{"error":"Not logged in"}')["class"], "auth")

    def test_verdict_json_quoting_the_phrase_is_not_scanned(self):
        v = json.dumps({"verdict": "pass", "summary": "diff contains: Not logged in", "findings": []})
        self.assertIsNone(self.m(v))

    def test_json_keys_not_scanned(self):
        self.assertIsNone(self.m('{"not logged in": 1}'))

    def test_json_value_with_quoted_component_still_rejected(self):
        self.assertIsNone(self.m('{"result":"MCP server \'docs\' not logged in; continuing"}'))

    def test_diff_and_markdown_prefixes_rejected(self):
        for t in ("+Not logged in", "> Not logged in", "+    print(Not logged in)"):
            self.assertIsNone(self.m(t), t)

    def test_existing_behaviour_kept(self):
        self.assertEqual(self.m("Not logged in · Please run /login")["class"], "auth")
        self.assertEqual(self.m("2026-11-06T10:00:00Z ERROR: Not logged in")["class"], "auth")
        self.assertIsNone(self.m("MCP server 'docs' not logged in; continuing"))

if __name__ == "__main__":
    unittest.main()
