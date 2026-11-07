"""Epic E2 + E4 — tiered panels and the escalation rule.

E2: E1's risk band sizes the panel — low runs a designated
pre-screen seat (or seats) only, medium a reduced panel,
high the full panel with evidence required. E4: a reduced
panel that returns a blocking finding, a reviewer failure,
or an unserved lens escalates to the full panel within the
same run; escalation never removes a stage-1 finding, and
the verdict is computed on the full evidence by the normal
rules.

The fixtures below pin: the [risk] tiering schema (B1
style, including the tiering-requires-enabled rejection),
the seat-plan and trigger-evaluation units, the run_review
integration with synthetic reviewer outputs (E4's stated
acceptance), the S1 binding semantics at reduced tiers,
the high tier's evidence rule, the fixture-level cost drop
(E2's acceptance, at mechanism level — the public-corpus
demonstration is reported with the track, not asserted
here), and the unconfigured equivalence: tiering off, a
run is exactly what it was before E2.
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from codereview import core, policy, tiering  # noqa: E402


def _section(path, added=(), removed=()):
    body = "".join(f"+{line}\n" for line in added)
    body += "".join(f"-{line}\n" for line in removed)
    return (f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n"
            f"@@ -1,{len(removed)} +1,{len(added)} @@\n" + body)


def _patch(*sections):
    return "".join(_section(p, a, r) for p, a, r in sections)


# Score 0 under the default thresholds: band "low".
LOW_PATCH = _patch(("app/util.py",
                    ("def sub(a, b):", "    return a - b",
                     "def add(a, b):", "    return a + b"), ()))
# auth path (25) + dependency manifest (15) = 40: "medium".
MEDIUM_PATCH = _patch(
    ("src/auth/login.py", ("def view():", "    pass"), ()),
    ("requirements.txt", ("requests==2.32",), ()))
# Pattern classes cap at 60 (E1), so the high fixture adds a
# dependency manifest: 60 (capped) + 15 = 75: "high".
HIGH_PATCH = _patch(
    ("src/auth/login.py", ("def view():", "    pass"), ()),
    ("app/billing/charge.py", ("def charge():", "    pass"), ()),
    ("app/secrets.py", ("VALUE = 1",), ()),
    ("requirements.txt", ("requests==2.32",), ()))

PASS = json.dumps({"verdict": "pass", "summary": "looks fine",
                   "findings": []})


def _finding(sev, title, quote, file="app/util.py"):
    return {"severity": sev, "category": "correctness",
            "file": file, "line": 2, "title": title,
            "evidence": quote, "evidence_quote": quote,
            "recommendation": "fix it", "confidence": 0.9}


def _seat(calls, name, response):
    """A counting stub seat. `response` is a JSON string or
    an exception instance to raise on every call."""
    def fn(prompt):
        calls[name] = calls.get(name, 0) + 1
        if isinstance(response, Exception):
            raise response
        return response
    return fn


def _panel(calls, responses):
    return {name: _seat(calls, name, resp)
            for name, resp in responses.items()}


def _load_policy(tmp, text):
    path = os.path.join(tmp, ".codereview.toml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return policy.load_policy(path)


TIERING = "[risk]\nenabled = true\ntiering = true\n"
NO_SLEEP = lambda *a, **k: None  # noqa: E731


def _run(patch, providers, pol=None, **kw):
    kw.setdefault("sleep", NO_SLEEP)
    return core.run_review(patch, providers, policy=pol, **kw)


class PolicyTieringSchemaTests(unittest.TestCase):
    """B1-style validation of the [risk] tiering keys."""

    def test_tiering_keys_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = _load_policy(
                tmp, TIERING + 'prescreen_seats = ["a", "b"]\n'
                               'medium_seats = ["c"]\n')
        self.assertTrue(pol["risk"]["tiering"])
        self.assertEqual(pol["risk"]["prescreen_seats"],
                         ["a", "b"])
        self.assertEqual(pol["risk"]["medium_seats"], ["c"])

    def test_tiering_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = _load_policy(tmp, "[risk]\nenabled = true\n")
        self.assertFalse(pol["risk"]["tiering"])
        self.assertEqual(pol["risk"]["prescreen_seats"], [])
        self.assertEqual(pol["risk"]["medium_seats"], [])

    def test_tiering_requires_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as cm:
                _load_policy(tmp, "[risk]\ntiering = true\n")
        self.assertIn("requires enabled = true",
                      str(cm.exception))
        self.assertIn(":2:", str(cm.exception))

    def test_tiering_non_bool_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError):
                _load_policy(
                    tmp, '[risk]\nenabled = true\n'
                         'tiering = "yes"\n')

    def test_seat_lists_must_be_string_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError):
                _load_policy(
                    tmp, TIERING + 'prescreen_seats = "a"\n')
            with self.assertRaises(policy.PolicyError):
                _load_policy(
                    tmp, TIERING + "medium_seats = [1]\n")

    def test_unknown_risk_key_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError):
                _load_policy(tmp, TIERING + "tierng = true\n")

    def test_render_shows_tiering_only_when_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            off = _load_policy(tmp, "[risk]\nenabled = true\n")
            on = _load_policy(
                tmp, TIERING + 'prescreen_seats = ["a"]\n')
        self.assertNotIn("tiering", policy.render_effective(off))
        rendered = policy.render_effective(on)
        self.assertIn("tiering = true", rendered)
        self.assertIn('prescreen_seats = ["a"]', rendered)
        self.assertIn("medium_seats = []", rendered)


class TieringConfigTests(unittest.TestCase):
    """The defensive resolver core consults."""

    def test_unconfigured_resolves_none(self):
        self.assertIsNone(tiering.tiering_config(None))
        self.assertIsNone(tiering.tiering_config({}))
        self.assertIsNone(tiering.tiering_config(
            {"risk": {"enabled": True}}))
        self.assertIsNone(tiering.tiering_config(
            {"risk": {"enabled": True, "tiering": False}}))
        self.assertIsNone(tiering.tiering_config(
            {"risk": {"tiering": True}}))

    def test_resolved_config(self):
        cfg = tiering.tiering_config(
            {"risk": {"enabled": True, "tiering": True,
                      "prescreen_seats": ["a"],
                      "medium_seats": ["b", "c"]}})
        self.assertEqual(cfg, {"prescreen_seats": ["a"],
                               "medium_seats": ["b", "c"]})

    def test_mistyped_values_fall_back(self):
        cfg = tiering.tiering_config(
            {"risk": {"enabled": True, "tiering": True,
                      "prescreen_seats": "a",
                      "medium_seats": [1, "b"]}})
        self.assertEqual(cfg, {"prescreen_seats": [],
                               "medium_seats": ["b"]})


def _tasks(*spec):
    return [(name, None, lens) for name, lens in spec]


TASKS3 = _tasks(("a", "correctness"), ("b", "operations"),
                ("c", "correctness"))


class PlanStagesTests(unittest.TestCase):
    """The seat-level plan, per band and configuration."""

    def test_low_default_is_first_seat(self):
        plan = tiering.plan_stages("low", TASKS3, {})
        self.assertEqual(plan["stage1_seats"], ["a"])
        self.assertEqual(plan["missing_seats"], [])
        self.assertIsNone(plan["fallback_to_full"])

    def test_low_explicit_seats(self):
        plan = tiering.plan_stages(
            "low", TASKS3, {"prescreen_seats": ["c", "a"]})
        # Panel order, not config order.
        self.assertEqual(plan["stage1_seats"], ["a", "c"])
        self.assertEqual(plan["prescreen_seats"], ["c", "a"])

    def test_missing_seats_recorded_not_dropped(self):
        plan = tiering.plan_stages(
            "low", TASKS3, {"prescreen_seats": ["c", "zzz"]})
        self.assertEqual(plan["stage1_seats"], ["c"])
        self.assertEqual(plan["missing_seats"], ["zzz"])
        self.assertIsNone(plan["fallback_to_full"])

    def test_all_missing_falls_back_to_full(self):
        plan = tiering.plan_stages(
            "low", TASKS3, {"prescreen_seats": ["zzz"]})
        self.assertEqual(plan["stage1_seats"], ["a", "b", "c"])
        self.assertIn("prescreen_seats",
                      plan["fallback_to_full"])

    def test_medium_default_first_seat_per_lens(self):
        plan = tiering.plan_stages("medium", TASKS3, {})
        self.assertEqual(plan["stage1_seats"], ["a", "b"])
        self.assertIsNone(plan["medium_seats"])

    def test_medium_explicit_seats(self):
        plan = tiering.plan_stages(
            "medium", TASKS3, {"medium_seats": ["c"]})
        self.assertEqual(plan["stage1_seats"], ["c"])
        self.assertEqual(plan["medium_seats"], ["c"])

    def test_high_is_full_panel(self):
        plan = tiering.plan_stages(
            "high", TASKS3, {"prescreen_seats": ["a"]})
        self.assertEqual(plan["stage1_seats"], ["a", "b", "c"])
        self.assertIsNone(plan["fallback_to_full"])

    def test_duplicate_missing_seat_recorded_once(self):
        # Survivor 95: a seat named twice in the config is
        # recorded once in missing_seats, both bands.
        plan = tiering.plan_stages(
            "low", TASKS3,
            {"prescreen_seats": ["zzz", "zzz", "c"]})
        self.assertEqual(plan["missing_seats"], ["zzz"])
        self.assertEqual(plan["stage1_seats"], ["c"])
        plan = tiering.plan_stages(
            "medium", TASKS3,
            {"medium_seats": ["zzz", "zzz", "c"]})
        self.assertEqual(plan["missing_seats"], ["zzz"])
        self.assertEqual(plan["stage1_seats"], ["c"])


def _rep(provider="a", lens="correctness", status="ok",
         findings=()):
    return {"provider": provider, "lens": lens,
            "status": status, "findings": list(findings)}


STAGE2 = [("b", None, "operations")]
# A stage-2 task on an already-covered lens: isolates the
# trigger under test from the lens-unserved trigger.
STAGE2_COVERED = [("c", None, "correctness")]


class EscalationTriggerTests(unittest.TestCase):
    """E4's evaluation over synthetic stage-1 reports."""

    def test_blocking_finding_triggers(self):
        triggers = tiering.escalation_triggers(
            [_rep(findings=[{"severity": "major"}])],
            STAGE2_COVERED, core.BLOCKING_DEFAULT)
        self.assertEqual([t["kind"] for t in triggers],
                         ["blocking finding"])

    def test_blocking_set_respects_allow_major(self):
        major = [_rep(findings=[{"severity": "major"}])]
        self.assertEqual(tiering.escalation_triggers(
            major, STAGE2_COVERED, ("blocker",)), [])
        blocker = [_rep(findings=[{"severity": "blocker"}])]
        self.assertEqual(len(tiering.escalation_triggers(
            blocker, STAGE2_COVERED, ("blocker",))), 1)

    def test_non_blocking_findings_do_not_trigger(self):
        triggers = tiering.escalation_triggers(
            [_rep(findings=[{"severity": "minor"},
                            {"severity": "nit"}])],
            STAGE2_COVERED, core.BLOCKING_DEFAULT)
        self.assertEqual(triggers, [])

    def test_reviewer_failure_triggers(self):
        reports = [_rep(status="error"),
                   _rep(provider="b", lens="operations")]
        triggers = tiering.escalation_triggers(
            reports, [("c", None, "operations")],
            core.BLOCKING_DEFAULT)
        self.assertEqual([t["kind"] for t in triggers],
                         ["reviewer failure"])

    def test_unserved_lens_triggers(self):
        triggers = tiering.escalation_triggers(
            [_rep(lens="correctness")], STAGE2,
            core.BLOCKING_DEFAULT)
        self.assertEqual([t["kind"] for t in triggers],
                         ["lens unserved"])
        self.assertIn("operations", triggers[0]["detail"])

    def test_clean_full_coverage_no_triggers(self):
        reports = [_rep(lens="correctness"),
                   _rep(provider="b", lens="operations")]
        self.assertEqual(tiering.escalation_triggers(
            reports, STAGE2, core.BLOCKING_DEFAULT), [])

    def test_no_stage2_no_triggers(self):
        reports = [_rep(status="error",
                        findings=[{"severity": "blocker"}])]
        self.assertEqual(tiering.escalation_triggers(
            reports, [], core.BLOCKING_DEFAULT), [])

    def test_trigger_order_is_fixed(self):
        reports = [_rep(status="error",
                        findings=[{"severity": "blocker"}])]
        triggers = tiering.escalation_triggers(
            reports, STAGE2, core.BLOCKING_DEFAULT)
        self.assertEqual([t["kind"] for t in triggers],
                         ["blocking finding", "reviewer failure",
                          "lens unserved"])


