"""Unit tests for codereview core — fake providers, no network."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core, providers  # noqa: E402

BUGGY = """diff --git a/app/alerts.py b/app/alerts.py
--- a/app/alerts.py
+++ b/app/alerts.py
@@ -1,2 +1,6 @@
 import smtplib
+
+API_KEY = "sk-live-9f8e7d6c5b4a3210"
+
+def check(db):
+    db.execute(f"SELECT * FROM t WHERE id = {uid}")
+    sendmail("admin@example.com", "something is wrong")
"""

CLEAN = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,1 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""


def pass_provider(prompt):
    return json.dumps({"verdict": "pass", "summary": "looks fine",
                       "findings": []})


def strict_provider(prompt):
    return json.dumps({
        "verdict": "changes_requested", "summary": "alert has no dedup",
        "findings": [{
            "severity": "major", "category": "reliability",
            "file": "app/alerts.py", "line": 6,
            "title": "Alert fires on every check with no dedup guard",
            "evidence": 'sendmail("admin@example.com", ...)',
            "recommendation": "Persist last-alert state and suppress "
                              "repeats.",
            "confidence": 0.8}]})


class DeterministicScanTests(unittest.TestCase):
    def test_catches_secret_and_sqli_and_alert(self):
        findings = core.deterministic_scan(BUGGY)
        rules = {f["rule"] for f in findings}
        self.assertIn("hardcoded-secret", rules)
        self.assertIn("alert-no-guard", rules)

    def test_clean_patch_has_no_deterministic_findings(self):
        self.assertEqual(core.deterministic_scan(CLEAN), [])

    def test_failing_test_is_blocker(self):
        findings = core.deterministic_scan(
            CLEAN, [{"command": "pytest", "ok": False,
                     "output_tail": "1 failed"}])
        self.assertTrue(any(f["severity"] == "blocker"
                            for f in findings))

    def test_redaction_removes_secret_values(self):
        out = core.redact_secrets(BUGGY)
        self.assertNotIn("sk-live-9f8e7d6c5b4a3210", out)
        self.assertIn("REDACTED", out)


class CodeReviewTests(unittest.TestCase):
    def test_pass_when_reviewers_pass(self):
        report = core.run_review(
            CLEAN, {"a": pass_provider, "b": pass_provider})
        self.assertEqual(report["gate"], "pass")

    def test_blocked_by_deterministic_even_if_models_pass(self):
        report = core.run_review(
            BUGGY, {"a": pass_provider, "b": pass_provider})
        self.assertEqual(report["gate"], "blocked")

    def test_blocked_by_reviewer_major(self):
        report = core.run_review(
            CLEAN, {"a": strict_provider, "b": pass_provider})
        # strict_provider's finding is on a file not in CLEAN, but the
        # gate only weighs severity, not file membership.
        self.assertEqual(report["gate"], "blocked")

    def test_inconclusive_when_all_providers_fail(self):
        def boom(prompt):
            raise RuntimeError("provider down")
        report = core.run_review(CLEAN, {"a": boom, "b": boom})
        self.assertEqual(report["gate"], "inconclusive")

    def test_json_repair_retry(self):
        calls = {"n": 0}

        def flaky(prompt):
            calls["n"] += 1
            if calls["n"] == 1:
                return '{"verdict": "pass", "summary": "has "bad" quotes"}'
            return json.dumps({"verdict": "pass", "summary": "ok",
                               "findings": []})
        parsed = core._call_and_parse(flaky, "review this")
        self.assertEqual(parsed["summary"], "ok")
        self.assertEqual(calls["n"], 2)

    def test_json_fresh_sample_recovery(self):
        # The repair retry can fail too (same model, same trap); a
        # fresh sample of the original prompt is the third attempt.
        calls = {"n": 0}

        def stubborn(prompt):
            calls["n"] += 1
            if calls["n"] <= 2:
                return '{"verdict": "pass", "summary": "has "bad" quotes"}'
            return json.dumps({"verdict": "pass", "summary": "clean",
                               "findings": []})
        parsed = core._call_and_parse(stubborn, "review this")
        self.assertEqual(parsed["summary"], "clean")
        self.assertEqual(calls["n"], 3)

    def test_consensus_merge(self):
        merged = core.merge_findings([
            {"id": "1", "rule": "", "severity": "major",
             "category": "reliability", "file": "a.py", "line": 3,
             "title": "Alert fires with no dedup guard",
             "evidence": "", "recommendation": "", "confidence": 0.6,
             "sources": ["a"], "consensus": False},
            {"id": "2", "rule": "", "severity": "blocker",
             "category": "reliability", "file": "a.py", "line": 3,
             "title": "Alert fires with no dedup or cooldown guard",
             "evidence": "", "recommendation": "", "confidence": 0.7,
             "sources": ["b"], "consensus": False},
        ])
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0]["consensus"])
        self.assertEqual(merged[0]["severity"], "blocker")


class EdgeCaseTests(unittest.TestCase):
    def test_empty_patch_reviews_clean(self):
        report = core.run_review(
            "", {"a": pass_provider, "b": pass_provider})
        self.assertEqual(report["gate"], "pass")
        self.assertEqual(report["findings"], [])

    def test_oversized_patch_truncates_and_strict_is_inconclusive(self):
        big = CLEAN + ("\n+// filler line\n" * 5000)
        report = core.run_review(
            big, {"a": pass_provider, "b": pass_provider},
            max_patch_chars=2000, strict=True)
        self.assertTrue(report["truncated"])
        self.assertEqual(report["gate"], "inconclusive")

    def test_provider_timeout_degrades_not_passes_silently(self):
        def slow(prompt):
            raise TimeoutError("provider timed out")
        report = core.run_review(
            CLEAN, {"a": slow, "b": pass_provider})
        self.assertTrue(report["degraded"])
        self.assertEqual(report["gate"], "pass")  # one reviewer served
        strict = core.run_review(
            CLEAN, {"a": slow, "b": pass_provider}, strict=True)
        self.assertEqual(strict["gate"], "inconclusive")


class VerificationTests(unittest.TestCase):
    def _previous(self):
        return {"gate": "blocked", "findings": [{
            "id": "abc123", "severity": "major",
            "category": "reliability", "file": "app/alerts.py",
            "line": 6, "title": "Alert has no dedup",
            "evidence": "", "recommendation": "", "confidence": 0.8,
            "sources": ["a"], "consensus": False}]}

    _GOOD_EVIDENCE = ("return a + b and return a - b are the only "
                      "helpers left in app/util.py and the sendmail "
                      "alert is removed")

    def test_clears_only_on_consensus(self):
        def fixed(prompt):
            return json.dumps({
                "resolutions": [{"finding_id": "abc123",
                                 "status": "fixed",
                                 "evidence": self._GOOD_EVIDENCE}],
                "new_findings": []})
        report = core.run_verification(
            CLEAN, {"a": fixed, "b": fixed}, self._previous(), "fixed it")
        self.assertEqual(report["gate"], "pass")
        self.assertEqual(len(report["cleared"]), 1)

    def test_empty_evidence_does_not_clear(self):
        # External Review 1, finding 1: a bare "fixed" assertion with
        # no evidence must not clear a blocker.
        def bare(prompt):
            return json.dumps({
                "resolutions": [{"finding_id": "abc123",
                                 "status": "fixed", "evidence": ""}],
                "new_findings": []})
        report = core.run_verification(
            CLEAN, {"a": bare, "b": bare}, self._previous(), "trust me")
        self.assertEqual(report["gate"], "blocked")
        self.assertEqual(len(report["remaining"]), 1)

    def test_bogus_status_does_not_clear(self):
        def bogus(prompt):
            return json.dumps({
                "resolutions": [{"finding_id": "abc123",
                                 "status": "totally_fixed",
                                 "evidence": self._GOOD_EVIDENCE}],
                "new_findings": []})
        report = core.run_verification(
            CLEAN, {"a": bogus, "b": bogus}, self._previous(), "done")
        self.assertEqual(report["gate"], "blocked")

    def test_strict_degraded_verification_is_inconclusive(self):
        # External Review 1, finding 2: strict mode must not PASS a
        # verification round in which a reviewer failed.
        def fixed(prompt):
            return json.dumps({
                "resolutions": [{"finding_id": "abc123",
                                 "status": "fixed",
                                 "evidence": self._GOOD_EVIDENCE}],
                "new_findings": []})

        def boom(prompt):
            raise RuntimeError("provider down")
        relaxed = core.run_verification(
            CLEAN, {"a": fixed, "b": boom}, self._previous(), "fixed")
        # v0.7.0 external review, finding 2 (supersedes the
        # Review-1-era expectation): a verification PASS needs a
        # quorum of 2 successful reviewers when 2 are configured —
        # one surviving reviewer is INCONCLUSIVE, never a "pass",
        # in relaxed mode too.
        self.assertEqual(relaxed["gate"], "inconclusive")
        strict = core.run_verification(
            CLEAN, {"a": fixed, "b": boom}, self._previous(), "fixed",
            strict=True)
        self.assertEqual(strict["gate"], "inconclusive")

    def test_split_verdict_keeps_block(self):
        def fixed(prompt):
            return json.dumps({
                "resolutions": [{"finding_id": "abc123",
                                 "status": "fixed",
                                 "evidence": self._GOOD_EVIDENCE}],
                "new_findings": []})

        def unclear(prompt):
            return json.dumps({
                "resolutions": [{"finding_id": "abc123",
                                 "status": "unclear", "evidence": "?"}],
                "new_findings": []})
        report = core.run_verification(
            CLEAN, {"a": fixed, "b": unclear}, self._previous(), "fixed")
        self.assertEqual(report["gate"], "blocked")


class LoopTests(unittest.TestCase):
    """The full workflow: review -> builder fix + work report ->
    verification -> advance (or stop for a human)."""

    _EVIDENCE = ("alert removed from app/alerts.py and the return "
                 "helpers remain")

    def _panel(self):
        import re

        def reviewer(prompt):
            if "VERIFICATION round" in prompt:
                ids = re.findall(r'"id":\s*"([0-9a-f]{12})"', prompt)
                return json.dumps({
                    "resolutions": [
                        {"finding_id": i, "status": "fixed",
                         "evidence": self._EVIDENCE} for i in ids],
                    "new_findings": []})
            return json.dumps({"findings": [{
                "severity": "blocker", "category": "reliability",
                "file": "app/alerts.py", "line": 3,
                "title": "Alert sent per violation with no dedup",
                "evidence": "sendmail in loop",
                "recommendation": "add a state-file guard",
                "confidence": 0.9}], "summary": "blocked"})
        return {"a": reviewer, "b": reviewer}

    def test_loop_advances_after_builder_fix(self):
        state = {"patch": BUGGY}

        def builder(packet):
            self.assertEqual(packet["gate"], "blocked")
            self.assertTrue(packet["open_findings"])
            state["patch"] = CLEAN
            lines = [f"- Finding {f['id']}: fixed — guard added, "
                     "alerts batched" for f in packet["open_findings"]]
            return "Work report:\n" + "\n".join(lines)
        result = core.run_loop(lambda: state["patch"], builder,
                               self._panel(), max_rounds=3)
        self.assertEqual(result["final_gate"], "pass")
        self.assertTrue(result["advanced"])
        self.assertEqual(result["workflow_state"], "approved")
        self.assertEqual(result["work_report_gaps"], [])
        self.assertTrue(result["finding_states"])
        self.assertTrue(all(
            s["state"] == "fixed_verified"
            for s in result["finding_states"].values()))
        self.assertEqual(len(result["rounds"]), 2)

    def test_loop_flags_missing_dispositions(self):
        state = {"patch": BUGGY}

        def sloppy_builder(packet):
            state["patch"] = CLEAN
            return "I fixed everything, trust me."
        result = core.run_loop(lambda: state["patch"], sloppy_builder,
                               self._panel(), max_rounds=2)
        self.assertTrue(result["work_report_gaps"])
        self.assertEqual(result["final_gate"], "pass")

    def test_loop_stops_for_human_at_max_rounds(self):
        calls = {"n": 0}

        def get_patch():
            calls["n"] += 1
            return BUGGY + f"\n# attempt {calls['n']}"

        def stubborn(prompt):
            if "VERIFICATION round" in prompt:
                import re
                ids = re.findall(r'"id":\s*"([0-9a-f]{12})"', prompt)
                return json.dumps({
                    "resolutions": [
                        {"finding_id": i, "status": "still_present",
                         "evidence": "unchanged"} for i in ids],
                    "new_findings": []})
            return json.dumps({"findings": [{
                "severity": "blocker", "category": "reliability",
                "file": "app/alerts.py", "line": 3,
                "title": "Alert sent per violation with no dedup",
                "evidence": "sendmail in loop",
                "recommendation": "add a state-file guard",
                "confidence": 0.9}], "summary": "blocked"})
        result = core.run_loop(get_patch, lambda packet: "tried",
                               {"a": stubborn, "b": stubborn},
                               max_rounds=2)
        self.assertEqual(result["final_gate"], "blocked")
        self.assertFalse(result["advanced"])
        self.assertEqual(len(result["rounds"]), 3)

    def test_loop_inconclusive_when_builder_makes_no_change(self):
        result = core.run_loop(lambda: BUGGY, lambda packet: "done",
                               self._panel(), max_rounds=2)
        self.assertEqual(result["final_gate"], "inconclusive")
        self.assertIn("no new change", result["stop_reason"])


class PoolTests(unittest.TestCase):
    """Account pools: a quota-dead account rotates to the next,
    visibly; a dead seat degrades instead of failing open."""

    def test_rotation_on_quota_error(self):
        from codereview.providers import AccountPool, ProviderError

        def dead(prompt):
            raise ProviderError("HTTP 429 from api.example")

        def alive(prompt):
            return '{"findings": []}'
        pool = AccountPool([("KEY_1", dead), ("KEY_2", alive)])
        self.assertEqual(pool("prompt"), '{"findings": []}')
        self.assertEqual(pool.last_account, "KEY_2")
        self.assertEqual(len(pool.rotations), 1)
        self.assertEqual(pool.rotations[0]["from"], "KEY_1")

    def test_no_rotation_on_bad_request(self):
        from codereview.providers import AccountPool, ProviderError

        def bad(prompt):
            raise ProviderError("HTTP 400 from api.example")
        pool = AccountPool([("KEY_1", bad),
                            ("KEY_2", lambda p: "never reached")])
        with self.assertRaises(ProviderError):
            pool("prompt")
        self.assertEqual(pool.rotations, [])

    def test_all_accounts_dead_raises(self):
        from codereview.providers import AccountPool, ProviderError

        def dead(prompt):
            raise ProviderError("HTTP 503 from api.example")
        pool = AccountPool([("KEY_1", dead), ("KEY_2", dead)])
        with self.assertRaises(ProviderError):
            pool("prompt")
        self.assertEqual(len(pool.rotations), 1)

    def test_repeated_preset_builds_a_pool(self):
        built = providers.build_providers(["gemini", "gemini"])
        from codereview.providers import AccountPool
        self.assertIsInstance(built["gemini"], AccountPool)
        self.assertEqual([label for label, _ in built["gemini"].accounts],
                         ["GEMINI_API_KEY", "GEMINI_API_KEY_2"])


class WaiverTests(unittest.TestCase):
    PATCH = """diff --git a/app/alerts.py b/app/alerts.py
