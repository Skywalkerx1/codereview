"""v0.9.5 fixes — the three machinery bars of the review-v15
closing run (issue report
~/workspace/issue-reports/2026-11-04-codereview-v15-closing-run.md):

1. Oversized diff sections are sub-split across batches at hunk
   boundaries (then line boundaries, then character splits of a
   single over-long line) instead of being truncated by
   _batch_sections_detailed — round 1 of review-v15 degraded
   solely because core.py's cumulative section (94,494 chars)
   exceeded the 80,000-char batch budget.
2. Verification runs honor the fallback seat map: a quota-failed
   primary is served by the fallback configured for its lens, so
   the family that raised a finding can finder-confirm it (in
   review-v15-verify1 the OpenAI-raised blocker came back
   unjudged because the runner's verify path dropped the map).
3. record-verify --chain normalizes abbreviated range endpoints
   to full SHAs before the contiguity comparison — records store
   full SHAs in `head`, and a raw string comparison reported a
   gap between a commit and itself.

All providers are scripted fakes; the git fixtures are real
temporary repositories, in the established suite style."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, core  # noqa: E402


def _hunk(idx, n_lines, line_len=40):
    lines = [f"@@ -{idx * 100},1 +{idx * 100},{n_lines} @@\n"]
    for j in range(n_lines):
        lines.append("+" + f"hunk{idx} line{j} ".ljust(line_len, "x")
                     + "\n")
    return "".join(lines)


def _section(file, hunks):
    head = (f"diff --git a/{file} b/{file}\n"
            f"--- a/{file}\n+++ b/{file}\n")
    return head + "".join(hunks)


class SubSplitBatchingTests(unittest.TestCase):
    """FIX 1: _batch_sections_detailed sub-splits oversized
    sections; nothing is truncated, every batch is in budget,
    and the coverage ledger names the file in every batch that
    carries a piece of it."""

    def test_multi_hunk_section_lands_completely(self):
        hunks = [_hunk(i, 12) for i in range(6)]
        text = _section("src/big.py", hunks)
        self.assertGreater(len(text), 2000)
        batches, batch_files, incomplete = \
            core._batch_sections_detailed(
                [("src/big.py", text)], 1000)
        self.assertFalse(incomplete)
        self.assertTrue(all(len(b) <= 1000 for b in batches))
        self.assertGreater(len(batches), 1)
        joined = "".join(batches)
        for i in range(6):
            self.assertIn(f"hunk{i} line0", joined)
            self.assertIn(f"hunk{i} line11", joined)
        self.assertEqual(batch_files,
                         [["src/big.py"]] * len(batches))

    def test_v15_shaped_section_real_numbers(self):
        # The review-v15 shape by construction: one file whose
        # cumulative section is ~94,494 chars against an 80,000
        # budget. It must land completely, truncated=False.
        hunks = [_hunk(i, 20, line_len=460) for i in range(10)]
        text = _section("src/codereview/core.py", hunks)
        self.assertGreater(len(text), 90000)
        self.assertLess(len(text), 100000)
        batches, batch_files, incomplete = \
            core._batch_sections_detailed(
                [("src/codereview/core.py", text)], 80000)
        self.assertFalse(incomplete)
        self.assertTrue(all(len(b) <= 80000 for b in batches))
        joined = "".join(batches)
        for i in range(10):
            self.assertIn(f"hunk{i} line19", joined)
        self.assertEqual(
            batch_files,
            [["src/codereview/core.py"]] * len(batches))

    def test_oversized_hunk_splits_at_line_boundaries(self):
        # One hunk far larger than the budget, many short lines:
        # the hunk splits at line boundaries, the @@ header and
        # file preamble repeat, no line is lost or cut.
        text = _section("a.py", [_hunk(0, 60)])
        batches, batch_files, incomplete = \
            core._batch_sections_detailed([("a.py", text)], 400)
        self.assertFalse(incomplete)
        self.assertTrue(all(len(b) <= 400 for b in batches))
        joined = "".join(batches)
        for j in range(60):
            self.assertIn(f"hunk0 line{j} ", joined)
        self.assertEqual(batch_files, [["a.py"]] * len(batches))

    def test_single_overlong_line_is_character_split(self):
        line = "+" + "q" * 4999 + "\n"
        text = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                "@@ -1,1 +1,1 @@\n" + line)
        batches, batch_files, incomplete = \
            core._batch_sections_detailed([("a.py", text)], 1000)
        self.assertFalse(incomplete)
        self.assertTrue(all(len(b) <= 1000 for b in batches))
        self.assertGreater(len(batches), 1)
        # Every character of the line survives (the repeated
        # stems add header text, never remove content; "q"
        # appears nowhere in the headers, so the count is exact).
        self.assertEqual("".join(batches).count("q"), 4999)
        self.assertEqual(batch_files, [["a.py"]] * len(batches))

    def test_unplaceable_budget_is_loud_and_keeps_content(self):
        # A budget smaller than the repeated section head cannot
        # frame any piece: the batching reports incomplete (the
        # run degrades) and the section is carried whole — loud,
        # never a silent truncation.
        text = _section("a.py", [_hunk(0, 3)])
        batches, batch_files, incomplete = \
            core._batch_sections_detailed([("a.py", text)], 10)
        self.assertTrue(incomplete)
        self.assertEqual("".join(batches), text)
        self.assertEqual(batch_files, [["a.py"]])

    def test_run_review_coverage_complete_on_oversized_section(self):
        hunks = [_hunk(i, 12) for i in range(4)]
        patch = _section("src/big.py", hunks)

        def ok(prompt):
            return json.dumps({"verdict": "pass", "summary": "ok",
                               "findings": []})

        meta = {"a": {"family": "famA", "tier": "paid"},
                "b": {"family": "famB", "tier": "paid"}}
        report = core.run_review(
            patch, {"a": ok, "b": ok}, max_patch_chars=600,
            seat_meta=meta, sleep=lambda *_a: None)
        self.assertFalse(report["truncated"])
        self.assertFalse(report["degraded"])
        cov = report["coverage"]
        self.assertTrue(cov["complete"], cov)
        self.assertGreater(cov["batch_count"], 1)
        self.assertEqual(
            cov["files"]["src/big.py"]["batches"],
            list(range(1, cov["batch_count"] + 1)))
        self.assertEqual(report["gate"], "pass")


VERIFY_PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,3 @@\n"
    " import os\n"
    "+VALUE = compute_total(items) if items else 0\n"
    "+print(VALUE)\n")

EVIDENCE = ("compute_total in app.py guards the total: VALUE is "
            "only computed when items is non-empty")


def _previous():
    return {"gate": "blocked", "findings": [{
        "id": "f-openai-1", "severity": "blocker",
        "category": "correctness", "file": "app.py", "line": 2,
        "title": "Total computed without a guard",
        "evidence": "VALUE = compute_total(items)",
        "recommendation": "guard it", "confidence": 0.9,
        "sources": ["openai"], "consensus": False}]}


def _judge(prompt):
    return json.dumps({
        "resolutions": [{"finding_id": "f-openai-1",
                         "status": "invalid",
                         "evidence": EVIDENCE}],
        "new_findings": []})


def _quota_boom(prompt):
    raise RuntimeError("HTTP 429 quota exceeded: "
                       "resource_exhausted")


class VerifyFallbackTests(unittest.TestCase):
    """FIX 2: run_verification honors the review path's fallback
    map — the finder-confirmation deadlock of review-v15-verify1
    (quota-failed Gemini primary, no OpenAI seat, the OpenAI
    blocker unjudged) cannot recur."""

    def test_fallback_serves_and_finder_confirmation_completes(self):
        report = core.run_verification(
            VERIFY_PATCH,
            {"gemini": _quota_boom, "nvidia": _judge},
            _previous(), "rebutted with evidence",
            fallbacks={"correctness": ("openai", _judge)},
            sleep=lambda *_a: None)
        self.assertEqual(report["gate"], "pass",
                         report["gate_reasons"])
        self.assertEqual([f["id"] for f in report["cleared"]],
                         ["f-openai-1"])
        self.assertEqual(report["unjudged"], [])
        self.assertFalse(report["degraded"])
        by_provider = {r["provider"]: r
                       for r in report["reviewer_reports"]}
        self.assertIn("openai", by_provider)
        self.assertEqual(by_provider["openai"]["status"], "ok")
        self.assertEqual(by_provider["openai"]["fallback_for"],
                         "gemini")
        self.assertIn("429", by_provider["openai"]
                      ["primary_error"])
        self.assertTrue(any("fallback" in reason
                            for reason in report["gate_reasons"]))

    def test_without_fallback_the_finding_stays_unjudged(self):
        # The pre-fix behaviour, pinned: same panel, no fallback
        # map — the finder's family never speaks, so the finding
        # is unjudged and the round is INCONCLUSIVE.
        report = core.run_verification(
            VERIFY_PATCH,
            {"gemini": _quota_boom, "nvidia": _judge},
            _previous(), "rebutted with evidence",
            sleep=lambda *_a: None)
        self.assertEqual(report["gate"], "inconclusive")
        self.assertEqual([f["id"] for f in report["unjudged"]],
                         ["f-openai-1"])
        self.assertTrue(report["degraded"])

    def test_fallback_failure_is_recorded_not_silent(self):
        def fb_boom(prompt):
            raise RuntimeError("openai down")

        report = core.run_verification(
            VERIFY_PATCH,
            {"gemini": _quota_boom, "nvidia": _judge},
            _previous(), "rebutted with evidence",
            fallbacks={"correctness": ("openai", fb_boom)},
            sleep=lambda *_a: None)
        self.assertTrue(report["degraded"])
        gemini_rec = [r for r in report["reviewer_reports"]
                      if r["provider"] == "gemini"][0]
        self.assertEqual(gemini_rec["status"], "error")
        self.assertIn("fallback 'openai' also failed",
                      gemini_rec["error"])

    def test_cli_verify_path_forwards_fallbacks(self):
        # The runner seam (internal_review.py passes
        # fallbacks_override into cli.main): the verify branch
        # must forward it to run_verification.
        with tempfile.TemporaryDirectory() as tmp:
            patch_path = os.path.join(tmp, "fix.diff")
            with open(patch_path, "w", encoding="utf-8") as fh:
                fh.write(VERIFY_PATCH)
            prev_path = os.path.join(tmp, "previous.json")
            with open(prev_path, "w", encoding="utf-8") as fh:
                json.dump(_previous(), fh)
            out = os.path.join(tmp, "out")
            rc = cli.main(
                ["--patch", patch_path,
                 "--verify-previous", prev_path,
                 "--builder-response", "rebutted with evidence",
                 "--out", out],
                providers_override={"gemini": _quota_boom,
                                    "nvidia": _judge},
                seat_meta_override={
                    "gemini": {"family": "google", "tier": "free"},
                    "nvidia": {"family": "nvidia", "tier": "free"},
                    "openai": {"family": "openai", "tier": "paid"}},
                fallbacks_override={
                    "correctness": ("openai", _judge)})
            self.assertEqual(rc, 0)
            written = [n for n in os.listdir(out)
                       if n.endswith(".json")]
            self.assertEqual(len(written), 1)
            with open(os.path.join(out, written[0]),
                      encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertEqual(report["gate"], "pass")
            providers = {r["provider"] for r in
                         report["reviewer_reports"]}
            self.assertIn("openai", providers)


class _GitRepo(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        env = dict(os.environ, HOME="/home/hatch")
        self.env = env

        def git(*args):
            return subprocess.run(
                ["git", "-C", self.td, "-c", "user.email=t@t",
                 "-c", "user.name=t", *args],
                capture_output=True, text=True, env=env,
                check=True).stdout.strip()

        self.git = git
        git("init", "-q")

    def write_commit(self, files, message):
        for path, content in files.items():
            full = os.path.join(self.td, path)
            if os.path.dirname(path):
                os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(content)
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def patch_hash(self, rng):
        patch = core.collect_git_patch(self.td, range_spec=rng)
        return hashlib.sha256(patch.encode("utf-8")).hexdigest()


class ChainShaNormalizationTests(_GitRepo):
    """FIX 3: verify_chain resolves abbreviated range endpoints
    to full SHAs before comparing contiguity — the review-v15
    chain (ranges supplied as e3fc6a8…, heads stored full) failed
    ranges_contiguous against itself."""

    def setUp(self):
        super().setUp()
        self.c1 = self.write_commit({"a.txt": "one\n"}, "c1")
        self.c2 = self.write_commit({"a.txt": "one\ntwo\n"}, "c2")
        self.c3 = self.write_commit(
            {"a.txt": "one\ntwo\nthree\n"}, "c3")
        self.finding = {"id": "f123", "severity": "major",
                        "file": "a.txt", "title": "a defect",
                        "sources": ["seatA"], "consensus": False}
        reports = [
            {"provider": "g", "lens": "correctness",
             "status": "ok", "family": "google", "tier": "free"},
            {"provider": "n", "lens": "operations",
             "status": "ok", "family": "nvidia", "tier": "paid"}]
        # Both rounds carry the pre-stamp declarations
        # every real record of the era carried (P6-12b: a
        # hash-less record with NO declarations no longer
        # reads legacy).
        self.round1 = {
            "version": "0.9.5",
            "created_at": "2026-11-04T00:00:00+00:00",
            "mode": "review", "gate": "blocked", "degraded": False,
            "test_results": [{"command": "t", "ok": True}],
            "reviewer_reports": reports,
            "coverage": {"complete": True, "batch_count": 1,
                         "files": {}},
            "findings": [self.finding],
            "range": f"{self.c1}..{self.c2}", "head": self.c2,
            "patch_sha256": self.patch_hash(
                f"{self.c1}..{self.c2}")}
        self.verify = {
            "version": "0.9.5",
            "created_at": "2026-11-04T01:00:00+00:00",
            "mode": "verify", "gate": "pass", "degraded": False,
            "test_results": [{"command": "t", "ok": True}],
            "reviewer_reports": [
                {k: v for k, v in r.items() if k != "lens"}
                for r in reports],
            "cleared": [{**self.finding,
                         "cleared_by": ["fixed", "fixed"]}],
            "remaining": [], "unjudged": [], "findings": [],
            "range": f"{self.c2}..{self.c3}", "head": self.c3,
            "patch_sha256": self.patch_hash(
                f"{self.c2}..{self.c3}")}

    def _chain(self, records):
        return core.verify_chain(records, repo=self.td,
                                 record_dirs=["r1", "r2"])

    def _checks(self, result):
        return {c["name"]: c for c in result["checks"]}

    def test_abbreviated_ranges_verify_like_full(self):
        full = self._chain([self.round1, self.verify])
        self.assertTrue(full["eligible"], full["checks"])
        import copy
        r1 = copy.deepcopy(self.round1)
        r2 = copy.deepcopy(self.verify)
        r1["range"] = f"{self.c1[:7]}..{self.c2[:7]}"
        r2["range"] = f"{self.c2[:7]}..{self.c3[:7]}"
        abbr = self._chain([r1, r2])
        self.assertTrue(self._checks(abbr)
                        ["ranges_contiguous"]["ok"],
                        abbr["checks"])
        self.assertEqual(abbr["eligible"], full["eligible"])

    def test_abbreviated_gap_still_fails(self):
        import copy
        r2 = copy.deepcopy(self.verify)
        # Starts at c1 instead of c2: a real gap, in abbreviated
        # form — normalization must not paper over it.
        r2["range"] = f"{self.c1[:7]}..{self.c3[:7]}"
        result = self._chain([self.round1, r2])
        self.assertFalse(result["eligible"])
        self.assertFalse(self._checks(result)
                         ["ranges_contiguous"]["ok"])


if __name__ == "__main__":
    unittest.main()
