"""Review modes and the same-vendor warning (improvement plan
2026-11-11, owner decision: "User could choose single reviewer
mode, or multiple reviewer mode at their discretion").

Covers: the registry helpers (mode names, seat-count rule,
builder-family aliases, same-vendor matching); the saved setup's
new top-level keys (round trip, byte-identical default, loud
validation); the wizard with ask_mode (single default, single
refuses two seats, panel refuses one seat and keeps the role
step, same-vendor warning); and the gate CLI refusing a seat
count that does not fit --review-mode before anything is sent.

Written and not yet run by its author in the authoring sandbox:
see docs/IMPROVEMENT_PLAN.md, "Verification status"."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, registry, setup_wizard, userconfig  # noqa: E402

PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,1 +1,2 @@
 x = 1
+y = 2
"""


def fresh_env(tmp, **extra):
    # PATH pinned to the empty temp dir: discovery finds no
    # agent CLIs, so the scripted answers below stay aligned.
    env = {"HOME": tmp, "PATH": tmp}
    env.update(extra)
    return env


class RegistryHelperTests(unittest.TestCase):
    def test_mode_names_and_aliases(self):
        self.assertEqual(registry.normalize_review_mode("single"),
                         "single")
        self.assertEqual(registry.normalize_review_mode("Solo"),
                         "single")
        self.assertEqual(registry.normalize_review_mode("multi"),
                         "panel")
        self.assertIsNone(registry.normalize_review_mode(""))
        self.assertIsNone(registry.normalize_review_mode(None))
        with self.assertRaises(ValueError):
            registry.normalize_review_mode("quorum")
        self.assertEqual(registry.DEFAULT_REVIEW_MODE, "single")

    def test_seat_count_rule(self):
        self.assertIsNone(registry.review_mode_error(1, "single"))
        self.assertIn("exactly one",
                      registry.review_mode_error(2, "single"))
        self.assertIsNone(registry.review_mode_error(2, "panel"))
        self.assertIn("at least two",
                      registry.review_mode_error(1, "panel"))
        # No mode = no constraint (the pre-mode behaviour).
        self.assertIsNone(registry.review_mode_error(5, None))

    def test_builder_family_aliases(self):
        self.assertEqual(
            registry.normalize_builder_family("Claude Code"),
            "anthropic")
        self.assertEqual(registry.normalize_builder_family("codex"),
                         "openai")
        self.assertEqual(registry.normalize_builder_family("gemini"),
                         "google")
        self.assertEqual(registry.normalize_builder_family("acme"),
                         "acme")
        self.assertIsNone(registry.normalize_builder_family("  "))

    def test_same_vendor_matching(self):
        seats = {"anthropic": "anthropic", "gemini": "google",
                 "bot": "agent", "box": "local"}
        self.assertEqual(
            registry.same_vendor_seats(seats, "claude"),
            ["anthropic"])
        self.assertEqual(registry.same_vendor_seats(seats, "xai"), [])
        # Unattributable families never match.
        self.assertEqual(registry.same_vendor_seats(seats, "agent"),
                         [])
        self.assertEqual(registry.same_vendor_seats(seats, "local"),
                         [])
        self.assertEqual(registry.same_vendor_seats(seats, None), [])


class UserConfigModeTests(unittest.TestCase):
    def test_round_trip_and_default_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "config.toml")
            env = fresh_env(tmp, CODEREVIEW_CONFIG=cfg)
            with mock.patch.dict(os.environ, env, clear=True):
                userconfig.save_user_config(["deepseek"], {})
                with open(cfg, encoding="utf-8") as fh:
                    plain = fh.read()
                self.assertNotIn("review_mode", plain)
                self.assertNotIn("builder_family", plain)
                self.assertIsNone(userconfig.default_review_mode())
                userconfig.save_user_config(
                    ["deepseek"], {}, review_mode="single",
                    builder_family="Claude")
                loaded = userconfig.load_user_config()
                self.assertEqual(loaded["review_mode"], "single")
                self.assertEqual(loaded["builder_family"],
                                 "anthropic")
                self.assertEqual(userconfig.default_review_mode(),
                                 "single")
                self.assertEqual(
                    userconfig.default_builder_family(),
                    "anthropic")

    def test_mode_that_does_not_fit_the_saved_panel_is_loud(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "config.toml")
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write('providers = ["deepseek", "moonshot"]\n'
                         'review_mode = "single"\n')
            env = fresh_env(tmp, CODEREVIEW_CONFIG=cfg)
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ValueError) as ctx:
                    userconfig.load_user_config()
                self.assertIn("exactly one", str(ctx.exception))

    def test_bad_mode_value_is_loud(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "config.toml")
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write('providers = ["deepseek"]\n'
                         'review_mode = "quorum"\n')
            env = fresh_env(tmp, CODEREVIEW_CONFIG=cfg)
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ValueError):
                    userconfig.load_user_config()


