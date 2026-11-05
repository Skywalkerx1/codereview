"""Epic B — project policy file (.codereview.toml).

B1: the loader validates with line-referenced errors and fills
documented defaults. B2: the gate reads policy — evaluation is
pure (evaluate_policy over a round's facts) and run_review
records every applied rule, turns a PASS into BLOCKED on a
blocking violation, and leaves advisory violations recorded
only. B3: `codereview policy check` validates and prints the
effective policy. The user setup config (userconfig) is a
different file for a different purpose and is untouched here.
"""

import datetime
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, core, policy  # noqa: E402

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

AUTH = """diff --git a/auth/login.py b/auth/login.py
--- a/auth/login.py
+++ b/auth/login.py
@@ -1,1 +1,2 @@
 def login(user):
     return establish_session(user)
+# audit hook added
"""


def pass_provider(prompt):
    return json.dumps({"verdict": "pass", "summary": "looks fine",
                       "findings": []})


def write_policy(tmp, text, name=".codereview.toml"):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def load(tmp, text):
    return policy.load_policy(write_policy(tmp, text))


def report(provider, family="unknown", lens="correctness",
           status="ok"):
    return {"provider": provider, "family": family, "lens": lens,
            "status": status}


def evaluate(pol, **kw):
    kw.setdefault("files", [])
    kw.setdefault("reviewer_reports", [])
    kw.setdefault("test_results", [])
    kw.setdefault("path_matches", core.path_matches)
    return policy.evaluate_policy(pol, **kw)


class LoaderTests(unittest.TestCase):
    def test_empty_file_yields_documented_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = load(tmp, "# nothing required here\n")
            self.assertEqual(pol["panel"]["min_seats"], 0)
            self.assertEqual(pol["panel"]["required_families"], [])
            self.assertEqual(pol["evidence"],
                             {"require_tests": False,
                              "require_tests_pass": False})
            self.assertEqual(pol["paths"], [])
            self.assertEqual(pol["waivers"],
                             {"allow": True, "require_reason": False,
                              "max_age_days": 0})
            self.assertTrue(pol["sha256"])
            self.assertTrue(pol["path"].endswith(".codereview.toml"))

    def test_partial_file_fills_remaining_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = load(tmp, "[panel]\nmin_seats = 2\n")
            self.assertEqual(pol["panel"]["min_seats"], 2)
            self.assertEqual(pol["panel"]["min_families"], 0)
            self.assertEqual(pol["waivers"]["allow"], True)

    def test_full_file_parses(self):
        text = (
            "[panel]\nmin_seats = 2\nmin_families = 2\n"
            "required_families = [\"google\"]\n"
            "require_lenses = [\"correctness\", \"operations\"]\n"
            "[evidence]\nrequire_tests_pass = true\n"
            "[[paths]]\nmatch = \"auth/**\"\n"
            "require_full_panel = true\nrequire_tests_pass = true\n"
            "[[paths]]\nmatch = \"docs/**\"\nenforce = \"advisory\"\n"
            "[waivers]\nrequire_reason = true\nmax_age_days = 30\n")
        with tempfile.TemporaryDirectory() as tmp:
            pol = load(tmp, text)
            self.assertEqual(pol["panel"]["required_families"],
                             ["google"])
            self.assertEqual(len(pol["paths"]), 2)
            self.assertEqual(pol["paths"][0]["enforce"], "block")
            self.assertEqual(pol["paths"][1]["enforce"], "advisory")
            self.assertEqual(pol["waivers"]["max_age_days"], 30)

    def test_syntax_error_names_the_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as ctx:
                load(tmp, "[panel\nmin_seats = 2\n")
            self.assertIn("invalid TOML", str(ctx.exception))
            self.assertIn("line 1", str(ctx.exception))

    def test_type_error_is_line_referenced(self):
        text = "# comment\n\n[panel]\nmin_seats = \"two\"\n"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as ctx:
                load(tmp, text)
            self.assertIn(":4:", str(ctx.exception))
            self.assertIn("min_seats", str(ctx.exception))

    def test_unknown_key_is_line_referenced(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as ctx:
                load(tmp, "[evidence]\nbogus = true\n")
            self.assertIn(":2:", str(ctx.exception))
            self.assertIn("bogus", str(ctx.exception))

    def test_unknown_table_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as ctx:
                load(tmp, "[deploy]\nfast = true\n")
            self.assertIn("deploy", str(ctx.exception))

    def test_bare_top_level_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError):
                load(tmp, "min_seats = 2\n")

    def test_bool_is_not_an_int(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError):
                load(tmp, "[panel]\nmin_seats = true\n")

    def test_negative_int_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError):
                load(tmp, "[waivers]\nmax_age_days = -1\n")

    def test_unknown_lens_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as ctx:
                load(tmp, "[panel]\nrequire_lenses = [\"style\"]\n")
            self.assertIn("style", str(ctx.exception))

    def test_paths_entry_needs_a_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as ctx:
                load(tmp, "[[paths]]\nrequire_tests = true\n")
            self.assertIn("match", str(ctx.exception))

    def test_paths_bad_enforce_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError):
                load(tmp, "[[paths]]\nmatch = \"a/**\"\n"
                          "enforce = \"hard\"\n")

    def test_paths_as_single_table_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError):
                load(tmp, "[paths]\nmatch = \"a/**\"\n")

    def test_known_lenses_mirror_the_engine(self):
        self.assertEqual(set(policy.KNOWN_LENSES),
                         set(core.LENSES))

    def test_find_policy_discovers_repo_root_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(policy.find_policy(tmp))
            write_policy(tmp, "")
            self.assertEqual(policy.find_policy(tmp),
                             os.path.join(tmp, ".codereview.toml"))


