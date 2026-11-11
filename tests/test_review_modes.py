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

Review 2026-11-11 (Mike) added: the single-mode discovery dead
end, the wizard's own wording (no gate flags), --review-mode on
the providers_override path, and end-to-end runs of the gate's
and the loop's same-vendor warning and the loop's mode handling.

Not run by its author in the authoring sandbox: see
docs/IMPROVEMENT_PLAN.md, "Verification status"."""

import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import (cli, discovery, registry,  # noqa: E402
                        setup_wizard, userconfig)

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


PASS_VERDICT = json.dumps({"verdict": "pass", "summary": "ok",
                           "findings": []})


def _entry(name, path):
    base = next(e for e in discovery.KNOWN_CLIS
                if e["name"] == name)
    return {**base, "path": path, "probe_ok": True,
            "probe_detail": "1.0"}


TWO_CLIS = [_entry("claude", "/fake/bin/claude"),
            _entry("codex", "/fake/bin/codex")]
CLAUDE = discovery.seat_spec(TWO_CLIS[0])
CODEX = discovery.seat_spec(TWO_CLIS[1])


def _assert_no_gate_flags(case, printed):
    # Inside the wizard the user answers prompts; a message that
    # tells them to pass a gate flag sends them nowhere.
    for line in printed:
        case.assertNotIn("--provider", line)
        case.assertNotIn("--review-mode", line)


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
            self.assertTrue(any("uses one seat" in line
                                for line in printed), printed)
            _assert_no_gate_flags(self, printed)

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


class WizardDiscoveryModeTests(unittest.TestCase):
    """Review 2026-11-11 item 1: single mode with two discovered
    CLIs used to dead-end (Enter refused, the one seat typed by
    hand skipped as a duplicate, an API seat made three, abort
    after three tries with nothing saved)."""

    def _run(self, answers, tmp):
        env = fresh_env(
            tmp, CODEREVIEW_CONFIG=os.path.join(tmp, "c.toml"))
        it = iter(answers)
        printed = []
        result = setup_wizard.run_wizard(
            input_fn=lambda _prompt: next(it),
            print_fn=printed.append, environ=env,
            discover_fn=lambda: list(TWO_CLIS), ask_mode=True)
        return result, printed

    def test_single_asking_for_both_is_reasked_then_saves_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, printed = self._run(
                ["",        # mode: single
                 "1, 2",    # both CLIs: refused in wizard words
                 "1",       # keep Claude Code only
                 "",        # provider prompt: Enter keeps it
                 "openai"],  # builder vendor
                tmp)
            self.assertEqual(result["review_mode"], "single")
            self.assertEqual(result["providers"], [CLAUDE])
            self.assertTrue(os.path.exists(result["path"]))
            self.assertTrue(any("uses one seat" in line
                                for line in printed), printed)
            _assert_no_gate_flags(self, printed)

    def test_single_typed_provider_replaces_the_discovered_seat(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, printed = self._run(
                ["", "1", "deepseek", ""], tmp)
            self.assertEqual(result["providers"], ["deepseek"])
            self.assertTrue(any("instead of" in line
                                for line in printed), printed)

    def test_panel_typed_at_discovery_keeps_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, printed = self._run(
                ["",        # mode: single
                 "panel",   # switch at the discovery prompt
                 "1, 2",    # both CLIs
                 "",        # provider prompt: keep both
                 "",        # builder vendor: skip
                 "", "", "", "", ""],  # five role prompts
                tmp)
            self.assertEqual(result["review_mode"], "panel")
            self.assertEqual(result["providers"], [CLAUDE, CODEX])
            self.assertTrue(any("Switched to a multi-reviewer"
                                in line for line in printed))
            with open(result["path"], encoding="utf-8") as fh:
                self.assertIn('review_mode = "panel"', fh.read())

    def test_panel_typed_at_the_provider_prompt_switches(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, printed = self._run(
                ["", "1", "panel", "deepseek", "",
                 "", "", "", "", ""], tmp)
            self.assertEqual(result["review_mode"], "panel")
            self.assertEqual(result["providers"],
                             [CLAUDE, "deepseek"])
            _assert_no_gate_flags(self, printed)


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


class OverridePathModeTests(unittest.TestCase):
    """Review 2026-11-11: --review-mode used to be silently
    ignored on the internal providers_override path."""

    def test_gate_override_refuses_a_mismatch_before_any_call(self):
        calls = []

        def seat(_prompt):
            calls.append(1)
            return PASS_VERDICT

        with tempfile.TemporaryDirectory() as tmp:
            patch = os.path.join(tmp, "c.diff")
            with open(patch, "w", encoding="utf-8") as fh:
                fh.write(PATCH)
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                rc = cli.main(
                    ["--patch", patch, "--review-mode", "single",
                     "--out", os.path.join(tmp, "out")],
                    providers_override={"a": seat, "b": seat})
            self.assertEqual(rc, 2)
            self.assertIn("exactly one", err.getvalue())
            self.assertEqual(calls, [])

    def test_loop_override_refuses_a_mismatch_before_any_call(self):
        calls = []

        def seat(_prompt):
            calls.append(1)
            return PASS_VERDICT

        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                rc = cli.main(
                    ["loop", "--repo", tmp, "--builder-cmd", "true",
                     "--review-mode", "panel",
                     "--out", os.path.join(tmp, "out")],
                    providers_override={"a": seat})
            self.assertEqual(rc, 2)
            self.assertIn("at least two", err.getvalue())
            self.assertEqual(calls, [])


class GateSameVendorEndToEndTests(unittest.TestCase):
    def test_warning_reaches_stderr_and_the_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = os.path.join(tmp, "c.diff")
            with open(patch, "w", encoding="utf-8") as fh:
                fh.write(PATCH)
            out = os.path.join(tmp, "out")
            err = io.StringIO()
            # Real PATH (the run may shell out); no saved setup.
            env = dict(os.environ, HOME=tmp,
                       CODEREVIEW_CONFIG=os.path.join(
                           tmp, "none.toml"))
            with mock.patch.dict(os.environ, env, clear=True), \
                    redirect_stderr(err), \
                    redirect_stdout(io.StringIO()):
                rc = cli.main(
                    ["--patch", patch, "--out", out,
                     "--builder-family", "claude",
                     "--review-mode", "single"],
                    providers_override={
                        "anthropic": lambda _p: PASS_VERDICT},
                    seat_meta_override={
                        "anthropic": {"family": "anthropic",
                                      "tier": "paid"}})
            self.assertEqual(rc, 0, err.getvalue())
            self.assertIn("share", err.getvalue())
            self.assertIn("'anthropic'", err.getvalue())
            records = [f for f in os.listdir(out)
                       if f.endswith(".json")]
            self.assertEqual(len(records), 1, records)
            with open(os.path.join(out, records[0]),
                      encoding="utf-8") as fh:
                record = json.load(fh)
            setup = record.get("review_setup") or {}
            self.assertEqual(setup.get("review_mode"), "single")
            self.assertEqual(setup.get("builder_family"),
                             "anthropic")
            self.assertEqual(setup.get("same_vendor_seats"),
                             ["anthropic"])
            self.assertEqual(record.get("gate"), "pass")

    def test_other_vendor_seat_draws_no_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = os.path.join(tmp, "c.diff")
            with open(patch, "w", encoding="utf-8") as fh:
                fh.write(PATCH)
            err = io.StringIO()
            # Real PATH (the run may shell out); no saved setup.
            env = dict(os.environ, HOME=tmp,
                       CODEREVIEW_CONFIG=os.path.join(
                           tmp, "none.toml"))
            with mock.patch.dict(os.environ, env, clear=True), \
                    redirect_stderr(err), \
                    redirect_stdout(io.StringIO()):
                rc = cli.main(
                    ["--patch", patch,
                     "--out", os.path.join(tmp, "out"),
                     "--builder-family", "claude"],
                    providers_override={
                        "deepseek": lambda _p: PASS_VERDICT},
                    seat_meta_override={
                        "deepseek": {"family": "deepseek",
                                     "tier": "paid"}})
            self.assertEqual(rc, 0, err.getvalue())
            self.assertNotIn("same-vendor review", err.getvalue())


@unittest.skipUnless(shutil.which("git"), "needs git")
class LoopEndToEndTests(unittest.TestCase):
    """The loop's mode handling and run-time same-vendor
    warning, driven through cli.main(["loop", ...])."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        git = ["git", "-C", self.repo, "-c", "user.name=t",
               "-c", "user.email=t@example.invalid",
               "-c", "commit.gpgsign=false"]
        subprocess.run(git[:3] + ["init", "-q"], check=True)
        with open(os.path.join(self.repo, "app.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("x = 1\n")
        subprocess.run(git + ["add", "app.py"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "init"],
                       check=True)
        with open(os.path.join(self.repo, "app.py"), "a",
                  encoding="utf-8") as fh:
            fh.write("y = 2\n")
        # A stand-in coding agent named like Claude Code: it
        # only records that it ran. Never the real CLI.
        bindir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bindir)
        self.marker = os.path.join(self.tmp.name, "builder-ran")
        self.builder = os.path.join(bindir, "claude")
        with open(self.builder, "w", encoding="utf-8") as fh:
            fh.write(f"#!/bin/sh\ntouch '{self.marker}'\n")
        os.chmod(self.builder, os.stat(self.builder).st_mode
                 | stat.S_IXUSR)
        self.env = dict(
            os.environ, HOME=self.tmp.name,
            CODEREVIEW_CONFIG=os.path.join(self.tmp.name,
                                           "c.toml"))
        self.env.pop("CODEREVIEW_PROVIDERS", None)
        self.env.pop("REVIEWLOOP_PROVIDERS", None)

    def tearDown(self):
        self.tmp.cleanup()

    def _loop(self, extra, providers_override=None):
        err = io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), \
                redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = cli.main(
                ["loop", "--repo", self.repo,
                 "--builder-cmd", self.builder,
                 "--out", os.path.join(self.tmp.name, "out"),
                 *extra],
                providers_override=providers_override)
        return rc, err.getvalue()

    def test_single_with_two_providers_is_refused_before_any_round(self):
        rc, err = self._loop(["--provider", "deepseek",
                              "--provider", "moonshot",
                              "--review-mode", "single"])
        self.assertEqual(rc, 2)
        self.assertIn("exactly one", err)
        self.assertFalse(os.path.exists(self.marker))

    def test_flag_overrides_the_saved_mode(self):
        with open(self.env["CODEREVIEW_CONFIG"], "w",
                  encoding="utf-8") as fh:
            fh.write('providers = ["deepseek"]\n'
                     'review_mode = "single"\n')
        rc, err = self._loop(["--review-mode", "panel"])
        self.assertEqual(rc, 2)
        self.assertIn("at least two", err)
        self.assertFalse(os.path.exists(self.marker))

    def test_saved_mode_that_does_not_fit_is_refused(self):
        with open(self.env["CODEREVIEW_CONFIG"], "w",
                  encoding="utf-8") as fh:
            fh.write('providers = ["deepseek", "moonshot"]\n'
                     'review_mode = "single"\n')
        rc, err = self._loop([])
        self.assertEqual(rc, 2)
        self.assertIn("exactly one", err)

    def test_same_vendor_warning_from_the_builder_command(self):
        rc, err = self._loop(
            ["--review-mode", "single"],
            providers_override={
                "anthropic": lambda _p: PASS_VERDICT})
        self.assertIn("codereview loop: warning", err)
        self.assertIn("'anthropic'", err)
        self.assertTrue(os.path.exists(os.path.join(
            self.tmp.name, "out", "loop-result.json")), err)
        self.assertEqual(rc, 0, err)

    def test_explicit_builder_family_wins_over_the_command(self):
        rc, err = self._loop(
            ["--builder-family", "openai"],
            providers_override={
                "anthropic": lambda _p: PASS_VERDICT})
        self.assertNotIn("codereview loop: warning", err)
        self.assertEqual(rc, 0, err)


if __name__ == "__main__":
    unittest.main()
