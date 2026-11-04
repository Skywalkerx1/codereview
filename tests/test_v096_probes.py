"""v0.9.6 — the probe pack of the v15-closing-run solution (§4,
Step 2 of §6): one executable probe per disputed major from
review-v15, added to the suite permanently so the owner's
rulings (solution §3) rest on rerunnable evidence rather than
on either family's say-so.

Probe → disputed finding map:
  P1  -> 3c39c4bdc15a  (--private vs free-tier seats)
  P3  -> 474297e6ffdc  (bench --force and old degraded records)
  P4  -> 09c536d15270  (nearest-rank percentile bounds)
  P5  -> bca4074a632c  (attempts-log path provenance)
  P6/P8 -> eae8137a6db3 + 3cecf66f6ce5 (commonpath ValueError at
         the two containment call sites; the shared _is_within
         helper itself ships in cli.py with this release)
  P9  -> d93089253022  (directory-pattern normalization)
  P10 -> c5f02551d077  (solo-panel verification labelling)
  P11 -> 0e57186e8be8  (agent spec parsing with colons)
  P12/P13 -> 1aec997aaec4 + 0ad4ed7db98e (seat-name uniqueness)
  P14 -> 2242edbba9c9  (providers module-scope imports)

All providers are scripted fakes or local stubs; the git
fixtures are real temporary repositories, in the established
suite style."""

import ast
import hashlib
import http.server
import itertools
import json
import ntpath
import os
import random
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import bench, cli, core, providers  # noqa: E402

SRC_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "src", "codereview"))

TINY_PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,1 @@\n"
    "-x = 1\n"
    "+x = 2\n")


def _ok_verdict(prompt):
    return json.dumps({"verdict": "pass", "summary": "clean",
                       "findings": []})


# ---------------------------------------------------------------- P1

