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

    def test_stale_check_then_late_claim_yields_the_stem(self):
        # F5 rerun interleaving: our exists-check runs BEFORE a
        # rival writes (stem looks free), the rival claims,
        # writes and releases, and only then does our claim
        # land. The post-claim revalidation must spot the pair
        # that appeared in between and move to the next stem —
        # without it this second write silently overwrites the
        # first record (reproduced with her f5_race.py: two
        # writers returning the same stem, one record lost).
        with tempfile.TemporaryDirectory() as tmp:
            jpath1, _mpath1 = _write(REPORT, tmp)
            self.assertEqual(os.path.basename(jpath1),
                             BASE + ".json")
            real_exists = os.path.exists
            lied = set()

            def stale_exists(path):
                name = os.path.basename(str(path))
                if name in (BASE + ".json", BASE + ".md") \
                        and name not in lied:
                    lied.add(name)
                    return False
                return real_exists(path)

            other = {"gate": "blocked", "gate_reasons": [],
                     "findings": []}
            with mock.patch.object(os.path, "exists",
                                   stale_exists):
                jpath2, _mpath2 = _write(other, tmp)
            self.assertEqual(os.path.basename(jpath2),
                             BASE + "-2.json")
            with open(jpath1, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["gate"], "pass")
            self.assertEqual(
                [n for n in os.listdir(tmp)
                 if n.endswith(".claim")], [])

    def test_explicit_stem_ignores_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            claim = os.path.join(tmp, "rec.json.claim")
            with open(claim, "w", encoding="utf-8") as fh:
                fh.write("not ours")
            jpath, _mpath = _write(REPORT, tmp, stem="rec")
            self.assertEqual(os.path.basename(jpath), "rec.json")
            self.assertTrue(os.path.exists(claim))


class RangeRecordedWordingTests(unittest.TestCase):
    """L6 rerun S3: a fresh patch-mode record carries no range
    because of its MODE, and verify_record must not explain the
    absence as 'predates range/head tracking (v0.7.3)'. Only a
    record whose own version stamp predates the tracking (or
    declares none) earns the pre-tracking explanation."""

    def _detail(self, record):
        result = core.verify_record(record)
        for check in result["checks"]:
            if check["name"] == "range_recorded":
                self.assertFalse(check["ok"])
                return check["detail"]
        self.fail("no range_recorded check emitted")

    def test_fresh_patch_mode_record_says_patch_mode(self):
        detail = self._detail({"gate": "pass",
                               "degraded": False,
                               "version": "0.13.0"})
        self.assertIn("no range recorded (patch mode)", detail)

    def test_pre_tracking_record_keeps_age_explanation(self):
        detail = self._detail({"gate": "pass",
                               "degraded": False,
                               "version": "0.7.0"})
        self.assertIn("predates range/head tracking", detail)

    def test_unversioned_record_keeps_age_explanation(self):
        detail = self._detail({"gate": "pass",
                               "degraded": False})
        self.assertIn("predates range/head tracking", detail)


if __name__ == "__main__":
    unittest.main()
