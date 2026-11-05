"""First-run setup (owner amendment 2026-11-04): no shipped
default panel; the user sets up their own providers and
per-role models (OpenClaw-style), saved to a per-user config.

Covers: fresh-HOME has NO effective defaults; the wizard with
scripted answers saves a spec-only config (keys never stored);
later runs resolve providers/roles from that config; explicit
flags beat the config; a non-interactive run without setup
refuses with instructions; an interactive first run launches
the wizard and proceeds with the user's choices; doctor
reports not-set-up as JSON. Plus the cross-kind role-seat
collision hardening from this track's internal review."""

import glob
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, providers, setup_wizard, userconfig  # noqa: E402

PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,1 +1,2 @@
 x = 1
+y = 2
"""


def fresh_env(tmp, **extra):
    env = {"HOME": tmp, "PATH": os.environ.get("PATH", "")}
    env.update(extra)
    return env


class FreshHomeTests(unittest.TestCase):
    def test_fresh_home_has_no_config_and_no_default_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, fresh_env(tmp),
                                 clear=True):
                self.assertIsNone(userconfig.load_user_config())
                # The core of the amendment: NOTHING resolves —
                # no silent gemini/openai panel materializes.
                self.assertEqual(
                    userconfig.default_provider_specs(), [])
                self.assertEqual(
                    userconfig.default_role_assignments(), {})

    def test_config_roundtrip_and_env_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.toml")
            with mock.patch.dict(
                    os.environ,
                    fresh_env(tmp, CODEREVIEW_CONFIG=cfg_path),
                    clear=True):
                path = userconfig.save_user_config(
                    ["deepseek", "moonshot"],
                    {"tech-lead": "deepseek"})
                self.assertEqual(path, cfg_path)
                loaded = userconfig.load_user_config()
                self.assertEqual(loaded["providers"],
                                 ["deepseek", "moonshot"])
                self.assertEqual(loaded["roles"],
                                 {"tech-lead": "deepseek"})
                self.assertEqual(
                    userconfig.default_provider_specs(),
                    ["deepseek", "moonshot"])
                with mock.patch.dict(
                        os.environ,
                        {"CODEREVIEW_PROVIDERS": "mistral"}):
                    self.assertEqual(
                        userconfig.default_provider_specs(),
                        ["mistral"])


class WizardTests(unittest.TestCase):
    def _run(self, answers, environ):
        it = iter(answers)
        printed = []
        result = setup_wizard.run_wizard(
            input_fn=lambda _prompt: next(it),
            print_fn=printed.append, environ=environ)
        return result, printed

    def test_scripted_wizard_saves_spec_only_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.toml")
            environ = fresh_env(
                tmp, CODEREVIEW_CONFIG=cfg_path,
                DEEPSEEK_API_KEY="sentinel-value-never-stored")
            result, _printed = self._run(
                ["deepseek, moonshot",  # providers
                 "",                     # correctness <- deepseek
                 "",                     # operations <- moonshot
                 "minimax",              # verifier override
                 "-",                    # tech-lead: to the panel
                 ""],                    # solver <- deepseek
                environ)
            self.assertEqual(result["providers"],
                             ["deepseek", "moonshot"])
            self.assertEqual(
                result["roles"],
                {"correctness": "deepseek",
                 "operations": "moonshot",
                 "verifier": "minimax",
                 "solver": "deepseek"})
            with open(cfg_path, encoding="utf-8") as fh:
                text = fh.read()
            # The key VALUE is never written — only specs.
            self.assertNotIn("sentinel-value-never-stored", text)
            self.assertIn("deepseek", text)
            with mock.patch.dict(os.environ, environ, clear=True):
                self.assertEqual(
                    userconfig.default_role_assignments(),
                    result["roles"])

    def test_wizard_eof_aborts_without_saving(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.toml")
            environ = fresh_env(tmp, CODEREVIEW_CONFIG=cfg_path)

            def eof(_prompt):
                raise EOFError
            with self.assertRaises(EOFError):
                setup_wizard.run_wizard(
                    input_fn=eof, print_fn=lambda _m: None,
                    environ=environ)
            self.assertFalse(os.path.exists(cfg_path))


class RunResolutionTests(unittest.TestCase):
    def _patch_file(self, tmp):
        path = os.path.join(tmp, "change.diff")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(PATCH)
        return path

    def test_non_interactive_run_without_setup_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = self._patch_file(tmp)
            err = io.StringIO()
            with mock.patch.dict(os.environ, fresh_env(tmp),
                                 clear=True), \
                    mock.patch.object(sys, "stdin",
                                      io.StringIO("")), \
                    redirect_stderr(err):
                rc = cli.main(["--patch", patch, "--out",
                               os.path.join(tmp, "out")])
            self.assertEqual(rc, 2)
            self.assertIn("not set up", err.getvalue())
            self.assertIn("codereview setup", err.getvalue())

    def test_doctor_without_setup_reports_json_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.dict(os.environ, fresh_env(tmp),
                                 clear=True), \
                    redirect_stdout(out):
                rc = cli._doctor_main([])
            self.assertEqual(rc, 2)
            result = json.loads(out.getvalue())
            self.assertFalse(result["ok"])
            self.assertIn("not set up", result["error"])

    def test_interactive_first_run_wizards_then_reviews(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = self._patch_file(tmp)
            cfg_path = os.path.join(tmp, "config.toml")
            environ = fresh_env(tmp, CODEREVIEW_CONFIG=cfg_path)

            def fake_wizard():
                return userconfig.save_user_config(
                    ["agent:echo:cat"],
                    {"correctness": "agent:echo:cat"})

            with mock.patch.dict(os.environ, environ,
                                 clear=True), \
                    mock.patch.object(cli, "_stdin_is_tty",
                                      lambda: True), \
                    mock.patch.object(cli, "_run_setup_wizard",
                                      fake_wizard):
                rc = cli.main(["--patch", patch, "--out",
                               os.path.join(tmp, "out")])
            # The echo seat answers with the prompt (not JSON),
            # so the gate is inconclusive — but the run HAPPENED
            # with the user's setup, and the record proves it.
            self.assertEqual(rc, 2)
            records = glob.glob(
                os.path.join(tmp, "out", "codereview-*.json"))
            self.assertEqual(len(records), 1)
            with open(records[0], encoding="utf-8") as fh:
                record = json.load(fh)
            self.assertEqual(record["seat_roles"],
                             {"correctness": "echo"})
            self.assertIn(
                "echo",
                {r["provider"]
                 for r in record["reviewer_reports"]})

    def test_aborted_first_run_wizard_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = self._patch_file(tmp)
            err = io.StringIO()

            def aborting_wizard():
                raise EOFError

            with mock.patch.dict(os.environ, fresh_env(tmp),
                                 clear=True), \
                    mock.patch.object(cli, "_stdin_is_tty",
                                      lambda: True), \
                    mock.patch.object(cli, "_run_setup_wizard",
                                      aborting_wizard), \
                    redirect_stderr(err):
                rc = cli.main(["--patch", patch, "--out",
                               os.path.join(tmp, "out")])
            self.assertEqual(rc, 2)
            self.assertIn("setup did not complete",
                          err.getvalue())

    def test_saved_setup_supplies_providers_and_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = self._patch_file(tmp)
            cfg_path = os.path.join(tmp, "config.toml")
            environ = fresh_env(tmp, CODEREVIEW_CONFIG=cfg_path)
            userconfig.save_user_config(
                ["agent:echo:cat"],
                {"operations": "agent:echo:cat"},
                environ=environ)
            with mock.patch.dict(os.environ, environ,
                                 clear=True), \
                    mock.patch.object(cli, "_stdin_is_tty",
                                      lambda: False):
                rc = cli.main(["--patch", patch, "--out",
                               os.path.join(tmp, "out")])
            self.assertEqual(rc, 2)  # echo seat: inconclusive
            records = glob.glob(
                os.path.join(tmp, "out", "codereview-*.json"))
            self.assertEqual(len(records), 1)
            with open(records[0], encoding="utf-8") as fh:
                record = json.load(fh)
            self.assertEqual(record["seat_roles"],
                             {"operations": "echo"})


class CrossKindRoleCollisionTests(unittest.TestCase):
    def test_agent_role_seat_cannot_shadow_an_api_seat(self):
        panel = providers.build_providers(["gemini"])
        with self.assertRaises(providers.ProviderError):
            cli._apply_role_assignments(
                panel, ["tech-lead=agent:gemini:cat"])

    def test_api_role_seat_cannot_shadow_an_agent_seat(self):
        panel = providers.build_providers(["agent:claude:cat"])
        with self.assertRaises(providers.ProviderError):
            cli._apply_role_assignments(
                panel,
                ["correctness=claude|openai-compatible|"
                 "https://example.com/v1|m|SOME_KEY_ENV"])

    def test_same_kind_same_name_still_merges(self):
        panel = providers.build_providers(["gemini"])
        _lens, seat_roles, _models, _tl = \
            cli._apply_role_assignments(
                panel, ["tech-lead=gemini"])
        self.assertEqual(seat_roles["tech-lead"], "gemini")
        self.assertEqual(set(panel), {"gemini"})


if __name__ == "__main__":
    unittest.main()
