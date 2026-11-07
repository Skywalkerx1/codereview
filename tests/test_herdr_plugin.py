"""Epic K3b herdr ecosystem artefact tests.

The artefact is thin by design — a herdr plugin manifest + a
launcher script, plus an agent SKILL.md — so the tests pin
the contract, not an engine:

- the manifest parses and declares exactly what the spec
  asks (one workspace action, one overlay pane, ids inside
  herdr's charset rules, the 0.9.0 version floor K3a set);
- the launcher's missing-`codereview` path prints the
  `pip install codereview-loop` hint, exits non-zero, and has
  NO side effects;
- with a stub `codereview` on PATH (a script honouring the
  real CLI's printed contract: gate line, findings line,
  report/data paths, exit codes 0/1/2), the launcher resolves
  the workspace from herdr's context JSON, runs the gate
  there, streams its output, and propagates its exit code;
- a stub `herdr` exercises the plugin's action contract the
  way herdr itself invokes it (command run from the plugin
  directory, HERDR_PLUGIN_* env injected) — real herdr is
  not installed on the build machine, so `herdr plugin link`
  on a clean profile stays UNVERIFIED (recorded in the
  changelog), and this stub is the closest honest exercise;
- the launcher imports only an allowlist of stdlib modules
  and opens files read-only (no network, no credential
  surface, no writes of its own — by construction);
- the SKILL.md carries the honesty contract (verdicts quoted
  from the record, BLOCKED never softened, INCONCLUSIVE
  never upgraded).

Nothing here touches the network or a real account.
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(REPO_ROOT, "herdr-plugin-codereview")
MANIFEST = os.path.join(PLUGIN_DIR, "herdr-plugin.toml")
LAUNCHER = os.path.join(PLUGIN_DIR, "codereview_launch.py")
PLUGIN_README = os.path.join(PLUGIN_DIR, "README.md")
SKILL = os.path.join(REPO_ROOT, "skills", "codereview",
                     "SKILL.md")
MANIFEST_IN = os.path.join(REPO_ROOT, "MANIFEST.in")

STUB_CODEREVIEW = '''
import json, os, sys

argv = sys.argv[1:]
log = os.environ.get("STUB_CR_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": argv,
                             "cwd": os.getcwd()}) + "\\n")
out = "codereview-out"
if "--out" in argv:
    out = argv[argv.index("--out") + 1]
gate = os.environ.get("STUB_CR_GATE", "pass")
os.makedirs(out, exist_ok=True)
stem = "codereview-20990101-000000"
record = {"gate": gate, "gate_reasons": ["stub reason"],
          "findings": []}
jpath = os.path.join(out, stem + ".json")
mpath = os.path.join(out, stem + ".md")
with open(jpath, "w", encoding="utf-8") as fh:
    json.dump(record, fh)
with open(mpath, "w", encoding="utf-8") as fh:
    fh.write("# stub record\\n")
print(f"codereview: gate = {gate.upper()} (stub reason)")
print("  findings: 0 (0 blocking-severity)")
print(f"  report: {mpath}")
print(f"  data:   {jpath}")
sys.exit({"pass": 0, "blocked": 1, "inconclusive": 2}[gate])
'''

STUB_HERDR = '''
import json, os, subprocess, sys, tomllib

"""Minimal herdr stand-in: implements just enough of the
plugin surface to invoke this plugin's declared commands the
way herdr does — argv from the manifest, cwd = the plugin
directory, HERDR_PLUGIN_* context injected."""

plugin_dir, mode = sys.argv[1], sys.argv[2]
with open(os.path.join(plugin_dir, "herdr-plugin.toml"),
          "rb") as fh:
    manifest = tomllib.load(fh)
pid = manifest["id"]
if mode == "action-list":
    for action in manifest.get("actions", []):
        print(f"{pid}.{action['id']}")
    sys.exit(0)
if mode == "invoke":
    wanted = sys.argv[3]
    entries = [(a["id"], a["command"])
               for a in manifest.get("actions", [])]
    entries += [(p["id"], p["command"])
                for p in manifest.get("panes", [])]
    for entry_id, command in entries:
        if f"{pid}.{entry_id}" == wanted or entry_id == wanted:
            env = dict(os.environ)
            env.update({
                "HERDR_BIN_PATH": os.path.abspath(__file__),
                "HERDR_PLUGIN_ID": pid,
                "HERDR_PLUGIN_ROOT": plugin_dir,
                "HERDR_PLUGIN_CONFIG_DIR":
                    os.environ.get("STUB_PLUGIN_CONFIG", ""),
                "HERDR_PLUGIN_STATE_DIR":
                    os.environ.get("STUB_PLUGIN_STATE", ""),
                "HERDR_PLUGIN_CONTEXT_JSON":
                    os.environ.get("STUB_CONTEXT_JSON", "{}"),
            })
            proc = subprocess.run(command, cwd=plugin_dir,
                                  env=env)
            sys.exit(proc.returncode)
    print(f"no such action: {wanted}", file=sys.stderr)
    sys.exit(2)
print(f"unknown mode: {mode}", file=sys.stderr)
sys.exit(2)
'''


def _write_script(directory, name, body):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"#!{sys.executable}\n" + body)
    os.chmod(path, 0o755)
    return path


def _snapshot(root):
    """{relative path: size} for every file under root."""
    out = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(base, name)
            out[os.path.relpath(path, root)] = os.path.getsize(path)
    return out


class _LauncherCase(unittest.TestCase):
    """Base: a temp world with a stub-codereview bin dir, a
    scratch workspace, and a controlled environment."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="k3b-")
        self.addCleanup(self._rmtree)
        self.bin_dir = os.path.join(self.tmp, "bin")
        self.empty_bin = os.path.join(self.tmp, "empty-bin")
        self.workspace = os.path.join(self.tmp, "workspace")
        self.config_dir = os.path.join(self.tmp, "plugin-config")
        self.state_dir = os.path.join(self.tmp, "plugin-state")
        for d in (self.bin_dir, self.empty_bin, self.workspace,
                  self.config_dir, self.state_dir):
            os.makedirs(d)
        _write_script(self.bin_dir, "codereview", STUB_CODEREVIEW)
        self.log = os.path.join(self.tmp, "stub-log.jsonl")

    def _rmtree(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self, **overrides):
        env = {
            "PATH": self.bin_dir,
            "HOME": self.tmp,
            "STUB_CR_LOG": self.log,
            "HERDR_PLUGIN_CONFIG_DIR": self.config_dir,
            "HERDR_PLUGIN_STATE_DIR": self.state_dir,
        }
        env.update(overrides)
        return env

    def context(self, cwd=None):
        return json.dumps(
            {"workspace_cwd": cwd or self.workspace,
             "invocation_source": "test"})

    def run_launcher(self, args=(), env=None, cwd=None):
        return subprocess.run(
            [sys.executable, LAUNCHER, *args],
            env=env if env is not None else self.env(),
            cwd=cwd or self.tmp,
            capture_output=True, text=True, timeout=120)

    def stub_calls(self):
        if not os.path.isfile(self.log):
            return []
        with open(self.log, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]


