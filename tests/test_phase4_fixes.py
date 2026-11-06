"""Phase 4 (integration & failure injection) fix regressions.

Each test pins one defect from the external tester's Phase 4
report (2026-11-06), reproduced first against the unfixed tree
with the tester's own scripts, then fixed:

  P4-01  HTTP error bodies are read: quota classes reachable for
         API seats; Retry-After honoured as a capped delay floor.
  P4-02  API calls live under one overall deadline; --timeout
         (build_provider's agent_timeout) bounds API seats too.
  P4-03  Response bodies are size-capped (16 MiB).
  P4-04  Transport garbage (malformed JSON / HTML / non-UTF-8 /
         truncated body) is a transient ProviderError, retried.
  P4-05  The providers' empty-content raises carry kind="empty";
         _classify_error maps it to the content class (re-draw).
  P4-06  Seat-state patterns match the CLI's own unquoted
         diagnostic lines only — a warning quoting a component's
         state, or verdict text quoting a diff, cannot kill or
         classify a seat.
  P4-07  The herdr watch backs off on pane-get failures and
         gives up bounded, with the herdr-unreachable outcome.
  P4-08  A torn final JSONL line is tolerated on resume; a
         corrupt non-final line still raises.
  P4-09  Generation metering is durable at call time (event
         journal), so a kill between cache write and record
         write no longer understates attempts/tokens on resume.
  P4-10  A waiver dated in the future (beyond 1 day of skew) is
         a max_age_days violation.
  P4-11  A multi-seat single-family panel is labelled
         "single-family panel — no independent review".

Stdlib only; loopback stubs and fake CLIs throughout — no real
provider, account, or network is touched.
"""

import datetime
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "bench"))

from codereview import core, herdrhost, policy, providers  # noqa: E402
from codereview import seatstate  # noqa: E402
import generation as gen  # noqa: E402

GOOD_JSON = json.dumps({"summary": "ok", "findings": []})


def ok_body(content=None):
    c = GOOD_JSON if content is None else content
    return json.dumps(
        {"choices": [{"message": {"content": c}}]}).encode()


class Stub:
    """A scripted OpenAI-compatible loopback stub: one behaviour
    per request, then the default behaviour forever."""

    def __init__(self, script, default="ok"):
        self.script = list(script)
        self.default = default
        self.hits = []
        self.lock = threading.Lock()
        stub = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                self.rfile.read(n)
                with stub.lock:
                    beh = stub.script.pop(0) if stub.script \
                        else stub.default
                    stub.hits.append(beh)
                stub.act(self, beh)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever,
                         daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/v1"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def send(self, h, code, body, extra=None):
        try:
            h.send_response(code)
            h.send_header("Content-Type", "application/json")
            h.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                h.send_header(k, v)
            h.end_headers()
            h.wfile.write(body)
            h.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    def act(self, h, beh):
        try:
            if beh == "ok":
                self.send(h, 200, ok_body())
            elif beh == "429quota":
                self.send(h, 429, b'{"error":{"code":'
                                  b'"insufficient_quota","message"'
                                  b':"You exceeded your current '
                                  b'quota"}}')
            elif beh == "429daily":
                self.send(h, 429, b'{"error":{"status":'
                                  b'"RESOURCE_EXHAUSTED","message"'
                                  b':"Quota exceeded: daily '
                                  b'limit"}}')
            elif beh == "429plain":
                self.send(h, 429, b'{"error":{"message":"Rate '
                                  b'limit reached for requests '
                                  b'per min"}}')
            elif beh == "429retry":
                self.send(h, 429, b'{"error":{"message":"slow '
                                  b'down"}}',
                          extra={"Retry-After": "120"})
            elif beh == "429retryhuge":
                self.send(h, 429, b'{"error":{"message":"slow '
                                  b'down"}}',
                          extra={"Retry-After": "86400"})
            elif beh == "badjson":
                self.send(h, 200, b"{not json")
            elif beh == "html200":
                self.send(h, 200, b"<html>proxy login</html>")
            elif beh == "nonutf8":
                self.send(h, 200, b'{"choices":[{"message":'
                                  b'{"content":"\xff\xfe"}}]}')
            elif beh == "truncjson":
                full = ok_body()
                h.send_response(200)
                h.send_header("Content-Type", "application/json")
                h.send_header("Content-Length", str(len(full)))
                h.end_headers()
                h.wfile.write(full[:20])
                h.wfile.flush()
                h.connection.close()
            elif beh == "empty":
                self.send(h, 200, ok_body(""))
            elif beh == "trickle":
                full = ok_body()
                h.send_response(200)
                h.send_header("Content-Type", "application/json")
                h.send_header("Content-Length", str(len(full)))
                h.end_headers()
                for i in range(len(full)):
                    h.wfile.write(full[i:i + 1])
                    h.wfile.flush()
                    time.sleep(0.05)
            elif beh == "huge":
                total = 20 * 1024 * 1024
                h.send_response(200)
                h.send_header("Content-Type", "application/json")
                h.send_header("Content-Length", str(total))
                h.end_headers()
                chunk = b"a" * (1 << 20)
                sent = 0
                while sent < total:
                    h.wfile.write(chunk)
                    h.wfile.flush()
                    sent += len(chunk)
            else:
                self.send(h, 200, ok_body())
        except (BrokenPipeError, ConnectionError, OSError):
            pass


