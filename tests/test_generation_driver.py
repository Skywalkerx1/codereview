"""Driver-level guards for the generation phase (verification
round on void-sol-track2: one major + four minors).

  * the registered-set guard refuses EVERY non-public split by
    name — holdout, the expanded-clean stratum, and any split a
    future loader learns — before any seat call, unless
    CODEREVIEW_REGISTERED_RUN=1 (the blocking major);
  * fallbacks are validated at driver entry: panel membership
    (minor 1) and, under an explicit seat_lenses binding, no
    fallback may reassign a lens the binding gives to a
    different seat (minors 3+4);
  * the effective fallbacks join the run's identity in the
    generation manifest, and a resume with different fallbacks
    is a hard error (minor 2);
  * the two-level budget model: a 600 s per-job wall-clock cap
    (GenerationSeat) nested inside an 1,800 s per-case budget
    enforced via per-seat case deadlines.
"""

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import generation as gen  # noqa: E402
from codereview import bench as bench_mod  # noqa: E402


def _load_driver():
    spec = importlib.util.spec_from_file_location(
        "run_generation_v2",
        os.path.join(ROOT, "bench", "scripts",
                     "run_generation_v2.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


driver = _load_driver()

GOOD = json.dumps({"summary": "fine", "findings": []})
USAGE = {"prompt_tokens": 1000, "completion_tokens": 500}
BINDING = {"a": ["correctness"], "b": ["operations"]}


def seat(name, transport, model="deepseek-chat", **kw):
    kw.setdefault("sleep", lambda _s: None)
    kw.setdefault("rng", lambda: 0.5)
    return gen.GenerationSeat(name, model, transport, **kw)


def public_case():
    corpus = bench_mod.load_corpus(os.path.join(ROOT, "bench",
                                                "corpus"))
    pub = [c for c in corpus if c["split"] == "public"]
    pub.sort(key=lambda c: len(c["diff"]))
    return pub[0]


def run(cases, seats, out, cache_dir, **kw):
    kw.setdefault("gate_profile", "balanced")
    return gen.run_generation(
        cases, seats, BINDING, cache_dir=cache_dir, out_dir=out,
        config_name="testcfg", config_sha256="sha-" + cache_dir,
        log=lambda _m: None, **kw)


class RegisteredGuardTests(unittest.TestCase):
    def test_every_non_public_split_is_refused(self):
        for split in ("holdout", "expanded-clean", "sealed",
                      "future-registered-split"):
            msg = driver.registered_guard(split, registered=False)
            self.assertIsNotNone(msg, split)
            self.assertIn(split, msg)
            self.assertIn("CODEREVIEW_REGISTERED_RUN", msg)

    def test_public_open_and_registered_run_opens(self):
        self.assertIsNone(
            driver.registered_guard("public", registered=False))
        self.assertIsNone(
            driver.registered_guard("holdout", registered=True))
        self.assertIsNone(driver.registered_guard(
            "expanded-clean", registered=True))

    def test_main_refuses_before_any_seat_call(self):
        # The refusal happens before config load and preflight:
        # main returns 2 with the split named, no network touched.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CODEREVIEW_REGISTERED_RUN", None)
            for split in ("expanded-clean", "holdout"):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = driver.main(
                        ["run_generation_v2.py",
                         "--split", split])
                self.assertEqual(rc, 2, split)
                self.assertIn(split, err.getvalue())


class FallbackValidationTests(unittest.TestCase):
    PANEL = ["openai", "deepseek", "nvidia"]
    EXPLICIT = {"openai": ["correctness"],
                "deepseek": ["correctness"],
                "nvidia": ["operations"]}

    def test_unknown_seat_fails_loudly(self):
        with self.assertRaises(ValueError):
            driver.validate_fallbacks(
                {"correctness": "gpt-9"}, self.PANEL,
                self.EXPLICIT, explicit=True)
        with self.assertRaises(ValueError):
            driver.validate_fallbacks(
                {"correctness": "gpt-9"}, self.PANEL,
                self.EXPLICIT, explicit=False)

    def test_unknown_lens_fails_loudly(self):
        with self.assertRaises(ValueError):
            driver.validate_fallbacks(
                {"security": "openai"}, self.PANEL,
                self.EXPLICIT, explicit=True)

    def test_explicit_binding_conflict_raises(self):
        # operations is bound to nvidia alone; a fallback naming
        # deepseek would reassign the lens (the S1 remap).
        with self.assertRaises(ValueError) as cm:
            driver.validate_fallbacks(
                {"operations": "deepseek"}, self.PANEL,
                self.EXPLICIT, explicit=True)
        self.assertIn("operations", str(cm.exception))
        self.assertIn("deepseek", str(cm.exception))

    def test_explicit_binding_mutual_fallbacks_ok(self):
        # Addendum A item 5: the two correctness seats are each
        # other's fallback — both are bound to the lens.
        self.assertIsNone(driver.validate_fallbacks(
            {"correctness": "deepseek"}, self.PANEL,
            self.EXPLICIT, explicit=True))
        self.assertIsNone(driver.validate_fallbacks(
            {"correctness": "openai"}, self.PANEL,
            self.EXPLICIT, explicit=True))

    def test_fallback_for_unbound_lens_ok(self):
        binding = {"openai": ["correctness"],
                   "deepseek": ["correctness"]}
        self.assertIsNone(driver.validate_fallbacks(
            {"operations": "nvidia"}, self.PANEL, binding,
            explicit=True))

    def test_derived_binding_legacy_fallbacks_ok(self):
        derived = {"openai": ["correctness"],
                   "deepseek": ["operations"],
                   "nvidia": ["correctness"]}
        fb = driver.default_fallbacks(self.PANEL, derived)
        self.assertIsNone(driver.validate_fallbacks(
            fb, self.PANEL, derived, explicit=False))

    def test_default_fallbacks_stay_in_panel(self):
        for binding in (self.EXPLICIT,
                        {"solo": ["correctness", "operations"]}):
            panel = list(binding)
            fb = driver.default_fallbacks(panel, binding)
            for seat_name in fb.values():
                self.assertIn(seat_name, panel)


class RunGenerationFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        self.cache_dir = os.path.join(self.tmp.name, "cache")
        self.case = public_case()

    def good_seats(self):
        return {n: seat(n, lambda p: (GOOD, USAGE))
                for n in ("a", "b")}

    def manifest(self):
        path = os.path.join(
            self.out, "generation-manifest-attempt-1.json")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_unknown_fallback_seat_raises(self):
        with self.assertRaises(ValueError):
            run([self.case], self.good_seats(), self.out,
                self.cache_dir, fallbacks={"correctness": "nope"})

    def test_unknown_fallback_lens_raises(self):
        with self.assertRaises(ValueError):
            run([self.case], self.good_seats(), self.out,
                self.cache_dir, fallbacks={"security": "a"})

    def test_fallbacks_attested_in_run_identity(self):
        run([self.case], self.good_seats(), self.out,
            self.cache_dir, fallbacks={"correctness": "b"})
        man = self.manifest()
        self.assertEqual(man["fallbacks"], {"correctness": "b"})
        self.assertTrue(man["run_identity_sha256"])
        self.assertEqual(
            man["summary"]["budgets"]["per_case_wall_clock_s"],
            1800.0)
        # Resume with the same fallbacks: fine.
        run([self.case], self.good_seats(), self.out,
            self.cache_dir, fallbacks={"correctness": "b"})
        # Resume with different fallbacks: hard error — the
        # records must attest what actually served.
        with self.assertRaises(ValueError):
            run([self.case], self.good_seats(), self.out,
                self.cache_dir, fallbacks={"operations": "a"})


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class CaseBudgetTests(unittest.TestCase):
    def test_budget_constants_are_one_coherent_model(self):
        self.assertEqual(gen.JOB_WALL_CLOCK_BUDGET_S, 600.0)
        self.assertEqual(gen.CASE_WALL_CLOCK_BUDGET_S, 1800.0)
        s = seat("a", lambda p: (GOOD, USAGE))
        self.assertEqual(s.wall_clock_budget_s, 600.0)

    def test_case_deadline_exhausts_without_a_transport_call(self):
        clock = FakeClock()
        clock.t = 100.0
        calls = []

        def transport(prompt):
            calls.append(prompt)
            return GOOD, USAGE

        s = seat("a", transport, clock=clock)
        s.case_deadline = 50.0  # already past on the seat's clock
        with self.assertRaises(gen.GenerationExhausted):
            s("prompt")
        self.assertEqual(calls, [])
        # Re-entry under the same blown deadline still fails
        # fast — the product's retry layer cannot multiply
        # calls against it.
        with self.assertRaises(gen.GenerationExhausted):
            s("prompt")
        self.assertEqual(calls, [])
        # But the deadline exhaustion is NOT latched per key:
        # a later case stamps a fresh deadline and the same
        # prompt serves normally.
        s.case_deadline = 500.0
        self.assertEqual(s("prompt"), GOOD)
        self.assertEqual(len(calls), 1)

    def test_run_generation_case_budget_marks_case_unscored(self):
        clock = FakeClock()

        def slow(prompt):
            clock.t += 10000.0  # one call eats the case budget
            return GOOD, USAGE

        seats = {n: seat(n, slow, clock=clock) for n in ("a", "b")}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = os.path.join(tmp.name, "out")
        cache_dir = os.path.join(tmp.name, "cache")
        case = public_case()
        summary = run([case], seats, out, cache_dir,
                      case_budget_s=1800.0)
        # One seat served; the other hit the per-case deadline
        # and the case is incomplete — no exception escapes.
        self.assertEqual(list(summary["incomplete"]), [case["id"]])
        self.assertEqual(len(summary["incomplete"][case["id"]]),
                         1)
        path = os.path.join(out, "generation-attempt-1.jsonl")
        with open(path, encoding="utf-8") as fh:
            recs = [json.loads(l) for l in fh if l.strip()]
        statuses = sorted(r["status"] for r in recs)
        self.assertEqual(statuses, ["unscored_infra", "valid"])


if __name__ == "__main__":
    unittest.main()