class ManifestContractTest(unittest.TestCase):

    def setUp(self):
        with open(MANIFEST, "rb") as fh:
            self.manifest = tomllib.load(fh)

    def test_required_metadata(self):
        m = self.manifest
        self.assertEqual(m["id"], "superstartelecom.codereview")
        self.assertEqual(m["name"], "CodeReview")
        self.assertTrue(m["version"])
        # The floor K3a's adapter feature-detects against:
        # the oldest herdr whose surface this epic verified.
        self.assertEqual(m["min_herdr_version"], "0.9.0")
        self.assertEqual(m["platforms"],
                         ["linux", "macos", "windows"])

    def test_one_workspace_action_and_one_overlay_pane(self):
        actions = self.manifest.get("actions", [])
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action["id"], "review-workspace")
        self.assertIn("review current workspace",
                      action["title"].lower())
        self.assertEqual(action["contexts"], ["workspace"])
        self.assertEqual(action["command"],
                         ["python3", "codereview_launch.py"])
        panes = self.manifest.get("panes", [])
        self.assertEqual(len(panes), 1)
        self.assertEqual(panes[0]["placement"], "overlay")
        self.assertEqual(panes[0]["command"],
                         ["python3", "codereview_launch.py",
                          "--pane"])
        # The commands point at a real file in the artefact.
        self.assertTrue(os.path.isfile(LAUNCHER))
        self.assertTrue(os.path.isfile(PLUGIN_README))

    def test_ids_follow_herdr_charset_rules(self):
        # Plugin ids: letters/digits plus . : _ - ; action and
        # pane ids: the same WITHOUT dots (herdr manifest.rs).
        import re
        self.assertRegex(self.manifest["id"],
                         r"^[A-Za-z0-9._:-]+$")
        for entry in (self.manifest["actions"]
                      + self.manifest["panes"]):
            self.assertRegex(entry["id"], r"^[A-Za-z0-9_:-]+$")