def local_fn(stub, **kw):
    return providers.build_provider(
        f"local:box:{stub.url}|m", **kw)[1]


def review_job(fn):
    sleeps = []
    res = core._review_job(fn, "review this",
                           sleep=sleeps.append, seat="box")
    return res, sleeps


class QuotaClassificationTests(unittest.TestCase):
    """P4-01: the quota classes were unreachable for API seats
    because the HTTP error body was never read."""

    def run_script(self, script, default="ok"):
        st = Stub(script, default)
        self.addCleanup(st.close)
        res, sleeps = review_job(local_fn(st))
        return st, res, sleeps

    def test_insufficient_quota_body_classifies_quota(self):
        st, res, _ = self.run_script(["429quota"] * 3)
        self.assertEqual(len(st.hits), 1)          # never retried
        self.assertEqual(res["attempts"], 1)
        self.assertEqual(res["error_classes"], ["quota"])
        self.assertEqual(res["seat_state"]["state"], "blocked")
        self.assertEqual(res["seat_state"]["class"], "quota")

    def test_resource_exhausted_daily_body_classifies_quota(self):
        st, res, _ = self.run_script(["429daily"] * 3)
        self.assertEqual(len(st.hits), 1)
        self.assertEqual(res["error_classes"], ["quota"])
        self.assertEqual(res["seat_state"]["class"], "quota")

    def test_plain_429_stays_rate_limit_and_retries(self):
        st, res, _ = self.run_script(["429plain"] * 3)
        self.assertEqual(len(st.hits), 3)
        self.assertEqual(res["attempts"], 3)
        self.assertEqual(res["error_classes"],
                         ["rate_limit"] * 3)

    def test_error_body_excerpt_is_in_the_error(self):
        st = Stub(["429quota"])
        self.addCleanup(st.close)
        with self.assertRaises(providers.ProviderError) as cm:
            providers._post_json(st.url + "/chat/completions",
                                 {}, {})
        self.assertIn("insufficient_quota", str(cm.exception))
        self.assertEqual(cm.exception.retry_after, None)

    def test_retry_after_floors_the_retry_delay(self):
        st, res, sleeps = self.run_script(["429retry"] * 3)
        self.assertEqual(res["attempts"], 3)
        self.assertEqual(res["error_classes"],
                         ["rate_limit"] * 3)
        self.assertEqual(len(sleeps), 2)
        for s in sleeps:
            self.assertGreaterEqual(s, 120.0)
            self.assertLessEqual(s, 121.0)

    def test_retry_after_is_capped(self):
        st, res, sleeps = self.run_script(["429retryhuge"] * 3)
        self.assertEqual(res["attempts"], 3)
        for s in sleeps:
            self.assertGreaterEqual(s, 120.0)
            self.assertLessEqual(s, 121.0)

    def test_retry_after_header_parsing(self):
        class H(dict):
            def get(self, k):
                return dict.get(self, k)
        self.assertEqual(
            providers._retry_after_seconds(H({"Retry-After": "45"})),
            45.0)
        self.assertIsNone(providers._retry_after_seconds(H({})))
        self.assertIsNone(
            providers._retry_after_seconds(
                H({"Retry-After": "whenever"})))
        from email.utils import format_datetime
        future = format_datetime(
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(seconds=90))
        v = providers._retry_after_seconds(
            H({"Retry-After": future}))
        self.assertTrue(80.0 < v <= 90.0)
        past = format_datetime(
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=90))
        self.assertEqual(
            providers._retry_after_seconds(
                H({"Retry-After": past})), 0.0)