class EvaluatePanelTests(unittest.TestCase):
    def pol(self, tmp_text):
        with tempfile.TemporaryDirectory() as tmp:
            return load(tmp, tmp_text)

    def test_default_policy_applies_nothing(self):
        out = evaluate(policy.default_policy(),
                       reviewer_reports=[report("a")])
        self.assertEqual(out, {"applied": [], "violations": []})

    def test_min_seats(self):
        pol = self.pol("[panel]\nmin_seats = 2\n")
        ok = evaluate(pol, reviewer_reports=[
            report("a", lens="correctness"),
            report("b", lens="operations")])
        self.assertEqual(ok["violations"], [])
        short = evaluate(pol, reviewer_reports=[report("a")])
        self.assertEqual(len(short["violations"]), 1)
        self.assertEqual(short["applied"][0]["status"], "violated")

    def test_min_seats_counts_distinct_seats_not_jobs(self):
        pol = self.pol("[panel]\nmin_seats = 2\n")
        out = evaluate(pol, reviewer_reports=[
            report("a", lens="correctness"),
            report("a", lens="operations")])
        self.assertEqual(len(out["violations"]), 1)

    def test_min_families_ignores_unknown_family(self):
        pol = self.pol("[panel]\nmin_families = 1\n")
        out = evaluate(pol, reviewer_reports=[report("a")])
        self.assertEqual(len(out["violations"]), 1)
        out = evaluate(pol, reviewer_reports=[
            report("a", family="google")])
        self.assertEqual(out["violations"], [])

    def test_required_families(self):
        pol = self.pol("[panel]\nrequired_families = [\"google\"]\n")
        out = evaluate(pol, reviewer_reports=[
            report("a", family="openai")])
        self.assertEqual(len(out["violations"]), 1)
        self.assertIn("google", out["violations"][0]["detail"])
        out = evaluate(pol, reviewer_reports=[
            report("a", family="google")])
        self.assertEqual(out["violations"], [])

    def test_failed_seat_does_not_count_for_family(self):
        pol = self.pol("[panel]\nrequired_families = [\"google\"]\n")
        out = evaluate(pol, reviewer_reports=[
            report("a", family="google", status="error")])
        self.assertEqual(len(out["violations"]), 1)

    def test_require_lenses(self):
        pol = self.pol(
            "[panel]\nrequire_lenses = [\"operations\"]\n")
        out = evaluate(pol, reviewer_reports=[
            report("a", lens="correctness")])
        self.assertEqual(len(out["violations"]), 1)
        out = evaluate(pol, reviewer_reports=[
            report("a", lens="operations")])
        self.assertEqual(out["violations"], [])


