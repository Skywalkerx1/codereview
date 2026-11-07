"""Phase 4 rerun — supplementary regression tests.

The tester's own 15 tests live in test_phase4_residuals.py.
This file pins the parts of the rerun brief her patch did not
cover: the two-resume end-to-end torn-tail repro (P4-08b),
the record/report surface for the error-body redaction and
the agent-seat stderr tail found by audit (P4-01b), and the
quotation/call lead-in completions plus the accepted-residual
pin (P4-06c).
"""

import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import generation as gen  # noqa: E402
from codereview import core, providers, seatstate  # noqa: E402

GOOD_JSON = json.dumps({"summary": "ok", "findings": []})
USAGE = {"prompt_tokens": 100, "completion_tokens": 50}
BINDING = {"a": ["correctness"], "b": ["operations"]}
PATCH = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
         "@@ -1,1 +1,2 @@\n x=1\n+y=2\n")
# Assembled from fragments: the repo's secret-hygiene test
# scans test files for key-shaped literals.
SECRET = "sk-" + "proj-" + "RERUNLEAK" + "0123456789" + "abcdefghij"
LEAKED_BEARER = "RERUNTOKEN" + "0123456789" + "abcdefghij"


def _gen_case(i):
    return {"id": f"c{i}", "split": "public", "category": "logic",
            "title": f"case {i}", "context": "", "diff": PATCH,
            "expected": {}}


def _gen_seat(name):
    return gen.GenerationSeat(
        name, "m", lambda p: (GOOD_JSON, USAGE),
        sleep=lambda _s: None, rng=lambda: 0.5)


def _run_gen(out, cache_dir, cases):
    seats = {n: _gen_seat(n) for n in ("a", "b")}
    return gen.run_generation(
        cases, seats, BINDING, cache_dir=cache_dir, out_dir=out,
        config_name="testcfg", config_sha256="sha-x",
        gate_profile="balanced", log=lambda _m: None)


def _records(out, name):
    path = os.path.join(out, name)
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def _tear_tail(path, drop=0):
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    kept = lines[:len(lines) - drop] if drop else lines
    kept[-1] = kept[-1][:len(kept[-1]) // 2]
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(kept)


class TornTailTwoResumesTests(unittest.TestCase):
    """P4-08b, the rerun's repro end to end: after a torn
    tail, TWO consecutive resumes succeed, no corrupt line
    remains, and the records match the clean reference."""

    def _clean_reference(self, tmp, cases):
        out = os.path.join(tmp, "clean")
        summary = _run_gen(out, os.path.join(tmp, "cc"), cases)
        self.assertEqual(summary["complete"],
                         [c["id"] for c in cases])
        return {(r["case_id"], r["seat"], r["lens"]):
                (r["attempts"], r["tokens_in"], r["tokens_cached"])
                for r in _records(out, "generation-attempt-1.jsonl")}

    def test_two_resumes_after_torn_gen_and_attempt_files(self):
        cases = [_gen_case(0), _gen_case(1)]
        with tempfile.TemporaryDirectory() as tmp:
            clean = self._clean_reference(tmp, cases)
            out = os.path.join(tmp, "out")
            cache_dir = os.path.join(tmp, "cache")
            _run_gen(out, cache_dir, cases)
            # The rerun repro: drop the last records and leave
            # a half-written final line in each file.
            _tear_tail(os.path.join(
                out, "generation-attempt-1.jsonl"), drop=2)
            _tear_tail(os.path.join(out, "attempt-1.jsonl"),
                       drop=1)
            s1 = _run_gen(out, cache_dir, cases)
            self.assertEqual(s1["complete"], ["c0", "c1"])
            s2 = _run_gen(out, cache_dir, cases)
            self.assertEqual(s2["complete"], ["c0", "c1"])
            got = {(r["case_id"], r["seat"], r["lens"]):
                   (r["attempts"], r["tokens_in"],
                    r["tokens_cached"])
                   for r in _records(
                       out, "generation-attempt-1.jsonl")}
            self.assertEqual(got, clean)
            self.assertEqual(
                {r["case_id"] for r in _records(
                    out, "attempt-1.jsonl")}, {"c0", "c1"})

    def test_two_resumes_after_torn_journal_tail(self):
        cases = [_gen_case(0), _gen_case(1)]
        with tempfile.TemporaryDirectory() as tmp:
            clean = self._clean_reference(tmp, cases)
            out = os.path.join(tmp, "out")
            cache_dir = os.path.join(tmp, "cache")
            _run_gen(out, cache_dir, cases)
            _tear_tail(os.path.join(out, "events-attempt-1.jsonl"))
            s1 = _run_gen(out, cache_dir, cases)
            self.assertEqual(s1["complete"], ["c0", "c1"])
            s2 = _run_gen(out, cache_dir, cases)
            self.assertEqual(s2["complete"], ["c0", "c1"])
            # Every journal line parses (no corrupt line left
            # behind) and the folded records are untouched.
            _records(out, "events-attempt-1.jsonl")
            got = {(r["case_id"], r["seat"], r["lens"]):
                   (r["attempts"], r["tokens_in"],
                    r["tokens_cached"])
                   for r in _records(
                       out, "generation-attempt-1.jsonl")}
            self.assertEqual(got, clean)


class _Stub401:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        body = self.body

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                self.rfile.read(n)
                self.send_response(401)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever,
                         daemon=True).start()
        return (f"http://127.0.0.1:{self.srv.server_address[1]}"
                f"/v1/chat/completions")

    def __exit__(self, *exc):
        self.srv.shutdown()
        self.srv.server_close()