class DeadlineAndCapTests(unittest.TestCase):
    """P4-02 (overall deadline), P4-03 (size cap)."""

    def test_trickle_dies_at_the_overall_deadline(self):
        st = Stub(["trickle"])
        self.addCleanup(st.close)
        started = time.monotonic()
        with self.assertRaises(providers.ProviderError) as cm:
            providers._post_json(st.url + "/chat/completions",
                                 {}, {}, timeout=1)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 3.5)
        kind, tries = core._classify_error(cm.exception)
        self.assertEqual((kind, tries), ("transient", 3))

    def test_operator_timeout_bounds_api_seats(self):
        st = Stub(["trickle"])
        self.addCleanup(st.close)
        fn = local_fn(st, agent_timeout=1)
        started = time.monotonic()
        with self.assertRaises(providers.ProviderError):
            fn("review this")
        self.assertLess(time.monotonic() - started, 3.5)

    def test_normal_response_unaffected(self):
        st = Stub(["ok"])
        self.addCleanup(st.close)
        fn = local_fn(st, agent_timeout=30)
        text = fn("review this")
        self.assertIn("summary", text)

    def test_oversize_body_is_capped(self):
        st = Stub(["huge"])
        self.addCleanup(st.close)
        started = time.monotonic()
        with self.assertRaises(providers.ProviderError) as cm:
            providers._post_json(st.url + "/chat/completions",
                                 {}, {}, timeout=60)
        self.assertLess(time.monotonic() - started, 30)
        self.assertIn("cap", str(cm.exception))
        kind, tries = core._classify_error(cm.exception)
        self.assertEqual((kind, tries), ("transient", 3))


class TransportGarbageTests(unittest.TestCase):
    """P4-04: transport garbage must surface as a transient
    ProviderError — retried — not as a raw decode error treated
    as a model-output parse failure (1 attempt, no class)."""

    def assert_transient_provider_error(self, beh):
        st = Stub([beh])
        self.addCleanup(st.close)
        with self.assertRaises(providers.ProviderError) as cm:
            providers._post_json(st.url + "/chat/completions",
                                 {}, {})
        kind, tries = core._classify_error(cm.exception)
        self.assertEqual((kind, tries), ("transient", 3))

    def test_malformed_json(self):
        self.assert_transient_provider_error("badjson")

    def test_html_200(self):
        self.assert_transient_provider_error("html200")

    def test_non_utf8(self):
        self.assert_transient_provider_error("nonutf8")

    def test_truncated_body(self):
        self.assert_transient_provider_error("truncjson")

    def test_malformed_then_ok_succeeds_on_retry(self):
        st = Stub(["badjson", "ok"])
        self.addCleanup(st.close)
        res, _ = review_job(local_fn(st))
        self.assertTrue(res["ok"])
        self.assertEqual(res["attempts"], 2)
        self.assertEqual(res["error_classes"], ["transient"])
        self.assertEqual(len(st.hits), 2)


class EmptyContentKindTests(unittest.TestCase):
    """P4-05: the product providers' empty-content raises carry
    kind="empty", classified as the content class (re-draw)."""

    def test_empty_raise_carries_kind(self):
        st = Stub(["empty"])
        self.addCleanup(st.close)
        fn = local_fn(st)
        with self.assertRaises(providers.ProviderError) as cm:
            fn("review this")
        self.assertEqual(cm.exception.kind, "empty")

    def test_classify_maps_kind_empty_to_content_class(self):
        err = providers.ProviderError("empty content from model",
                                      kind="empty")
        self.assertEqual(core._classify_error(err), ("empty", 3))

    def test_empty_then_ok_succeeds_via_redraw(self):
        st = Stub(["empty", "ok"])
        self.addCleanup(st.close)
        res, _ = review_job(local_fn(st))
        self.assertTrue(res["ok"])
        self.assertEqual(res["attempts"], 2)
        self.assertEqual(res["error_classes"], ["empty"])

    def test_generation_seat_redraws_on_typed_empty(self):
        calls = []

        def transport(prompt):
            calls.append(prompt)
            if len(calls) == 1:
                raise providers.ProviderError(
                    "empty content from model", kind="empty")
            return GOOD_JSON, {"prompt_tokens": 100,
                               "completion_tokens": 50}

        s = gen.GenerationSeat("a", "m", transport,
                               sleep=lambda _s: None,
                               rng=lambda: 0.5)
        # The content-class hand-off: an unusable (empty) answer
        # for the product's own re-draw, no exhausted latch.
        self.assertEqual(s("p"), "")
        self.assertEqual(
            [(e["outcome"], e["error_class"]) for e in s.events],
            [("content_invalid", "empty")])
        self.assertEqual(s("p"), GOOD_JSON)
        self.assertEqual(len(calls), 2)


