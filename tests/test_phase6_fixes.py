"""Phase 6 follow-up pins (external test pass, 2026-11-06).

Each class pins one Phase 6 item as fixed on the master the
rerun verified. The tester's scripts live outside the repo;
these are the in-repo equivalents of her repros.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "src"))

from codereview import core  # noqa: E402

UNICODE_PATH = "src/日本語/ü ñ.py"


def _quoted(path):
    """The C-quoted form git emits for a path whose bytes are
    not bare-safe: octal escapes for every non-ASCII byte."""
    out = []
    for b in path.encode("utf-8"):
        if 32 <= b < 127 and b not in (34, 92):
            out.append(chr(b))
        else:
            out.append("\\%03o" % b)
    return '"' + "".join(out) + '"'


class TestP604QuotedPaths(unittest.TestCase):
    """P6-04: paths git C-quotes (non-ASCII, tab, quote) were
    attributed to the file 'unknown'; the parser now decodes
    the quoted form everywhere paths are read from a patch."""

    def test_quoted_unicode_path_in_sections(self):
        q = _quoted("a/" + UNICODE_PATH)
        qb = _quoted("b/" + UNICODE_PATH)
        patch = (f"diff --git {q} {qb}\n--- {q}\n+++ {qb}\n"
                 "@@ -0,0 +1 @@\n+x = 1\n")
        sections = core.split_patch_sections(patch)
        self.assertEqual([n for n, _ in sections],
                         [UNICODE_PATH])

    def test_quoted_tab_and_quote_paths(self):
        patch = (
            'diff --git "a/tab\\tname.py" "b/tab\\tname.py"\n'
            '--- "a/tab\\tname.py"\n+++ "b/tab\\tname.py"\n'
            "@@ -0,0 +1 @@\n+t\n"
            'diff --git "a/q\\"uote.py" "b/q\\"uote.py"\n'
            '--- "a/q\\"uote.py"\n+++ "b/q\\"uote.py"\n'
            "@@ -0,0 +1 @@\n+t\n")
        names = [n for n, _ in core.split_patch_sections(patch)]
        self.assertEqual(names, ["tab\tname.py", 'q"uote.py'])

    def test_bare_spaced_path_symmetric_header(self):
        patch = ("diff --git a/my file.py b/my file.py\n"
                 "--- a/my file.py\n+++ b/my file.py\n"
                 "@@ -0,0 +1 @@\n+s\n")
        self.assertEqual(
            [n for n, _ in core.split_patch_sections(patch)],
            ["my file.py"])

    def test_added_lines_and_stats_use_real_path(self):
        q = _quoted("a/" + UNICODE_PATH)
        qb = _quoted("b/" + UNICODE_PATH)
        patch = (f"diff --git {q} {qb}\n--- {q}\n+++ {qb}\n"
                 "@@ -0,0 +1 @@\n+x = 1\n")
        self.assertEqual(
            [f for f, _n, _t in core.added_lines(patch)],
            [UNICODE_PATH])
        self.assertEqual(core._patch_stats(patch),
                         {UNICODE_PATH: [1, 0]})

    def test_rename_and_delete_still_resolve(self):
        patch = (
            "diff --git a/old.py b/new.py\n"
            "rename from old.py\nrename to new.py\n"
            "diff --git a/gone.py b/gone.py\n"
            "--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-bye\n")
        self.assertEqual(
            [n for n, _ in core.split_patch_sections(patch)],
            ["new.py", "gone.py"])

    def test_real_git_unicode_path(self):
        """Her repro, end to end: a committed non-ASCII path
        is recorded under its real name, not 'unknown'."""
        with tempfile.TemporaryDirectory() as repo:
            env = dict(os.environ,
                       GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t",
                       GIT_COMMITTER_EMAIL="t@t")

            def git(*args):
                subprocess.run(["git", "-C", repo, *args],
                               check=True, env=env,
                               capture_output=True)

            git("init", "-q")
            full = os.path.join(repo, UNICODE_PATH)
            os.makedirs(os.path.dirname(full))
            with open(full, "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")
            git("add", "-A")
            git("commit", "-qm", "one")
            with open(full, "a", encoding="utf-8") as fh:
                fh.write("y = 2\n")
            patch = core.collect_git_patch(repo)
            self.assertIn(UNICODE_PATH,
                          [n for n, _ in
                           core.split_patch_sections(patch)])


if __name__ == "__main__":
    unittest.main()
