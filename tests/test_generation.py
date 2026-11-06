"""Generation/scoring separation (void solution §3.1–§3.3, S4).

The machinery under test (bench/generation.py):
  * a record/replay cache keyed by (seat, model, params hash,
    prompt hash) — transport errors never cached, first VALID
    response cached and never re-drawn;
  * §3.2 failure classes: transport failures retry inside a
    per-job budget and are not degraded when a valid response
    lands; content failures go through the product's own repair
    and then the pre-declared fallback seat; a seat unserved
    beyond budget marks the case unscored-infra;
  * resumable per-case x per-seat generation: complete when
    every configured seat has a valid response;
  * shadow cost metering from tokens (S4) — no $0 convention;
  * the adapter emits exactly the record shape the committed
    confirmation scorer consumes.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import generation as gen  # noqa: E402
from codereview import bench as bench_mod  # noqa: E402

GOOD = json.dumps({"summary": "fine", "findings": []})
USAGE = {"prompt_tokens": 1000, "completion_tokens": 500}


def seat(name, transport, model="deepseek-chat", **kw):
    kw.setdefault("sleep", lambda _s: None)
    kw.setdefault("rng", lambda: 0.5)
    return gen.GenerationSeat(name, model, transport, **kw)


def public_cases(n=2):
    corpus = bench_mod.load_corpus(os.path.join(ROOT, "bench",
                                                "corpus"))
    pub = [c for c in corpus if c["split"] == "public"]
    pub.sort(key=lambda c: len(c["diff"]))
    return pub[:n]


class CacheSeatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = gen.ResponseCache(
            os.path.join(self.tmp.name, "cache"))

    def test_first_valid_cached_and_never_redrawn(self):
        calls = []

        def transport(prompt):
            calls.append(prompt)
            return GOOD, USAGE

        s = seat("a", transport, cache=self.cache)
        self.assertEqual(s("prompt one"), GOOD)
        self.assertEqual(s("prompt one"), GOOD)
        self.assertEqual(len(calls), 1)
        outcomes = [e["outcome"] for e in s.events]
        self.assertEqual(outcomes, ["ok", "cache_hit"])

    def test_transport_error_never_cached(self):
        calls = []

        def transport(prompt):
            calls.append(prompt)
            if len(calls) == 1:
                raise Exception("HTTP 503 Service Unavailable")
            return GOOD, USAGE

        s = seat("a", transport, cache=self.cache)
        self.assertEqual(s("p"), GOOD)   # retried inside the seat
        self.assertEqual(s("p"), GOOD)   # cache hit, no new call
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [e["outcome"] for e in s.events],
            ["transport_error", "ok", "cache_hit"])

    def test_empty_body_is_a_transport_failure(self):
        calls = []

        def transport(prompt):
            calls.append(prompt)
            return ("", USAGE) if len(calls) == 1 else (GOOD, USAGE)

        s = seat("a", transport, cache=self.cache)
        self.assertEqual(s("p"), GOOD)
        self.assertEqual(s.events[0]["error_class"], "empty_body")

    def test_content_invalid_is_not_cached(self):
        calls = []

        def transport(prompt):
            calls.append(prompt)
            if len(calls) == 1:
                return "definitely not json", USAGE
            return GOOD, USAGE

        s = seat("a", transport, cache=self.cache)
        # The product's repair flow gets the raw text back; the
        # wrapper must not cache it as a response.
        self.assertEqual(s("p"), "definitely not json")
        self.assertEqual(s("p"), GOOD)   # fresh draw, now cached
        self.assertEqual(s("p"), GOOD)   # cache hit
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [e["outcome"] for e in s.events],
            ["content_invalid", "ok", "cache_hit"])

    def test_persistent_transport_exhausts_and_fails_fast(self):
        calls = []

        def transport(prompt):
            calls.append(prompt)
            raise Exception("HTTP 503 Service Unavailable")

        s = seat("a", transport, cache=self.cache, max_attempts=3)
        with self.assertRaises(Exception):
            s("p")
        self.assertEqual(len(calls), 3)
        self.assertEqual(
            [e["outcome"] for e in s.events],
            ["transport_error"] * 3)
        # The product's own retry layer re-entering the seat must
        # not multiply calls against a dead seat.
        with self.assertRaises(gen.GenerationExhausted):
            s("p")
        self.assertEqual(len(calls), 3)

    def test_cache_key_covers_seat_model_params_prompt(self):
        k1 = gen.cache_key("a", "m", {"t": 0.1}, "p1")[0]
        self.assertNotEqual(
            k1, gen.cache_key("b", "m", {"t": 0.1}, "p1")[0])
        self.assertNotEqual(
            k1, gen.cache_key("a", "m2", {"t": 0.1}, "p1")[0])
        self.assertNotEqual(
            k1, gen.cache_key("a", "m", {"t": 0.2}, "p1")[0])
        self.assertNotEqual(
            k1, gen.cache_key("a", "m", {"t": 0.1}, "p2")[0])


class FakeProviderError(Exception):
    """llm_chain.ProviderError's shape: a typed provider error
    (provider / kind / detail attributes, no `retryable`), whose
    string form is "<provider> <kind>: <detail>". core's
    classifier reads typed attributes first and the message text
    second, exactly as it does for the real wrapper's errors."""

    def __init__(self, provider, kind, detail):
        super().__init__(f"{provider} {kind}: {detail}")
        self.provider = provider
        self.kind = kind
        self.detail = detail


