"""Epic K1 — setup CLI discovery.

Discovery (discovery.py) scans PATH for known agent CLIs and
the wizard offers the found ones as agent seats. Every test
fakes the machine: temp-dir PATHs with stub executables,
injected which/probe functions, canned discover_fn results —
no test depends on the real PATH contents of the machine
running the suite.

Covers the spec's §3.3 criteria: detection iff present +
executable; scripted-wizard pick -> the exact saved agent
spec; decline -> saved config identical to a no-discovery run;
empty PATH -> today's flow plus exactly one line; the
family-diversity guard; EOF at the new prompts saves nothing;
a failed probe is reported, never smoothed over; a found CLI
without a verified seat command is reported, not offered.
"""

import glob
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, discovery, setup_wizard, userconfig  # noqa: E402

# The exact spec a confirmed Claude Code pick must save — the
# command is the shipped example wrapper's invocation
# (examples/agent-seat-claude.sh), pinned literally so a silent
# template edit fails here first.
CLAUDE_SPEC = (
    'agent:claude:claude -p --tools "" "You are a reviewer seat '
    "in a multi-model code review. The document on stdin is "
    "your complete brief: a diff plus instructions. Follow the "
    "instructions exactly and output ONLY the JSON verdict "
    "object they ask for — no prose, no markdown fences.\"")

PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,1 +1,2 @@
 x = 1
