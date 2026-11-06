"""Epic E1 — deterministic risk scorer.

`risk.scorer` computes a score + band + reasons from the
change's paths, size, touched sensitive patterns (auth,
payments, crypto, migrations, secrets, deserialization), and
dependency changes, and — when the project policy's [risk]
table enables it — run_review records the section in the run
record. The fixtures below pin the scoring model, the
determinism contract, the B1-style [risk] validation, and the
no-[risk] equivalence: disabled or absent, a run's record is
exactly what it was before E1, and the score never moves a
verdict either way.
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from codereview import core, policy, risk  # noqa: E402


def _section(path, added=(), removed=()):
    body = "".join(f"+{line}\n" for line in added)
    body += "".join(f"-{line}\n" for line in removed)
    return (f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n"
            f"@@ -1,{len(removed)} +1,{len(added)} @@\n" + body)


def _patch(*sections):
    return "".join(_section(p, a, r) for p, a, r in sections)


CLEAN = _patch(("app/util.py",
                ("def sub(a, b):", "    return a - b"), ()))

# The secrets fixture line is assembled from fragments: test
# files must not contain secret-shaped literals (see
# tests/test_fixture_secret_hygiene.py).
_SECRET_LINE = "api_" + "key" + " = " + "\"exam" + "ple-value\""

SECRETS_PATCH = _patch(("app/config.py", (_SECRET_LINE,), ()))


def pass_provider(prompt):
    return json.dumps({"summary": "looks fine", "findings": []})


def _load_policy(tmp, text):
    path = os.path.join(tmp, ".codereview.toml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return policy.load_policy(path), path


class ScorerPatternTests(unittest.TestCase):
    """Each pattern class: path match and content match."""

    def test_clean_patch_scores_zero(self):
        section = risk.score_patch(CLEAN)
        self.assertEqual(section["score"], 0)
        self.assertEqual(section["band"], "low")
        self.assertEqual(section["reasons"],
                         ["no risk signals detected"])
        self.assertEqual(section["points"],
                         {"patterns": 0, "dependencies": 0,
                          "size": 0})
        self.assertEqual(section["signals"]["patterns"], [])

    def test_auth_by_path(self):
        section = risk.score_patch(_patch(
            ("src/auth/login.py", ("def view():", "    pass"), ())))
        self.assertEqual(section["score"], 25)
        [signal] = section["signals"]["patterns"]
        self.assertEqual(signal["class"], "auth")
        self.assertEqual(signal["points"], 25)
        self.assertEqual(signal["files"], ["src/auth/login.py"])
        self.assertIn("auth patterns touched in 1 file(s): "
                      "src/auth/login.py (+25)",
                      section["reasons"])

    def test_auth_by_content(self):
        section = risk.score_patch(_patch(
            ("app/views.py",
             ("user = authenticate(request)",), ())))
        self.assertEqual(
            [s["class"] for s in section["signals"]["patterns"]],
            ["auth"])

    def test_payments_by_path_and_content(self):
        by_path = risk.score_patch(_patch(
            ("app/billing/invoice.py", ("total = 0",), ())))
        self.assertEqual(
            [s["class"] for s in by_path["signals"]["patterns"]],
            ["payments"])
        by_content = risk.score_patch(_patch(
            ("app/shop.py", ("import stripe",), ())))
        self.assertEqual(
            [s["class"]
             for s in by_content["signals"]["patterns"]],
            ["payments"])
        self.assertEqual(by_content["score"], 25)

    def test_crypto_by_content(self):
        section = risk.score_patch(_patch(
            ("app/util.py",
             ("from hashlib import pbkdf2_hmac",), ())))
        self.assertEqual(
            [(s["class"], s["points"])
             for s in section["signals"]["patterns"]],
            [("crypto", 20)])

    def test_migrations_by_path_and_sql_content(self):
        by_path = risk.score_patch(_patch(
            ("db/migrations/0002_users.py", ("pass",), ())))
        self.assertEqual(
            [s["class"] for s in by_path["signals"]["patterns"]],
            ["migrations"])
        by_content = risk.score_patch(_patch(
            ("db/schema.sql",
             ("ALTER TABLE users ADD COLUMN age INT;",), ())))
        self.assertEqual(
            [s["class"]
             for s in by_content["signals"]["patterns"]],
            ["migrations"])

    def test_secrets_by_content(self):
        section = risk.score_patch(SECRETS_PATCH)
        self.assertEqual(
            [(s["class"], s["points"])
             for s in section["signals"]["patterns"]],
            [("secrets", 25)])

    def test_secrets_by_env_path(self):
        section = risk.score_patch(_patch(
            ("config/.env.production", ("DEBUG=0",), ())))
        self.assertEqual(
            [s["class"] for s in section["signals"]["patterns"]],
            ["secrets"])

    def test_deserialization_by_content(self):
        section = risk.score_patch(_patch(
            ("app/loader.py", ("obj = pickle.loads(data)",), ())))
        self.assertEqual(
            [(s["class"], s["points"])
             for s in section["signals"]["patterns"]],
            [("deserialization", 20)])

    def test_class_points_awarded_once_for_many_files(self):
        patch = _patch(*[
            (f"src/auth/mod{i}.py", ("pass",), ())
            for i in range(7)])
        section = risk.score_patch(patch)
        self.assertEqual(section["points"]["patterns"], 25)
        [signal] = section["signals"]["patterns"]
        self.assertEqual(len(signal["files"]), 7)
        # The reason caps the named files and summarises the
        # rest; the signal keeps the full sorted list.
        self.assertIn("+2 more", section["reasons"][0])
        self.assertEqual(signal["files"],
                         sorted(signal["files"]))

    def test_removed_lines_are_not_content_scanned(self):
        # A change REMOVING a pickle.loads call introduces
        # nothing; the removal alone scores no pattern points.
        section = risk.score_patch(_patch(
            ("app/loader.py", (), ("obj = pickle.loads(data)",))))
        self.assertEqual(section["signals"]["patterns"], [])


class ScorerSizeAndDependencyTests(unittest.TestCase):

    def _big_patch(self, n_added, n_removed=0):
        return _patch(("app/big.py",
                       tuple(f"x{i} = {i}" for i in range(n_added)),
                       tuple(f"y{i} = {i}"
                             for i in range(n_removed))))

    def test_size_tiers(self):
        cases = [(49, 0), (50, 5), (149, 5), (150, 10),
                 (399, 10), (400, 15), (999, 15), (1000, 25)]
        for lines, points in cases:
            with self.subTest(lines=lines):
                section = risk.score_patch(self._big_patch(lines))
                self.assertEqual(section["points"]["size"],
                                 points)
                self.assertEqual(
                    section["signals"]["lines_added"], lines)

    def test_size_counts_added_plus_removed(self):
        section = risk.score_patch(self._big_patch(30, 25))
        self.assertEqual(section["points"]["size"], 5)
        self.assertEqual(section["signals"]["lines_removed"], 25)
        self.assertIn("change size: 55 changed line(s) (+5)",
                      section["reasons"])

    def test_dependency_manifest_change(self):
        section = risk.score_patch(_patch(
            ("package.json", ('"version": "1.2.3"',), ())))
        self.assertEqual(section["points"]["dependencies"], 15)
        self.assertEqual(section["signals"]["dependency_files"],
                         ["package.json"])
        self.assertIn("dependency manifests changed: "
                      "package.json (+15)", section["reasons"])

    def test_dependency_requirements_layouts(self):
        for path in ("requirements-dev.txt",
                     "requirements/prod.txt",
                     "pyproject.toml"):
            with self.subTest(path=path):
                section = risk.score_patch(_patch(
                    (path, ("flask",), ())))
                self.assertEqual(
                    section["points"]["dependencies"], 15)

    def test_non_manifest_txt_is_not_a_dependency(self):
        section = risk.score_patch(_patch(
            ("docs/notes.txt", ("hello",), ())))
        self.assertEqual(section["points"]["dependencies"], 0)

    def test_pattern_subtotal_capped(self):
        patch = _patch(
            ("src/auth/a.py", ("pass",), ()),
            ("app/billing/b.py", ("pass",), ()),
            ("app/c.py", ("from hashlib import sha256",), ()),
            ("db/migrations/0001.py", ("pass",), ()),
            ("app/config.py", (_SECRET_LINE,), ()),
            ("app/d.py", ("obj = pickle.loads(data)",), ()))
        section = risk.score_patch(patch)
        # Uncapped the six classes sum to 135; the cap binds.
        self.assertEqual(section["points"]["patterns"],
                         risk.PATTERN_CAP)
        self.assertEqual(section["score"], risk.PATTERN_CAP)
        self.assertTrue(any("capped" in r
                            for r in section["reasons"]))

    def test_score_ceiling_is_exactly_100(self):
        # Every contribution maxed: all six classes (subtotal
        # 135, capped at 60) + dependencies (15) + the top
        # size tier (25) = exactly 100 — the arithmetic
        # ceiling of the model, so the score can never pass
        # it (the min(100, ...) clamp is defence in depth).
        patch = _patch(
            ("src/auth/a.py",
             tuple(f"v{i} = {i}" for i in range(1000)), ()),
            ("app/billing/b.py", ("pass",), ()),
            ("app/c.py", ("from hashlib import sha256",), ()),
            ("db/migrations/0001.py", ("pass",), ()),
            ("app/config.py", (_SECRET_LINE,), ()),
            ("app/d.py", ("obj = pickle.loads(data)",), ()),
            ("package.json", ('"a": 1',), ()))
        section = risk.score_patch(patch)
        self.assertEqual(section["points"],
                         {"patterns": risk.PATTERN_CAP,
                          "dependencies": 15, "size": 25})
        self.assertEqual(section["score"], 100)
        self.assertEqual(section["band"], "high")


class ScorerDeterminismTests(unittest.TestCase):

    def test_same_input_same_output(self):
        patch = _patch(
            ("src/auth/login.py", ("pass",), ()),
            ("package.json", ('"a": 1',), ()))
        first = risk.score_patch(patch)
        second = risk.score_patch(patch)
        self.assertEqual(first, second)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def test_section_order_does_not_change_the_score(self):
        forward = _patch(
            ("src/auth/login.py", ("pass",), ()),
            ("package.json", ('"a": 1',), ()))
        backward = _patch(
            ("package.json", ('"a": 1',), ()),
            ("src/auth/login.py", ("pass",), ()))
        self.assertEqual(risk.score_patch(forward),
                         risk.score_patch(backward))

    def test_band_boundaries(self):
        self.assertEqual(risk.band_for(0), "low")
        self.assertEqual(risk.band_for(34), "low")
        self.assertEqual(risk.band_for(35), "medium")
        self.assertEqual(risk.band_for(69), "medium")
        self.assertEqual(risk.band_for(70), "high")
        self.assertEqual(risk.band_for(100), "high")

    def test_custom_thresholds_apply_and_echo(self):
        config = {"medium_threshold": 10, "high_threshold": 20}
        section = risk.score_patch(
            _patch(("src/auth/login.py", ("pass",), ())), config)
        self.assertEqual(section["score"], 25)
        self.assertEqual(section["band"], "high")
        self.assertEqual(section["thresholds"],
                         {"medium": 10, "high": 20})


class RiskConfigTests(unittest.TestCase):

    def test_no_policy_no_config(self):
        self.assertIsNone(risk.risk_config(None))
        self.assertIsNone(risk.risk_config({}))
        self.assertIsNone(risk.risk_config(
            {"risk": {"enabled": False}}))

    def test_enabled_resolves_defaults(self):
        self.assertEqual(
            risk.risk_config({"risk": {"enabled": True}}),
            {"medium_threshold": risk.DEFAULT_MEDIUM_THRESHOLD,
             "high_threshold": risk.DEFAULT_HIGH_THRESHOLD})

    def test_enabled_resolves_overrides(self):
        self.assertEqual(
            risk.risk_config({"risk": {
                "enabled": True, "medium_threshold": 10,
                "high_threshold": 90}}),
            {"medium_threshold": 10, "high_threshold": 90})

    def test_mistyped_values_fall_back_to_defaults(self):
        config = risk.risk_config({"risk": {
            "enabled": True, "medium_threshold": "high",
            "high_threshold": 700}})
        self.assertEqual(
            config,
            {"medium_threshold": risk.DEFAULT_MEDIUM_THRESHOLD,
             "high_threshold": risk.DEFAULT_HIGH_THRESHOLD})


class PolicyRiskSchemaTests(unittest.TestCase):
    """B1-style validation of the [risk] table."""

    def test_threshold_defaults_mirror_risk_module(self):
        self.assertEqual(policy._RISK_DEFAULT_MEDIUM_THRESHOLD,
                         risk.DEFAULT_MEDIUM_THRESHOLD)
        self.assertEqual(policy._RISK_DEFAULT_HIGH_THRESHOLD,
                         risk.DEFAULT_HIGH_THRESHOLD)

    def test_risk_table_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol, _ = _load_policy(
                tmp, "[risk]\nenabled = true\n"
                     "medium_threshold = 20\n")
        self.assertEqual(pol["risk"],
                         {"enabled": True, "medium_threshold": 20,
                          "high_threshold": None, "tiering": False,
                          "prescreen_seats": [],
                          "medium_seats": []})

    def test_no_risk_table_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol, _ = _load_policy(tmp, "[panel]\nmin_seats = 1\n")
        self.assertEqual(pol["risk"],
                         {"enabled": False,
                          "medium_threshold": None,
                          "high_threshold": None,
                          "tiering": False,
                          "prescreen_seats": [],
                          "medium_seats": []})

    def test_unknown_risk_key_rejected_with_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as cm:
                _load_policy(tmp, "[risk]\nenabld = true\n")
        self.assertIn(":2:", str(cm.exception))

    def test_non_bool_enabled_rejected_with_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as cm:
                _load_policy(tmp, '[risk]\nenabled = "yes"\n')
        self.assertIn(":2:", str(cm.exception))

    def test_threshold_above_100_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as cm:
                _load_policy(
                    tmp, "[risk]\nhigh_threshold = 101\n")
        self.assertIn("at most 100", str(cm.exception))

    def test_negative_threshold_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError):
                _load_policy(
                    tmp, "[risk]\nmedium_threshold = -1\n")

    def test_inverted_thresholds_rejected_with_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as cm:
                _load_policy(
                    tmp, "[risk]\nenabled = true\n"
                         "medium_threshold = 70\n"
                         "high_threshold = 70\n")
        self.assertIn(":4:", str(cm.exception))
        self.assertIn("must be below", str(cm.exception))

    def test_render_shows_risk_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            off, _ = _load_policy(tmp, "[panel]\nmin_seats = 1\n")
            on, _ = _load_policy(
                tmp, "[risk]\nenabled = true\n"
                     "medium_threshold = 20\n")
        self.assertNotIn("[risk]", policy.render_effective(off))
        rendered = policy.render_effective(on)
        self.assertIn("[risk]\nenabled = true\n"
                      "medium_threshold = 20\n"
                      "high_threshold = 70", rendered)


class RunReviewRiskTests(unittest.TestCase):

    def _policy(self, tmp, text):
        pol, _ = _load_policy(tmp, text)
        return pol

    def test_risk_section_recorded_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._policy(tmp, "[risk]\nenabled = true\n")
            report = core.run_review(
                _patch(("src/auth/login.py",
                        ("def view():", "    pass"), ())),
                {"a": pass_provider}, policy=pol)
        self.assertEqual(report["gate"], "pass")
        section = report["risk"]
        self.assertEqual(section["schema"], risk.SCHEMA)
        self.assertEqual(section["score"], 25)
        self.assertEqual(section["band"], "low")
        self.assertIn("auth patterns touched",
                      " ".join(section["reasons"]))

    def test_no_risk_section_when_disabled_or_absent(self):
        patch = _patch(("src/auth/login.py", ("pass",), ()))
        with tempfile.TemporaryDirectory() as tmp:
            disabled = self._policy(
                tmp, "[risk]\nenabled = false\n")
            plain = self._policy(tmp, "[panel]\nmin_seats = 0\n")
            for pol in (disabled, plain):
                report = core.run_review(
                    patch, {"a": pass_provider}, policy=pol)
                self.assertNotIn("risk", report)
        report = core.run_review(patch, {"a": pass_provider})
        self.assertNotIn("risk", report)

    def test_risk_never_changes_the_verdict(self):
        # Identical inputs, risk on vs off: the whole report
        # agrees once volatile fields (timestamps, durations)
        # and the two sections that legitimately differ — the
        # policy provenance (different policy files) and the
        # risk section itself — are set aside.
        patch = _patch(("src/auth/login.py",
                        ("def view():", "    pass"), ()))
        with tempfile.TemporaryDirectory() as tmp:
            on = self._policy(tmp, "[risk]\nenabled = true\n")
            off = self._policy(tmp, "[panel]\nmin_seats = 0\n")
            wired = core.run_review(
                patch, {"a": pass_provider}, policy=on)
            control = core.run_review(
                patch, {"a": pass_provider}, policy=off)

        def _strip(report):
            out = dict(report)
            out.pop("created_at", None)
            out.pop("duration_ms", None)
            out.pop("policy", None)
            out.pop("risk", None)
            reps = []
            for rec in report["reviewer_reports"]:
                rec = dict(rec)
                rec.pop("duration_ms", None)
                reps.append(rec)
            out["reviewer_reports"] = reps
            return out

        self.assertEqual(_strip(wired), _strip(control))
        self.assertIn("risk", wired)
        self.assertNotIn("risk", control)


if __name__ == "__main__":
    unittest.main()