def _write_cli(tmp, name, body):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!" + sys.executable + "\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class SeatStateAnchorTests(unittest.TestCase):
    """P4-06: the failure patterns are anchored to the CLI's own
    unquoted diagnostic lines. The verbatim vendor lines (with
    their lead-ins) still match; a warning quoting a component's
    state, and verdict text quoting a diff, do not."""

    BENIGN = ("warning: MCP server 'docs' not logged in; "
              "continuing without it\n")

    def test_benign_warning_matches_nothing(self):
        self.assertIsNone(
            seatstate.match_failure("claude", self.BENIGN))

    def test_verbatim_auth_line_still_matches(self):
        hit = seatstate.match_failure(
            "claude", "Not logged in · Please run /login\n")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["class"], "auth")
        self.assertEqual(hit["pattern"],
                         "claude-auth-not-logged-in")

    def test_verbatim_lead_ins_still_match(self):
        # The vendor lead-ins the evidence ships with: a
        # contraction, an ERROR label, status prefixes, and the
        # real codex capture's timestamped logger lines.
        hit = seatstate.match_failure(
            "claude", "You’ve hit your weekly limit\n")
        self.assertEqual(hit["class"], "quota")
        hit = seatstate.match_failure(
            "codex", "ERROR: You’ve hit your usage limit. "
                     "Upgrade to Pro\n")
        self.assertEqual(hit["class"], "quota")
        hit = seatstate.match_failure(
            "codex", "HTTP error: 401 Unauthorized\n"
                     "unexpected status 401 Unauthorized: "
                     "Missing bearer\n")
        self.assertEqual(hit["class"], "auth")
        self.assertEqual(hit["pattern"], "codex-auth-401")
        hit = seatstate.match_failure(
            "codex", "2026-11-05T13:33:58Z ERROR "
                     "codex_api::endpoint::responses_websocket: "
                     "failed to connect to websocket: HTTP "
                     "error: 401 Unauthorized, url: wss://x\n")
        self.assertEqual(hit["class"], "auth")
        hit = seatstate.match_failure(
            "gemini", "API error: 429 - Resource exhausted\n")
        self.assertEqual(hit["class"], "quota")

    def test_diff_quoted_stdout_no_longer_classifies_auth(self):
        verdict = json.dumps({
            "verdict": "pass", "summary":
            "reviewing a diff containing: Not logged in",
            "findings": []})
        state, cls, ev = seatstate.classify_exit(
            "claude", 3, verdict, "")
        self.assertEqual((state, cls), ("failed", "error"))
        self.assertEqual(ev, {"exit_code": 3})

    def test_failure_as_result_stdout_still_classifies(self):
        # Claude Code's failure-as-result channel (stdout on a
        # non-zero exit) is deliberate and preserved.
        state, cls, ev = seatstate.classify_exit(
            "claude", 1, "Not logged in · Please run /login", "")
        self.assertEqual((state, cls), ("blocked", "auth"))
        self.assertEqual(ev["source"], "stdout")

    def test_benign_warning_seat_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = json.dumps({"summary": "ok", "findings": []})
            body = (
                "import sys, time\n"
                "sys.stderr.write(\"warning: MCP server 'docs' "
                "not logged in; continuing without it\\n\")\n"
                "sys.stderr.flush()\n"
                "time.sleep(0.6)\n"
                f"sys.stdout.write({good!r})\n")
            path = _write_cli(tmp, "claude", body)
            fn = providers.command_agent(
                path, timeout=30, stall_after=60.0,
                block_grace=0.2)
            text = fn("brief")
        self.assertIn('"summary": "ok"', text)

    def test_verbatim_auth_line_still_terminates_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = (
                "import sys, time\n"
                "sys.stderr.write('Not logged in · Please run "
                "/login\\n')\n"
                "sys.stderr.flush()\n"
                "time.sleep(30)\n")
            path = _write_cli(tmp, "claude", body)
            fn = providers.command_agent(
                path, timeout=30, stall_after=60.0,
                block_grace=0.3)
            started = time.monotonic()
            with self.assertRaises(providers.ProviderError) as cm:
                fn("brief")
            self.assertLess(time.monotonic() - started, 15)
        facts = cm.exception.seat_facts
        self.assertEqual(facts["state"], "blocked")
        self.assertEqual(facts["class"], "auth")
        self.assertTrue(facts["evidence"]["early_terminated"])


