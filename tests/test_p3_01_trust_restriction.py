"""P3-01 trust restriction (owner ruling 2026-11-06, option 1).

A policy DISCOVERED in the reviewed repository is the tree's
own file, not the operator's. From such a policy the gate
honours only strengthening keys; hooks and gate-weakening keys
are dropped back to defaults at load (policy.py's
apply_discovered_restrictions, driven by
DISCOVERED_POLICY_RESTRICTED_KEYS) unless the operator names
the policy with --policy or passes --trust-repo-policy. Every
dropped key is named in the record's policy.ignored_keys, in
the CLI's stderr warning, and in the MCP payload's
policy_ignored_keys.

These tests fail on the pre-restriction code (where a
discovered policy governed in full) and pass after.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "src"))

from codereview import cli, mcp_tools  # noqa: E402
from codereview import policy as policy_mod  # noqa: E402

PASS_VERDICT = json.dumps({"verdict": "pass", "summary": "ok",
                           "findings": []})


def pass_provider(_prompt):
    return PASS_VERDICT


SIMPLE_PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,2 @@\n"
    " x = 1\n"
    "+y = 2\n")


def run_cli(argv, **kw):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv, **kw)
    return rc, out.getvalue(), err.getvalue()


def read_record(outdir):
    records = [f for f in os.listdir(outdir)
               if f.endswith(".json")]
    assert len(records) == 1, records
    with open(os.path.join(outdir, records[0]),
              encoding="utf-8") as fh:
        return json.load(fh)


def _toml_str(value):
    return '"' + value.replace("\\", "\\\\").replace(
        '"', '\\"') + '"'


class RestrictionFunctionTests(unittest.TestCase):
    """policy.apply_discovered_restrictions, unit level."""

    def _load(self, tmp, text, name=".codereview.toml"):
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return policy_mod.load_policy(path)

    def test_all_weakening_keys_dropped_and_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._load(tmp, (
                "[panel]\nmin_seats = 2\n"
                "[gate]\nprofile = \"balanced\"\n"
                "[[paths]]\nmatch = \"app.py\"\n"
                "require_tests = true\nenforce = \"advisory\"\n"
                "[waivers]\nallow = true\n"
                "require_reason = false\nmax_age_days = 0\n"
                "[diversity]\nmin_families = 2\n"
                "exclude_builder_family = true\n"
                "enforce = \"degrade\"\n"
                "[hooks]\npre_run = \"touch /tmp/never\"\n"
                "timeout = 30\n"
                "[risk]\nenabled = true\ntiering = true\n"
                "prescreen_seats = [\"a\"]\n"
                "medium_seats = [\"a\", \"b\"]\n"))
            ignored = policy_mod.apply_discovered_restrictions(
                policy)
            self.assertEqual(ignored, [
                "diversity.enforce",
                "diversity.exclude_builder_family",
                "gate.profile",
                "hooks.pre_run",
                "hooks.timeout",
                "paths[app.py].enforce",
                "risk.medium_seats",
                "risk.prescreen_seats",
                "risk.tiering",
                "waivers.allow",
                "waivers.max_age_days",
                "waivers.require_reason",
            ])
            self.assertEqual(policy["ignored_keys"], ignored)
            # Dropped values are back at their defaults.
            self.assertEqual(policy["hooks"], {
                "pre_run": None, "post_verdict": None,
                "on_blocked": None, "timeout": None})
            self.assertEqual(policy["gate"]["profile"],
                             "strict")
            self.assertEqual(policy["paths"][0]["enforce"],
                             "block")
            self.assertFalse(
                policy["diversity"]["exclude_builder_family"])
            self.assertFalse(policy["risk"]["tiering"])
            self.assertEqual(policy["risk"]["prescreen_seats"],
                             [])
            self.assertEqual(policy["risk"]["medium_seats"],
                             [])
            # Strengthening keys are untouched.
            self.assertEqual(policy["panel"]["min_seats"], 2)
            self.assertEqual(policy["diversity"]["min_families"],
                             2)
            self.assertTrue(policy["paths"][0]["require_tests"])

    def test_strengthening_values_honoured_nothing_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._load(tmp, (
                "[gate]\nprofile = \"strict\"\n"
                "[waivers]\nallow = false\n"
                "require_reason = true\nmax_age_days = 30\n"
                "[diversity]\nenforce = \"block\"\n"
                "exclude_builder_family = false\n"
                "[panel]\nmin_seats = 3\n"))
            ignored = policy_mod.apply_discovered_restrictions(
                policy)
            self.assertEqual(ignored, [])
            self.assertFalse(policy["waivers"]["allow"])
            self.assertTrue(policy["waivers"]["require_reason"])
            self.assertEqual(policy["waivers"]["max_age_days"],
                             30)
            self.assertEqual(policy["diversity"]["enforce"],
                             "block")

    def test_hook_timeout_alone_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._load(
                tmp, "[hooks]\ntimeout = 5\n")
            ignored = policy_mod.apply_discovered_restrictions(
                policy)
            self.assertEqual(ignored, ["hooks.timeout"])
            self.assertIsNone(policy["hooks"]["timeout"])

    def test_default_policy_ignores_nothing(self):
        policy = policy_mod.default_policy()
        self.assertEqual(
            policy_mod.apply_discovered_restrictions(policy),
            [])


class DiscoveredPolicyCliTests(unittest.TestCase):
    """End-to-end through cli.main with a stub seat: the
    policy lives INSIDE the reviewed repo and is discovered,
    never named with --policy."""

    def _repo(self, tmp, policy_text):
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        with open(os.path.join(repo, ".codereview.toml"),
                  "w", encoding="utf-8") as fh:
            fh.write(policy_text)
        return repo

    def _run(self, tmp, repo, extra=()):
        patch = os.path.join(tmp, "change.diff")
        with open(patch, "w", encoding="utf-8") as fh:
            fh.write(SIMPLE_PATCH)
        outdir = os.path.join(tmp, "out")
        rc, out, err = run_cli(
            ["--repo", repo, "--patch", patch, "--out", outdir,
             *extra],
            providers_override={"a": pass_provider})
        return rc, read_record(outdir), err

    def test_discovered_hook_never_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "hook.log")
            repo = self._repo(tmp, (
                "[hooks]\npre_run = "
                + _toml_str(f"echo hook-ran >> {log}") + "\n"))
            rc, record, err = self._run(tmp, repo)
            self.assertEqual(rc, 0)
            self.assertFalse(os.path.exists(log))
            self.assertNotIn("hooks", record)
            self.assertNotIn("lifecycle hooks", err)
            self.assertEqual(record["policy"]["origin"],
                             "discovered-in-repo")
            self.assertEqual(record["policy"]["ignored_keys"],
                             ["hooks.pre_run"])
            self.assertEqual(record["gate"], "pass")
            # The warning counts the dropped keys and names
            # the trust flag.
            self.assertIn("1 gate-weakening key(s)", err)
            self.assertIn("--trust-repo-policy", err)

    def test_discovered_balanced_profile_stays_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(
                tmp, "[gate]\nprofile = \"balanced\"\n")
            _rc, record, _err = self._run(tmp, repo)
            self.assertEqual(
                record["gate_profile"]["profile"], "strict")
            self.assertEqual(
                record["gate_profile"]["source"], "policy")
            self.assertEqual(record["policy"]["ignored_keys"],
                             ["gate.profile"])

    def test_discovered_corroborated_profile_stays_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(
                tmp, "[gate]\nprofile = \"corroborated\"\n")
            _rc, record, _err = self._run(tmp, repo)
            self.assertEqual(
                record["gate_profile"]["profile"], "strict")
            self.assertEqual(record["policy"]["ignored_keys"],
                             ["gate.profile"])

    def test_discovered_strict_profile_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(
                tmp, "[gate]\nprofile = \"strict\"\n")
            rc, record, err = self._run(tmp, repo)
            self.assertEqual(rc, 0)
            self.assertEqual(
                record["gate_profile"]["profile"], "strict")
            self.assertEqual(record["policy"]["ignored_keys"],
                             [])
            self.assertNotIn("gate-weakening", err)

    def test_discovered_advisory_path_rule_still_blocks(self):
        # The tree asked for the violation to be advisory
        # (recorded, never gate-changing); untrusted, the
        # rule enforces at the default "block" instead.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, (
                "[[paths]]\nmatch = \"app.py\"\n"
                "require_tests = true\nenforce = \"advisory\"\n"))
            _rc, record, _err = self._run(tmp, repo)
            self.assertEqual(record["gate"], "blocked")
            self.assertEqual(record["policy"]["ignored_keys"],
                             ["paths[app.py].enforce"])
            violations = record["policy"]["violations"]
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0]["enforce"], "block")

    def test_discovered_waiver_diversity_risk_keys_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, (
                "[waivers]\nallow = true\n"
                "require_reason = false\nmax_age_days = 0\n"
                "[diversity]\nexclude_builder_family = true\n"
                "enforce = \"degrade\"\n"
                "[risk]\nenabled = true\ntiering = true\n"
                "prescreen_seats = [\"a\"]\n"))
            _rc, record, _err = self._run(tmp, repo)
            ignored = record["policy"]["ignored_keys"]
            for name in ("waivers.allow",
                         "waivers.require_reason",
                         "waivers.max_age_days",
                         "diversity.enforce",
                         "diversity.exclude_builder_family",
                         "risk.tiering",
                         "risk.prescreen_seats"):
                self.assertIn(name, ignored)
            # Tiering was dropped, so no tier plan ran.
            self.assertNotIn("tiering", record)

    def test_trust_flag_honours_discovered_policy_in_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "hook.log")
            repo = self._repo(tmp, (
                "[hooks]\npre_run = "
                + _toml_str(f"echo hook-ran >> {log}") + "\n"
                "[gate]\nprofile = \"balanced\"\n"
                "[[paths]]\nmatch = \"app.py\"\n"
                "require_tests = true\nenforce = \"advisory\"\n"))
            rc, record, err = self._run(
                tmp, repo, extra=("--trust-repo-policy",))
            self.assertEqual(rc, 0)
            with open(log, encoding="utf-8") as fh:
                self.assertIn("hook-ran", fh.read())
            self.assertEqual(
                record["gate_profile"]["profile"], "balanced")
            self.assertEqual(record["policy"]["ignored_keys"],
                             [])
            # The advisory rule was honoured: the missing-test
            # violation is recorded but does not block.
            self.assertEqual(record["gate"], "pass")
            violations = record["policy"]["violations"]
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0]["enforce"],
                             "advisory")
            self.assertNotIn("gate-weakening", err)

    def test_explicit_policy_honoured_in_full(self):
        # Regression pin: an operator-named --policy keeps
        # everything, exactly as before the restriction.
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "hook.log")
            repo = os.path.join(tmp, "repo")
            os.makedirs(repo)
            policy_path = os.path.join(tmp, "operator.toml")
            with open(policy_path, "w", encoding="utf-8") as fh:
                fh.write(
                    "[hooks]\npre_run = "
                    + _toml_str(f"echo hook-ran >> {log}") + "\n"
                    "[gate]\nprofile = \"balanced\"\n")
            patch = os.path.join(tmp, "change.diff")
            with open(patch, "w", encoding="utf-8") as fh:
                fh.write(SIMPLE_PATCH)
            outdir = os.path.join(tmp, "out")
            rc, _out, _err = run_cli(
                ["--repo", repo, "--patch", patch,
                 "--policy", policy_path, "--out", outdir],
                providers_override={"a": pass_provider})
            self.assertEqual(rc, 0)
            with open(log, encoding="utf-8") as fh:
                self.assertIn("hook-ran", fh.read())
            record = read_record(outdir)
            self.assertEqual(record["policy"]["origin"],
                             "explicit")
            self.assertEqual(record["policy"]["ignored_keys"],
                             [])
            self.assertEqual(
                record["gate_profile"]["profile"], "balanced")

    def test_strengthening_discovered_policy_still_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "[panel]\nmin_seats = 3\n")
            _rc, record, _err = self._run(tmp, repo)
            self.assertEqual(record["gate"], "blocked")
            self.assertEqual(record["policy"]["ignored_keys"],
                             [])
            rules = [v["rule"]
                     for v in record["policy"]["violations"]]
            self.assertIn("panel.min_seats", rules)


class McpTrustRestrictionTests(unittest.TestCase):
    """run_gate must surface the restriction: the CLI's stderr
    warning is discarded on success, so the dropped keys
    travel in the payload as policy_ignored_keys."""

    def _tools(self):
        return mcp_tools.GateTools(
            providers_override={"a": pass_provider})

    def _call(self, tools, arguments):
        dispatch = mcp_tools.make_dispatch(tools)
        return dispatch("tools/call",
                        {"name": "run_gate",
                         "arguments": arguments}, False)

    def _repo_with_hook(self, tmp):
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        log = os.path.join(tmp, "hook.log")
        with open(os.path.join(repo, ".codereview.toml"),
                  "w", encoding="utf-8") as fh:
            fh.write("[hooks]\npre_run = "
                     + _toml_str(f"echo hook-ran >> {log}")
                     + "\n")
        return repo, log

    def test_run_gate_payload_lists_ignored_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, log = self._repo_with_hook(tmp)
            result = self._call(self._tools(), {
                "repo": repo, "patch": SIMPLE_PATCH,
                "out": os.path.join(tmp, "out")})
            self.assertFalse(result["isError"])
            payload = result["structuredContent"]
            self.assertEqual(payload["policy_origin"],
                             "discovered-in-repo")
            self.assertEqual(payload["policy_ignored_keys"],
                             ["hooks.pre_run"])
            self.assertFalse(os.path.exists(log))

    def test_run_gate_trust_flag_honours_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, log = self._repo_with_hook(tmp)
            result = self._call(self._tools(), {
                "repo": repo, "patch": SIMPLE_PATCH,
                "out": os.path.join(tmp, "out"),
                "trust_repo_policy": True})
            self.assertFalse(result["isError"])
            payload = result["structuredContent"]
            self.assertEqual(payload["policy_ignored_keys"],
                             [])
            with open(log, encoding="utf-8") as fh:
                self.assertIn("hook-ran", fh.read())

    def test_trust_repo_policy_must_be_boolean(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _log = self._repo_with_hook(tmp)
            result = self._call(self._tools(), {
                "repo": repo, "patch": SIMPLE_PATCH,
                "out": os.path.join(tmp, "out"),
                "trust_repo_policy": "yes"})
            self.assertTrue(result["isError"])


if __name__ == "__main__":
    unittest.main()