class EvaluateEvidenceTests(unittest.TestCase):
    def pol(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            return load(tmp, text)

    def test_require_tests(self):
        pol = self.pol("[evidence]\nrequire_tests = true\n")
        out = evaluate(pol)
        self.assertEqual(len(out["violations"]), 1)
        out = evaluate(pol, test_results=[
            {"command": "pytest", "ok": False}])
        self.assertEqual(out["violations"], [])

    def test_require_tests_pass_states(self):
        pol = self.pol("[evidence]\nrequire_tests_pass = true\n")
        none_ran = evaluate(pol)
        self.assertEqual(len(none_ran["violations"]), 1)
        self.assertIn("no test command ran",
                      none_ran["violations"][0]["detail"])
        failed = evaluate(pol, test_results=[
            {"command": "pytest", "ok": False}])
        self.assertEqual(len(failed["violations"]), 1)
        self.assertIn("1 of 1", failed["violations"][0]["detail"])
        passed = evaluate(pol, test_results=[
            {"command": "pytest", "ok": True}])
        self.assertEqual(passed["violations"], [])


class EvaluatePathRuleTests(unittest.TestCase):
    def pol(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            return load(tmp, text)

    def test_unmatched_path_rule_does_not_apply(self):
        pol = self.pol("[[paths]]\nmatch = \"auth/**\"\n"
                       "require_tests_pass = true\n")
        out = evaluate(pol, files=["app/util.py"])
        self.assertEqual(out, {"applied": [], "violations": []})

    def test_matched_path_rule_requires_passing_tests(self):
        pol = self.pol("[[paths]]\nmatch = \"auth/**\"\n"
                       "require_tests_pass = true\n")
        out = evaluate(pol, files=["auth/login.py"])
        self.assertEqual(len(out["violations"]), 1)
        self.assertEqual(out["violations"][0]["rule"],
                         "paths[auth/**].require_tests_pass")
        out = evaluate(pol, files=["auth/login.py"], test_results=[
            {"command": "pytest", "ok": True}])
        self.assertEqual(out["violations"], [])

    def test_require_full_panel(self):
        pol = self.pol("[[paths]]\nmatch = \"auth/**\"\n"
                       "require_full_panel = true\n")
        out = evaluate(pol, files=["auth/login.py"],
                       reviewer_reports=[
                           report("a"),
                           report("b", lens="operations",
                                  status="error")])
        self.assertEqual(len(out["violations"]), 1)
        self.assertIn("b", out["violations"][0]["detail"])
        out = evaluate(pol, files=["auth/login.py"],
                       reviewer_reports=[
                           report("a"),
                           report("b", lens="operations")])
        self.assertEqual(out["violations"], [])

    def test_advisory_enforce_is_recorded_as_advisory(self):
        pol = self.pol("[[paths]]\nmatch = \"auth/**\"\n"
                       "min_families = 2\nenforce = \"advisory\"\n")
        out = evaluate(pol, files=["auth/login.py"],
                       reviewer_reports=[report("a",
                                                  family="google")])
        self.assertEqual(len(out["violations"]), 1)
        self.assertEqual(out["violations"][0]["enforce"],
                         "advisory")


class EvaluateWaiverTests(unittest.TestCase):
    TODAY = datetime.date(2026, 11, 4)

    def pol(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            return load(tmp, text)

    def test_waivers_disallowed(self):
        pol = self.pol("[waivers]\nallow = false\n")
        out = evaluate(pol, waivers=[{"finding_id": "abc123"}],
                       today=self.TODAY)
        self.assertEqual(len(out["violations"]), 1)
        self.assertIn("abc123", out["violations"][0]["detail"])
        out = evaluate(pol, waivers=[], today=self.TODAY)
        self.assertEqual(out["violations"], [])

    def test_waiver_requires_reason(self):
        pol = self.pol("[waivers]\nrequire_reason = true\n")
        out = evaluate(pol, waivers=[{"finding_id": "abc123"}],
                       today=self.TODAY)
        self.assertEqual(len(out["violations"]), 1)
        out = evaluate(pol, waivers=[
            {"finding_id": "abc123", "reason": "accepted risk"}],
            today=self.TODAY)
        self.assertEqual(out["violations"], [])

    def test_waiver_expiry(self):
        pol = self.pol("[waivers]\nmax_age_days = 30\n")
        old = evaluate(pol, waivers=[
            {"finding_id": "abc123", "date": "2026-09-01"}],
            today=self.TODAY)
        self.assertEqual(len(old["violations"]), 1)
        fresh = evaluate(pol, waivers=[
            {"finding_id": "abc123", "waived_at": "2026-10-20"}],
            today=self.TODAY)
        self.assertEqual(fresh["violations"], [])

    def test_undated_waiver_cannot_prove_freshness(self):
        pol = self.pol("[waivers]\nmax_age_days = 30\n")
        out = evaluate(pol, waivers=[{"finding_id": "abc123"}],
                       today=self.TODAY)
        self.assertEqual(len(out["violations"]), 1)
        self.assertIn("no usable date",
                      out["violations"][0]["detail"])

    def test_malformed_waiver_is_a_violation(self):
        pol = self.pol("[waivers]\nrequire_reason = true\n")
        out = evaluate(pol, waivers=["abc123"], today=self.TODAY)
        self.assertEqual(len(out["violations"]), 1)
        self.assertEqual(out["violations"][0]["rule"],
                         "waivers.shape")


class GateIntegrationTests(unittest.TestCase):
    def pol(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            return load(tmp, text)

    def test_no_policy_no_policy_section(self):
        rep = core.run_review(
            CLEAN, {"a": pass_provider, "b": pass_provider})
        self.assertEqual(rep["gate"], "pass")
        self.assertNotIn("policy", rep)

    def test_satisfied_policy_records_applied_rules(self):
        pol = self.pol("[panel]\nmin_seats = 2\n")
        rep = core.run_review(
            CLEAN, {"a": pass_provider, "b": pass_provider},
            policy=pol)
        self.assertEqual(rep["gate"], "pass")
        self.assertEqual(rep["policy"]["violations"], [])
        self.assertEqual(rep["policy"]["applied"][0]["rule"],
                         "panel.min_seats")
        self.assertTrue(any("policy" in r and "applied" in r
                            for r in rep["gate_reasons"]))

    def test_blocking_violation_blocks_a_passing_review(self):
        pol = self.pol("[panel]\nmin_seats = 3\n")
        rep = core.run_review(
            CLEAN, {"a": pass_provider, "b": pass_provider},
            policy=pol)
        self.assertEqual(rep["gate"], "blocked")
        self.assertTrue(any("policy violation" in r
                            for r in rep["gate_reasons"]))
        self.assertEqual(rep["policy"]["violations"][0]["rule"],
                         "panel.min_seats")

    def test_required_family_uses_seat_meta(self):
        pol = self.pol("[panel]\nrequired_families = [\"google\"]\n")
        meta = {"a": {"family": "google", "tier": "paid"},
                "b": {"family": "openai", "tier": "paid"}}
        rep = core.run_review(
            CLEAN, {"a": pass_provider, "b": pass_provider},
            seat_meta=meta, policy=pol)
        self.assertEqual(rep["gate"], "pass")
        meta2 = {"a": {"family": "nvidia", "tier": "paid"},
                 "b": {"family": "openai", "tier": "paid"}}
        rep = core.run_review(
            CLEAN, {"a": pass_provider, "b": pass_provider},
            seat_meta=meta2, policy=pol)
        self.assertEqual(rep["gate"], "blocked")

    def test_auth_path_rule_blocks_without_tests(self):
        pol = self.pol("[[paths]]\nmatch = \"auth/**\"\n"
                       "require_tests_pass = true\n")
        rep = core.run_review(
            AUTH, {"a": pass_provider, "b": pass_provider},
            policy=pol)
        self.assertEqual(rep["gate"], "blocked")
        self.assertEqual(rep["policy"]["violations"][0]["rule"],
                         "paths[auth/**].require_tests_pass")
        # The same policy does not touch a non-auth change.
        rep = core.run_review(
            CLEAN, {"a": pass_provider, "b": pass_provider},
            policy=pol)
        self.assertEqual(rep["gate"], "pass")
        self.assertEqual(rep["policy"]["applied"], [])

    def test_advisory_violation_never_blocks(self):
        pol = self.pol("[[paths]]\nmatch = \"app/**\"\n"
                       "min_families = 2\nenforce = \"advisory\"\n")
        rep = core.run_review(
            CLEAN, {"a": pass_provider, "b": pass_provider},
            policy=pol)
        self.assertEqual(rep["gate"], "pass")
        self.assertEqual(len(rep["policy"]["violations"]), 1)
        self.assertTrue(any("policy advisory" in r
                            for r in rep["gate_reasons"]))

    def test_markdown_renders_policy_section(self):
        pol = self.pol("[panel]\nmin_seats = 3\n")
        rep = core.run_review(
            CLEAN, {"a": pass_provider, "b": pass_provider},
            policy=pol)
        md = core.render_markdown(rep)
        self.assertIn("Policy:", md)
        self.assertIn("panel.min_seats", md)


class PolicyCheckCliTests(unittest.TestCase):
    def run_cli(self, argv, **kw):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(argv, **kw)
        return rc, out.getvalue(), err.getvalue()

    def test_check_without_file_prints_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, _ = self.run_cli(
                ["policy", "check", "--repo", tmp])
            self.assertEqual(rc, 0)
            self.assertIn("default policy", out)
            self.assertIn("min_seats = 0", out)

    def test_check_with_valid_file_prints_effective(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_policy(tmp, "[panel]\nmin_seats = 2\n"
                              "[[paths]]\nmatch = \"auth/**\"\n"
                              "require_tests_pass = true\n")
            rc, out, _ = self.run_cli(
                ["policy", "check", "--repo", tmp])
            self.assertEqual(rc, 0)
            self.assertIn("is valid", out)
            self.assertIn("min_seats = 2", out)
            self.assertIn('match = "auth/**"', out)
            # Defaults are filled in, not omitted.
            self.assertIn("max_age_days = 0", out)

    def test_check_with_invalid_file_fails_with_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_policy(tmp, "[panel]\nmin_seats = \"two\"\n")
            rc, _, err = self.run_cli(
                ["policy", "check", "--repo", tmp])
            self.assertEqual(rc, 2)
            self.assertIn(":2:", err)

    def test_check_explicit_policy_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_policy(tmp, "[evidence]\n"
                                     "require_tests = true\n",
                                name="custom.toml")
            rc, out, _ = self.run_cli(
                ["policy", "check", "--policy", path])
            self.assertEqual(rc, 0)
            self.assertIn("require_tests = true", out)

    def test_policy_without_subcommand_is_usage_error(self):
        rc, _, err = self.run_cli(["policy"])
        self.assertEqual(rc, 2)
        self.assertIn("usage:", err)


class ReviewCliPolicyTests(unittest.TestCase):
    def run_cli(self, argv, **kw):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(argv, **kw)
        return rc, out.getvalue(), err.getvalue()

    def _patch_file(self, tmp, text=CLEAN):
        path = os.path.join(tmp, "change.diff")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_discovered_policy_blocks_the_cli_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_policy(tmp, "[panel]\nmin_seats = 5\n")
            patch = self._patch_file(tmp)
            old = os.getcwd()
            os.chdir(tmp)
            try:
                rc, out, err = self.run_cli(
                    ["--patch", patch, "--out",
                     os.path.join(tmp, "out")],
                    providers_override={"a": pass_provider,
                                        "b": pass_provider})
            finally:
                os.chdir(old)
            self.assertEqual(rc, 1)
            self.assertIn("project policy", err)

    def test_explicit_policy_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy_path = write_policy(
                tmp, "[panel]\nmin_seats = 5\n", name="p.toml")
            patch = self._patch_file(tmp)
            outdir = os.path.join(tmp, "out")
            rc, _, _ = self.run_cli(
                ["--patch", patch, "--policy", policy_path,
                 "--out", outdir],
                providers_override={"a": pass_provider,
                                    "b": pass_provider})
            self.assertEqual(rc, 1)
            records = [f for f in os.listdir(outdir)
                       if f.endswith(".json")]
            self.assertEqual(len(records), 1)
            with open(os.path.join(outdir, records[0]),
                      encoding="utf-8") as fh:
                record = json.load(fh)
            self.assertEqual(record["gate"], "blocked")
            self.assertEqual(
                record["policy"]["violations"][0]["rule"],
                "panel.min_seats")

    def test_invalid_discovered_policy_stops_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_policy(tmp, "[panel]\nmin_seats = \"two\"\n")
            patch = self._patch_file(tmp)
            old = os.getcwd()
            os.chdir(tmp)
            try:
                rc, _, err = self.run_cli(
                    ["--patch", patch, "--out",
                     os.path.join(tmp, "out")],
                    providers_override={"a": pass_provider,
                                        "b": pass_provider})
            finally:
                os.chdir(old)
            self.assertEqual(rc, 2)
            self.assertIn("could not load the project policy", err)


if __name__ == "__main__":
    unittest.main()
