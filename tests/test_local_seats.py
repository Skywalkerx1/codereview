"""Epic L5: first-class local-model seats.

Named local presets in the provider registry (ollama,
lmstudio) and the generic local:<name>:<base-url>|<model>
form, offered by the setup wizard as a first-class choice
with a recipe, keyless by construction (no API key is read,
sent, or prompted for), family tag 'local', and ordinary
seats in the record. The unnamed openai-compatible: escape
hatch keeps working unchanged for everything else.

The wire tests run against a real stub HTTP server on
loopback implementing the OpenAI chat-completions shape —
the local seat path is exercised end-to-end (registry ->
describe -> build -> HTTP -> response), and the review
smoke test runs with every non-loopback connection refused.
"""

import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core, providers, registry, setup_wizard  # noqa: E402

PASS_JSON = json.dumps({"verdict": "pass", "summary": "ok",
                        "findings": []})

PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,1 +1,2 @@
 x = 1
+y = 2
"""


class _StubHandler(BaseHTTPRequestHandler):
    """One OpenAI-compatible endpoint: records each request
    (path, headers, payload) on the server and answers with a
    fixed chat-completions body."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        self.server.seen.append({
            "path": self.path,
            "headers": dict(self.headers.items()),
            "payload": json.loads(body) if body else {}})
        data = json.dumps({
            "choices": [{"message": {"content": PASS_JSON}}]}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class StubServerCase(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0),
                                          _StubHandler)
        self.server.seen = []
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.thread.start()
        port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{port}/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def local_spec(self, name="stub", model="stub-model"):
        return f"local:{name}:{self.base}|{model}"


class RegistryTests(unittest.TestCase):
    def test_local_presets_are_keyless_family_local(self):
        for name, url in (("ollama", "http://localhost:11434/v1"),
                          ("lmstudio", "http://localhost:1234/v1")):
            preset = registry.PRESETS[name]
            self.assertEqual(preset["family"], "local")
            self.assertIsNone(preset["key_env"])
            self.assertEqual(preset["base_url"], url)
            self.assertEqual(preset["kind"], "openai-compatible")
            self.assertTrue(preset["recipe"])
            self.assertTrue(registry.is_local_preset(name))
        self.assertFalse(registry.is_local_preset("openai"))
        self.assertEqual(set(registry.local_presets()),
                         {"ollama", "lmstudio"})

    def test_describe_local_preset(self):
        desc = providers.describe_spec("ollama")
        self.assertEqual(desc["seat"], "ollama")
        self.assertEqual(desc["family"], "local")
        self.assertIsNone(desc["key_env"])
        self.assertEqual(desc["model"], "llama3.1")
        self.assertEqual(desc["base_url"],
                         "http://localhost:11434/v1")
        desc = providers.describe_spec("lmstudio:my-model")
        self.assertEqual(desc["model"], "my-model")
        self.assertEqual(desc["family"], "local")

    def test_describe_named_local_spec(self):
        desc = providers.describe_spec(
            "local:box:http://localhost:8080/v1|my-model")
        self.assertEqual(desc, {
            "seat": "box", "kind": "openai-compatible",
            "preset": None, "model": "my-model",
            "key_env": None, "family": "local",
            "base_url": "http://localhost:8080/v1"})

    def test_malformed_local_specs_raise(self):
        for bad in ("local:", "local:box", "local:box:http://x/v1",
                    "local:box:http://x/v1|",
                    "local::http://x/v1|m", "local:box:ftp://x|m"):
            with self.assertRaises(providers.ProviderError,
                                   msg=bad):
                providers.describe_spec(bad)


class WireTests(StubServerCase):
    def test_named_local_seat_sends_no_authorization(self):
        _name, fn, label = providers.build_provider(
            self.local_spec())
        self.assertEqual(fn("review this"), PASS_JSON)
        self.assertEqual(label, "local:stub")
        self.assertEqual(len(self.server.seen), 1)
        seen = self.server.seen[0]
        self.assertEqual(seen["path"], "/v1/chat/completions")
        self.assertNotIn("Authorization", seen["headers"])
        self.assertEqual(seen["payload"]["model"], "stub-model")

    def test_local_preset_is_keyless_on_the_wire(self):
        captured = {}

        def fake_post(url, headers, payload, timeout=240):
            captured.update(url=url, headers=headers,
                            payload=payload)
            return {"choices": [{"message": {"content": "ok"}}]}

        with mock.patch.object(providers, "_post_json",
                               fake_post):
            _name, fn, label = providers.build_provider("ollama")
            self.assertEqual(fn("hi"), "ok")
        self.assertEqual(captured["url"],
                         "http://localhost:11434/v1"
                         "/chat/completions")
        self.assertNotIn("Authorization", captured["headers"])
        self.assertEqual(label, "local:ollama")

    def test_two_local_endpoints_are_two_seats(self):
        seats = providers.build_providers([
            self.local_spec("alpha"), self.local_spec("beta")])
        self.assertEqual(set(seats), {"alpha", "beta"})
        for fn in seats.values():
            self.assertEqual(fn("hi"), PASS_JSON)
        self.assertEqual(len(self.server.seen), 2)

    def test_local_seat_family_tag_travels_with_the_callable(self):
        seats = providers.build_providers([self.local_spec()])
        self.assertEqual(seats["stub"]._codereview_family,
                         "local")
        seats = providers.build_providers(["ollama"])
        self.assertEqual(seats["ollama"]._codereview_family,
                         "local")