class MissingCodereviewTest(_LauncherCase):

    def test_hint_nonzero_and_no_side_effects(self):
        before_ws = _snapshot(self.workspace)
        before_tmp = _snapshot(self.tmp)
        proc = self.run_launcher(env=self.env(
            PATH=self.empty_bin,
            HERDR_PLUGIN_CONTEXT_JSON=self.context()))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("pip install codereview-loop",
                      proc.stdout + proc.stderr)
        # No gate run happened and nothing was written
        # anywhere: the failure is pure.
        self.assertEqual(self.stub_calls(), [])
        self.assertEqual(_snapshot(self.workspace), before_ws)
        self.assertEqual(_snapshot(self.tmp), before_tmp)


class PresentCodereviewTest(_LauncherCase):

    def test_pass_run_streams_verdict_record_and_exits_zero(self):
        proc = self.run_launcher(env=self.env(
            HERDR_PLUGIN_CONTEXT_JSON=self.context()))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("gate = PASS", proc.stdout)
        self.assertIn("data:", proc.stdout)
        calls = self.stub_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["argv"][:2],
                         ["--repo", self.workspace])
        self.assertEqual(calls[0]["cwd"], self.workspace)
        record = os.path.join(self.workspace, "codereview-out",
                              "codereview-20990101-000000.json")
        self.assertTrue(os.path.isfile(record))
        with open(record, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["gate"], "pass")

    def test_blocked_and_inconclusive_codes_propagate(self):
        for gate, code in (("blocked", 1), ("inconclusive", 2)):
            with self.subTest(gate=gate):
                proc = self.run_launcher(env=self.env(
                    STUB_CR_GATE=gate,
                    HERDR_PLUGIN_CONTEXT_JSON=self.context()))
                self.assertEqual(proc.returncode, code)
                self.assertIn(f"gate = {gate.upper()}",
                              proc.stdout)

    def test_repo_flag_beats_context(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        proc = self.run_launcher(
            args=("--repo", other),
            env=self.env(
                HERDR_PLUGIN_CONTEXT_JSON=self.context()))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.stub_calls()[0]["argv"][:2],
                         ["--repo", other])

    def test_outside_herdr_falls_back_to_cwd(self):
        proc = self.run_launcher(cwd=self.workspace)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.stub_calls()[0]["cwd"],
                         self.workspace)

    def test_plugin_runtime_without_workspace_fails_loudly(self):
        proc = self.run_launcher(env=self.env(
            HERDR_PLUGIN_ID="superstartelecom.codereview",
            HERDR_PLUGIN_CONTEXT_JSON="{}"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no workspace directory", proc.stderr)
        self.assertEqual(self.stub_calls(), [])

    def test_extra_args_pass_through(self):
        proc = self.run_launcher(
            args=("--", "--staged"),
            env=self.env(
                HERDR_PLUGIN_CONTEXT_JSON=self.context()))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--staged", self.stub_calls()[0]["argv"])

    def test_config_policy_and_out_pass_through(self):
        with open(os.path.join(self.config_dir, "config.toml"),
                  "w", encoding="utf-8") as fh:
            fh.write('policy = "pol/policy.toml"\n'
                     'out = "gate-out"\n')
        proc = self.run_launcher(env=self.env(
            HERDR_PLUGIN_CONTEXT_JSON=self.context()))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        argv = self.stub_calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--policy") + 1],
                         os.path.join(self.workspace,
                                      "pol/policy.toml"))
        self.assertEqual(argv[argv.index("--out") + 1],
                         "gate-out")
        self.assertTrue(os.path.isfile(os.path.join(
            self.workspace, "gate-out",
            "codereview-20990101-000000.json")))

    def test_malformed_config_warns_and_run_continues(self):
        with open(os.path.join(self.config_dir, "config.toml"),
                  "w", encoding="utf-8") as fh:
            fh.write("policy = [unclosed\n")
        proc = self.run_launcher(env=self.env(
            HERDR_PLUGIN_CONTEXT_JSON=self.context()))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("malformed plugin config", proc.stderr)
        self.assertEqual(len(self.stub_calls()), 1)


class StubHerdrContractTest(_LauncherCase):
    """The action contract, exercised the way herdr invokes
    it: manifest argv, cwd = plugin directory, HERDR_PLUGIN_*
    env. (Real `herdr plugin link` is UNVERIFIED — no herdr
    binary exists on this machine.)"""

    def setUp(self):
        super().setUp()
        self.herdr = _write_script(self.tmp, "herdr-stub",
                                   STUB_HERDR)

    def _invoke_env(self):
        env = self.env()
        env["STUB_PLUGIN_CONFIG"] = self.config_dir
        env["STUB_PLUGIN_STATE"] = self.state_dir
        env["STUB_CONTEXT_JSON"] = self.context()
        # The manifest commands call `python3`: make sure it
        # resolves, alongside the stub codereview.
        env["PATH"] = os.pathsep.join(
            [self.bin_dir, os.path.dirname(sys.executable),
             "/usr/bin", "/bin"])
        return env

    def test_action_list_shows_the_qualified_action(self):
        proc = subprocess.run(
            [sys.executable, self.herdr, PLUGIN_DIR,
             "action-list"],
            env=self._invoke_env(), capture_output=True,
            text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(
            "superstartelecom.codereview.review-workspace",
            proc.stdout)

    def test_invoke_runs_gate_against_context_workspace(self):
        proc = subprocess.run(
            [sys.executable, self.herdr, PLUGIN_DIR, "invoke",
             "superstartelecom.codereview.review-workspace"],
            env=self._invoke_env(), capture_output=True,
            text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("gate = PASS", proc.stdout)
        calls = self.stub_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["argv"][:2],
                         ["--repo", self.workspace])


class LauncherHygieneTest(unittest.TestCase):
    """No credentials, no network, no writes of its own —
    asserted by construction over the launcher's AST."""

    def setUp(self):
        with open(LAUNCHER, encoding="utf-8") as fh:
            self.source = fh.read()
        self.tree = ast.parse(self.source)

    def test_imports_are_allowlisted_stdlib_only(self):
        allowed = {"argparse", "json", "os", "shutil",
                   "subprocess", "sys", "tomllib"}
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0]
                                for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, allowed)
        # In particular: nothing that can open a socket.
        self.assertFalse(imported & {"socket", "urllib",
                                     "http", "requests"})

    def test_files_opened_read_only(self):
        for node in ast.walk(self.tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "open"):
                continue
            mode = None
            if len(node.args) >= 2 and isinstance(
                    node.args[1], ast.Constant):
                mode = node.args[1].value
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(
                        kw.value, ast.Constant):
                    mode = kw.value.value
            if mode is not None:
                self.assertTrue(
                    mode.startswith("r"),
                    f"launcher opens a file with mode {mode!r}")

    def test_no_credential_or_env_writes(self):
        # The launcher reads HERDR_*/PATH from the environment
        # but never writes environment entries (nothing to
        # leak into) and never handles key material.
        self.assertNotIn("os.environ[", self.source)
        self.assertNotIn("putenv", self.source)
        for marker in ("API_KEY", "SECRET", "TOKEN", "PASSWORD"):
            self.assertNotIn(marker, self.source)


class SkillContractTest(unittest.TestCase):

    def setUp(self):
        with open(SKILL, encoding="utf-8") as fh:
            self.text = fh.read()

    def test_frontmatter(self):
        self.assertTrue(self.text.startswith("---\n"))
        head = self.text.split("---", 2)[1]
        self.assertIn("name: codereview", head)
        self.assertIn("description:", head)

    def test_honesty_contract_is_taught(self):
        body = self.text.lower()
        for phrase in ("pass", "blocked", "inconclusive"):
            self.assertIn(phrase, body)
        self.assertIn("never soften", body)
        self.assertIn("source of truth", body)
        self.assertIn("record", body)
        self.assertIn("pip install codereview-loop", body)
        self.assertIn("codereview-out", body)


class SdistStoryTest(unittest.TestCase):

    def test_manifest_in_grafts_both_artefacts(self):
        with open(MANIFEST_IN, encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh
                     if ln.strip() and not ln.startswith("#")]
        self.assertIn("graft herdr-plugin-codereview", lines)
        self.assertIn("graft skills", lines)


if __name__ == "__main__":
    unittest.main()
