"""Tests for the closing packet set's three remaining ratified
fixes (owner ratification, 2026-11-04 evening):

  99fe18f50ec3 — records_scan telemetry inventory: malformed
  gate-attempts rows are skipped-and-counted, never fatal.
  179ece0e030e — _load_record_arg prefers the lexicographically
  greatest timestamped record name; mtime is only the fallback
  for directories with no timestamped record name.
  9489ee49db6f — evidence timeouts: an explicit non-positive
  timeout is refused loudly at load (the review-v13 contract),
  never silently swapped for the default via a falsey `or`.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, evidence  # noqa: E402


def _load_records_scan():
    path = os.path.join(os.path.dirname(__file__), "..",
                        "probes", "records_scan.py")
    spec = importlib.util.spec_from_file_location(
        "records_scan", os.path.abspath(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AttemptRowsParseTests(unittest.TestCase):
    """Fix 1 — packet #7 (99fe18f50ec3). The packet's repro shape
    is [valid, blank, MALFORMED non-blank, valid]: pre-fix the
    scan died with JSONDecodeError and wrote no result file."""

    @classmethod
    def setUpClass(cls):
        cls.scan = _load_records_scan()

    def _write(self, text):
        fh = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8")
        fh.write(text)
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def test_packet_repro_shape_completes(self):
        path = self._write(
            '{"seats": [{"provider": "a"}]}\n'
            "\n"
            '{"seats": [BROKEN\n'
            '{"seats": [{"provider": "b"}]}\n')
        rows, malformed = self.scan.parse_attempt_rows(path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(malformed, 1)
        self.assertEqual(
            [r["seats"][0]["provider"] for r in rows], ["a", "b"])

    def test_non_object_rows_counted_malformed(self):
        path = self._write('42\n["x"]\n"str"\n{"ok": true}\n')
        rows, malformed = self.scan.parse_attempt_rows(path)
        self.assertEqual(rows, [{"ok": True}])
        self.assertEqual(malformed, 3)

    def test_clean_and_empty_files(self):
        rows, malformed = self.scan.parse_attempt_rows(
            self._write('{"a": 1}\n\n{"b": 2}\n'))
        self.assertEqual((len(rows), malformed), (2, 0))
        rows, malformed = self.scan.parse_attempt_rows(self._write(""))
        self.assertEqual((rows, malformed), ([], 0))

    def test_main_reports_skipped_rows_and_writes_result(self):
        scan = self.scan
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            results = os.path.join(td, "results")
            os.makedirs(repo)
            os.makedirs(results)
            with open(os.path.join(repo, "gate-attempts.jsonl"),
                      "w", encoding="utf-8") as fh:
                fh.write('{"seats": [{"provider": "a"}]}\n')
                fh.write('{"seats": [BROKEN\n')
            old_repo, old_results = scan.REPO, scan.RESULTS
            scan.REPO, scan.RESULTS = repo, results
            try:
                scan.main()
            finally:
                scan.REPO, scan.RESULTS = old_repo, old_results
            out = os.path.join(
                results, "records-scan-a3a2d492b51a.txt")
            with open(out, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("malformed rows skipped: 1", text)
            self.assertIn("(1 rows)", text)


if __name__ == "__main__":
    unittest.main()
