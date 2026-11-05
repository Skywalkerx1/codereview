"""Tests for the ratified packet fixes (owner ratification,
2026-11-04 evening):

  7ea4e96603e9 / 212878ab6bba — the gate line states the degraded
  CAUSE and never claims a reviewer failed when none did.
  78ddf4d5ea27 — role_models credits the model that actually
  serves, never a discarded override.
  ec925437d0e3 / 20e4194e5ed9 — the records scan relativises
  local paths and masks account identifiers in committed output.
  3f50bf6b3349 — _prompt_slice respects its cap: the truncation
  marker lives INSIDE the budget.
"""

import hashlib
import importlib.util
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, core, providers  # noqa: E402

CLEAN = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,1 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""


def pass_provider(prompt):
    return json.dumps({"verdict": "pass", "summary": "looks fine",
                       "findings": []})


def failing_provider(prompt):
    raise TimeoutError("provider timed out")


class GateLineCauseTests(unittest.TestCase):
    """Fix 1 — packets #5/#6 (7ea4e96603e9, 212878ab6bba)."""

    def test_synthetic_coverage_degraded_claims_no_failure(self):
        # The PT1 synthetic verbatim: all reviewers ok, degraded
        # by incomplete coverage, built through core._gate.
        gate, reasons = core._gate([], degraded=True, incomplete=True)
        self.assertEqual(gate, "pass")
        joined = "; ".join(reasons)
        self.assertNotIn("at least one reviewer failed", joined)
        self.assertNotIn("reviewer failed", joined)
        self.assertIn("coverage incomplete", joined)

    def test_gate_with_coverage_cause_states_it(self):
        gate, reasons = core._gate(
            [], degraded=True, degraded_causes=["coverage incomplete"])
        self.assertEqual(gate, "pass")
        joined = "; ".join(reasons)
        self.assertIn("coverage incomplete", joined)
        self.assertNotIn("reviewer failed", joined)

    def test_gate_with_reviewer_failure_still_claims_it(self):
        # The normal degraded-with-failure case keeps the exact,
        # now TRUE, claim — and strict mode still turns a
        # non-blocked degraded round inconclusive.
        gate, reasons = core._gate(
            [], degraded=True, degraded_causes=["reviewer failure"])
        self.assertEqual(gate, "pass")
        self.assertIn("at least one reviewer failed (degraded review)",
                      reasons)
        gate, reasons = core._gate(
            [], degraded=True, strict=True,
            degraded_causes=["reviewer failure"])
        self.assertEqual(gate, "inconclusive")
        self.assertIn("at least one reviewer failed (degraded review)",
                      reasons)

    def test_run_review_failure_records_cause_and_renders_it(self):
        report = core.run_review(
            CLEAN, {"a": failing_provider, "b": pass_provider})
        self.assertTrue(report["degraded"])
        self.assertIn("reviewer failure", report["degraded_causes"])
        self.assertIn("at least one reviewer failed",
                      "; ".join(report["gate_reasons"]))
        gate_line = core.render_markdown(report).splitlines()[2]
        self.assertIn("DEGRADED: reviewer failure", gate_line)
        self.assertIn("1 of 2 reviewers succeeded", gate_line)

    def test_rendered_gate_line_for_coverage_degraded_run(self):
        # A stored-shape record for a run degraded by coverage
        # with every reviewer ok: the rendered gate line states
        # the cause next to the (full) success count.
        _gate, reasons = core._gate(
            [], degraded=True, incomplete=True,
            degraded_causes=["coverage incomplete"])
        report = {
            "mode": "review", "gate": "pass",
            "gate_reasons": reasons,
            "created_at": "2026-11-04T00:00:00+00:00",
            "patch_sha256": "0" * 64,
            "degraded": True,
            "degraded_causes": ["coverage incomplete"],
            "reviewer_reports": [{"status": "ok"}, {"status": "ok"}],
            "findings": [], "test_results": [],
        }
        gate_line = core.render_markdown(report).splitlines()[2]
        self.assertIn("DEGRADED: coverage incomplete", gate_line)
        self.assertIn("(2 of 2 reviewers succeeded)", gate_line)
        self.assertNotIn("at least one reviewer failed", gate_line)