class EscapeHatchRegressionTests(unittest.TestCase):
    def test_openai_compatible_hatch_unchanged(self):
        captured = {}

        def fake_post(url, headers, payload, timeout=240):
            captured.update(url=url, headers=headers,
                            payload=payload)
            return {"choices": [{"message": {"content": "ok"}}]}

        env = {"CODEREVIEW_HATCH_KEY": "placeholder-hatch-key"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(providers, "_post_json",
                                  fake_post):
            desc = providers.describe_spec(
                "openai-compatible:https://llm.example.com/v1"
                "|m|CODEREVIEW_HATCH_KEY")
            self.assertEqual(desc["family"], "unknown")
            self.assertEqual(desc["key_env"],
                             "CODEREVIEW_HATCH_KEY")
            _name, fn, label = providers.build_provider(
                "openai-compatible:https://llm.example.com/v1"
                "|m|CODEREVIEW_HATCH_KEY")
            self.assertEqual(fn("hi"), "ok")
        self.assertEqual(captured["headers"].get("Authorization"),
                         "Bearer placeholder-hatch-key")
        self.assertEqual(label, "CODEREVIEW_HATCH_KEY")


class DoctorTests(StubServerCase):
    def test_doctor_probe_against_stub_local_endpoint(self):
        seats = providers.build_providers([self.local_spec()])
        result = core.run_doctor(seats)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["seats"]), 1)
        entry = result["seats"][0]
        self.assertEqual(entry["name"], "stub")
        self.assertTrue(entry["ok"])
        # The probe really called the endpoint, keylessly.
        self.assertEqual(len(self.server.seen), 1)
        self.assertNotIn("Authorization",
                         self.server.seen[0]["headers"])


class _LoopbackOnly:
    """Refuse every non-loopback connection while active: the
    review smoke test proves the local-seat panel completes
    with external network unavailable."""

    def __enter__(self):
        self._real = socket.socket.connect

        def guarded(sock, address):
            host = (address[0] if isinstance(address, tuple)
                    else "")
            if host not in ("127.0.0.1", "::1", "localhost"):
                raise OSError(
                    f"external network refused in test: {host}")
            return self._real(sock, address)

        socket.socket.connect = guarded
        return self

    def __exit__(self, *exc):
        socket.socket.connect = self._real
        return False


class ReviewSmokeTests(StubServerCase):
    def test_panel_with_local_seat_reviews_offline(self):
        seats = providers.build_providers([self.local_spec()])

        def buddy(_prompt):
            return PASS_JSON

        panel = {"stub": seats["stub"], "buddy": buddy}
        with _LoopbackOnly():
            report = core.run_review(PATCH, panel,
                                     sleep=lambda _s: None)
        self.assertEqual(report["gate"], "pass")
        served = {r["provider"] for r in report["reviewer_reports"]
                  if r["status"] == "ok"}
        self.assertIn("stub", served)
        self.assertIn("buddy", served)
        # The local seat was really called over HTTP.
        self.assertTrue(self.server.seen)
        for seen in self.server.seen:
            self.assertNotIn("Authorization", seen["headers"])


class WizardTests(unittest.TestCase):
    def _run(self, answers, environ):
        prompts, printed = [], []

        def input_fn(prompt):
            prompts.append(prompt)
            return next(answers)

        result = setup_wizard.run_wizard(
            input_fn=input_fn, print_fn=printed.append,
            environ=environ)
        return result, prompts, printed

    def _env(self, tmp):
        return {"HOME": tmp, "PATH": tmp,
                "CODEREVIEW_CONFIG": os.path.join(tmp,
                                                  "config.toml")}

    def test_wizard_offers_local_presets_without_key_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            answers = iter(["ollama, deepseek",
                            "", "", "", "", ""])
            result, prompts, printed = self._run(
                answers, self._env(tmp))
            self.assertEqual(result["providers"],
                             ["ollama", "deepseek"])
            text = "\n".join(printed)
            # The local section lists the presets with the
            # recipe and the no-key / no-network statement.
            self.assertIn("Local model servers", text)
            self.assertIn("ollama", text)
            self.assertIn("no API key", text)
            self.assertIn("recipe:", text)
            self.assertIn("local:<name>:<base-url>|<model>", text)
            # The per-seat summary for the local seat never
            # speaks of a key env; the hosted seat's does.
            seat_lines = [ln for ln in printed
                          if ln.startswith("  seat ")]
            ollama_line = next(ln for ln in seat_lines
                               if "ollama" in ln)
            self.assertIn("no API key", ollama_line)
            self.assertIn("no network", ollama_line)
            deepseek_line = next(ln for ln in seat_lines
                                 if "deepseek" in ln)
            self.assertIn("key env DEEPSEEK_API_KEY",
                          deepseek_line)
            # No prompt anywhere asks for a key value.
            for prompt in prompts:
                self.assertNotIn("key", prompt.lower())

    def test_wizard_named_local_spec_seat_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            answers = iter([
                "local:box:http://127.0.0.1:9999/v1|m1, openai",
                "", "", "", "", ""])
            result, _prompts, printed = self._run(
                answers, self._env(tmp))
            self.assertEqual(
                result["providers"],
                ["local:box:http://127.0.0.1:9999/v1|m1",
                 "openai"])
            seat_lines = [ln for ln in printed
                          if ln.startswith("  seat ")]
            box_line = next(ln for ln in seat_lines
                            if "box" in ln)
            self.assertIn("local model server", box_line)
            self.assertIn("no API key", box_line)
            self.assertIn("http://127.0.0.1:9999/v1", box_line)


if __name__ == "__main__":
    unittest.main()