class FakeHerdrHost:
    """A duck-typed herdrhost stand-in for the hosted watch:
    pane_get fails a scripted number of times (or forever);
    snapshot always proves the same pane under the same
    terminal — the P4-07 precondition."""

    def __init__(self, fail_first=0, fail_forever=False):
        self.get_calls = 0
        self.snap_calls = 0
        self.fail_first = fail_first
        self.fail_forever = fail_forever

    def pane_get(self, pane_id):
        self.get_calls += 1
        if self.fail_forever or self.get_calls <= self.fail_first:
            raise herdrhost.HerdrError("connection refused")
        return {"pane_id": pane_id, "terminal_id": "t1",
                "agent_status": "working"}

    def snapshot(self):
        self.snap_calls += 1
        return {"panes": [{"pane_id": "p1", "terminal_id": "t1",
                           "agent_status": "working"}]}


class HerdrWatchBackoffTests(unittest.TestCase):
    """P4-07: the hosted watch had no backoff or bound on
    pane-get failures (~13 spawns/s forever)."""

    def _watch(self, host, timeout=60.0):
        tmp = tempfile.mkdtemp()
        out_path = os.path.join(tmp, "out")
        err_path = os.path.join(tmp, "err")
        rc_path = os.path.join(tmp, "rc")
        open(out_path, "w").close()
        open(err_path, "w").close()
        receipt = {"transport": "herdr"}
        outcome = providers._run_hosted_seat(
            host, receipt, "p1", out_path, err_path, rc_path,
            None, None, timeout, 3600.0, 10.0)
        return outcome, receipt

    def test_persistent_failure_gives_up_bounded(self):
        host = FakeHerdrHost(fail_forever=True)
        with unittest.mock.patch.object(
                providers, "_HERDR_GET_MAX_FAILURES", 5):
            started = time.monotonic()
            outcome, receipt = self._watch(host)
            elapsed = time.monotonic() - started
        self.assertEqual(outcome["kind"], "herdr-failure")
        self.assertEqual(outcome["stage"], "herdr-unreachable")
        self.assertEqual(host.get_calls, 5)
        self.assertEqual(host.snap_calls, 5)
        self.assertEqual(receipt["events_lost"], 5)
        # The backoff actually paced the loop: 0.1+0.2+0.4+0.8
        # of sleeps separate the five failures.
        self.assertGreaterEqual(elapsed, 1.4)

    def test_spawn_rate_collapses_under_persistent_failure(self):
        host = FakeHerdrHost(fail_forever=True)
        outcome, receipt = self._watch(host, timeout=1.2)
        self.assertEqual(outcome["kind"], "timeout")
        # Unbacked-off this window held ~24 polls; backed off
        # (0.1, 0.2, 0.4, 0.8, ...) it holds a handful.
        self.assertLessEqual(host.get_calls, 8)
        self.assertEqual(receipt["events_lost"], host.get_calls)

    def test_transient_failures_recover(self):
        host = FakeHerdrHost(fail_first=2)
        tmp = tempfile.mkdtemp()
        out_path = os.path.join(tmp, "out")
        err_path = os.path.join(tmp, "err")
        rc_path = os.path.join(tmp, "rc")
        open(out_path, "w").close()
        open(err_path, "w").close()

        def write_rc():
            with open(rc_path, "w") as fh:
                fh.write("0")

        timer = threading.Timer(0.5, write_rc)
        timer.start()
        try:
            receipt = {"transport": "herdr"}
            outcome = providers._run_hosted_seat(
                host, receipt, "p1", out_path, err_path, rc_path,
                None, None, 30.0, 3600.0, 10.0)
        finally:
            timer.cancel()
        self.assertEqual(outcome,
                         {"kind": "exit", "returncode": 0})
        self.assertEqual(receipt["events_lost"], 2)
        self.assertGreaterEqual(host.get_calls, 3)


if __name__ == "__main__":
    unittest.main()
