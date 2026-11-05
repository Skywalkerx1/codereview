"""Acceptance fixes D1–D4 (clean-room acceptance report
2026-11-05, verdict READY-WITH-DEFECTS).

D1: on the standard diff path, reviewers received only the
plain unified diff, so a definition outside the hunk was
invisible and correct code drew confident false "undefined
symbol" majors from two families. The product path now attaches
post-change file contents for the changed files (run_review's
`file_context`, built by core.collect_file_context). The bench /
registered-run path never passes it: its prompts stay
byte-identical (guarded below).

D2: stored seat error strings were head-truncated at 300 chars,
so neither the exception type nor the HTTP status survived.
core._stored_error leads with both.

D3: top-level `codereview --help` listed none of the
subcommands; the review parser's help now carries a subcommand
epilog.

D4: the same defect raised by two seats under paraphrased
titles was reported (and gate-counted) twice. merge_findings
gains a same-file + same-line + title-overlap route.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from codereview import cli, core  # noqa: E402

BASE_APP = '''USERS = {"alice": {"admin": True}}


def greet(name):
    return "hello " + name


def delete_user(actor, name):
    if not USERS.get(actor, {}).get("admin"):
        raise PermissionError("not admin")
    del USERS[name]
'''

CLEAN_APP_TAIL = '''

def list_users():
    return sorted(USERS)
'''


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   capture_output=True, text=True)


def _commit(repo, files, message):
    for name, text in files.items():
        path = os.path.join(repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True) \
            if os.path.dirname(name) else None
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        _git(repo, "add", name)
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", message)


class ScratchRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q")
        _commit(self.repo, {"app.py": BASE_APP}, "base")
        _commit(self.repo, {"app.py": BASE_APP + CLEAN_APP_TAIL},
                "clean helper")
        self.patch = core.collect_git_patch(
            self.repo, range_spec="HEAD~1...HEAD")


class FileContextTests(ScratchRepo):
    def test_range_context_comes_from_the_range_target(self):
        fctx, entries = core.collect_file_context(
            self.repo, self.patch, range_spec="HEAD~1...HEAD")
        self.assertIn("app.py", fctx)
        # The definition sits outside the diff hunk; it must be
        # in the attached context, from HEAD's version.
        self.assertIn('USERS = {"alice"', fctx["app.py"])
        self.assertIn("def list_users", fctx["app.py"])
        entry = {e["file"]: e for e in entries}["app.py"]
        self.assertEqual(entry["source"], "ref:HEAD")
        self.assertFalse(entry["truncated"])
        # Even after the working tree drifts, the range context
        # stays the range target's content.
        with open(os.path.join(self.repo, "app.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("DRIFTED = True\n")
        fctx2, _ = core.collect_file_context(
            self.repo, self.patch, range_spec="HEAD~1...HEAD")
        self.assertNotIn("DRIFTED", fctx2["app.py"])

    def test_worktree_context_reads_the_disk_file(self):
        with open(os.path.join(self.repo, "app.py"), "a",
                  encoding="utf-8") as fh:
            fh.write("\nEXTRA = 1\n")
        patch = core.collect_git_patch(self.repo)
        fctx, entries = core.collect_file_context(self.repo, patch)
        self.assertIn("EXTRA = 1", fctx["app.py"])
        entry = {e["file"]: e for e in entries}["app.py"]
        self.assertEqual(entry["source"], "worktree")

    def test_new_and_deleted_files_are_skipped(self):
        _commit(self.repo, {"newfile.py": "X = 1\n"}, "add")
        _git(self.repo, "rm", "-q", "app.py")
        _git(self.repo, "-c", "user.email=t@t", "-c",
             "user.name=t", "commit", "-q", "-m", "del")
        patch = core.collect_git_patch(
            self.repo, range_spec="HEAD~2...HEAD")
        fctx, entries = core.collect_file_context(
            self.repo, patch, range_spec="HEAD~2...HEAD")
        self.assertEqual(fctx, {})
        skipped = {e["file"]: e["skipped"] for e in entries
                   if e.get("skipped")}
        self.assertEqual(skipped.get("newfile.py"), "new_file")
        self.assertEqual(skipped.get("app.py"), "deleted")

    def test_per_file_cap_truncates_with_a_marker(self):
        big = "A = 1\n" + ("# filler line\n" * 4000)
        _commit(self.repo, {"big.py": big}, "big")
        patch = core.collect_git_patch(
            self.repo, range_spec="HEAD~1...HEAD")
        # big.py is a NEW file in this range; use a modification
        # range instead: commit a change to it.
        _commit(self.repo, {"big.py": big + "B = 2\n"}, "big2")
        patch = core.collect_git_patch(
            self.repo, range_spec="HEAD~1...HEAD")
        fctx, entries = core.collect_file_context(
            self.repo, patch, range_spec="HEAD~1...HEAD",
            per_file_cap=1000)
        self.assertIn("truncated", fctx["big.py"])
        self.assertLessEqual(len(fctx["big.py"]), 1300)
        entry = {e["file"]: e for e in entries}["big.py"]
        self.assertEqual(entry["truncated"], "file_cap")

    def test_budget_goes_to_the_most_changed_file_first(self):
        # Two modified files and a budget that fits only one:
        # the file with the larger diff section wins, the other
        # is listed as budget-truncated, never silently absent.
        small = "S = 1\n"
        big_base = "B = 1\n" + ("# pad\n" * 300)
        _commit(self.repo, {"small.py": small, "big.py": big_base},
                "both")
        _commit(self.repo,
                {"small.py": small + "S2 = 2\n",
                 "big.py": big_base + ("B2 = 2\n" * 40)},
                "change both")
        patch = core.collect_git_patch(
            self.repo, range_spec="HEAD~1...HEAD")
        fctx, entries = core.collect_file_context(
            self.repo, patch, range_spec="HEAD~1...HEAD",
            total_cap=2000)
        by_file = {e["file"]: e for e in entries}
        self.assertGreater(by_file["big.py"]["sent_chars"], 0)
        self.assertEqual(by_file["small.py"]["truncated"],
                         "budget")
        self.assertNotIn("small.py", fctx)

    def test_reviewer_prompt_carries_the_context(self):
        fctx, _ = core.collect_file_context(
            self.repo, self.patch, range_spec="HEAD~1...HEAD")
        prompts = []

        def seat(prompt):
            prompts.append(prompt)
            return json.dumps({"verdict": "pass", "summary": "ok",
                               "findings": []})

        report = core.run_review(self.patch, {"seat-a": seat},
                                 file_context=fctx,
                                 sleep=lambda _s: None)
        self.assertTrue(prompts)
        joined = "\n".join(prompts)
        self.assertIn('USERS = {"alice"', joined)
        self.assertIn("app.py", joined)
        attached = {e["file"] for e in
                    report["file_context"]["attached"]}
        self.assertEqual(attached, {"app.py"})

    def test_no_context_means_legacy_prompt_shape(self):
        # Bench / registered-run guard: without file_context the
        # prompt is byte-identical to the pre-D1 construction.
        prompts = []

        def seat(prompt):
            prompts.append(prompt)
            return json.dumps({"verdict": "pass", "summary": "ok",
                               "findings": []})

        report = core.run_review(self.patch, {"seat-a": seat},
                                 sleep=lambda _s: None)
        self.assertNotIn("file_context", report)
        sections = core.split_patch_sections(
            core.redact_secrets(self.patch))
        batch = sections[0][1]
        self.assertEqual(len(prompts), 2)  # two lenses, one batch
        for prompt in prompts:
            self.assertIn(prompt, [
                core._REVIEW_PROMPT.format(
                    lens=core.LENSES[lens], context="(none)",
                    tests="(no test commands were run)",
                    batch="batch 1/1", patch=batch)
                for lens in core.LENSES])
            self.assertNotIn("File context", prompt)


class StoredErrorTests(unittest.TestCase):
    def _report_with_error(self, exc):
        def seat(prompt):
            raise exc

        return core.run_review("diff --git a/x.py b/x.py\n",
                               {"seat-a": seat},
                               sleep=lambda _s: None)

    def test_long_traceback_keeps_type_and_status(self):
        tb = ("agent command exited 1: Traceback (most recent "
              "call last):\n"
              + "".join(f'  File "/x/mod{i}.py", line {i}, '
                        f"in f{i}\n" for i in range(30))
              + "urllib.error.HTTPError: HTTP Error 502: "
                "Bad Gateway")
        report = self._report_with_error(RuntimeError(tb))
        rec = report["reviewer_reports"][0]
        self.assertLessEqual(len(rec["error"]), 300)
        self.assertIn("HTTPError", rec["error"])
        self.assertIn("502", rec["error"])
        # The full string is untouched in error_detail.
        self.assertEqual(rec["error_detail"]["error"], tb)
        self.assertEqual(rec["error_detail"]["http_status"], 502)

    def test_provider_error_keeps_status(self):
        report = self._report_with_error(
            ValueError("HTTP 429 from api.example.com: slow down"))
        rec = report["reviewer_reports"][0]
        self.assertIn("429", rec["error"])
        self.assertIn("ValueError", rec["error"])


class HelpTests(unittest.TestCase):
    def test_top_level_help_lists_subcommands(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                cli.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        out = buf.getvalue()
        self.assertIn("Subcommands", out)
        section = out[out.index("Subcommands"):]
        for name in ("setup", "policy", "record-verify",
                     "disputes", "bench", "doctor", "intake",
                     "pr", "sarif", "evidence", "locate",
                     "workflow"):
            self.assertIn(name, section)


ACCEPT_A = {
    "severity": "major", "category": "correctness",
    "file": "app.py", "line": 12,
    "title": "list_users crashes with NameError because USERS "
             "is undefined in this module",
    "evidence": "return sorted(USERS)",
    "evidence_quote": "return sorted(USERS)",
    "recommendation": "define USERS", "confidence": 0.98}
ACCEPT_B = {
    "severity": "major", "category": "correctness",
    "file": "app.py", "line": 12,
    "title": "list_users references undefined USERS global",
    "evidence": "return sorted(USERS)",
    "evidence_quote": "return sorted(USERS)",
    "recommendation": "define USERS", "confidence": 0.9}


class MergeFindingsTests(ScratchRepo):
    def test_paraphrased_same_line_findings_merge(self):
        fa = core._normalize_finding(ACCEPT_A, "openai-wrap",
                                     lens="correctness")
        fb = core._normalize_finding(ACCEPT_B, "deepseek-wrap",
                                     lens="operations")
        merged = core.merge_findings([fa, fb])
        self.assertEqual(len(merged), 1)
        self.assertEqual(sorted(merged[0]["sources"]),
                         ["deepseek-wrap", "openai-wrap"])
        self.assertTrue(merged[0]["consensus"])
        self.assertEqual(merged[0]["severity"], "major")

    def test_same_line_unrelated_findings_do_not_merge(self):
        a = dict(ACCEPT_A, title="eval() on user input allows "
                                 "code execution")
        b = dict(ACCEPT_B, title="missing timeout on the "
                                 "outbound HTTP call")
        fa = core._normalize_finding(a, "seat-a")
        fb = core._normalize_finding(b, "seat-b")
        self.assertEqual(len(core.merge_findings([fa, fb])), 2)

    def test_gate_counts_the_merged_defect_once(self):
        def seat_a(prompt):
            return json.dumps({"verdict": "changes_requested",
                               "summary": "s", "findings": [ACCEPT_A]})

        def seat_b(prompt):
            return json.dumps({"verdict": "changes_requested",
                               "summary": "s", "findings": [ACCEPT_B]})

        report = core.run_review(
            self.patch, {"seat-a": seat_a, "seat-b": seat_b},
            sleep=lambda _s: None)
        majors = [f for f in report["findings"]
                  if f["severity"] == "major"]
        self.assertEqual(len(majors), 1)
        self.assertEqual(sorted(majors[0]["sources"]),
                         ["seat-a", "seat-b"])


if __name__ == "__main__":
    unittest.main()
