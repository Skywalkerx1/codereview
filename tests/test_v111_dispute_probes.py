"""Suite versions of the PT-1 dispute probes (open-refutations
solution §§2–3, 2026-11-04) for the 17 open disputes. The
full-text probe scripts live in probes/; these tests pin the
guard properties the probes established so a regression
re-opens the question loudly instead of silently.

  7baa0147d8d4  regeneration: the verify renderer agrees with
                the stored JSON's cleared count.
  6219e04d4c00  oversize: an unplaceable section is flagged
                incomplete and degrades the run; placeable
                sections never exceed the budget.
  35dbb7d20941  lens mapping: a verification fallback serves
                only the lens its failed seat was assigned.
  3d9645200bc5  unknown family fails closed (Tech Lead +
                record-verify two_families).
  e1e22d48db4d  stub payloads carry 'model' (custom spec +
                preset override).
  78ddf4d5ea27  seat names/pool sizes are permutation-stable.
  e7fc93e0bb77  parse_role_assignments table: every malformed
                input raises ValueError (this is the parse
                half; the saved-config half is in
                test_v111_hardening.py with the fix).
"""

import itertools
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core, providers, registry  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), "..")
OK_JSON = json.dumps({"verdict": "pass", "summary": "ok",
                      "findings": []})
EMPTY_VERIFY = json.dumps({"resolutions": [], "new_findings": []})


def ok(prompt):
    return OK_JSON


class RegenerationAgreementTests(unittest.TestCase):
    def test_verify_renderer_agrees_with_stored_json(self):
        path = os.path.join(
            REPO, "review-v15-verify1",
            "codereview-20261104-225424.json")
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        md = core.render_markdown(rec)
        self.assertIn(
            f"Cleared prior blockers: {len(rec['cleared'])}", md)
        self.assertEqual(len(rec["cleared"]), 4)

    def test_not_degraded_check_correctly_fails_degraded(self):
        # The 212878ab6bba pair: verify_record FAILING a degraded
        # record is CORRECT — the run was degraded by coverage.
        rec = {"mode": "review", "gate": "pass", "degraded": True,
               "reviewer_reports": [], "findings": []}
        checks = core.verify_record(rec)
        nd = [c for c in checks["checks"]
              if c["name"] == "not_degraded"]
        self.assertFalse(nd[0]["ok"])


class OversizeGuardTests(unittest.TestCase):
    HEAD = ("diff --git a/some/deeply/nested/module/path/app.py "
            "b/some/deeply/nested/module/path/app.py\n"
            "--- a/some/deeply/nested/module/path/app.py\n"
            "+++ b/some/deeply/nested/module/path/app.py\n")
    SECTION = HEAD + "@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"

    def test_unplaceable_section_flagged_and_degrades(self):
        _pieces, unplaceable = core._split_section(
            self.SECTION, 40)
        self.assertTrue(unplaceable)
        _b, _f, incomplete = core._batch_sections_detailed(
            [("app.py", self.SECTION)], 40)
        self.assertTrue(incomplete)
        report = core.run_review(
            self.SECTION, {"a": ok, "b": ok}, max_patch_chars=40,
            sleep=lambda *a: None)
        self.assertTrue(report["truncated"])
        self.assertFalse(report["coverage"]["complete"])
        self.assertTrue(report["degraded"])
        self.assertTrue(any("could not be placed within the "
                            "batch budget" in r
                            for r in report["gate_reasons"]))

    def test_placeable_batches_within_budget(self):
        head = "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n"
        section = head + "@@ -1,3 +1,3 @@\n" + "".join(
            f"+line {i:03d} " + "y" * 60 + "\n" for i in range(30))
        batches, _f, incomplete = core._batch_sections_detailed(
            [("b.py", section)], 400)
        self.assertFalse(incomplete)
        self.assertTrue(all(len(b) <= 400 for b in batches))


class LensMappingTests(unittest.TestCase):
    def _run(self, seat_names, failing):
        def fail(prompt):
            raise RuntimeError("quota exhausted")

        def okv(prompt):
            return EMPTY_VERIFY
        providers_map = {n: (fail if n == failing else okv)
                         for n in seat_names}
        lenses = {}
        for name, _fn, lens in core._reviewer_tasks(
                list(providers_map.items())):
            lenses.setdefault(name, []).append(lens)
        report = core.run_verification(
            "diff --git a/app.py b/app.py\n+x = 1\n", providers_map,
            {"findings": [], "gate": "blocked", "mode": "review"},
            "probe",
            fallbacks={"correctness": ("fb-correctness", okv),
                       "operations": ("fb-operations", okv)},
            sleep=lambda *a: None)
        recs = [r for r in report["reviewer_reports"]
                if r["provider"].startswith("fb-")]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["provider"],
                         "fb-" + lenses[failing][0])
        self.assertEqual(recs[0]["fallback_for"], failing)

    def test_all_orderings_and_failures(self):
        for ordering in itertools.permutations(["seatA", "seatB"]):
            for failing in ordering:
                self._run(list(ordering), failing)
        self._run(["onlySeat"], "onlySeat")
        self._run(["s0", "s1", "s2"], "s2")
        self._run(["s0", "s1", "s2"], "s1")