class RunReviewTieringTests(unittest.TestCase):
    """End-to-end over run_review with synthetic seats."""

    def _tiering_policy(self, tmp, extra=""):
        return _load_policy(tmp, TIERING + extra)

    def test_low_clean_prescreen_only(self):
        calls = {}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(tmp)
            report = _run(LOW_PATCH, _panel(
                calls, {"a": PASS, "b": PASS, "c": PASS}), pol)
        self.assertEqual(report["gate"], "pass")
        self.assertEqual(calls.get("a"), 2)  # both lenses
        self.assertNotIn("b", calls)
        self.assertNotIn("c", calls)
        section = report["tiering"]
        self.assertEqual(section["schema"], tiering.SCHEMA)
        self.assertEqual(section["band"], "low")
        self.assertEqual(section["stage1_seats"], ["a"])
        self.assertFalse(section["escalated"])
        self.assertEqual(section["escalation_triggers"], [])
        self.assertEqual(section["evidence"], "not_required")
        self.assertFalse(section["evidence_required"])

    def test_low_blocking_finding_escalates(self):
        major = json.dumps({
            "verdict": "changes_requested", "summary": "bug",
            "findings": [_finding("major", "sub is wrong",
                                  "return a - b")]})
        calls = {}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(tmp)
            report = _run(LOW_PATCH, _panel(
                calls, {"a": major, "b": PASS, "c": PASS}), pol)
        self.assertTrue(report["tiering"]["escalated"])
        self.assertEqual(
            [t["kind"] for t in
             report["tiering"]["escalation_triggers"]],
            ["blocking finding"])
        self.assertGreater(calls.get("b", 0), 0)
        self.assertGreater(calls.get("c", 0), 0)
        # The stage-1 finding stands in the final record and
        # the gate is computed on the full evidence.
        self.assertEqual(
            [f["title"] for f in report["findings"]],
            ["sub is wrong"])
        self.assertEqual(report["gate"], "blocked")
        self.assertTrue(any("escalated to the full panel" in r
                            for r in report["gate_reasons"]))

    def test_escalation_never_removes_stage1_findings(self):
        both = json.dumps({
            "verdict": "changes_requested", "summary": "issues",
            "findings": [
                _finding("minor", "add is trivial",
                         "return a + b"),
                _finding("major", "sub is wrong",
                         "return a - b")]})
        calls = {}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(tmp)
            report = _run(LOW_PATCH, _panel(
                calls, {"a": both, "b": PASS, "c": PASS}), pol)
        self.assertTrue(report["tiering"]["escalated"])
        self.assertEqual(
            sorted(f["title"] for f in report["findings"]),
            ["add is trivial", "sub is wrong"])

    def test_low_reviewer_failure_escalates(self):
        calls = {}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(tmp)
            report = _run(LOW_PATCH, _panel(
                calls, {"a": RuntimeError("seat down"),
                        "b": PASS, "c": PASS}), pol)
        self.assertTrue(report["tiering"]["escalated"])
        self.assertIn("reviewer failure",
                      [t["kind"] for t in
                       report["tiering"]["escalation_triggers"]])
        self.assertGreater(calls.get("b", 0), 0)
        # The failed stage-1 reports stay in the record.
        self.assertTrue(any(
            r["provider"] == "a" and r["status"] == "error"
            for r in report["reviewer_reports"]))
        self.assertTrue(report["degraded"])

    def test_low_minor_only_does_not_escalate(self):
        minor = json.dumps({
            "verdict": "changes_requested", "summary": "nit",
            "findings": [_finding("minor", "add is trivial",
                                  "return a + b")]})
        calls = {}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(tmp)
            report = _run(LOW_PATCH, _panel(
                calls, {"a": minor, "b": PASS, "c": PASS}), pol)
        self.assertFalse(report["tiering"]["escalated"])
        self.assertNotIn("b", calls)
        self.assertNotIn("c", calls)
        self.assertEqual(
            [f["title"] for f in report["findings"]],
            ["add is trivial"])

    def test_medium_default_reduced_panel(self):
        calls = {}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(tmp)
            report = _run(MEDIUM_PATCH, _panel(
                calls, {"a": PASS, "b": PASS, "c": PASS}), pol)
        self.assertEqual(report["tiering"]["band"], "medium")
        self.assertEqual(report["tiering"]["stage1_seats"],
                         ["a", "b"])
        self.assertFalse(report["tiering"]["escalated"])
        self.assertNotIn("c", calls)
        self.assertEqual(report["gate"], "pass")

    def test_medium_explicit_seat_is_a_one_seat_panel(self):
        calls = {}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(
                tmp, 'medium_seats = ["c"]\n')
            report = _run(MEDIUM_PATCH, _panel(
                calls, {"a": PASS, "b": PASS, "c": PASS}), pol)
        self.assertEqual(report["tiering"]["stage1_seats"],
                         ["c"])
        self.assertNotIn("a", calls)
        self.assertNotIn("b", calls)
        self.assertEqual(calls.get("c"), 2)  # both lenses
        self.assertFalse(report["tiering"]["escalated"])

    def test_missing_prescreen_seat_falls_back_to_full(self):
        calls = {}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(
                tmp, 'prescreen_seats = ["zzz"]\n')
            report = _run(LOW_PATCH, _panel(
                calls, {"a": PASS, "b": PASS, "c": PASS}), pol)
        section = report["tiering"]
        self.assertEqual(section["missing_seats"], ["zzz"])
        self.assertIn("prescreen_seats",
                      section["fallback_to_full"])
        self.assertEqual(section["stage1_seats"],
                         ["a", "b", "c"])
        self.assertFalse(section["escalated"])
        for name in ("a", "b", "c"):
            self.assertGreater(calls.get(name, 0), 0)

    def test_high_full_panel_and_evidence_missing_blocks(self):
        calls = {}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(tmp)
            report = _run(HIGH_PATCH, _panel(
                calls, {"a": PASS, "b": PASS, "c": PASS}), pol)
        for name in ("a", "b", "c"):
            self.assertGreater(calls.get(name, 0), 0)
        self.assertEqual(report["gate"], "blocked")
        self.assertTrue(any("requires evidence" in r
                            for r in report["gate_reasons"]))
        section = report["tiering"]
        self.assertEqual(section["band"], "high")
        self.assertTrue(section["evidence_required"])
        self.assertEqual(section["evidence"], "missing")
        self.assertFalse(section["escalated"])

    def test_high_with_unavailable_evidence_is_inconclusive(self):
        # P6-11 contrast pin: a SUPPLIED evidence record whose
        # required item is unavailable (tool not installed)
        # takes C3's INCONCLUSIVE branch — "unavailable" is a
        # status of a configured item. It is the absent record
        # (test_high_full_panel_and_evidence_missing_blocks)
        # that is "missing" and blocks: the tiering policy
        # itself is the requirement, and nothing configured
        # satisfies it.
        evidence = {"items": [{"name": "gitleaks",
                               "required": True,
                               "status": "unavailable",
                               "detail": "tool not installed"}]}
        calls = {}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(tmp)
            report = _run(HIGH_PATCH, _panel(
                calls, {"a": PASS, "b": PASS, "c": PASS}), pol,
                evidence=evidence)
        self.assertEqual(report["tiering"]["evidence"],
                         "supplied")
        self.assertEqual(report["gate"], "inconclusive")
        self.assertTrue(any("unavailable" in r
                            for r in report["gate_reasons"]))

    def test_high_with_passing_evidence_passes(self):
        evidence = {"items": [{"name": "tests",
                               "required": True,
                               "status": "passed"}]}
        calls = {}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(tmp)
            report = _run(HIGH_PATCH, _panel(
                calls, {"a": PASS, "b": PASS, "c": PASS}), pol,
                evidence=evidence)
        self.assertEqual(report["tiering"]["evidence"],
                         "supplied")
        self.assertEqual(report["gate"], "pass")

    def test_high_with_failing_evidence_blocks_via_c3(self):
        evidence = {"items": [{"name": "tests",
                               "required": True,
                               "status": "failed"}]}
        calls = {}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(tmp)
            report = _run(HIGH_PATCH, _panel(
                calls, {"a": PASS, "b": PASS, "c": PASS}), pol,
                evidence=evidence)
        self.assertEqual(report["tiering"]["evidence"],
                         "supplied")
        self.assertEqual(report["gate"], "blocked")
        self.assertTrue(any("required evidence" in r
                            for r in report["gate_reasons"]))

    def test_binding_subset_never_remaps_lenses(self):
        calls = {}
        binding = {"a": ["correctness"], "b": ["operations"],
                   "c": ["operations"]}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(
                tmp, 'prescreen_seats = ["a", "b"]\n')
            report = _run(LOW_PATCH, _panel(
                calls, {"a": PASS, "b": PASS, "c": PASS}), pol,
                seat_lenses=binding)
        self.assertFalse(report["tiering"]["escalated"])
        self.assertNotIn("c", calls)
        pairs = {(r["provider"], r["lens"])
                 for r in report["reviewer_reports"]}
        self.assertEqual(pairs, {("a", "correctness"),
                                 ("b", "operations")})

    def test_binding_unserved_lens_escalates(self):
        calls = {}
        binding = {"a": ["correctness"], "b": ["operations"],
                   "c": ["operations"]}
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._tiering_policy(
                tmp, 'prescreen_seats = ["a"]\n')
            report = _run(LOW_PATCH, _panel(
                calls, {"a": PASS, "b": PASS, "c": PASS}), pol,
                seat_lenses=binding)
        self.assertTrue(report["tiering"]["escalated"])
        self.assertEqual(
            [t["kind"] for t in
             report["tiering"]["escalation_triggers"]],
            ["lens unserved"])
        self.assertGreater(calls.get("b", 0), 0)

    def test_tiering_off_is_byte_identical(self):
        # Risk on but tiering off vs a plain policy: the whole
        # report agrees once volatile fields and the sections
        # that legitimately differ (policy provenance, the
        # risk section) are set aside — and no tiering key
        # appears on either side.
        def _strip(report):
            out = dict(report)
            # duration_ms and record_identity (schema v1.0.0)
            # are volatile by construction — a wall clock and
            # an identity hashed from created_at — same class
            # as created_at itself.
            for key in ("created_at", "policy", "risk",
                        "duration_ms", "record_identity"):
                out.pop(key, None)
            reps = []
            for rec in report["reviewer_reports"]:
                rec = dict(rec)
                rec.pop("duration_ms", None)
                reps.append(rec)
            # Completion order is a thread artifact, not a
            # fact of the run: sort before comparing.
            reps.sort(key=lambda r: (r["provider"], r["lens"],
                                     r["batch"]))
            out["reviewer_reports"] = reps
            return out

        with tempfile.TemporaryDirectory() as tmp:
            risk_only = _load_policy(
                tmp, "[risk]\nenabled = true\n")
            plain = _load_policy(tmp, "[panel]\nmin_seats = 0\n")
            calls_on, calls_off = {}, {}
            on = _run(LOW_PATCH, _panel(
                calls_on, {"a": PASS, "b": PASS, "c": PASS}),
                risk_only)
            off = _run(LOW_PATCH, _panel(
                calls_off, {"a": PASS, "b": PASS, "c": PASS}),
                plain)
        self.assertNotIn("tiering", on)
        self.assertNotIn("tiering", off)
        self.assertEqual(_strip(on), _strip(off))
        self.assertEqual(calls_on, calls_off)

    def test_no_policy_no_tiering_section(self):
        calls = {}
        report = _run(LOW_PATCH, _panel(
            calls, {"a": PASS, "b": PASS, "c": PASS}))
        self.assertNotIn("tiering", report)
        self.assertNotIn("risk", report)


