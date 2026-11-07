"""L6 F5: write_report's auto-stem choice must CLAIM the stem
exclusively. The P6-02 exists-check left a same-second race:
two processes could both observe the stem free, both write,
and the later os.replace silently overwrote the earlier run's
record. An auto stem is now claimed with an O_EXCL claim file
for the duration of the write; an explicit stem (the caller's
contract — the CLI's post-hooks rewrite) is never claimed or
renamed."""

import datetime as _dt
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core  # noqa: E402

FIXED = _dt.datetime(2026, 11, 7, 12, 0, 0, tzinfo=_dt.timezone.utc)
BASE = "codereview-20261107-120000"
REPORT = {"gate": "pass", "gate_reasons": [], "findings": []}


class _FixedDateTime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED


_FAKE_DATETIME = types.SimpleNamespace(
    datetime=_FixedDateTime, timezone=_dt.timezone,
    timedelta=_dt.timedelta, date=_dt.date, time=_dt.time)


def _write(report, out, stem=None):
    with mock.patch.object(core, "datetime", _FAKE_DATETIME):
        return core.write_report(report, out, stem=stem)


class AutoStemClaimTests(unittest.TestCase):
    def test_claimed_stem_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            claim = os.path.join(tmp, BASE + ".json.claim")
            with open(claim, "w", encoding="utf-8") as fh:
                fh.write("held by another process")
            jpath, _mpath = _write(REPORT, tmp)
            self.assertEqual(os.path.basename(jpath),
                             BASE + "-2.json")
            # The other process's claim is not ours to remove;
            # our own claim on the -2 stem is released.
            self.assertTrue(os.path.exists(claim))
            self.assertFalse(os.path.exists(
                os.path.join(tmp, BASE + "-2.json.claim")))

    def test_no_claim_left_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            jpath, _mpath = _write(REPORT, tmp)
            self.assertEqual(os.path.basename(jpath), BASE + ".json")
            self.assertEqual(
                [n for n in os.listdir(tmp)
                 if n.endswith(".claim")], [])
            with open(jpath, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["gate"], "pass")

    def test_explicit_stem_ignores_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            claim = os.path.join(tmp, "rec.json.claim")
            with open(claim, "w", encoding="utf-8") as fh:
                fh.write("not ours")
            jpath, _mpath = _write(REPORT, tmp, stem="rec")
            self.assertEqual(os.path.basename(jpath), "rec.json")
            self.assertTrue(os.path.exists(claim))


if __name__ == "__main__":
    unittest.main()