def empty_error():
    return FakeProviderError("deepseek", "empty", "empty content")


class EmptyContentClassTests(unittest.TestCase):
    """ProviderError kind="empty" is a CONTENT-class failure
    (soak 2026-11-05): the provider answered with an empty
    content channel. It must not burn the transport retry
    budget and must not latch the per-key exhausted state —
    the product's own retry behaviour is the re-draw, and the
    per-lens fallback seat is the next step."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = gen.ResponseCache(
            os.path.join(self.tmp.name, "cache"))

    def test_empty_is_content_class_and_seat_redraws(self):
        calls = []

        def transport(prompt):
            calls.append(prompt)
            if len(calls) == 1:
                raise empty_error()
            return GOOD, USAGE

        s = seat("a", transport, cache=self.cache)
        # The failure is handed to the caller's repair flow as an
        # unusable (empty) response — never raised as transport.
        self.assertEqual(s("p"), "")
        self.assertEqual(
            [(e["outcome"], e["error_class"]) for e in s.events],
            [("content_invalid", "empty")])
        # The key is NOT latched: a re-draw reaches the transport
        # and the valid response is served (and cached).
        self.assertEqual(s("p"), GOOD)
        self.assertEqual(s("p"), GOOD)   # cache hit
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [e["outcome"] for e in s.events],
            ["content_invalid", "ok", "cache_hit"])

    def test_typed_nonempty_error_still_takes_transport_path(
            self):
        calls = []

        def transport(prompt):
            calls.append(prompt)
            if len(calls) == 1:
                raise FakeProviderError(
                    "deepseek", "http",
                    "HTTP 503 Service Unavailable")
            return GOOD, USAGE

        s = seat("a", transport, cache=self.cache)
        # Retried inside the seat under the transport budget,
        # exactly as before the empty mapping existed.
        self.assertEqual(s("p"), GOOD)
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [(e["outcome"], e["error_class"]) for e in s.events],
            [("transport_error", "transient"), ("ok", None)])


class ShadowCostTests(unittest.TestCase):
    def test_priced_model_and_unknown_model(self):
        usd, known = gen.shadow_price("deepseek-chat", 1_000_000,
                                      1_000_000)
        self.assertTrue(known)
        self.assertAlmostEqual(usd, 0.27 + 1.10)
        usd, known = gen.shadow_price("mystery-model", 10, 10)
        self.assertEqual((usd, known), (0.0, False))

    def test_usage_normalisation_and_estimate(self):
        self.assertEqual(
            gen.normalize_usage(USAGE, "x" * 400, "y" * 40),
            (1000, 500, False))
        tin, tout, est = gen.normalize_usage(None, "x" * 400,
                                             "y" * 40)
        self.assertEqual((tin, tout, est), (100, 10, True))


BINDING = {"a": ["correctness"], "b": ["operations"]}


def run(cases, seats, out, cache_dir, **kw):
    kw.setdefault("gate_profile", "balanced")
    return gen.run_generation(
        cases, seats, BINDING, cache_dir=cache_dir, out_dir=out,
        config_name="testcfg", config_sha256="sha-" + cache_dir,
        log=lambda _m: None, **kw)


class RunGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        self.cache_dir = os.path.join(self.tmp.name, "cache")
        self.cases = public_cases(2)

    def good_seats(self):
        return {n: seat(n, lambda p: (GOOD, USAGE))
                for n in ("a", "b")}

    def gen_records(self):
        path = os.path.join(self.out, "generation-attempt-1.jsonl")
        with open(path, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def test_complete_run_records_and_adapter_shape(self):
        summary = run(self.cases, self.good_seats(), self.out,
                      self.cache_dir)
        self.assertEqual(sorted(summary["complete"]),
                         sorted(c["id"] for c in self.cases))
        self.assertEqual(summary["incomplete"], {})
        self.assertGreater(summary["shadow_cost_usd"], 0)
        recs = self.gen_records()
        for r in recs:
            self.assertEqual(r["status"], "valid")
            self.assertEqual(r["served_by"], r["seat"])
            self.assertTrue(r["prompt_hashes"])
            self.assertTrue(r["params_hash"])
            self.assertTrue(r["started_at"])
            self.assertGreater(r["shadow_cost_usd"], 0)
        # The frozen set is exactly what the committed scorer
        # consumes — run it, unmodified, over the attempt file.
        spec = importlib.util.spec_from_file_location(
            "score_confirmation_v2",
            os.path.join(ROOT, "bench", "scripts",
                         "score_confirmation_v2.py"))
        scorer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scorer)
        try:
            scored = scorer.score_attempt(
                os.path.join(self.out, "attempt-1.jsonl"))
        except ModuleNotFoundError as exc:  # env dependent
            if exc.name != "llm_chain":
                raise
            self.skipTest(
                "the committed scorer imports the swarm's llm_chain "
                "(not importable here); the assertions above ran")
        self.assertEqual(scored["records"], len(self.cases))
        with open(os.path.join(self.out, "attempt-1.jsonl"),
                  encoding="utf-8") as fh:
            att = [json.loads(l) for l in fh if l.strip()]
        for r in att:
            self.assertGreater(r["cost_usd"], 0)  # S4: not $0
            self.assertEqual(r["schema"],
                             "codereview.benchresult/1")

    def test_transport_retries_are_not_degraded(self):
        calls = {"n": 0}

        def flaky(prompt):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise Exception("HTTP 429 Too Many Requests")
            return GOOD, USAGE

        seats = self.good_seats()
        seats["b"] = seat("b", flaky)
        summary = run(self.cases[:1], seats, self.out,
                      self.cache_dir)
        self.assertEqual(summary["incomplete"], {})
        rec = [r for r in self.gen_records()
               if r["seat"] == "b"][0]
        self.assertEqual(rec["status"], "valid")
        self.assertEqual(rec["failure_count"], 2)
        self.assertEqual(rec["retries"], 2)
        self.assertEqual(rec["error_classes"], ["rate_limit"])

    def test_persistent_infra_marks_unscored_and_resume_heals(self):
        def dead(prompt):
            raise Exception("HTTP 503 Service Unavailable")

        seats = self.good_seats()
        seats["b"] = seat("b", dead, max_attempts=2)
        summary = run(self.cases[:1], seats, self.out,
                      self.cache_dir)
        cid = self.cases[0]["id"]
        self.assertEqual(summary["incomplete"], {cid: ["b"]})
        rec = [r for r in self.gen_records()
               if r["seat"] == "b"][0]
        self.assertEqual(rec["status"], "unscored_infra")
        # No attempt record yet: the frozen set holds complete
        # cases only.
        att_path = os.path.join(self.out, "attempt-1.jsonl")
        att_text = ""
        if os.path.exists(att_path):
            with open(att_path, encoding="utf-8") as fh:
                att_text = fh.read().strip()
        self.assertFalse(att_text)
        # Resume with the seat back: completes, records the pair
        # once, and only now writes the attempt record.
        summary = run(self.cases[:1], self.good_seats(), self.out,
                      self.cache_dir)
        self.assertEqual(summary["incomplete"], {})
        b_recs = [r for r in self.gen_records()
                  if r["seat"] == "b"]
        self.assertEqual([r["status"] for r in b_recs],
                         ["unscored_infra", "valid"])
        a_recs = [r for r in self.gen_records()
                  if r["seat"] == "a"]
        self.assertEqual(len(a_recs), 1)  # never re-recorded
        with open(att_path, encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().strip().splitlines()),
                             1)

    def test_content_failure_served_by_declared_fallback(self):
        seats = self.good_seats()
        seats["a"] = seat("a", lambda p: ("garbage", USAGE))
        summary = run(self.cases[:1], seats, self.out,
                      self.cache_dir,
                      fallbacks={"correctness": "b"})
        self.assertEqual(summary["incomplete"], {})
        recs = {(r["seat"], r["lens"]): r
                for r in self.gen_records()}
        a = recs[("a", "correctness")]
        self.assertEqual(a["status"], "valid")
        self.assertEqual(a["served_by"], "b")
        fb = recs[("b", "correctness")]
        self.assertEqual(fb["fallback_for"], "a")
        self.assertEqual(fb["status"], "valid")
        with open(os.path.join(self.out, "attempt-1.jsonl"),
                  encoding="utf-8") as fh:
            att = json.loads(fh.read().strip())
        self.assertFalse(att["degraded"])
        fb_rep = [r for r in att["reviewer_reports"]
                  if r.get("fallback_for") == "a"]
        self.assertEqual(len(fb_rep), 1)
        self.assertEqual(fb_rep[0]["provider"], "b")

    def test_content_failure_without_fallback_is_content_failed(
            self):
        seats = self.good_seats()
        seats["a"] = seat("a", lambda p: ("garbage", USAGE))
        summary = run(self.cases[:1], seats, self.out,
                      self.cache_dir)
        cid = self.cases[0]["id"]
        self.assertEqual(summary["incomplete"], {cid: ["a"]})
        rec = [r for r in self.gen_records()
               if r["seat"] == "a"][0]
        self.assertEqual(rec["status"], "content_failed")
        self.assertGreaterEqual(rec["failure_count"], 1)

    def test_empty_once_then_valid_served_by_redraw(self):
        calls = {"n": 0}

        def empty_once(prompt):
            calls["n"] += 1
            if calls["n"] == 1:
                raise empty_error()
            return GOOD, USAGE

        seats = self.good_seats()
        seats["a"] = seat("a", empty_once)
        summary = run(self.cases[:1], seats, self.out,
                      self.cache_dir)
        self.assertEqual(summary["incomplete"], {})
        rec = [r for r in self.gen_records()
               if r["seat"] == "a"][0]
        # Served by the seat itself via the product's re-draw;
        # the empty is on the record as a content failure.
        self.assertEqual(rec["status"], "valid")
        self.assertEqual(rec["served_by"], "a")
        self.assertEqual(rec["failure_count"], 1)
        self.assertEqual(rec["error_classes"], ["empty"])
        self.assertEqual(len(rec["error_detail"]), 1)
        self.assertEqual(rec["error_detail"][0]["error_class"],
                         "empty")
        self.assertEqual(rec["error_detail"][0]["outcome"],
                         "content_invalid")
        self.assertGreaterEqual(calls["n"], 2)   # the re-draw

    def test_empty_on_seat_and_fallback_is_unscored(self):
        def always_empty(prompt):
            raise empty_error()

        seats = self.good_seats()
        seats["a"] = seat("a", always_empty)
        seats["b"] = seat("b", always_empty)
        summary = run(self.cases[:1], seats, self.out,
                      self.cache_dir,
                      fallbacks={"correctness": "b"})
        cid = self.cases[0]["id"]
        # Nothing served: the case is unscored for the seat —
        # incomplete, no attempt record, and the seat's record
        # carries the content class (Addendum A item 6 counts a
        # content-failure case no fallback served toward the
        # same unscored cap as unscored-infra).
        self.assertIn(cid, summary["incomplete"])
        self.assertIn("a", summary["incomplete"][cid])
        rec = [r for r in self.gen_records()
               if r["seat"] == "a" and r["lens"] == "correctness"
               ][0]
        self.assertEqual(rec["status"], "content_failed")
        self.assertEqual(rec["error_classes"], ["empty"])
        att_path = os.path.join(self.out, "attempt-1.jsonl")
        att_text = ""
        if os.path.exists(att_path):
            with open(att_path, encoding="utf-8") as fh:
                att_text = fh.read().strip()
        self.assertFalse(att_text)

    def test_config_hash_mismatch_refuses_to_mix_panels(self):
        run(self.cases[:1], self.good_seats(), self.out,
            self.cache_dir)
        with self.assertRaises(ValueError):
            gen.run_generation(
                self.cases[:1], self.good_seats(), BINDING,
                cache_dir=self.cache_dir, out_dir=self.out,
                config_name="testcfg", config_sha256="different",
                log=lambda _m: None)


if __name__ == "__main__":
    unittest.main()