class _StubHandler(http.server.BaseHTTPRequestHandler):
    """An OpenAI-compatible stub endpoint that counts requests."""

    seen = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        type(self).seen.append(self.path)
        content = json.dumps({"verdict": "pass",
                              "summary": "stub seat: clean",
                              "findings": []})
        raw = json.dumps({"choices": [{"message": {
            "content": content}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class PrivateStubProbeTests(unittest.TestCase):
    """P1 (disputed 3c39c4bdc15a): under --private, a free-tier
    seat is refused BEFORE any call — the stub endpoint must see
    zero requests. The control run without --private proves the
    stub was live and reachable, so the zero is the refusal."""

    def setUp(self):
        _StubHandler.seen = []
        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), _StubHandler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.thread.start()
        port = self.server.server_address[1]
        self._env = mock.patch.dict(
            os.environ, {"STUBFREE_API_KEY": "stub-key"})
        self._env.start()
        _name, self.seat, _label = providers.build_provider(
            f"stubfree|openai-compatible|"
            f"http://127.0.0.1:{port}/v1|stub-model|STUBFREE_API_KEY")
        self.tmp = tempfile.TemporaryDirectory()
        self.patch_path = os.path.join(self.tmp.name, "change.diff")
        with open(self.patch_path, "w", encoding="utf-8") as fh:
            fh.write(TINY_PATCH)
        self.out = os.path.join(self.tmp.name, "out")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._env.stop()
        self.tmp.cleanup()

    def _run(self, *extra):
        return cli.main(
            ["--patch", self.patch_path, "--out", self.out, *extra],
            providers_override={"stubfree": self.seat},
            seat_meta_override={
                "stubfree": {"family": "stub", "tier": "free"}})

    def test_private_refuses_before_any_call(self):
        rc = self._run("--private")
        self.assertEqual(rc, 2)
        self.assertEqual(_StubHandler.seen, [])

    def test_control_without_private_the_stub_is_called(self):
        rc = self._run()
        self.assertEqual(rc, 0)
        self.assertGreaterEqual(len(_StubHandler.seen), 1)
        self.assertTrue(all(p.endswith("/chat/completions")
                            for p in _StubHandler.seen))

    def test_tier_policy_fails_for_successful_free_seat_private(self):
        # The verify half of P1: a record attesting private=true
        # whose successful seat ran on a free tier fails
        # record-verify's tier_policy check (record-and-attest).
        record = {
            "gate": "pass", "degraded": False, "private": True,
            "test_results": [{"command": "t", "ok": True}],
            "reviewer_reports": [
                {"provider": "stubfree", "lens": "correctness",
                 "status": "ok", "family": "stub", "tier": "free"}]}
        checks = {c["name"]: c
                  for c in core.verify_record(record)["checks"]}
        self.assertFalse(checks["tier_policy"]["ok"],
                         checks["tier_policy"])
        record["private"] = False
        checks = {c["name"]: c
                  for c in core.verify_record(record)["checks"]}
        self.assertTrue(checks["tier_policy"]["ok"],
                        checks["tier_policy"])


# ---------------------------------------------------------------- P3

P3_DIFF = """diff --git a/billing/charge.py b/billing/charge.py
--- a/billing/charge.py
+++ b/billing/charge.py
@@ -3,4 +3,4 @@ def checkout(order, card):
     # The gateway bills in cents.
     total = order.total_dollars()
-    return gateway.charge(card, int(total * 100))
+    return gateway.charge(card, total)
"""


def _write_bench_case(root, cid, diff):
    cdir = os.path.join(root, cid)
    os.makedirs(cdir)
    meta = {"id": cid, "title": f"case {cid}",
            "category": "payments", "split": "public",
            "source": "test fixture", "license": "MIT",
            "expected": []}
    with open(os.path.join(cdir, "case.json"), "w") as fh:
        json.dump(meta, fh)
    with open(os.path.join(cdir, "diff.patch"), "w") as fh:
        fh.write(diff)


class ForcedRerunProbeTests(unittest.TestCase):
    """P3 (disputed 474297e6ffdc): a forced bench rerun starts
    from an EMPTY in-memory record list — degraded records in
    the stored file are replaced, never carried into the new
    run's degraded check. And the v12 failure-safety still
    holds: a rerun that dies mid-run leaves the old file
    byte-identical."""

    CASES = ("pay-bug", "pay-bug-2")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.corpus = os.path.join(root, "corpus")
        for cid in self.CASES:
            _write_bench_case(self.corpus, cid, P3_DIFF)
        self.cfg_path = os.path.join(root, "p3cfg.json")
        with open(self.cfg_path, "w") as fh:
            json.dump({"name": "p3cfg", "providers": [
                {"name": "scripted", "script": "unused.json"}]}, fh)
        self.out = os.path.join(root, "out")
        os.makedirs(self.out)
        self.results_path = os.path.join(self.out, "p3cfg.jsonl")
        cfg = bench.load_config(self.cfg_path)
        cfg_sha = bench._config_sha(cfg)
        diff_sha = hashlib.sha256(P3_DIFF.encode("utf-8")).hexdigest()
        old = []
        for cid in self.CASES:
            old.append({
                "schema": bench.RESULT_SCHEMA, "config": "p3cfg",
                "config_sha256": cfg_sha, "case_id": cid,
                "split": "public", "category": "payments",
                "created_at": "2000-01-01T00:00:00+00:00",
                "gate": "inconclusive", "degraded": True,
                "duration_ms": 1, "calls": 1, "cost_usd": 999999.0,
                "patch_sha256": diff_sha, "findings": [],
                "reviewer_reports": []})
        with open(self.results_path, "w", encoding="utf-8") as fh:
            for rec in old:
                fh.write(json.dumps(rec) + "\n")
        self.seats = {"p3cfg": {"seat": _ok_verdict}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_force_starts_clean_of_old_degraded_records(self):
        results = bench.run_bench(
            self.corpus, [self.cfg_path], self.out, force=True,
            providers_by_config=self.seats)
        records = results["p3cfg"]
        self.assertEqual(len(records), len(self.CASES))
        # None of the stored degraded records is in the new
        # run's in-memory list (marker: cost and timestamp).
        self.assertTrue(all(not r["degraded"] for r in records))
        self.assertTrue(all(r["cost_usd"] != 999999.0
                            for r in records))
        self.assertTrue(all(
            not str(r["created_at"]).startswith("2000")
            for r in records))
        # The file on disk was replaced, not appended to.
        with open(self.results_path, encoding="utf-8") as fh:
            disk = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(disk), len(self.CASES))
        self.assertTrue(all(not r["degraded"] for r in disk))
        # A later degraded check (report build) ignores them too.
        loaded = bench.load_results(self.out)["p3cfg"]
        self.assertTrue(all(not r["degraded"] for r in loaded))
        report = bench.build_report(results, self.corpus)
        metrics = report["configs"]["p3cfg"]["metrics"]
        self.assertEqual(metrics["degraded_cases"], 0)

    def test_failed_rerun_leaves_previous_file_intact(self):
        with open(self.results_path, "rb") as fh:
            before = fh.read()
        with mock.patch.object(core, "run_review",
                               side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                bench.run_bench(
                    self.corpus, [self.cfg_path], self.out,
                    force=True, providers_by_config=self.seats)
        with open(self.results_path, "rb") as fh:
            self.assertEqual(fh.read(), before)


# ---------------------------------------------------------------- P4

class PercentilePropertyTests(unittest.TestCase):
    """P4 (disputed 09c536d15270): the doc's property test,
    verbatim in spirit — nearest-rank never raises, always
    returns a member of the sample, and pct=100 returns the
    maximum (rank is clamped to [1, n] by construction)."""

    def test_percentile_property(self):
        rng = random.Random(20261104)
        for n in range(1, 60):
            vals = sorted(rng.random() for _ in range(n))
            for pct in range(0, 101):
                r = bench.percentile(vals, pct)
                self.assertIn(r, vals)
            self.assertEqual(bench.percentile(vals, 100), vals[-1])
            self.assertEqual(bench.percentile(vals, 0), vals[0])


# ---------------------------------------------------------------- P5

class AttemptsLogProvenanceTests(unittest.TestCase):
    """P5 (disputed bca4074a632c): the attempts-log path is
    operator-supplied — statically, every read of the setting
    is `args.attempts_log` (the argparse namespace, fed by the
    command line only); nothing assigns it, no environment
    lookup feeds it, and no other module knows it exists."""

    def test_attempts_log_comes_from_argv_only(self):
        with open(os.path.join(SRC_DIR, "cli.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
        reads = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) \
                    and node.attr == "attempts_log":
                self.assertIsInstance(node.value, ast.Name)
                self.assertEqual(node.value.id, "args")
                self.assertIsInstance(node.ctx, ast.Load)
                reads += 1
            if isinstance(node, ast.Name) \
                    and node.id == "attempts_log":
                self.fail("attempts_log must only ever appear as "
                          "args.attempts_log (argv), never as an "
                          "assigned variable")
        self.assertGreaterEqual(reads, 1)
        for line in src.splitlines():
            if "attempts" in line:
                self.assertNotIn("environ", line)
                self.assertNotIn("getenv", line)
        for name in sorted(os.listdir(SRC_DIR)):
            if name.endswith(".py") and name != "cli.py":
                with open(os.path.join(SRC_DIR, name),
                          encoding="utf-8") as fh:
                    self.assertNotIn("attempts_log", fh.read(), name)

    def test_attempts_log_written_from_the_argv_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch_path = os.path.join(tmp, "change.diff")
            with open(patch_path, "w", encoding="utf-8") as fh:
                fh.write(TINY_PATCH)
            log_path = os.path.join(tmp, "attempts.jsonl")
            rc = cli.main(
                ["--patch", patch_path, "--out",
                 os.path.join(tmp, "out"),
                 "--attempts-log", log_path],
                providers_override={"a": _ok_verdict,
                                    "b": _ok_verdict})
            self.assertEqual(rc, 0)
            with open(log_path, encoding="utf-8") as fh:
                lines = [line for line in fh if line.strip()]
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["mode"], "review")
            self.assertEqual(entry["gate"], "pass")


# ------------------------------------------------------------- P6/P8

class IsWithinProbeTests(unittest.TestCase):
    """P6/P8 (disputed eae8137a6db3 + 3cecf66f6ce5): the shared
    _is_within helper behind BOTH containment call sites
    (fixture-manifest loader, precedent loader) fails closed
    when os.path.commonpath raises ValueError — the
    different-drives / mixed absolute-relative failure mode —
    and leaves normal within/outside behaviour unchanged."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        self.manifest_path = os.path.join(self.repo, "fixtures.json")
        with open(self.manifest_path, "w", encoding="utf-8") as fh:
            json.dump({"schema": core.FIXTURE_MANIFEST_SCHEMA,
                       "policy_version": 1,
                       "fixtures": [{"path": "bench/corpus/**"}]},
                      fh)
        self.store_path = os.path.join(self.repo, "precedents.json")
        with open(self.store_path, "w", encoding="utf-8") as fh:
            json.dump({"schema": core.PRECEDENTS_SCHEMA,
                       "entries": []}, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def test_within_outside_and_prefix_sibling(self):
        self.assertTrue(cli._is_within(
            os.path.join(self.repo, "sub", "x.json"), self.repo))
        self.assertTrue(cli._is_within(self.repo, self.repo))
        self.assertFalse(cli._is_within(
            os.path.join(self.repo, "..", "evil.json"), self.repo))
        # A sibling whose name merely extends the root's name is
        # NOT within it.
        self.assertFalse(cli._is_within(
            self.repo + "2" + os.sep + "x.json", self.repo))

    def test_commonpath_valueerror_fails_closed(self):
        with mock.patch.object(
                cli.os.path, "commonpath",
                side_effect=ValueError(
                    "Cannot mix absolute and relative paths")):
            self.assertFalse(cli._is_within(
                os.path.join(self.repo, "fixtures.json"), self.repo))
            # The loader surfaces its own containment error, not
            # the raw commonpath ValueError.
            with self.assertRaises(ValueError) as cm:
                cli._load_fixture_scope(self.manifest_path,
                                        repo=self.repo)
            self.assertIn("resolves outside", str(cm.exception))

    def test_ntpath_drive_mismatch_is_the_documented_failure(self):
        # The mechanism behind the disputed findings, in the
        # stdlib's own terms: commonpath across Windows drives
        # raises ValueError on any platform (ntpath is pure
        # string handling), which is why the helper must catch it.
        with self.assertRaises(ValueError):
            ntpath.commonpath([r"C:\repo\a", r"D:\repo\b"])

    def test_both_loaders_load_and_refuse_outside(self):
        scope = cli._load_fixture_scope(self.manifest_path,
                                        repo=self.repo)
        self.assertEqual(scope["manifest_path"], "fixtures.json")
        store = cli._load_precedents(self.store_path, repo=self.repo)
        self.assertEqual(store["entries"], [])
        outside = os.path.join(self.tmp.name, "outside.json")
        with open(outside, "w", encoding="utf-8") as fh:
            fh.write("{}")
        with self.assertRaises(ValueError):
            cli._load_fixture_scope(outside, repo=self.repo)
        with self.assertRaises(ValueError):
            cli._load_precedents(outside, repo=self.repo)


# ---------------------------------------------------------------- P9

class DirectoryPatternProbeTests(unittest.TestCase):
    """P9 (disputed d93089253022): the doc's normalization
    matrix. The disputed claim was OVERmatching (siblings and
    prefixes matching a directory pattern); the matrix also
    exposes any spelling that fails to match real children."""

    PATHS = ("app/users.py", "app/users2.py", "app2/x.py",
             "application/x.py", "app/users/x.py")

    def test_directory_spellings_match_children_never_siblings(self):
        expected = {"app/users.py": True, "app/users2.py": True,
                    "app2/x.py": False, "application/x.py": False,
                    "app/users/x.py": True}
        for pat in ("app/", "app"):
            got = {p: core.path_matches(p, [pat]) for p in self.PATHS}
            self.assertEqual(got, expected, pat)

    def test_plain_directory_pattern_prefix_traps(self):
        # "app/users" as a directory: its children match; the
        # sibling file "app/users.py", the prefix trap
        # "app/users2.py", and unrelated prefixes do not.
        self.assertTrue(core.path_matches("app/users/x.py",
                                          ["app/users"]))
        for p in ("app/users.py", "app/users2.py", "app2/x.py",
                  "application/x.py"):
            self.assertFalse(core.path_matches(p, ["app/users"]), p)

    def test_dot_slash_spelling_is_inert_probe_result(self):
        # PROBE RESULT (reported to the owner with the §3 ruling
        # for d93089253022 — deliberately NOT silently fixed in
        # this release): a leading "./" is not normalized away,
        # so the "app" directory spelled "./app" matches NOTHING
        # — not even its own children. The failure direction is
        # safe (an inert fixture pattern leaves findings as
        # product findings; it can never hide one), but a
        # manifest author gets silence, not an error. This test
        # pins the observed behaviour so a future normalization
        # fix must update it together with the dispositions.
        for p in self.PATHS:
            self.assertFalse(core.path_matches(p, ["./app"]), p)


# --------------------------------------------------------------- P10

VERIFY_PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,3 @@\n"
    " import os\n"
    "+VALUE = compute_total(items) if items else 0\n"
    "+print(VALUE)\n")

VERIFY_EVIDENCE = ("compute_total in app.py guards the total: "
                   "VALUE is only computed when items is non-empty")


def _solo_previous():
    return {"gate": "blocked", "findings": [{
        "id": "f-openai-1", "severity": "blocker",
        "category": "correctness", "file": "app.py", "line": 2,
        "title": "Total computed without a guard",
        "evidence": "VALUE = compute_total(items)",
        "recommendation": "guard it", "confidence": 0.9,
        "sources": ["solo"], "consensus": False}]}


def _solo_judge(prompt):
    return json.dumps({
        "resolutions": [{"finding_id": "f-openai-1",
                         "status": "invalid",
                         "evidence": VERIFY_EVIDENCE}],
        "new_findings": []})


def _solo_boom(prompt):
    raise RuntimeError("provider down")


class SoloPanelProbeTests(unittest.TestCase):
    """P10 (disputed c5f02551d077): a single-provider
    verification round can pass its own gate (the quorum
    exception is deliberate), but the record must LABEL it a
    solo panel — in every outcome, not just a clean pass — and
    it still cannot make a chain eligible."""

    def test_solo_verification_that_passes_is_labelled(self):
        report = core.run_verification(
            VERIFY_PATCH, {"solo": _solo_judge}, _solo_previous(),
            "rebutted with evidence", sleep=lambda *_a: None)
        self.assertEqual(report["gate"], "pass",
                         report["gate_reasons"])
        self.assertIn("solo panel — no independent review",
                      " ".join(report["gate_reasons"]))
        self.assertIn("solo panel", json.dumps(report))

    def test_solo_verification_that_cannot_pass_is_labelled(self):
        report = core.run_verification(
            VERIFY_PATCH, {"solo": _solo_boom}, _solo_previous(),
            "rebutted with evidence", sleep=lambda *_a: None)
        self.assertEqual(report["gate"], "inconclusive")
        self.assertIn("solo panel — no independent review",
                      " ".join(report["gate_reasons"]))


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


class SoloChainProbeTests(_GitRepo):
    """P10, eligibility half: a chain whose verification round
    was a solo panel fails record-verify --chain's
    rounds_two_families check, however clean the round itself."""

    def test_solo_verification_round_fails_two_families(self):
        c1 = self.write_commit({"a.txt": "one\n"}, "c1")
        c2 = self.write_commit({"a.txt": "one\ntwo\n"}, "c2")
        c3 = self.write_commit({"a.txt": "one\ntwo\nthree\n"}, "c3")
        finding = {"id": "f123", "severity": "major",
                   "file": "a.txt", "title": "a defect",
                   "sources": ["seatA"], "consensus": False}
        round1 = {
            "mode": "review", "gate": "blocked", "degraded": False,
            "test_results": [{"command": "t", "ok": True}],
            "reviewer_reports": [
                {"provider": "g", "lens": "correctness",
                 "status": "ok", "family": "google", "tier": "free"},
                {"provider": "n", "lens": "operations",
                 "status": "ok", "family": "nvidia",
                 "tier": "paid"}],
            "coverage": {"complete": True, "batch_count": 1,
                         "files": {}},
            "findings": [finding],
            "range": f"{c1}..{c2}", "head": c2,
            "patch_sha256": self.patch_hash(f"{c1}..{c2}")}
        solo_verify = {
            "mode": "verify", "gate": "pass", "degraded": False,
            "test_results": [{"command": "t", "ok": True}],
            "reviewer_reports": [
                {"provider": "g", "status": "ok",
                 "family": "google", "tier": "free"}],
            "cleared": [{**finding, "cleared_by": ["fixed"]}],
            "remaining": [], "unjudged": [], "findings": [],
            "range": f"{c2}..{c3}", "head": c3,
            "patch_sha256": self.patch_hash(f"{c2}..{c3}")}
        result = core.verify_chain([round1, solo_verify],
                                   repo=self.td,
                                   record_dirs=["r1", "r2"])
        checks = {c["name"]: c for c in result["checks"]}
        self.assertFalse(checks["rounds_two_families"]["ok"],
                         checks["rounds_two_families"])
        self.assertFalse(result["eligible"])


# --------------------------------------------------------------- P11

class AgentColonProbeTests(unittest.TestCase):
    """P11 (disputed 0e57186e8be8): split(':', 2) keeps the
    command — colons and all — intact as the third field."""

    SPEC = "agent:x:sh -c 'echo a:b'"

    def test_parse_keeps_command_intact(self):
        name, _options, command = providers._parse_agent_spec(
            self.SPEC)
        self.assertEqual(name, "x")
        self.assertEqual(command, "sh -c 'echo a:b'")

    def test_built_seat_runs_the_intact_command(self):
        name, fn, _label = providers.build_provider(self.SPEC)
        self.assertEqual(name, "x")
        self.assertIn("a:b", fn("the prompt is ignored by echo"))


# ---------------------------------------------------------- P12/P13

class SeatNameUniquenessPropertyTests(unittest.TestCase):
    """P12/P13 (disputed 1aec997aaec4 + 0ad4ed7db98e): the doc's
    property test — every permutation of every subset of a
    spec list mixing presets, custom API specs, case variants,
    and agent suffix collisions must either raise loudly
    (ProviderError: a configured seat is never silently
    dropped) or build exactly one seat per spec with
    case-insensitively unique names."""

    SPECS = ["gemini", "agent:gemini:printf A",
             "agent:Gemini:printf B", "agent:bot:printf C",
             "agent:bot:printf D", "agent:bot-2:printf E",
             "bot|openai-compatible|https://x/v1|m|K"]

    def test_no_silent_merge_or_case_insensitive_duplicate(self):
        built_count = raised_count = 0
        for k in range(2, len(self.SPECS) + 1):
            for combo in itertools.permutations(self.SPECS, k):
                try:
                    built = providers.build_providers(list(combo))
                except providers.ProviderError:
                    raised_count += 1
                    continue
                built_count += 1
                self.assertEqual(len(built), len(combo), combo)
                lowered = [n.lower() for n in built]
                self.assertEqual(len(set(lowered)), len(lowered),
                                 combo)
        # Both outcomes must actually occur in the space, or the
        # property was vacuous.
        self.assertGreater(built_count, 0)
        self.assertGreater(raised_count, 0)


# --------------------------------------------------------------- P14

class KillTreeImportGuardTests(unittest.TestCase):
    """P14 (disputed 2242edbba9c9): _kill_tree's module-scope
    names (os, signal) are provided by providers' own imports —
    a direct assertion plus a clean import under
    warnings-as-errors, so a future import shuffle fails here
    instead of as a NameError inside a timeout path."""

    def test_module_scope_provides_kill_tree_names(self):
        self.assertIs(providers.os, os)
        self.assertIs(providers.signal,
                      __import__("signal"))
        self.assertTrue(callable(providers._kill_tree))

    def test_providers_imports_clean_under_warnings_as_errors(self):
        src = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "src"))
        env = dict(os.environ, PYTHONPATH=src)
        proc = subprocess.run(
            [sys.executable, "-W", "error", "-c",
             "import codereview.providers"],
            capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