class RoleModelFidelityTests(unittest.TestCase):
    """Fix 2 — packet #16 (78ddf4d5ea27): the packet's own repro.
    A panel built from ['openai', 'openai'] pools two accounts
    under one seat that sends the registry default on both; a
    --role override naming a different model used to be built,
    discarded on the name collision, and recorded anyway."""

    ENV = {"OPENAI_API_KEY": "k-one", "OPENAI_API_KEY_2": "k-two"}

    def _served_models(self, seat_fn):
        calls = []

        def fake(url, headers, payload, timeout=240):
            calls.append(payload)
            return {"choices": [{"message": {"content": "ok"}}]}

        with mock.patch.object(providers, "_post_json", fake):
            accounts = getattr(seat_fn, "accounts", None)
            if accounts:
                for _label, fn in accounts:
                    fn("probe")
            else:
                seat_fn("probe")
        return [c["model"] for c in calls]

    def test_pooled_seat_records_served_model_not_override(self):
        with mock.patch.dict(os.environ, self.ENV):
            panel = providers.build_providers(["openai", "openai"])
            _lens, _sr, role_models, _tl = \
                cli._apply_role_assignments(
                    panel, ["correctness=openai:gpt-9.9-probe"])
            served = self._served_models(panel["openai"])
        default = providers.describe_spec("openai")["model"]
        self.assertEqual(set(served), {default})
        rec = role_models["correctness"]
        # The record credits the model that actually serves, and
        # keeps the requested override visible as requested.
        self.assertEqual(rec["model"], default)
        self.assertIn(rec["model"], served)
        self.assertEqual(rec["requested_model"], "gpt-9.9-probe")
        self.assertNotIn("gpt-9.9-probe", served)

    def test_matching_model_records_without_requested_field(self):
        with mock.patch.dict(os.environ, self.ENV):
            panel = providers.build_providers(["openai"])
            _l, _s, role_models, _t = cli._apply_role_assignments(
                panel, ["correctness=openai"])
        rec = role_models["correctness"]
        self.assertEqual(rec["model"],
                         providers.describe_spec("openai")["model"])
        self.assertNotIn("requested_model", rec)

    def test_mixed_model_pool_refuses_role_credit(self):
        with mock.patch.dict(os.environ, self.ENV):
            panel = providers.build_providers(
                ["openai:gpt-a-model", "openai:gpt-b-model"])
            with self.assertRaises(providers.ProviderError):
                cli._apply_role_assignments(
                    panel, ["correctness=openai:gpt-a-model"])

    def test_new_seat_role_records_its_own_model(self):
        # The unchanged path: the seat is not in the panel yet,
        # so it is built, added, and its own model recorded.
        with mock.patch.dict(os.environ, self.ENV):
            panel = {}
            _l, _s, role_models, _t = cli._apply_role_assignments(
                panel, ["correctness=openai:gpt-9.9-probe"])
        self.assertIn("openai", panel)
        rec = role_models["correctness"]
        self.assertEqual(rec["model"], "gpt-9.9-probe")
        self.assertNotIn("requested_model", rec)


