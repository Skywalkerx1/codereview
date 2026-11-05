"""S1 (void solution §6): lenses bind to seats EXPLICITLY.

Before this fix, core assigned lenses by seat order — excluding a
seat pre-run silently remapped the lenses onto the remaining seats
(confirmation attempts 3–4: DeepSeek ended up serving operations
because NVIDIA was dropped). With an explicit seat->lens binding,
removing a seat leaves its lens UNSERVED: a configured fallback for
that lens serves it (recorded), otherwise the run is degraded and
cannot PASS — never a silent reassignment.

Backwards compatibility: with no binding anywhere, task assignment
is byte-for-byte the legacy order rule, and bench configs without
an explicit `seat_lenses` get the binding DERIVED from the provider
order at load, recorded on the loaded config.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import bench, core  # noqa: E402

PATCH = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,3 @@
 def main():
     print("hello")
+    return 0
"""


def ok_seat(name):
    def fn(prompt):
        return json.dumps({"summary": f"{name} reviewed",
                           "findings": []})
    fn.__name__ = name
    return fn


BINDING = {"openai": ["correctness"], "nvidia": ["operations"],
           "deepseek": ["correctness"]}


class ReviewerTasksBinding(unittest.TestCase):
    def test_tasks_follow_binding_not_seat_order(self):
        # Panel order deliberately differs from the v1 order: the
        # lens map must come from the binding, not positions.
        items = [("deepseek", ok_seat("deepseek")),
                 ("nvidia", ok_seat("nvidia")),
                 ("openai", ok_seat("openai"))]
        tasks = core._reviewer_tasks(items, seat_lenses=BINDING)
        self.assertEqual([(n, lens) for n, _f, lens in tasks],
                         [("deepseek", "correctness"),
                          ("nvidia", "operations"),
                          ("openai", "correctness")])

    def test_binding_accepts_single_string_form(self):
        items = [("a", ok_seat("a")), ("b", ok_seat("b"))]
        tasks = core._reviewer_tasks(
            items, seat_lenses={"a": "operations",
                                "b": "correctness"})
        self.assertEqual([(n, lens) for n, _f, lens in tasks],
                         [("a", "operations"), ("b", "correctness")])

    def test_unknown_lens_in_binding_is_a_loud_error(self):
        items = [("a", ok_seat("a"))]
        with self.assertRaises(ValueError):
            core._reviewer_tasks(items, seat_lenses={"a": ["bogus"]})

    def test_unbound_seat_serves_nothing(self):
        items = [("a", ok_seat("a")), ("extra", ok_seat("extra"))]
        tasks = core._reviewer_tasks(
            items, seat_lenses={"a": ["correctness", "operations"]})
        self.assertEqual([n for n, _f, _l in tasks], ["a", "a"])


class LegacyAssignmentUnchanged(unittest.TestCase):
    def test_no_binding_matches_legacy_cycle(self):
        for n, want in (
                (1, ["correctness", "operations"]),
                (2, ["correctness", "operations"]),
                (3, ["correctness", "operations", "correctness"]),
                (4, ["correctness", "operations",
                     "correctness", "operations"])):
            items = [(f"s{i}", ok_seat(f"s{i}")) for i in range(n)]
            tasks = core._reviewer_tasks(items)
            self.assertEqual([lens for _n, _f, lens in tasks], want)

    def test_derived_binding_reproduces_legacy_tasks(self):
        for n in (1, 2, 3, 4):
            names = [f"s{i}" for i in range(n)]
            items = [(name, ok_seat(name)) for name in names]
            derived = core.derive_seat_lenses(names)
            self.assertEqual(
                [(nm, lens) for nm, _f, lens in
                 core._reviewer_tasks(items, seat_lenses=derived)],
                [(nm, lens) for nm, _f, lens in
                 core._reviewer_tasks(items)])