class FixtureCostTests(unittest.TestCase):
    """E2's cost acceptance at mechanism level: across a
    low/medium/high fixture mix, the tiered panel spends
    fewer seat calls than the untiered panel, and the high
    band spends exactly the untiered count (the full panel —
    which is also why high-risk recall is unchanged by
    construction)."""

    def test_cost_drop_and_high_parity(self):
        panel_spec = {"a": PASS, "b": PASS, "c": PASS,
                      "d": PASS}
        evidence = {"items": [{"name": "tests",
                               "required": True,
                               "status": "passed"}]}
        with tempfile.TemporaryDirectory() as tmp:
            tiered_pol = _load_policy(tmp, TIERING)
            plain_pol = _load_policy(
                tmp, "[panel]\nmin_seats = 0\n")
            totals = {"tiered": 0, "plain": 0}
            per_band = {}
            for patch in (LOW_PATCH, MEDIUM_PATCH, HIGH_PATCH):
                calls = {}
                rep = _run(patch, _panel(calls, panel_spec),
                           tiered_pol, evidence=evidence)
                tiered_calls = sum(calls.values())
                totals["tiered"] += tiered_calls
                per_band[rep["tiering"]["band"]] = tiered_calls
                calls = {}
                _run(patch, _panel(calls, panel_spec),
                     plain_pol, evidence=evidence)
                totals["plain"] += sum(calls.values())
        self.assertEqual(per_band["high"], 4)
        self.assertEqual(per_band["low"], 2)
        self.assertEqual(per_band["medium"], 2)
        self.assertEqual(totals["plain"], 12)
        self.assertLess(totals["tiered"], totals["plain"])


if __name__ == "__main__":
    unittest.main()