def _load_records_scan():
    path = os.path.join(os.path.dirname(__file__), "..",
                        "probes", "records_scan.py")
    spec = importlib.util.spec_from_file_location(
        "records_scan", os.path.abspath(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RecordsScanScrubTests(unittest.TestCase):
    """Fix 3 — gap packets G14/G13 (ec925437d0e3, 20e4194e5ed9):
    the scan's committed output is scrubbed by mask() itself, so
    regenerated output can never republish what the profile
    excludes."""

    @classmethod
    def setUpClass(cls):
        cls.scan = _load_records_scan()

    def test_repo_internal_path_becomes_repo_relative(self):
        inside = os.path.join(self.scan.REPO,
                              "tests", "test_v093_fixes.py") + ":373:"
        self.assertEqual(self.scan.mask("local_path", inside),
                         "tests/test_v093_fixes.py:373:")

    def test_home_path_collapses_to_tilde_form(self):
        self.assertEqual(
            self.scan.mask("local_path",
                           "/home/operator/workspace/x/y.py"),
            "~/workspace/x/y.py")
        self.assertEqual(
            self.scan.mask("local_path", "/root/secrets/f.txt"),
            "~root/secrets/f.txt")

    def test_no_username_survives_masking(self):
        samples = [
            "/home/hatch/workspace/codereview/tests/t.py:352:",
            "/home/someone/elsewhere/f.py",
            "/root/f.py",
        ]
        for s in samples:
            out = self.scan.mask("local_path", s)
            self.assertNotIn("/home/", out)
            self.assertNotIn("hatch", out)

    def test_account_id_masked_to_domain(self):
        self.assertEqual(self.scan.mask("account_id",
                                        "admin@example.com"),
                         "a***@example.com")

    def test_key_shaped_mask_unchanged(self):
        # Assembled from fragments: a key-SHAPED literal must
        # never sit in a test file (the fixture-hygiene guard —
        # the runtime value is identical).
        fake = "sk-" + "abcdefgh" + "ijklmnop"
        out = self.scan.mask("key_shaped", fake)
        self.assertTrue(out.startswith("sk-a"))
        self.assertIn("chars)", out)

    def test_committed_scan_file_is_scrubbed(self):
        # The artifact the finding cited: regenerated by the
        # guarded scan, it must carry neither the operator's
        # absolute home paths nor a verbatim account identifier.
        path = os.path.join(os.path.dirname(__file__), "..",
                            "probes", "results",
                            "records-scan-a3a2d492b51a.txt")
        with open(os.path.abspath(path), encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("/home/", text)
        self.assertNotIn("admin@example.com", text)
        self.assertIn("a***@example.com", text)


class PromptSliceCapTests(unittest.TestCase):
    """Fix 4 — gap packet G15 (3f50bf6b3349). The packet's own
    measurement table, as assertions: every over-cap input used
    to return cap + up to ~98 chars."""

    CASES = [  # (text, cap) — the packet's measured rows + edges
        ("x" * 101, 100),
        ("lorem ipsum dolor sit amet " * 65, 300),
        ("x" * 5000, 300),
        ("y" * 2500, 50),
        ("z" * 5, 1),
        ("w" * 2000, 1000),
        ("v" * 1001, 1000),
    ]

    def test_returned_string_never_exceeds_cap(self):
        for text, cap in self.CASES:
            out = core._prompt_slice(text, cap)
            self.assertLessEqual(len(out), cap, (len(text), cap))

    def test_marker_complete_and_honest_when_it_fits(self):
        for text, cap in self.CASES:
            if cap < 100:
                continue  # marker itself cannot fit; see below
            out = core._prompt_slice(text, cap)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            self.assertTrue(out.endswith(
                f"…[truncated, {len(text)} chars, "
                f"sha256:{digest}]"), (len(text), cap))
            visible = out.split(" …[truncated")[0]
            self.assertTrue(text.startswith(visible))

    def test_boundary_cut_stays_at_a_word_boundary(self):
        text = " ".join(["w%08d" % i for i in range(400)])
        out = core._prompt_slice(text, 2000)
        visible = out.split(" …[truncated")[0]
        self.assertLessEqual(len(out), 2000)
        self.assertEqual(text[len(visible)], " ")

    def test_exactly_at_cap_is_unchanged(self):
        text = "q" * 300
        self.assertEqual(core._prompt_slice(text, 300), text)
        over = core._prompt_slice(text + "q", 300)
        self.assertLessEqual(len(over), 300)
        self.assertIn("…[truncated, 301 chars", over)

    def test_cap_smaller_than_marker_still_signals(self):
        out = core._prompt_slice("z" * 5, 1)
        self.assertEqual(len(out), 1)
        self.assertEqual(core._prompt_slice("z" * 5, 0), "")


if __name__ == "__main__":
    unittest.main()