class RemovedSeatProbe(unittest.TestCase):
    """The S1 probe from the solution: build the panel with the
    second seat removed and assert the lens map + gate behaviour."""

    def panel(self, *names):
        return {n: ok_seat(n) for n in names}

    def test_removed_seat_leaves_lens_unserved(self):
        # nvidia (operations) removed, as in attempts 3–4.
        report = core.run_review(
            PATCH, self.panel("openai", "deepseek"),
            seat_lenses=BINDING)
        served = {(r["provider"], r["lens"])
                  for r in report["reviewer_reports"]}
        # correctness still served by its bound seats; operations
        # by NOBODY — deepseek must not be remapped onto it.
        self.assertEqual(served, {("openai", "correctness"),
                                  ("deepseek", "correctness")})
        self.assertTrue(report["degraded"])
        self.assertIn("lens unserved: operations",
                      report["degraded_causes"])
        self.assertEqual(report["gate"], "inconclusive")
        self.assertEqual(report["seat_lenses"]["unserved_lenses"],
                         ["operations"])
        self.assertEqual(report["seat_lenses"]["binding"], BINDING)

    def test_full_panel_with_binding_is_clean(self):
        report = core.run_review(
            PATCH, self.panel("openai", "nvidia", "deepseek"),
            seat_lenses=BINDING)
        self.assertEqual(report["gate"], "pass")
        self.assertFalse(report["degraded"])
        self.assertEqual(report["seat_lenses"]["unserved_lenses"],
                         [])

    def test_fallback_serves_the_unserved_lens_on_the_record(self):
        relief = ok_seat("relief")
        report = core.run_review(
            PATCH, self.panel("openai", "deepseek"),
            seat_lenses=BINDING,
            fallbacks={"operations": ("relief", relief)})
        ops = [r for r in report["reviewer_reports"]
               if r["lens"] == "operations"]
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["provider"], "relief")
        self.assertEqual(ops[0]["status"], "ok")
        # The substitution names the seat whose absence it covers.
        self.assertEqual(ops[0]["fallback_for"], "nvidia")
        self.assertFalse(report["degraded"])
        self.assertEqual(report["gate"], "pass")


class BenchConfigBinding(unittest.TestCase):
    def write_cfg(self, payload):
        fh = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False)
        json.dump(payload, fh)
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def test_legacy_config_gets_derived_binding_recorded(self):
        path = self.write_cfg(
            {"name": "legacy", "providers": ["a", "b", "c"]})
        cfg = bench.load_config(path)
        self.assertEqual(cfg["seat_lenses"],
                         {"a": ["correctness"], "b": ["operations"],
                          "c": ["correctness"]})
        self.assertEqual(cfg["seat_lenses_source"], "derived")

    def test_explicit_binding_is_kept_and_marked(self):
        path = self.write_cfg(
            {"name": "explicit", "providers": ["a", "b"],
             "seat_lenses": {"a": "operations", "b": "correctness"}})
        cfg = bench.load_config(path)
        self.assertEqual(cfg["seat_lenses"],
                         {"a": ["operations"], "b": ["correctness"]})
        self.assertEqual(cfg["seat_lenses_source"], "explicit")

    def test_derived_binding_does_not_change_config_identity(self):
        # The v1 panel config's sha keys every stored bench record;
        # deriving a binding from the provider order (already in
        # the identity) must not move it.
        path = self.write_cfg(
            {"name": "legacy", "providers": ["a", "b"]})
        cfg = bench.load_config(path)
        identity = {"name": "legacy", "providers": ["a", "b"],
                    "seat_meta": {}, "allow_major": False,
                    "strict": False, "cost_per_call_usd": 0}
        import hashlib
        want = hashlib.sha256(json.dumps(
            identity, sort_keys=True).encode("utf-8")).hexdigest()
        self.assertEqual(bench._config_sha(cfg), want)

    def test_explicit_binding_does_change_config_identity(self):
        base = {"name": "x", "providers": ["a", "b"]}
        p1 = self.write_cfg(base)
        p2 = self.write_cfg(
            dict(base, seat_lenses={"a": "operations",
                                    "b": "correctness"}))
        self.assertNotEqual(bench._config_sha(bench.load_config(p1)),
                            bench._config_sha(bench.load_config(p2)))


if __name__ == "__main__":
    unittest.main()