class UnknownFamilyFailClosedTests(unittest.TestCase):
    def test_custom_seats_same_vendor_are_unknown(self):
        env = {"PT1_KEY_A": "k", "PT1_KEY_B": "k"}
        specs = ["vendor-a|openai-compatible|"
                 "http://127.0.0.1:9/v1|m|PT1_KEY_A",
                 "vendor-b|openai-compatible|"
                 "http://127.0.0.1:9/v1|m|PT1_KEY_B"]
        with mock.patch.dict(os.environ, env):
            panel = providers.build_providers(specs)
        self.assertEqual(
            {getattr(fn, "_codereview_family", None)
             for fn in panel.values()}, {"unknown"})

    def test_unknown_never_tech_lead(self):
        fns = {"a": ok, "b": ok, "known": ok}
        fam = {"a": "unknown", "b": "unknown", "known": "famK"}
        name, _f, _fam, subst, _u = core._select_tech_lead(
            fns, set(fns), fam, "a", "famA", "famB")
        self.assertEqual(name, "known")
        self.assertIn("unknown", subst["reason"])
        name2, _f, _fam, _s, unavail = core._select_tech_lead(
            {"a": ok, "b": ok}, {"a", "b"},
            {"a": "unknown", "b": "unknown"}, None,
            "unknown", "unknown")
        self.assertIsNone(name2)
        self.assertTrue(unavail)

    def test_two_families_check_rejects_all_unknown(self):
        record = {
            "mode": "review", "gate": "pass", "degraded": False,
            "test_results": [{"command": "true", "ok": True}],
            "reviewer_reports": [
                {"provider": "a", "lens": "correctness",
                 "status": "ok", "family": "unknown"},
                {"provider": "b", "lens": "operations",
                 "status": "ok", "family": "unknown"}],
            "coverage": {"complete": True, "files": {}},
            "findings": []}
        checks = core.verify_record(record)
        tf = [c for c in checks["checks"]
              if c["name"] == "two_families"]
        self.assertFalse(tf[0]["ok"])


class StubPayloadTests(unittest.TestCase):
    def _capture(self, spec, env):
        calls = []

        def fake(url, headers, payload, timeout=240):
            calls.append(payload)
            return {"choices": [{"message": {"content": "t"}}]}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(providers, "_post_json", fake):
            _n, fn, _l = providers.build_provider(spec)
            fn("hi")
        return calls[0]

    def test_custom_spec_payload_carries_model(self):
        payload = self._capture(
            "openai-compatible:https://llm.example.com/v1"
            "|my-model|CUSTOM_KEY_ENV",
            {"CUSTOM_KEY_ENV": "k"})
        self.assertEqual(payload["model"], "my-model")

    def test_override_payload_carries_override_model(self):
        payload = self._capture("deepseek:deepseek-reasoner",
                                {"DEEPSEEK_API_KEY": "k"})
        self.assertEqual(payload["model"], "deepseek-reasoner")


class SeatNameDeterminismTests(unittest.TestCase):
    def test_permutation_invariant_names_and_pool_sizes(self):
        env = {"OPENAI_API_KEY": "k1", "OPENAI_API_KEY_2": "k2",
               "GEMINI_API_KEY": "k3"}
        shapes = set()
        with mock.patch.dict(os.environ, env):
            for ordering in itertools.permutations(
                    ["openai", "openai", "gemini"]):
                panel = providers.build_providers(list(ordering))
                shapes.add(tuple(sorted(
                    (n, len(getattr(fn, "accounts", [fn])))
                    for n, fn in panel.items())))
        self.assertEqual(len(shapes), 1)


class RoleParserTableTests(unittest.TestCase):
    def test_valid_forms(self):
        self.assertEqual(
            registry.parse_role_assignments(
                ["correctness=openai", " Tech-Lead = gemini "]),
            {"correctness": "openai", "tech-lead": "gemini"})
        self.assertEqual(registry.parse_role_assignments([]), {})
        self.assertEqual(registry.parse_role_assignments(None), {})

    def test_every_malformed_form_raises_value_error(self):
        for bad in (["correctness="], ["correctness=  "], ["=x"],
                    [""], ["correctness"], ["bogus-role=openai"],
                    ["correctness=openai", "correctness=gemini"],
                    ["CORRECTNESS=openai", "correctness=gemini"]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                registry.parse_role_assignments(bad)


if __name__ == "__main__":
    unittest.main()