class RecordRedactionTests(unittest.TestCase):
    """P4-01b at the surface the finding named: the written
    .json record and .md report carry neither the key nor the
    bearer token the provider's 401 body echoed."""

    def test_secret_reaches_neither_record_nor_report(self):
        body = json.dumps({"error": {"message":
            f"Incorrect API key provided: {SECRET}. "
            f"Header was Bearer {LEAKED_BEARER}"}}).encode()
        with _Stub401(body) as url:
            try:
                providers._post_json(url, {}, {"model": "m"}, 5)
                self.fail("401 must raise")
            except providers.ProviderError as exc:
                message = str(exc)
        self.assertNotIn(SECRET, message)
        self.assertNotIn(LEAKED_BEARER, message)

        def seat(_prompt):
            raise providers.ProviderError(message)

        report = core.run_review(
            PATCH, {"a": seat, "b": seat})
        with tempfile.TemporaryDirectory() as tmp:
            jpath, mpath = core.write_report(report, tmp)
            with open(jpath, encoding="utf-8") as fh:
                record_text = fh.read()
            with open(mpath, encoding="utf-8") as fh:
                report_text = fh.read()
        for text in (record_text, report_text):
            self.assertNotIn(SECRET, text)
            self.assertNotIn(LEAKED_BEARER, text)
        self.assertIn("401", record_text)


def _write_cli(tmp, name, body):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!" + sys.executable + "\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class AgentTailRedactionTests(unittest.TestCase):
    """P4-01b audit extension: an agent seat's stderr tail is
    quoted into its ProviderError — and from there the record
    — so it is redacted at the same boundary."""

    def test_stderr_tail_key_is_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = ("import sys\n"
                    f"sys.stderr.write('fatal: auth failed for "
                    f"key {SECRET}\\n')\n"
                    "sys.exit(1)\n")
            path = _write_cli(tmp, "fakecli", body)
            fn = providers.command_agent(path, timeout=30)
            with self.assertRaises(providers.ProviderError) as cm:
                fn("prompt")
        self.assertNotIn(SECRET, str(cm.exception))
        self.assertIn("exited 1", str(cm.exception))


class LeadInCompletionTests(unittest.TestCase):
    """P4-06c completions over the tester's patch: the '|'
    marker, indented diff/quote markers, and bare code-call
    lead-ins are quotation contexts too; '-' stays allowed
    (deliberate: an ordinary vendor bullet), and the unquoted
    benign warning stays matched — the accepted residual,
    pinned so lifting it later is a deliberate change."""

    def m(self, text):
        return seatstate.match_failure("claude", text)

    def test_pipe_and_indented_markers_rejected(self):
        for line in ("| Not logged in", "  +Not logged in",
                     "    > Not logged in"):
            self.assertIsNone(self.m(line), line)

    def test_bare_code_call_rejected(self):
        self.assertIsNone(self.m("print(Not logged in)"))
        self.assertIsNone(self.m("logger.info(Not logged in)"))

    def test_dash_bullet_still_matches_by_design(self):
        self.assertEqual(self.m("- Not logged in")["class"],
                         "auth")

    def test_unquoted_benign_warning_is_the_accepted_residual(self):
        hit = self.m("MCP server docs not logged in; continuing")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["class"], "auth")

    def test_vendor_line_with_paren_after_match_still_matches(self):
        # codex-quota.txt verbatim: the '(' sits after the
        # matched core, never in the lead-in.
        hit = seatstate.match_failure(
            "codex", "ERROR: You’ve hit your usage limit. "
            "Upgrade to Pro (https://chatgpt.com/explore/pro), "
            "visit https://chatgpt.com/settings/usage\n")
        self.assertEqual(hit["class"], "quota")
        self.assertEqual(hit["pattern"], "codex-quota-usage-limit")


if __name__ == "__main__":
    unittest.main()