+y = 2
"""

ROLES_ACCEPT = ["", "", "", "", ""]  # 5 wizard roles


def _entry(name, path, probe_ok=True, detail="1.0"):
    base = next(e for e in discovery.KNOWN_CLIS
                if e["name"] == name)
    return {**base, "path": path, "probe_ok": probe_ok,
            "probe_detail": detail}


def _fresh_env(tmp, **extra):
    env = {"HOME": tmp, "PATH": ""}
    env.update(extra)
    return env


def _write_stub(directory, name, body, executable=True):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    if executable:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


class DiscoveryUnitTests(unittest.TestCase):
    def test_detects_only_present_executable_binaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_stub(tmp, "claude", "#!/bin/sh\n")
            _write_stub(tmp, "codex", "#!/bin/sh\n")
            # gemini present but NOT executable -> not detected
            _write_stub(tmp, "gemini", "#!/bin/sh\n",
                        executable=False)
            probed = []

            def probe(path):
                probed.append(path)
                return True, "9.9"
            found = discovery.discover_clis(
                path_value=tmp, probe_fn=probe)
            self.assertEqual([f["name"] for f in found],
                             ["claude", "codex"])
            self.assertEqual(found[0]["path"],
                             os.path.join(tmp, "claude"))
            self.assertTrue(found[0]["probe_ok"])
            self.assertEqual(found[0]["probe_detail"], "9.9")
            self.assertEqual(probed, [found[0]["path"],
                                      found[1]["path"]])

    def test_directory_named_like_a_cli_is_not_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "claude"))
            found = discovery.discover_clis(
                path_value=tmp, probe_fn=lambda p: (True, ""))
            self.assertEqual(found, [])

    def test_empty_path_finds_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                discovery.discover_clis(
                    path_value=tmp,
                    probe_fn=lambda p: (True, "")), [])

    def test_probe_failure_is_recorded_not_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_stub(tmp, "claude", "#!/bin/sh\n")
            found = discovery.discover_clis(
                path_value=tmp,
                probe_fn=lambda p: (False, "exited 1: boom"))
            self.assertEqual(len(found), 1)
            self.assertFalse(found[0]["probe_ok"])
            self.assertEqual(found[0]["probe_detail"],
                             "exited 1: boom")

    def test_table_order_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("gemini", "codex", "claude"):
                _write_stub(tmp, name, "#!/bin/sh\n")
            found = discovery.discover_clis(
                path_value=tmp, probe_fn=lambda p: (True, ""))
            self.assertEqual([f["name"] for f in found],
                             ["claude", "codex", "gemini"])

    def test_seat_spec_is_the_verified_template(self):
        entry = next(e for e in discovery.KNOWN_CLIS
                     if e["name"] == "claude")
        self.assertEqual(discovery.seat_spec(entry), CLAUDE_SPEC)

    def test_unverified_cli_has_no_seat_spec(self):
        for name in ("codex", "gemini"):
            entry = next(e for e in discovery.KNOWN_CLIS
                         if e["name"] == name)
            self.assertIsNone(entry["command"])
            with self.assertRaises(ValueError):
                discovery.seat_spec(entry)

    def test_family_for_seat_name(self):
        self.assertEqual(
            discovery.family_for_seat_name("claude"), "anthropic")
        self.assertEqual(
            discovery.family_for_seat_name("Codex"), "openai")
        self.assertIsNone(discovery.family_for_seat_name("echo"))

    def test_default_probe_against_stub_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = _write_stub(tmp, "okcli",
                             "#!/bin/sh\necho 'stub 1.0'\n")
            bad = _write_stub(tmp, "badcli",
                              "#!/bin/sh\nexit 3\n")
            self.assertEqual(discovery.default_probe(ok),
                             (True, "stub 1.0"))
            okflag, detail = discovery.default_probe(bad)
            self.assertFalse(okflag)
            self.assertIn("exited 3", detail)
            okflag, detail = discovery.default_probe(
                os.path.join(tmp, "missing"))
            self.assertFalse(okflag)
            self.assertIn("could not run", detail)


class WizardDiscoveryTests(unittest.TestCase):
    def _run(self, answers, found, environ, probe_fn=None):
        it = iter(answers)
        printed = []
        result = setup_wizard.run_wizard(
            input_fn=lambda _prompt: next(it),
            print_fn=printed.append, environ=environ,
            probe_fn=probe_fn,
            discover_fn=lambda: found)
        return result, printed

    def _env(self, tmp):
        return _fresh_env(
            tmp, CODEREVIEW_CONFIG=os.path.join(tmp, "config.toml"))

    def test_pick_by_number_saves_exact_agent_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = self._env(tmp)
            found = [_entry("claude", "/fake/bin/claude",
                            detail="2.0.0")]
            result, printed = self._run(
                ["1",        # pick Claude Code
                 "",         # providers: keep discovered seats
                 "",         # family guard: continue as-is
                 *ROLES_ACCEPT],
                found, environ)
            self.assertEqual(result["providers"], [CLAUDE_SPEC])
            self.assertEqual(result["roles"]["correctness"],
                             CLAUDE_SPEC)
            with open(environ["CODEREVIEW_CONFIG"],
                      encoding="utf-8") as fh:
                saved = fh.read()
            self.assertIn("agent:claude:claude -p", saved)
            # Round-trip: the saved spec loads back identical.
            with mock.patch.dict(os.environ, environ,
                                 clear=True):
                self.assertEqual(
                    userconfig.default_provider_specs(),
                    [CLAUDE_SPEC])
            joined = "\n".join(printed)
            self.assertIn("no API key needed", joined)
            self.assertIn("/fake/bin/claude", joined)
            self.assertIn("version probe ok (2.0.0)", joined)

    def test_pick_by_name_dedupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = self._env(tmp)
            found = [_entry("claude", "/fake/bin/claude")]
            result, _printed = self._run(
                ["claude, 1, claude", "", "", *ROLES_ACCEPT],
                found, environ)
            self.assertEqual(result["providers"], [CLAUDE_SPEC])

    def test_invalid_pick_tokens_are_reported_and_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = self._env(tmp)
            found = [_entry("claude", "/fake/bin/claude")]
            result, printed = self._run(
                ["9, bogus",   # both invalid picks
                 "",           # providers attempt: empty, no picks
                 "deepseek",   # providers
                 *ROLES_ACCEPT],
                found, environ)
            self.assertEqual(result["providers"], ["deepseek"])
            joined = "\n".join(printed)
            self.assertIn("'9' is not one of the choices", joined)
            self.assertIn("'bogus' is not one of the choices",
                          joined)

    def test_decline_all_saves_identical_config_to_no_discovery(
            self):
        answers_tail = ["deepseek, moonshot", "", "", "minimax",
                        "-", ""]
        saved = []
        for found, answers in (
                ([_entry("claude", "/fake/bin/claude")],
                 ["", *answers_tail]),
                ([], answers_tail)):
            with tempfile.TemporaryDirectory() as tmp:
                environ = self._env(tmp)
                result, _p = self._run(answers, found, environ)
                with open(environ["CODEREVIEW_CONFIG"],
                          "rb") as fh:
                    saved.append(fh.read())
                self.assertEqual(result["providers"],
                                 ["deepseek", "moonshot"])
        self.assertEqual(saved[0], saved[1])

    def test_none_found_prints_one_line_and_flow_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = self._env(tmp)
            result, printed = self._run(
                ["deepseek", *ROLES_ACCEPT], [], environ)
            self.assertEqual(result["providers"], ["deepseek"])
            lines = [m for m in printed
                     if "No supported agent CLIs found" in m]
            self.assertEqual(len(lines), 1)

    def test_unofferable_cli_is_reported_without_a_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = self._env(tmp)
            found = [_entry("codex", "/fake/bin/codex")]
            # First answer must land on the PROVIDERS prompt:
            # if a pick prompt were asked, "deepseek" would be
            # consumed as an (invalid) pick token and the flow
            # would misalign.
            result, printed = self._run(
                ["deepseek", *ROLES_ACCEPT], found, environ)
            self.assertEqual(result["providers"], ["deepseek"])
            joined = "\n".join(printed)
            self.assertIn("Codex", joined)
            self.assertIn("/fake/bin/codex", joined)
            self.assertIn("no verified seat command", joined)

    def test_failed_probe_is_reported_and_seat_still_addable(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = self._env(tmp)
            found = [_entry("claude", "/fake/bin/claude",
                            probe_ok=False,
                            detail="exited 1: boom")]
            result, printed = self._run(
                ["1", "", "", *ROLES_ACCEPT], found, environ)
            self.assertEqual(result["providers"], [CLAUDE_SPEC])
            self.assertIn("version probe FAILED "
                          "(exited 1: boom)",
                          "\n".join(printed))

    def test_family_guard_fires_for_single_family_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = self._env(tmp)
            found = [_entry("claude", "/fake/bin/claude")]
            result, printed = self._run(
                ["1", "", "", *ROLES_ACCEPT], found, environ)
            self.assertEqual(result["providers"], [CLAUDE_SPEC])
            joined = "\n".join(printed)
            self.assertEqual(joined.count("Panel check"), 1)
            self.assertIn("single vendor family (anthropic)",
                          joined)

    def test_family_guard_offer_adds_the_second_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = self._env(tmp)
            found = [_entry("claude", "/fake/bin/claude")]
            result, printed = self._run(
                ["1", "", "deepseek", *ROLES_ACCEPT],
                found, environ)
            self.assertEqual(result["providers"],
                             [CLAUDE_SPEC, "deepseek"])
            self.assertIn("Panel check", "\n".join(printed))

    def test_family_guard_silent_for_two_family_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = self._env(tmp)
            found = [_entry("claude", "/fake/bin/claude")]
            # pick + providers "deepseek": two families, so the
            # NEXT answer must land on the correctness role —
            # if the guard asked anything, roles would misalign.
            result, printed = self._run(
                ["1", "deepseek", *ROLES_ACCEPT], found, environ)
            self.assertEqual(result["providers"],
                             [CLAUDE_SPEC, "deepseek"])
            self.assertNotIn("Panel check", "\n".join(printed))
            self.assertEqual(result["roles"]["operations"],
                             "deepseek")

    def test_eof_at_pick_prompt_saves_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = self._env(tmp)
            found = [_entry("claude", "/fake/bin/claude")]

            def eof(_prompt):
                raise EOFError
            with self.assertRaises(EOFError):
                setup_wizard.run_wizard(
                    input_fn=eof, print_fn=lambda _m: None,
                    environ=environ,
                    discover_fn=lambda: found)
            self.assertFalse(
                os.path.exists(environ["CODEREVIEW_CONFIG"]))

    def test_eof_at_family_guard_saves_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = self._env(tmp)
            found = [_entry("claude", "/fake/bin/claude")]
            answers = iter(["1", ""])

            def input_fn(_prompt):
                try:
                    return next(answers)
                except StopIteration:
                    raise EOFError
            with self.assertRaises(EOFError):
                setup_wizard.run_wizard(
                    input_fn=input_fn, print_fn=lambda _m: None,
                    environ=environ,
                    discover_fn=lambda: found)
            self.assertFalse(
                os.path.exists(environ["CODEREVIEW_CONFIG"]))


STUB_CLAUDE = """#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "claude-stub 1.0"
  exit 0
