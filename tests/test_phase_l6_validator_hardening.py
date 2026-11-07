"""validate_record must report, never raise, on a non-list checks.*."""
import copy
import glob
import json
import unittest

from codereview import record_schema


class ChecksTypeTests(unittest.TestCase):
    def _record(self):
        from codereview import core
        report = core.run_review(
            "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n",
            {"a": lambda p: '{"findings": []}'})
        return record_schema.finalize_record(report)

    def test_non_list_checks_value_is_a_problem_not_a_crash(self):
        record = self._record()
        for junk in (5, 1.5, float("nan"), True, "x", {"a": 1}):
            for key in ("run", "not_run", "unavailable"):
                bad = copy.deepcopy(record)
                bad["checks"][key] = junk
                problems = record_schema.validate_record(bad)
                self.assertTrue(
                    any(f"checks.{key}" in p for p in problems),
                    (key, junk, problems))


if __name__ == "__main__":
    unittest.main()
