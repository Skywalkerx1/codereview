#!/usr/bin/env python3
"""Stub-payload re-run — open-refutations solution §3, for
e1e22d48db4d (bucket C #4): the claim said a custom-provider
stub record lacked the payload 'model' field; the refutation
said build_provider sets model = desc['model'], which already
includes any preset:model override.

Re-run at HEAD (§3 're-run the stub payload tests and close
the evidence gap'): (1) the two suite tests that assert the
payload model field; (2) a direct stub capture for the custom
escape-hatch spec form — the 'custom provider' of the claim —
printing the exact payload keys sent.

Exit 0 = tests pass and every captured payload carries the
expected model."""

import io
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "tests"))

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)

OC_RESPONSE = {"choices": [{"message": {"content": "oc-text"}}]}


def main():
    lines = ["STUB-PAYLOAD RE-RUN — e1e22d48db4d",
             "Claim: the custom-provider stub captured a payload",
             "without the 'model' field.", ""]
    # (1) the suite tests, at HEAD
    import test_role_providers as trp
    suite = unittest.TestSuite()
    for name in ("test_openai_compatible_presets",
                 "test_model_override_and_temperature_quirk",
                 "test_openai_compatible_escape_hatch"):
        suite.addTest(trp.PresetRequestShapeTests(name))
    buf = io.StringIO()
    result = unittest.TextTestRunner(stream=buf, verbosity=2).run(
        suite)
    lines.append("--- suite tests at HEAD "
                 "(tests/test_role_providers.py::"
                 "PresetRequestShapeTests):")
    lines.append(buf.getvalue().strip())
    assert result.wasSuccessful()

    # (2) direct capture: custom escape-hatch + preset override
    from codereview import providers
    calls = []

    def fake(url, headers, payload, timeout=240):
        calls.append({"url": url, "payload": payload})
        return OC_RESPONSE

    env = {"CUSTOM_KEY_ENV": "k-custom", "DEEPSEEK_API_KEY": "k-ds"}
    with mock.patch.dict(os.environ, env), \
            mock.patch.object(providers, "_post_json", fake):
        seats = providers.build_providers(
            ["openai-compatible:https://llm.example.com/v1"
             "|my-model|CUSTOM_KEY_ENV"])
        seats["openai-compatible"]("hi")
        _n, fn2, _l = providers.build_provider(
            "deepseek:deepseek-reasoner")
        fn2("hi")
    lines += ["", "--- direct stub captures at HEAD:"]
    for spec, call in zip(
            ("openai-compatible:...|my-model|CUSTOM_KEY_ENV",
             "deepseek:deepseek-reasoner (preset:model override)"),
            calls):
        lines.append(f"  spec {spec}")
        lines.append(f"    url: {call['url']}")
        lines.append(f"    payload keys: {sorted(call['payload'])}")
        lines.append(f"    payload['model'] = "
                     f"{call['payload'].get('model')!r}")
    assert calls[0]["payload"]["model"] == "my-model"
    assert calls[1]["payload"]["model"] == "deepseek-reasoner"
    lines += ["",
              "PROBE OUTCOME: every captured payload at HEAD",
              "carries 'model' — for presets, for preset:model",
              "overrides, and for the custom escape-hatch spec.",
              "The evidence gap the claim rested on does not",
              "reproduce; the refutation's mechanism (model =",
              "desc['model'], override included) is confirmed by",
              "direct capture. Supports the pre-filled",
              "recommendation: sustain refutation."]
    text = "\n".join(lines) + "\n"
    with open(os.path.join(RESULTS, "stub-payload-e1e22d48db4d.txt"),
              "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