fi
cat > /dev/null
printf '%s\\n' '{"verdict": "pass", "summary": "stub claude: no issues", "findings": []}'
"""


class EndToEndStubTests(unittest.TestCase):
    """The full K1 shape with hermetic stubs: a fake `claude`
    on a fake PATH is discovered by the REAL discovery (real
    which + real --version probe), confirmed in the wizard,
    saved, and then actually seats a real review run whose
    record names it."""

    def test_discovered_stub_seat_reviews(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = os.path.join(tmp, "bin")
            os.mkdir(bin_dir)
            _write_stub(bin_dir, "claude", STUB_CLAUDE)
            cfg_path = os.path.join(tmp, "config.toml")
            environ = {"HOME": tmp, "PATH": bin_dir,
                       "CODEREVIEW_CONFIG": cfg_path}
            answers = iter(["1", "", "", *ROLES_ACCEPT])
            printed = []
            result = setup_wizard.run_wizard(
                input_fn=lambda _p: next(answers),
                print_fn=printed.append, environ=environ)
            self.assertEqual(result["providers"], [CLAUDE_SPEC])
            self.assertIn("claude-stub 1.0", "\n".join(printed))

            patch = os.path.join(tmp, "change.diff")
            with open(patch, "w", encoding="utf-8") as fh:
                fh.write(PATCH)
            run_env = dict(environ)
            run_env["PATH"] = (bin_dir + os.pathsep
                               + os.environ.get("PATH", ""))
            err = io.StringIO()
            with mock.patch.dict(os.environ, run_env,
                                 clear=True), \
                    mock.patch.object(cli, "_stdin_is_tty",
                                      lambda: False), \
                    redirect_stderr(err):
                cli.main(["--patch", patch, "--out",
                          os.path.join(tmp, "out")])
            records = glob.glob(
                os.path.join(tmp, "out", "codereview-*.json"))
            self.assertEqual(len(records), 1, err.getvalue())
            with open(records[0], encoding="utf-8") as fh:
                record = json.load(fh)
            reporters = {r["provider"]
                         for r in record["reviewer_reports"]}
            self.assertIn("claude", reporters)


if __name__ == "__main__":
    unittest.main()