class WizardModeTests(unittest.TestCase):
    def _run(self, answers, environ):
        it = iter(answers)
        printed = []
        result = setup_wizard.run_wizard(
            input_fn=lambda _prompt: next(it),
            print_fn=printed.append, environ=environ,
            discover_fn=lambda: [], ask_mode=True)
        return result, printed

    def test_single_is_the_default_and_warns_same_vendor(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "config.toml")
            env = fresh_env(tmp, CODEREVIEW_CONFIG=cfg)
            result, printed = self._run(
                ["",            # mode: Enter -> single
                 "anthropic",   # the one reviewer
                 "claude"],     # coding agent's vendor
                env)
            self.assertEqual(result["review_mode"], "single")
            self.assertEqual(result["providers"], ["anthropic"])
            self.assertEqual(result["roles"], {})
            self.assertEqual(result["builder_family"], "anthropic")
            self.assertTrue(any("Same-vendor check: anthropic is "
                                "from anthropic" in line
                                for line in printed), printed)
            with open(cfg, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn('review_mode = "single"', text)
            self.assertIn('builder_family = "anthropic"', text)

    def test_single_refuses_two_seats_then_accepts_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fresh_env(
                tmp, CODEREVIEW_CONFIG=os.path.join(tmp, "c.toml"))
            result, printed = self._run(
                ["1", "deepseek, moonshot", "deepseek", ""], env)
            self.assertEqual(result["providers"], ["deepseek"])
            self.assertIsNone(result["builder_family"])
            self.assertTrue(any("exactly one" in line
                                for line in printed))

    def test_panel_needs_two_seats_and_keeps_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fresh_env(
                tmp, CODEREVIEW_CONFIG=os.path.join(tmp, "c.toml"))
            result, printed = self._run(
                ["2", "deepseek", "deepseek, moonshot",
                 "openai",                 # builder: no match
                 "", "", "", "", ""],      # five role prompts
                env)
            self.assertEqual(result["review_mode"], "panel")
            self.assertEqual(result["providers"],
                             ["deepseek", "moonshot"])
            self.assertEqual(result["builder_family"], "openai")
            self.assertEqual(len(result["roles"]), 5)
            self.assertTrue(any("at least two" in line
                                for line in printed))
            self.assertTrue(any("no reviewer seat is from openai"
                                in line for line in printed))

    def test_without_ask_mode_the_flow_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fresh_env(
                tmp, CODEREVIEW_CONFIG=os.path.join(tmp, "c.toml"))
            it = iter(["deepseek, moonshot", "", "", "", "", ""])
            result = setup_wizard.run_wizard(
                input_fn=lambda _p: next(it),
                print_fn=lambda _m: None, environ=env,
                discover_fn=lambda: [])
            self.assertNotIn("review_mode", result)
            with open(result["path"], encoding="utf-8") as fh:
                self.assertNotIn("review_mode", fh.read())


class GateModeRefusalTests(unittest.TestCase):
    def test_single_mode_refuses_two_providers_before_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = os.path.join(tmp, "c.diff")
            with open(patch, "w", encoding="utf-8") as fh:
                fh.write(PATCH)
            env = fresh_env(tmp)
            err = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=True), \
                    redirect_stderr(err), \
                    redirect_stdout(io.StringIO()):
                rc = cli.main(["--patch", patch,
                               "--provider", "deepseek",
                               "--provider", "moonshot",
                               "--review-mode", "single",
                               "--out", os.path.join(tmp, "out")])
            self.assertEqual(rc, 2)
            self.assertIn("exactly one", err.getvalue())

    def test_panel_mode_refuses_one_provider_before_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = os.path.join(tmp, "c.diff")
            with open(patch, "w", encoding="utf-8") as fh:
                fh.write(PATCH)
            err = io.StringIO()
            with mock.patch.dict(os.environ, fresh_env(tmp),
                                 clear=True), \
                    redirect_stderr(err), \
                    redirect_stdout(io.StringIO()):
                rc = cli.main(["--patch", patch,
                               "--provider", "deepseek",
                               "--review-mode", "panel",
                               "--out", os.path.join(tmp, "out")])
            self.assertEqual(rc, 2)
            self.assertIn("at least two", err.getvalue())

    def test_same_vendor_warning_helper(self):
        err = io.StringIO()
        with redirect_stderr(err):
            same = cli._same_vendor_warning(
                {"anthropic": "anthropic", "gemini": "google"},
                "claude", "codereview")
        self.assertEqual(same, ["anthropic"])
        self.assertIn("share", err.getvalue())
        self.assertIn("'anthropic'", err.getvalue())

    def test_builder_family_from_loop_command(self):
        self.assertEqual(
            cli._builder_family_from_cmd("claude -p 'fix it'"),
            "anthropic")
        self.assertEqual(
            cli._builder_family_from_cmd("/usr/local/bin/codex exec -"),
            "openai")
        self.assertIsNone(cli._builder_family_from_cmd("./my-agent.sh"))
        self.assertIsNone(cli._builder_family_from_cmd("'unclosed"))


if __name__ == "__main__":
    unittest.main()
