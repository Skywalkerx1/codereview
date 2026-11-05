"""Hardening tests for the PT-1 open-refutations track
(solution §3), covering the three code changes:

  4ce0212286e0  _prompt_slice: prompt slices are explicit —
                a truncation marker with full length + sha256,
                cut at a word boundary when one exists; never
                a silent or mid-word slice.
  6b29fe953939  function_key callee resolution fails safe:
                qualified name where determinable (self.x(),
                scope-local sibling); an ambiguous bare name
                keys to ALL candidate hashes, so changing any
                same-named function re-opens the precedent;
                an unambiguous name keeps the historical bare
                hash (existing precedents keep matching).
  9a4415ddafa6  load_user_config type-validates: non-list
                providers / non-table roles raise the
                documented ValueError naming the config path.
  bf4c451e8751  non-dict-entry test for the evidence-sidecar
                walk: entries that are not dicts are skipped
                by the isinstance guard, and dict entries
                among them still get their sidecars (the
                refutation's conclusion holds; its stated
                mechanism was corrected in the packet — the
                guard it never cited is what protects it).
"""

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core, userconfig  # noqa: E402


class PromptSliceTests(unittest.TestCase):
    def test_under_cap_unchanged(self):
        self.assertEqual(core._prompt_slice("short text", 2000),
                         "short text")
        self.assertEqual(core._prompt_slice("", 2000), "")
        self.assertEqual(core._prompt_slice(None, 2000), "")

    def test_over_cap_marker_complete_and_boundary_clean(self):
        text = " ".join(["w%08d" % i for i in range(400)])
        out = core._prompt_slice(text, 2000)
        digest = hashlib.sha256(text.encode()).hexdigest()
        self.assertIn(f"…[truncated, {len(text)} chars, "
                      f"sha256:{digest}]", out)
        visible = out.split(" …[truncated")[0]
        self.assertLessEqual(len(visible), 2000)
        # the visible part ends exactly at a word boundary:
        self.assertTrue(text.startswith(visible))
        self.assertEqual(text[len(visible)], " ")

    def test_single_long_word_still_marked(self):
        text = "x" * 3000
        out = core._prompt_slice(text, 2000)
        self.assertIn("…[truncated, 3000 chars", out)
        self.assertTrue(out.startswith("x" * 2000))

    def test_finding_public_marks_long_evidence(self):
        finding = {"id": "x", "severity": "major",
                   "evidence": " ".join(["w%08d" % i
                                         for i in range(400)]),
                   "evidence_quote": " ".join(["q%08d" % i
                                               for i in range(200)])}
        shown = json.loads(core._finding_public(finding))
        self.assertIn("…[truncated,", shown["evidence"])
        self.assertIn("…[truncated,", shown["evidence_quote"])


class CalleeKeyTests(unittest.TestCase):
    AMBIG = (
        "def helper():\n    return 1\n\n\n"
        "def helper():\n    return 2\n\n\n"
        "def caller():\n    return helper()\n")
    AMBIG_CHANGED = AMBIG.replace("return 2", "return 99")

    def test_ambiguous_name_keys_to_all_candidates(self):
        key = core.function_key(self.AMBIG, 9)
        self.assertIsNotNone(key)
        self.assertIn("|", key["callees"]["helper"])
        changed = core.function_key(self.AMBIG_CHANGED, 9)
        self.assertNotEqual(key["callees"], changed["callees"])
        self.assertEqual(key["function_hash"],
                         changed["function_hash"])

    def test_unambiguous_name_keeps_bare_hash(self):
        src = ("def helper():\n    return 1\n\n\n"
               "def caller():\n    return helper()\n")
        key = core.function_key(src, 5)
        self.assertNotIn("|", key["callees"]["helper"])
        self.assertEqual(len(key["callees"]["helper"]), 64)

    SELF = (
        "def b():\n    return 'module'\n\n\n"
        "class C:\n"
        "    def b(self):\n        return 'method'\n\n"
        "    def a(self):\n        return self.b()\n")

    def test_self_call_resolves_to_the_method(self):
        key = core.function_key(self.SELF, 9)
        changed_module = core.function_key(
            self.SELF.replace("return 'module'",
                              "return 'changed'"), 9)
        changed_method = core.function_key(
            self.SELF.replace("return 'method'",
                              "return 'changed'"), 9)
        # The key follows the METHOD named b, not the
        # module-level function the old first-wins map picked.
        self.assertEqual(key["callees"], changed_module["callees"])
        self.assertNotEqual(key["callees"],
                            changed_method["callees"])

    def test_nested_sibling_resolution(self):
        src = ("def outer():\n"
               "    def inner():\n        return 1\n\n"
               "    def caller():\n        return inner()\n\n"
               "    return caller()\n")
        key_outer = core.function_key(src, 8)
        self.assertEqual(key_outer["function"], "outer")
        key_caller = core.function_key(src, 5)
        self.assertEqual(key_caller["function"], "outer.caller")
        self.assertNotIn("|", key_caller["callees"]["inner"])
        changed = core.function_key(
            src.replace("return 1", "return 2"), 5)
        self.assertNotEqual(key_caller["callees"],
                            changed["callees"])


class UserConfigTypeTests(unittest.TestCase):
    def _load(self, text):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "config.toml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            return userconfig.load_user_config(
                {"CODEREVIEW_CONFIG": path})

    def test_roles_wrong_types_raise_value_error(self):
        for text in ('roles = []\n', 'roles = ["x"]\n',
                     'roles = "x"\n', "roles = 3\n"):
            with self.assertRaises(ValueError, msg=text) as cm:
                self._load(text)
            self.assertIn("roles", str(cm.exception))

    def test_providers_wrong_types_raise_value_error(self):
        for text in ('providers = "openai"\n',
                     "providers = {}\n", "providers = 3\n"):
            with self.assertRaises(ValueError, msg=text) as cm:
                self._load(text)
            self.assertIn("providers", str(cm.exception))

    def test_missing_and_valid_configs(self):
        cfg = self._load("")
        self.assertEqual(cfg["providers"], [])
        self.assertEqual(cfg["roles"], {})
        self.assertTrue(cfg["path"].endswith("config.toml"))
        cfg = self._load('providers = ["openai"]\n\n'
                         '[roles]\ncorrectness = "gemini"\n')
        self.assertEqual(cfg["providers"], ["openai"])
        self.assertEqual(cfg["roles"], {"correctness": "gemini"})


class NonDictEntryTests(unittest.TestCase):
    REPORT = {
        "mode": "review", "gate": "blocked",
        "gate_reasons": ["x"], "degraded": False,
        "created_at": "t", "patch_sha256": "0" * 64,
        "findings": [],
        "disputed_findings": [
            None, 42, "dispute", ["dispute"],
            {"id": "abc123def456", "evidence": "ev text",
             "evidence_quote": "ev",
             "dispute": {"reason": "r",
                         "evidence_quote": "q"}}]}

    def test_sidecar_walk_skips_non_dicts_and_serves_dicts(self):
        report = copy.deepcopy(self.REPORT)
        with tempfile.TemporaryDirectory() as td:
            written = core._attach_evidence_sidecars(report, td)
            entry = written["disputed_findings"][4]
            self.assertIn("evidence_ref", entry)
            refs = list(core._iter_evidence_refs(written))
            self.assertTrue(refs)
            sidecar = os.path.join(
                td, "evidence",
                entry["evidence_ref"]["sha256"])
            self.assertTrue(os.path.exists(sidecar))


if __name__ == "__main__":
    unittest.main()
