"""v0.9.2 — adjudication of the review-v13 record, per the
successor issue report's closure criteria
(~/workspace/issue-reports/2026-11-04-codereview-v13-gate-findings.md):

- the one real defect, v13 [5]: the library seam in
  providers.build_provider used `agent_timeout or AGENT_TIMEOUT`,
  silently swapping an explicit 0 for the 900s default. Explicit
  values are now honored verbatim; non-positive values are
  refused at construction in command_agent. Tests below pin all
  four quadrants (None / 0 / negative / positive) at BOTH seams
  (build_provider and build_providers, plus command_agent
  direct).
- executable evidence for two rebuttals, kept as characterization
  tests so the invariants cannot rot silently:
  * v13 [2] — bench resume cannot be bypassed by a config
    rename: the config NAME is inside _config_sha's hashed
    identity, so records written under another name are stale
    and dropped before dedup keys are built;
  * v13 [3] — fixture path matching is boundary-aware: for
    every pattern in the SHIPPED fixtures-manifest.json,
    sibling-prefix mutations (next char not '/') must NOT
    classify, while genuine children must.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "src"))

from codereview import bench, cli, core, providers  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), ".."))


def _captured_timeout(fn):
    cells = dict(zip(fn.__code__.co_freevars,
                     [c.cell_contents for c in fn.__closure__ or []]))
    return cells.get("timeout")


class AgentTimeoutSeamTests(unittest.TestCase):
    """v13 [5]: explicit agent_timeout is honored or refused
    loudly — never silently swapped for the default."""

    def test_none_means_default(self):
        _name, fn, _label = providers.build_provider(
            "agent:bot:true", agent_timeout=None)
        self.assertEqual(_captured_timeout(fn),
                         providers.AGENT_TIMEOUT)

    def test_positive_value_honored_verbatim(self):
        _name, fn, _label = providers.build_provider(
            "agent:bot:true", agent_timeout=5)
        self.assertEqual(_captured_timeout(fn), 5)

    def test_zero_refused_loudly(self):
        with self.assertRaises(providers.ProviderError):
            providers.build_provider("agent:bot:true",
                                     agent_timeout=0)

    def test_negative_refused_loudly(self):
        with self.assertRaises(providers.ProviderError):
            providers.build_provider("agent:bot:true",
                                     agent_timeout=-3)

    def test_plural_builder_seam_also_refuses(self):
        with self.assertRaises(providers.ProviderError):
            providers.build_providers(["agent:bot:true"],
                                      agent_timeout=0)

    def test_command_agent_direct_seam(self):
        with self.assertRaises(providers.ProviderError):
            providers.command_agent("true", timeout=0)
        fn = providers.command_agent("true", timeout=None)
        self.assertEqual(_captured_timeout(fn),
                         providers.AGENT_TIMEOUT)


class BenchResumeRenameTests(unittest.TestCase):
    """v13 [2] characterization: a config rename cannot resurrect
    stale records or duplicate a case — the name is hashed into
    the config identity, so foreign records are dropped as stale
    before the dedup set is built."""

    DIFF = ("diff --git a/app/pay.py b/app/pay.py\n"
            "--- a/app/pay.py\n+++ b/app/pay.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-    total = amount\n"
            "+    total = amount * 100\n")

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="bench-rename-")
        self.corpus = os.path.join(self.root, "corpus")
        self.out = os.path.join(self.root, "out")
        cdir = os.path.join(self.corpus, "pay-bug")
        os.makedirs(cdir)
        os.makedirs(self.out)
        with open(os.path.join(cdir, "case.json"), "w") as fh:
            json.dump({"id": "pay-bug", "title": "case pay-bug",
                       "category": "payments", "split": "public",
                       "source": "test fixture", "license": "MIT",
                       "expected": []}, fh)
        with open(os.path.join(cdir, "diff.patch"), "w") as fh:
            fh.write(self.DIFF)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def _seat(_prompt):
        return json.dumps({"findings": []})

    def _cfg(self, name):
        path = os.path.join(self.root, f"{name}.json")
        with open(path, "w") as fh:
            json.dump({"name": name, "providers": ["scripted-x"],
                       "cost_per_call_usd": 0}, fh)
        return path

    def _records(self, name):
        path = os.path.join(self.out, f"{name}.jsonl")
        if not os.path.isfile(path):
            return []
        with open(path) as fh:
            return [json.loads(ln) for ln in fh if ln.strip()]

    def test_rename_cannot_duplicate(self):
        alpha = self._cfg("alpha")
        bench.run_bench(self.corpus, [alpha], self.out,
                        providers_by_config={"alpha":
                                             {"s": self._seat}})
        self.assertEqual(len(self._records("alpha")), 1)
        # Resume under the same name: skipped, still one record.
        bench.run_bench(self.corpus, [alpha], self.out,
                        providers_by_config={"alpha":
                                             {"s": self._seat}})
        self.assertEqual(len(self._records("alpha")), 1)
        # Strongest form of the claim: the old records are placed
        # in the renamed config's own results file. They must be
        # dropped as stale (name is in the config hash) and the
        # case re-run exactly once under the new name.
        beta = self._cfg("beta")
        shutil.copyfile(os.path.join(self.out, "alpha.jsonl"),
                        os.path.join(self.out, "beta.jsonl"))
        bench.run_bench(self.corpus, [beta], self.out,
                        providers_by_config={"beta":
                                             {"s": self._seat}})
        records = self._records("beta")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["config"], "beta")
        self.assertEqual(records[0]["case_id"], "pay-bug")


class FixtureSiblingTests(unittest.TestCase):
    """v13 [3] characterization: for every pattern in the shipped
    fixture manifest, genuine children classify and sibling
    prefixes (shared string prefix, next char not '/') do not."""

    @classmethod
    def setUpClass(cls):
        scope = cli._load_fixture_scope(
            "fixtures-manifest.json", repo=REPO_ROOT)
        cls.patterns = scope["patterns"]

    def test_every_shipped_pattern_rejects_siblings(self):
        self.assertEqual(len(self.patterns), 39)
        for pat in self.patterns:
            if pat.endswith("/**"):
                base = pat[:-3]
                good = [base, base + "/diff.patch"]
                bad = [base + "x/diff.patch", base + "-evil/x",
                       base + "2"]
            else:
                base = pat
                good = [base]
                bad = [base + "x", base + ".bak", base + "2/raw.py"]
            for path in good:
                self.assertTrue(
                    core.path_matches(path, self.patterns),
                    f"genuine fixture path not classified: {path}")
            for path in bad:
                self.assertFalse(
                    core.path_matches(path, self.patterns),
                    f"sibling wrongly classified: {path} "
                    f"(pattern {pat})")

    def test_product_paths_never_classify(self):
        for product in ("src/codereview/core.py",
                        "src/codereview/bench.py",
                        "bench/configs/oracle.json",
                        "bench/corpusx/diff.patch"):
            self.assertFalse(
                core.path_matches(product, self.patterns), product)


if __name__ == "__main__":
    unittest.main()
