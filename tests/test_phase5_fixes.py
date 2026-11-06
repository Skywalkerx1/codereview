"""Phase 5 (external test pass, interfaces & protocol
conformance) regression pins. One class per finding; each test
names the behaviour the Phase 5 report found missing on the
0.12.1 drop and that master must now hold."""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import sarif  # noqa: E402


def _sarif_result(finding):
    record = {"gate": "blocked", "findings": [finding]}
    log = sarif.record_to_sarif(record)
    return log["runs"][0]["results"][0]


class TestP501Sarif(unittest.TestCase):
    BASE = {"id": "f1", "severity": "major", "title": "t",
            "category": "security"}

    def loc(self, **kw):
        f = dict(self.BASE, **kw)
        return _sarif_result(f)["locations"][0]["physicalLocation"]

    def test_uri_percent_encoded(self):
        self.assertEqual(
            self.loc(file="src/a b.py")["artifactLocation"]["uri"],
            "src/a%20b.py")
        self.assertEqual(
            self.loc(file="a#b.py")["artifactLocation"]["uri"],
            "a%23b.py")
        self.assertEqual(
            self.loc(file="src/ü.py")["artifactLocation"]["uri"],
            "src/%C3%BC.py")

    def test_uri_never_absolute_or_escaping(self):
        for hostile in ("C:/work/x.py", "C:\\work\\x.py",
                        "/etc/passwd", "../outside.py",
                        "a/../../b.py", "//server/share.py"):
            uri = self.loc(file=hostile)["artifactLocation"]["uri"]
            self.assertFalse(uri.startswith("/"), uri)
            self.assertNotIn("..", uri.split("/"), uri)
            self.assertNotRegex(uri, r"^[A-Za-z][A-Za-z0-9+.-]*:")

    def test_uri_normal_paths_unchanged(self):
        self.assertEqual(
            self.loc(file="src/app.py")["artifactLocation"]["uri"],
            "src/app.py")

    def test_start_line_clamped_to_int32(self):
        region = self.loc(file="a.py", line=10 ** 12)["region"]
        self.assertEqual(region["startLine"], 2 ** 31 - 1)

    def test_message_control_characters_stripped(self):
        r = _sarif_result(dict(self.BASE, title="a\nb\x00c\x1bd"))
        self.assertEqual(r["message"]["text"], "abcd")

    def test_determinism_kept(self):
        record = {"gate": "blocked", "findings": [
            dict(self.BASE, file="src/a b.py", line=3)]}
        one = json.dumps(sarif.record_to_sarif(record),
                         sort_keys=True)
        two = json.dumps(sarif.record_to_sarif(record),
                         sort_keys=True)
        self.assertEqual(one, two)


if __name__ == "__main__":
    unittest.main()