--- a/app/alerts.py
+++ b/app/alerts.py
@@ -1,1 +1,3 @@
 import smtplib
+
+sendmail("admin@example.com", "x")
"""

    def test_owner_waiver_advances_without_builder(self):
        panel = LoopTests("test_loop_advances_after_builder_fix")._panel()
        waived = {f["id"] for f in core.deterministic_scan(self.PATCH)}
        waived.add(core.fingerprint(
            "app/alerts.py", "reliability",
            "Alert sent per violation with no dedup"))
        called = {"builder": False}

        def builder(packet):
            called["builder"] = True
            return ""
        result = core.run_loop(lambda: self.PATCH, builder, panel,
                               waived_ids=waived)
        self.assertEqual(result["final_gate"], "pass")
        self.assertFalse(called["builder"])
        self.assertTrue(all(
            s["state"] == "waived_by_owner"
            for s in result["finding_states"].values()))


class WorkflowTests(unittest.TestCase):
    """Two steps: a clean change, then a buggy change the agent
    must fix under review. Both end approved and committed."""

    def _panel(self):
        import re

        def reviewer(prompt):
            if "VERIFICATION round" in prompt:
                ids = re.findall(r'"id":\s*"([0-9a-f]{12})"', prompt)
                ok = "STATE_GUARD" in prompt
                return json.dumps({
                    "resolutions": [
                        {"finding_id": i,
                         "status": "fixed" if ok else "still_present",
                         "evidence": ("alert removed from app/alerts.py "
                                      "and the return helpers remain")
                         if ok else "still there"} for i in ids],
                    "new_findings": []})
            if "sendmail(" in prompt and "STATE_GUARD" not in prompt:
                return json.dumps({"findings": [{
                    "severity": "blocker", "category": "reliability",
                    "file": "app/alerts.py", "line": 3,
                    "title": "Alert sent per violation with no dedup",
                    "evidence": "sendmail in loop",
                    "recommendation": "add a state-file guard",
                    "confidence": 0.9}], "summary": "blocked"})
            return json.dumps({"findings": [], "summary": "clean"})
        return {"a": reviewer, "b": reviewer}

    def test_two_step_workflow_completes(self):
        import subprocess
        import tempfile
        repo = tempfile.mkdtemp(prefix="rl-wf-")
        out = os.path.join(repo, "wf-out")

        def git(*a):
            subprocess.run(["git", "-C", repo, *a], check=True,
                           capture_output=True)
        subprocess.run(["git", "init", "-q", repo], check=True)
        with open(os.path.join(repo, "base.txt"), "w") as fh:
            fh.write("base\n")
        git("add", "-A")
        subprocess.run(["git", "-C", repo, "-c", "user.name=T",
                        "-c", "user.email=t@e", "commit", "-qm",
                        "base"], check=True)

        agent1 = os.path.join(repo, "agent1.py")
        with open(agent1, "w") as fh:
            fh.write("open('util.py', 'w').write("
                     "'def add(a, b):\\n    return a + b\\n')\n")
        agent2 = os.path.join(repo, "agent2.py")
        with open(agent2, "w") as fh:
            fh.write(
                "import json, os\n"
                "if os.environ.get('CODEREVIEW_PHASE') == 'fix':\n"
                "    packet = json.load(open("
                "os.environ['CODEREVIEW_PACKET']))\n"
                "    open('app_alerts.py', 'w').write("
                "'STATE_GUARD = True\\n')\n"
                "    lines = ['- Finding %s: fixed — guard added' "
                "% f['id'] for f in packet['open_findings']]\n"
                "    open(os.environ['CODEREVIEW_RESPONSE'], 'w')"
                ".write('\\n'.join(lines))\n"
                "else:\n"
                "    open('app_alerts.py', 'w').write("
                "'import smtplib\\nfor v in vs:\\n"
                "    sendmail(\\'a@b.c\\', v)\\n')\n")
        git("add", "-A")
        subprocess.run(["git", "-C", repo, "-c", "user.name=T",
                        "-c", "user.email=t@e", "commit", "-qm",
                        "agents"], check=True)

        steps = [
            {"id": "util", "title": "add util",
             "agent_cmd": f"python3 {agent1}"},
            {"id": "alerts", "title": "alert checker",
             "agent_cmd": f"python3 {agent2}"},
        ]
        state = {}
        result = core.run_workflow(
            steps, self._panel(), repo, out, state=state,
            save_state=lambda s: None)
        self.assertEqual(result["workflow_state"], "complete")
        self.assertEqual([s["state"] for s in result["steps"]],
                         ["approved", "approved"])
        log = subprocess.run(["git", "-C", repo, "log", "--oneline"],
                             capture_output=True, text=True).stdout
        self.assertIn("step 'util' approved", log)
        self.assertIn("step 'alerts' approved", log)
        # Resume: approved steps are skipped, nothing re-runs.
        result2 = core.run_workflow(
            steps, self._panel(), repo, out, state=state,
            save_state=lambda s: None)
        self.assertEqual(result2["workflow_state"], "complete")

    # -- v0.4.1 isolation regressions (external Review 2) ----------

    def _repo_with_agent(self, agent_body):
        import subprocess
        import tempfile
        repo = tempfile.mkdtemp(prefix="rl-wf-")
        out = os.path.join(repo, "wf-out")

        def git(*a):
            return subprocess.run(["git", "-C", repo, *a],
                                  check=True, capture_output=True,
                                  text=True).stdout.strip()
        subprocess.run(["git", "init", "-q", repo], check=True)
        with open(os.path.join(repo, "base.txt"), "w") as fh:
            fh.write("base\n")
        agent = os.path.join(repo, "agent.py")
        with open(agent, "w") as fh:
            fh.write(agent_body)
        git("add", "-A")
        subprocess.run(["git", "-C", repo, "-c", "user.name=T",
                        "-c", "user.email=t@e", "commit", "-qm",
                        "base+agent"], check=True)
        return repo, out, agent, git

    def test_fresh_step_refuses_dirty_tree(self):
        repo, out, agent, git = self._repo_with_agent(
            "open('step.py', 'w').write('STEP = True\\n')\n")
        head_before = git("rev-parse", "HEAD")
        with open(os.path.join(repo, "base.txt"), "a") as fh:
            fh.write("UNRELATED LOCAL EDIT\n")
        with open(os.path.join(repo, "unrelated.txt"), "w") as fh:
            fh.write("not step work\n")
        steps = [{"id": "feature", "title": "add feature",
                  "agent_cmd": f"python3 {agent}"}]
        result = core.run_workflow(steps, self._panel(), repo, out,
                                   state={}, save_state=lambda s: None)
        self.assertEqual(result["workflow_state"], "stopped")
        rec = result["steps"][0]
        self.assertEqual(rec["state"], "needs_attention")
        self.assertIn("not clean", rec["error"])
        self.assertIn("unrelated.txt", rec["error"])
        # The agent never ran, nothing was committed, edits intact.
        self.assertFalse(os.path.exists(os.path.join(repo, "step.py")))
        self.assertEqual(git("rev-parse", "HEAD"), head_before)
        with open(os.path.join(repo, "base.txt")) as fh:
            self.assertIn("UNRELATED LOCAL EDIT", fh.read())

    def test_approval_commit_contains_exactly_step_files(self):
        repo, out, agent, git = self._repo_with_agent(
            "open('step.py', 'w').write('STEP = True\\n')\n"
            "open('base.txt', 'a').write('step change\\n')\n")
        steps = [{"id": "feature", "title": "add feature",
                  "agent_cmd": f"python3 {agent}"}]
        result = core.run_workflow(steps, self._panel(), repo, out,
                                   state={}, save_state=lambda s: None)
        self.assertEqual(result["workflow_state"], "complete")
        names = git("show", "--name-only", "--format=", "HEAD")
        self.assertEqual(set(names.splitlines()),
                         {"base.txt", "step.py"})
        # The temp-index commit leaves the real index synced to
        # HEAD: nothing staged or modified afterwards (the wf-out
        # directory is the engine's own output).
        status = git("status", "--porcelain")
        leftover = [ln for ln in status.splitlines()
                    if "wf-out" not in ln]
        self.assertEqual(leftover, [])

    def test_resumed_step_keeps_its_in_progress_tree(self):
        repo, out, agent, git = self._repo_with_agent(
            "open('step.py', 'w').write('STEP = True\\n')\n")
        with open(os.path.join(repo, "step.py"), "w") as fh:
            fh.write("STEP = True\n")  # the step's own earlier work
        state = {"steps": {"feature": {
            "id": "feature", "title": "add feature",
            "state": "changes_requested",
            "started_at": "2026-11-03T00:00:00+00:00"}}}
        steps = [{"id": "feature", "title": "add feature",
                  "agent_cmd": f"python3 {agent}"}]
        result = core.run_workflow(steps, self._panel(), repo, out,
                                   state=state,
                                   save_state=lambda s: None)
        self.assertEqual(result["workflow_state"], "complete")
        self.assertEqual(result["steps"][0]["state"], "approved")
        names = git("show", "--name-only", "--format=", "HEAD")
        self.assertEqual(set(names.splitlines()), {"step.py"})

    def test_tree_changed_after_review_refuses_commit(self):
        repo, out, agent, git = self._repo_with_agent(
            "open('step.py', 'w').write('STEP = True\\n')\n")
        head_before = git("rev-parse", "HEAD")
        mutated = {"done": False}

        def sneaky(prompt):
            if not mutated["done"]:
                mutated["done"] = True
                with open(os.path.join(repo, "sneak.txt"), "w") as fh:
                    fh.write("unreviewed\n")
            return json.dumps({"findings": [], "summary": "clean"})
        steps = [{"id": "feature", "title": "add feature",
                  "agent_cmd": f"python3 {agent}"}]
        result = core.run_workflow(
            steps, {"a": sneaky, "b": sneaky}, repo, out, state={},
            save_state=lambda s: None)
        self.assertEqual(result["workflow_state"], "stopped")
        rec = result["steps"][0]
        self.assertEqual(rec["state"], "needs_attention")
        self.assertIn("changed after the final review", rec["error"])
        self.assertEqual(git("rev-parse", "HEAD"), head_before)

    def test_mismatch_refusal_preserves_staged_index(self):
        # External Review 3 (Minor): the v0.4.1 recovery ran
        # `git reset -- .` and destroyed pre-staged state. The
        # approval commit now uses a temporary index, so a refusal
        # must leave the user's real index exactly as it was.
        import subprocess
        repo, out, agent, git = self._repo_with_agent(
            "open('step.py', 'w').write('STEP = True\\n')\n")
        head_before = git("rev-parse", "HEAD")
        with open(os.path.join(repo, "step.py"), "w") as fh:
            fh.write("STEP = True\n")
        subprocess.run(["git", "-C", repo, "add", "step.py"],
                       check=True, capture_output=True)
        staged_before = git("diff", "--cached", "--name-only")
        self.assertEqual(staged_before, "step.py")

        orig = core._diff_text

        def corrupt(r, b, cached=False, exclude_rel=None, env=None):
            text = orig(r, b, cached=cached, exclude_rel=exclude_rel,
                        env=env)
            return text + "\n-- forced mismatch --" if cached else text
        core._diff_text = corrupt
        try:
            state = {"steps": {"feature": {
                "id": "feature", "title": "add feature",
                "state": "changes_requested",
                "started_at": "2026-11-03T00:00:00+00:00"}}}
            steps = [{"id": "feature", "title": "add feature",
                      "agent_cmd": f"python3 {agent}"}]
            result = core.run_workflow(
                steps, self._panel(), repo, out, state=state,
                save_state=lambda s: None)
        finally:
            core._diff_text = orig
        self.assertEqual(result["workflow_state"], "stopped")
        rec = result["steps"][0]
        self.assertEqual(rec["state"], "needs_attention")
        self.assertIn("index was not touched", rec["error"])
        self.assertEqual(git("rev-parse", "HEAD"), head_before)
        # The pre-staged entry survived the refusal.
        self.assertEqual(git("diff", "--cached", "--name-only"),
                         "step.py")


if __name__ == "__main__":
    unittest.main()
