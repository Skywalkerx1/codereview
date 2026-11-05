"""Dedicated bench key switch (2026-11-05): llm_chain.call_deepseek
draws on custom.deepseek by default (the editorial key) and on
custom.deepseek-bench when CODEREVIEW_DEEPSEEK_CONNECTOR names it —
which is what every bench driver entry point sets. The bench must
never silently fall back to the editorial key, and no other caller
(editorial drain, internal review loop) may change behaviour.

The transport is stubbed: the tests capture which connector name
reaches add_surrogate_to_request, which is the entire seam. The
module under test is the swarm's llm_chain, imported from the same
path the bench drivers use (SWARM_AGENTS_DIR overrides it, which is
how the parent-fail check runs this file against a pristine copy).
"""

import contextlib
import json
import os
import sys
import unittest
from unittest import mock

AGENTS = os.environ.get(
    "SWARM_AGENTS_DIR",
    "/home/hatch/workspace/mitbbs-ai-swarm/agents")
sys.path.insert(0, AGENTS)

import llm_chain  # noqa: E402

CANNED = {
    "choices": [{"message": {"content": "ok"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1,
              "total_tokens": 2},
}


class _Resp:
    pass


def _capture_call():
    """Run call_deepseek with the network stubbed; return the
    connector name passed to add_surrogate_to_request."""
    seen = {}

    def fake_surrogate(req, connector, allowed_hosts=None):
        seen["connector"] = connector

    @contextlib.contextmanager
    def fake_open(req, timeout):
        yield _Resp()

    with mock.patch.object(llm_chain, "add_surrogate_to_request",
                           fake_surrogate), \
            mock.patch.object(llm_chain, "_open", fake_open), \
            mock.patch.object(llm_chain, "read_json_response",
                              lambda resp: json.loads(
                                  json.dumps(CANNED))):
        text, _usage = llm_chain.call_deepseek("ping", max_tokens=8)
    assert text == "ok"
    return seen["connector"]


class DeepseekConnectorSwitchTests(unittest.TestCase):
    def test_unset_env_uses_editorial_connector(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CODEREVIEW_DEEPSEEK_CONNECTOR", None)
            self.assertEqual(_capture_call(), "custom.deepseek")

    def test_set_env_uses_bench_connector(self):
        with mock.patch.dict(
                os.environ,
                {"CODEREVIEW_DEEPSEEK_CONNECTOR":
                 "custom.deepseek-bench"}):
            self.assertEqual(_capture_call(),
                             "custom.deepseek-bench")

    def test_empty_env_falls_back_to_editorial(self):
        with mock.patch.dict(
                os.environ, {"CODEREVIEW_DEEPSEEK_CONNECTOR": ""}):
            self.assertEqual(_capture_call(), "custom.deepseek")


if __name__ == "__main__":
    unittest.main()
