"""Step 6 — gate profiles: policy B1 as the `balanced` profile
(honest-negatives solution §2.4/§2.6; candidate frozen by the
step-4 replay sweep, 2026-11-04).

B1 (per-lens corroboration): a blocking-severity finding whose
merged sources are SOLELY the operations lens is demoted to a
visible minor unless a correctness-lens seat or the
deterministic layer also reported the same defect — "same
defect" approximated live by the gate's own merge identity
(the replay grouped semantically/adjudicated; the gap is
documented in core._apply_gate_profile).

`strict` is today's behaviour and stays the DEFAULT: the
freeze terms confirm B1 once on the holdout (step 7, Baseline
v2) before any default change. `quiet` (blanket corroboration)
was rejected on the sweep evidence and must stay unimplemented
— an unknown profile is a loud error, never a silent fallback.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, core, policy  # noqa: E402

PATCH = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,1 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""

FINDING = {
    "severity": "blocker", "category": "reliability",
    "file": "app/util.py", "line": 6,
    "title": "sub() retries forever with no timeout or backoff",
    "evidence": "    return a - b",
    "evidence_quote": "    return a - b",
    "recommendation": "bound the retry loop",
    "confidence": 0.9,
}


def lens_provider(ops_finding=None, corr_finding=None):
    """One stub seat serving whichever lens the prompt asks
    for: the ops finding under the operations lens, the
    correctness finding under the correctness lens."""
    def serve(prompt):
        if "OPERATIONS & RELIABILITY lens" in prompt:
            findings = [ops_finding] if ops_finding else []
        else:
            findings = [corr_finding] if corr_finding else []
        return json.dumps({"summary": "stub", "findings": findings})
    return serve


def merged_finding(severity="blocker", sources=("ops-seat",),
                   source_lenses=None, **kw):
    f = {"id": "fp1", "rule": "", "severity": severity,
         "category": "reliability", "file": "app/util.py",
         "line": 6, "title": "t", "evidence": "e",
         "evidence_quote": "q", "recommendation": "r",
         "confidence": 0.9, "sources": list(sources),
         "consensus": len(sources) > 1}
    if source_lenses is not None:
        f["source_lenses"] = source_lenses
    f.update(kw)
    return f


class ApplyGateProfileTests(unittest.TestCase):
    """The pure profile pass over merged findings."""

    def test_strict_changes_no_severity(self):
        f = merged_finding(source_lenses={"ops-seat": ["operations"]})
        out, demotions = core._apply_gate_profile([f], "strict")
        self.assertEqual(out[0]["severity"], "blocker")
        self.assertEqual(demotions, [])
        self.assertNotIn("profile_demotion", out[0])

    def test_balanced_demotes_ops_only_blocker(self):
        f = merged_finding(source_lenses={"ops-seat": ["operations"]})
        out, demotions = core._apply_gate_profile([f], "balanced")
        self.assertEqual(len(out), 1)  # demoted, never deleted
        self.assertEqual(out[0]["severity"], "minor")
        dem = out[0]["profile_demotion"]
        self.assertEqual(dem["rule"], "B1")
        self.assertEqual(dem["from"], "blocker")
        self.assertEqual(dem["to"], "minor")
        self.assertEqual(demotions[0]["finding_id"], "fp1")
        self.assertEqual(demotions[0]["from"], "blocker")

    def test_balanced_demotes_ops_only_major(self):
        f = merged_finding(
            severity="major",
            source_lenses={"ops-seat": ["operations"]})
        out, _ = core._apply_gate_profile([f], "balanced")
        self.assertEqual(out[0]["severity"], "minor")

    def test_balanced_keeps_corroborated_ops_finding(self):
        f = merged_finding(
            sources=("ops-seat", "corr-seat"),
            source_lenses={"ops-seat": ["operations"],
                           "corr-seat": ["correctness"]})
        out, demotions = core._apply_gate_profile([f], "balanced")
        self.assertEqual(out[0]["severity"], "blocker")
        self.assertEqual(demotions, [])

    def test_balanced_keeps_ops_plus_deterministic(self):
        f = merged_finding(
            sources=("ops-seat", "deterministic"),
            source_lenses={"ops-seat": ["operations"],
                           "deterministic": ["deterministic"]})
        out, demotions = core._apply_gate_profile([f], "balanced")
        self.assertEqual(out[0]["severity"], "blocker")
        self.assertEqual(demotions, [])

    def test_balanced_never_gates_correctness_or_deterministic(self):
        corr = merged_finding(
            sources=("corr-seat",),
            source_lenses={"corr-seat": ["correctness"]})
        det = merged_finding(
            sources=("deterministic",),
            source_lenses={"deterministic": ["deterministic"]})
        out, demotions = core._apply_gate_profile(
            [corr, det], "balanced")
        self.assertEqual([f["severity"] for f in out],
                         ["blocker", "blocker"])
        self.assertEqual(demotions, [])

    def test_seat_serving_both_lenses_is_not_solely_operations(self):
        f = merged_finding(
            sources=("solo",),
            source_lenses={"solo": ["correctness", "operations"]})
        out, demotions = core._apply_gate_profile([f], "balanced")
        self.assertEqual(out[0]["severity"], "blocker")
        self.assertEqual(demotions, [])

    def test_unattributed_source_fails_safe(self):
        # A merged finding whose raising lens is not recorded
        # (legacy shape) must never be demoted on a guess.
        f = merged_finding()
        self.assertNotIn("source_lenses", f)
        out, demotions = core._apply_gate_profile([f], "balanced")
        self.assertEqual(out[0]["severity"], "blocker")
        self.assertEqual(demotions, [])

    def test_non_blocking_ops_finding_untouched(self):
        f = merged_finding(
            severity="minor",
            source_lenses={"ops-seat": ["operations"]})
        out, demotions = core._apply_gate_profile([f], "balanced")
        self.assertEqual(out[0]["severity"], "minor")
        self.assertNotIn("profile_demotion", out[0])
        self.assertEqual(demotions, [])

    def test_evidence_class_metadata(self):
        det = merged_finding(sources=("deterministic",),
                             source_lenses={
                                 "deterministic": ["deterministic"]})
        merged = merged_finding(
            sources=("a", "b"),
            source_lenses={"a": ["operations"],
                           "b": ["correctness"]})
        single = merged_finding(
            sources=("a",), source_lenses={"a": ["operations"]})
        out, _ = core._apply_gate_profile(
            [det, merged, single], "strict")
        self.assertEqual([f["evidence_class"] for f in out],
                         ["E0", "E1", "E3"])


class MergeLensAttributionTests(unittest.TestCase):
    """merge_findings unions per-source lens attribution."""

    def test_merge_unions_source_lenses(self):
        a = core._normalize_finding(FINDING, "ops-seat",
                                    lens="operations")
        b = core._normalize_finding(FINDING, "corr-seat",
                                    lens="correctness")
        merged = core.merge_findings([a, b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source_lenses"],
                         {"corr-seat": ["correctness"],
                          "ops-seat": ["operations"]})
        self.assertEqual(sorted(merged[0]["sources"]),
                         ["corr-seat", "ops-seat"])


class RunReviewProfileTests(unittest.TestCase):
    """Profile plumbing through a full review round."""

    def review(self, **kw):
        return core.run_review(PATCH, {"a": lens_provider(FINDING),
                                       "b": lens_provider(FINDING)},
                               **kw)

    def test_default_profile_is_strict_and_blocks(self):
        rep = self.review()
        self.assertEqual(rep["gate"], "blocked")
        self.assertEqual(rep["gate_profile"]["profile"], "strict")
        self.assertEqual(rep["gate_profile"]["demotions"], [])
        f = rep["findings"][0]
        self.assertEqual(f["severity"], "blocker")
        # Seat b drew the operations task (tasks cycle the
        # lenses in order); only its prompt earned the finding.
        self.assertEqual(f["source_lenses"],
                         {"b": ["operations"]})

    def test_balanced_demotes_and_passes(self):
        rep = self.review(gate_profile="balanced")
        self.assertEqual(rep["gate"], "pass")
        self.assertEqual(rep["gate_profile"]["profile"], "balanced")
        self.assertEqual(rep["gate_profile"]["source"], "argument")
        self.assertEqual(len(rep["gate_profile"]["demotions"]), 1)
        f = rep["findings"][0]
        self.assertEqual(f["severity"], "minor")
        self.assertEqual(f["profile_demotion"]["from"], "blocker")
        self.assertEqual(f["evidence_class"], "E3")
        # Demoted before the dispute ladder: it consumes no
        # cross-family confirmation.
        self.assertNotIn("cross_family", f)
        self.assertTrue(any("balanced" in r and "B1" in r
                            for r in rep["gate_reasons"]))

    def test_balanced_keeps_corroborated_blocker(self):
        both = lens_provider(FINDING, FINDING)
        rep = core.run_review(PATCH, {"a": both, "b": both},
                              gate_profile="balanced")
        self.assertEqual(rep["gate"], "blocked")
        self.assertEqual(rep["gate_profile"]["demotions"], [])
        self.assertEqual(rep["findings"][0]["severity"], "blocker")
        self.assertEqual(rep["findings"][0]["evidence_class"], "E1")

    def test_policy_file_profile_applies(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".codereview.toml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('[gate]\nprofile = "balanced"\n')
            pol = policy.load_policy(path)
        rep = self.review(policy=pol)
        self.assertEqual(rep["gate"], "pass")
        self.assertEqual(rep["gate_profile"]["profile"], "balanced")
        self.assertEqual(rep["gate_profile"]["source"], "policy")

    def test_argument_overrides_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".codereview.toml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('[gate]\nprofile = "balanced"\n')
            pol = policy.load_policy(path)
        rep = self.review(policy=pol, gate_profile="strict")
        self.assertEqual(rep["gate"], "blocked")
        self.assertEqual(rep["gate_profile"]["profile"], "strict")

    def test_unknown_profile_is_a_loud_error(self):
        with self.assertRaises(ValueError):
            self.review(gate_profile="quiet")


class PolicyGateTableTests(unittest.TestCase):
    def load(self, tmp, text):
        path = os.path.join(tmp, ".codereview.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return policy.load_policy(path)

    def test_default_profile_is_strict(self):
        self.assertEqual(policy.default_policy()["gate"],
                         {"profile": "strict"})

    def test_file_without_gate_table_defaults_to_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = self.load(tmp, "[panel]\nmin_seats = 1\n")
        self.assertEqual(pol["gate"]["profile"], "strict")

    def test_balanced_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = self.load(tmp, '[gate]\nprofile = "balanced"\n')
        self.assertEqual(pol["gate"]["profile"], "balanced")

    def test_unknown_profile_rejected_with_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError) as cm:
                self.load(tmp, '[gate]\nprofile = "quiet"\n')
        self.assertIn(":2:", str(cm.exception))

    def test_unknown_gate_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(policy.PolicyError):
                self.load(tmp, '[gate]\nprofil = "strict"\n')

    def test_render_includes_gate_table(self):
        text = policy.render_effective(policy.default_policy())
        self.assertIn("[gate]", text)
        self.assertIn('profile = "strict"', text)

    def test_profiles_pin_core_and_policy(self):
        self.assertEqual(policy.KNOWN_GATE_PROFILES,
                         core.GATE_PROFILES)


class GateProfileCliTests(unittest.TestCase):
    def run_cli(self, argv, **kw):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(argv, **kw)
        return rc, out.getvalue(), err.getvalue()

    def test_gate_profile_flag_reaches_the_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = os.path.join(tmp, "change.diff")
            with open(patch, "w", encoding="utf-8") as fh:
                fh.write(PATCH)
            outdir = os.path.join(tmp, "out")
            stub = lens_provider(FINDING)
            rc, _, _ = self.run_cli(
                ["--patch", patch, "--gate-profile", "balanced",
                 "--out", outdir],
                providers_override={"a": stub, "b": stub})
            self.assertEqual(rc, 0)
            records = [f for f in os.listdir(outdir)
                       if f.endswith(".json")]
            self.assertEqual(len(records), 1)
            with open(os.path.join(outdir, records[0]),
                      encoding="utf-8") as fh:
                record = json.load(fh)
            self.assertEqual(record["gate"], "pass")
            self.assertEqual(record["gate_profile"]["profile"],
                             "balanced")
            self.assertEqual(
                len(record["gate_profile"]["demotions"]), 1)

    def test_policy_check_prints_gate_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".codereview.toml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('[gate]\nprofile = "balanced"\n')
            rc, out, _ = self.run_cli(
                ["policy", "check", "--repo", tmp])
            self.assertEqual(rc, 0)
            self.assertIn('profile = "balanced"', out)


if __name__ == "__main__":
    unittest.main()
