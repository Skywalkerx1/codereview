"""Epic C5 — sandbox safety, audited and pinned (2026-11-05).

The C1–C3 evidence runner shipped with most of C5's machinery
(throwaway copy, env allow-list, proxied-namespace network
default, timeouts, CPU/file-size rlimits). This file is the
line-by-line audit of ticket C5 ("Sandbox safety: no network
by default, resource limits, run in temp worktree; never run
untrusted PR code with secrets" — acceptance: documented
threat model + tests):

- GAP CLOSED by this track: captured output was buffered
  without bound in the parent (proc.communicate()), so a
  spewing command could grow the gate process's memory until
  the wall-clock/CPU bound fired. _execute now drains each
  stream under a per-stream cap; these tests FAIL on the
  pre-C5 code.
- Already met, pinned here because no test held them: the CPU
  and per-file rlimits actually reach the child; provider-key
  shaped variables and proxy variables stay out of the child
  (allow_network re-admits ONLY the proxies); the throwaway
  copy is deleted on every exit path, including after a
  timeout kill; namespace mode is a real, different network
  namespace with no route out (where unshare works).
- NOT pinned because not true: there is no memory (address
  space) limit — see THREAT-MODEL.md for why an rlimit there
  would break legitimate toolchains, and the other residual
  risks, stated plainly.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import evidence  # noqa: E402

# The cap the C5 fix sets. Read off the module when present;
# on the pre-C5 code the attribute does not exist and the
# fallback keeps the spew commands the same size, so the cap
# tests fail there on their assertions (no marker, unbounded
# output, no limits entry) rather than at import.
CAP = getattr(evidence, "_OUTPUT_CAP_BYTES", 8 * 1024 * 1024)
SPEW_BYTES = CAP + 1024 * 1024  # one MiB past the cap
SPEW_CMD = ("head -c %d /dev/zero | tr '\\0' 'x'; "
            "head -c %d /dev/zero | tr '\\0' 'y' 1>&2"
            % (SPEW_BYTES, SPEW_BYTES))


def _tree(files):
    root = tempfile.mkdtemp(prefix="c5-src-")
    for rel, content in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    return root


def _sandbox_leftovers():
    tmp = tempfile.gettempdir()
    return {n for n in os.listdir(tmp)
            if n.startswith(("codereview-evidence-",
                             "codereview-claims-"))}


class OutputCapTests(unittest.TestCase):
    """The gap this track closes: unbounded output capture."""

    def _run(self, command, timeout=60):
        workdir = tempfile.mkdtemp(prefix="c5-work-")
        return evidence._execute(
            ["sh", "-c", command], workdir, timeout,
            dict(os.environ), False)

    def test_captured_output_is_capped_and_marked(self):
        status, code, _dur, output, _net = self._run(SPEW_CMD)
        self.assertEqual(status, "passed")
        self.assertEqual(code, 0)
        # Both streams together are bounded by 2 caps plus the
        # marker — never by the ~2x(CAP+1MiB) the child wrote.
        self.assertLessEqual(len(output), 2 * CAP + 200)
        self.assertIn(b"output truncated at the sandbox cap",
                      output)

    def test_spewing_child_is_drained_not_blocked(self):
        # If the parent stopped reading at the cap, the child
        # would block on a full pipe and the run would end as
        # a timeout instead of a pass.
        status, code, duration, _out, _net = self._run(
            SPEW_CMD, timeout=30)
        self.assertEqual((status, code), ("passed", 0))
        self.assertLess(duration, 25)

    def test_collect_records_the_cap_and_the_marker(self):
        src = _tree({"app.py": "x\n"})
        record = evidence.collect(
            {"commands": [{"name": "spew", "command": SPEW_CMD,
                           "timeout": 60}]}, src)
        (item,) = record["items"]
        self.assertEqual(item["status"], "passed")
        self.assertIn("output truncated at the sandbox cap",
                      item["output_tail"])
        self.assertEqual(
            record["sandbox"]["limits"]
                  ["output_cap_bytes_per_stream"], CAP)

    def test_under_cap_output_is_byte_identical(self):
        # Pin of the pre-existing contract the cap must not
        # disturb: stdout bytes then stderr bytes, nothing
        # added, when both are under the cap.
        status, code, _dur, output, _net = self._run(
            "echo out-line; echo err-line 1>&2")
        self.assertEqual((status, code), ("passed", 0))
        self.assertEqual(output, b"out-line\nerr-line\n")


class ResourceLimitPinTests(unittest.TestCase):
    """Already met by _apply_limits; pinned end-to-end here."""

    def test_cpu_and_file_size_rlimits_reach_the_child(self):
        src = _tree({"app.py": "x\n"})
        probe = ("python3 -c 'import resource;"
                 " print(resource.getrlimit(resource.RLIMIT_CPU)"
                 "[0]);"
                 " print(resource.getrlimit("
                 "resource.RLIMIT_FSIZE)[0])'")
        record = evidence.collect(
            {"commands": [{"name": "limits", "command": probe,
                           "timeout": 10}]}, src)
        (item,) = record["items"]
        self.assertEqual(item["status"], "passed")
        lines = item["output_tail"].split()
        self.assertIn(str(10 + evidence._CPU_SLACK), lines)
        self.assertIn(str(evidence._FILE_SIZE_LIMIT), lines)

    def test_record_limits_block_states_the_pre_existing_caps(self):
        src = _tree({"app.py": "x\n"})
        record = evidence.collect(
            {"commands": [{"name": "t", "command": "true"}]}, src)
        limits = record["sandbox"]["limits"]
        self.assertEqual(limits["cpu_slack_s"], evidence._CPU_SLACK)
        self.assertEqual(limits["file_size_limit_bytes"],
                         evidence._FILE_SIZE_LIMIT)


class EnvAllowListPinTests(unittest.TestCase):
    """Already met by the positive allow-list; the evidence
    suite's marker test used one generic name — these pin the
    names that actually matter (provider keys, agent sockets)
    and the proxy rule."""

    KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN",
            "SSH_AUTH_SOCK")

    def _environ(self):
        environ = {"PATH": os.environ["PATH"]}
        for name in self.KEYS:
            environ[name] = "marker-" + name.lower()
        return environ

    def _probe(self, names):
        return "; ".join(
            "echo %s=${%s:-ABSENT}" % (n, n) for n in names)

    def test_provider_keys_and_agent_socket_never_cross(self):
        src = _tree({"app.py": "x\n"})
        record = evidence.collect(
            {"commands": [{"name": "env",
                           "command": self._probe(self.KEYS)}]},
            src, environ=self._environ())
        (item,) = record["items"]
        for name in self.KEYS:
            self.assertIn(f"{name}=ABSENT", item["output_tail"])
            self.assertNotIn("marker-" + name.lower(),
                             item["output_tail"])

    def test_proxy_stripped_by_default_readmitted_on_opt_in(self):
        src = _tree({"app.py": "x\n"})
        environ = self._environ()
        environ["HTTPS_PROXY"] = "http://proxy-marker:1234"
        probe = self._probe(("HTTPS_PROXY", "OPENAI_API_KEY"))
        record = evidence.collect(
            {"commands": [{"name": "off", "command": probe},
                          {"name": "on", "command": probe,
                           "allow_network": True}]},
            src, environ=environ)
        off, on = record["items"]
        self.assertIn("HTTPS_PROXY=ABSENT", off["output_tail"])
        self.assertIn("HTTPS_PROXY=http://proxy-marker:1234",
                      on["output_tail"])
        # The opt-in re-admits proxies ONLY — keys stay out.
        self.assertIn("OPENAI_API_KEY=ABSENT", on["output_tail"])


class CleanupPinTests(unittest.TestCase):
    """Already met by try/finally in collect/verify_claims;
    pinned on the normal, timeout-kill, and copy-failure
    paths (a leftover would be a copy of untrusted code
    sitting in the operator's temp dir)."""

    def test_no_leftover_after_a_normal_run(self):
        before = _sandbox_leftovers()
        src = _tree({"app.py": "x\n"})
        evidence.collect(
            {"commands": [{"name": "t", "command": "true"}]}, src)
        self.assertEqual(_sandbox_leftovers() - before, set())

    def test_no_leftover_after_a_timeout_kill(self):
        before = _sandbox_leftovers()
        src = _tree({"app.py": "x\n"})
        record = evidence.collect(
            {"commands": [{"name": "slow", "command": "sleep 30",
                           "timeout": 1}]}, src)
        self.assertEqual(record["items"][0]["status"], "timeout")
        self.assertEqual(_sandbox_leftovers() - before, set())

    def test_no_leftover_after_a_copy_failure(self):
        before = _sandbox_leftovers()
        record = evidence.collect(
            {"commands": [{"name": "t", "command": "true"}]},
            "/nonexistent/path/that/does/not/exist")
        self.assertEqual(record["items"][0]["status"], "error")
        self.assertEqual(_sandbox_leftovers() - before, set())

    def test_no_leftover_after_claim_verification(self):
        before = _sandbox_leftovers()
        src = _tree({"app.py": "x\n"})
        evidence.verify_claims("Ran `true` — passed\n", src)
        self.assertEqual(_sandbox_leftovers() - before, set())


@unittest.skipUnless(evidence._unshare_ok(),
                     "unshare -rn unavailable on this platform")
class NetworkEnforcementTests(unittest.TestCase):
    """Already met where unshare works; pinned as real
    enforcement, not just honest labelling."""

    def test_namespace_mode_is_a_different_namespace(self):
        src = _tree({"app.py": "x\n"})
        record = evidence.collect(
            {"commands": [{"name": "ns",
                           "command": "readlink "
                                      "/proc/self/ns/net"}]}, src)
        (item,) = record["items"]
        self.assertEqual(item["network_mode"], "namespace")
        child_ns = item["output_tail"].strip().splitlines()[-1]
        self.assertNotEqual(child_ns,
                            os.readlink("/proc/self/ns/net"))

    def test_namespace_mode_has_no_route_out(self):
        src = _tree({
            "probe_net.py": (
                "import socket\n"
                "s = socket.socket()\n"
                "s.settimeout(5)\n"
                "try:\n"
                "    s.connect(('10.255.255.1', 65000))\n"
                "    print('CONNECTED')\n"
                "except OSError as exc:\n"
                "    print('errno=%s' % exc.errno)\n"),
            "app.py": "x\n"})
        record = evidence.collect(
            {"commands": [{"name": "net",
                           "command": "python3 probe_net.py"}]},
            src)
        (item,) = record["items"]
        self.assertEqual(item["network_mode"], "namespace")
        self.assertNotIn("CONNECTED", item["output_tail"])
        # The connect fails inside the namespace. The exact
        # errno is platform-dependent (ENETUNREACH 101 on a
        # stock kernel — a fresh namespace's only interface is
        # a down loopback; EPERM 1 where netfilter policy
        # denies first, as on this VM) — what is pinned is
        # that it never connects.
        self.assertRegex(item["output_tail"], r"errno=\d+")


if __name__ == "__main__":
    unittest.main()
