"""Per-role model choice + full major-provider support
(owner directive 2026-11-04): the provider registry, the new
presets (Anthropic native, DeepSeek, MiniMax, Moonshot/Kimi,
Mistral, OpenRouter), the preset:model override, the generic
openai-compatible escape hatch, per-model temperature quirks,
family tagging for the independence checks, and --role
assignment (lens pins, Tech Lead designation, record detail).

No network: every API call is stubbed at providers._post_json.
Live verification exists only where a key is held (DeepSeek, via
the connector path) and is NOT part of this suite."""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, core, providers, registry  # noqa: E402

PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,1 +1,2 @@
 x = 1
+y = 2
"""

PASS_JSON = '{"verdict": "pass", "summary": "ok", "findings": []}'

OC_RESPONSE = {"choices": [{"message": {"content": "oc-text"}}]}
ANTHROPIC_RESPONSE = {"content": [
    {"type": "thinking", "thinking": "ignored"},
    {"type": "text", "text": "anthropic-text"}]}
GEMINI_RESPONSE = {"candidates": [
    {"content": {"parts": [{"text": "gemini-text"}]}}]}

KEYS = {
    "OPENAI_API_KEY": "k-openai", "GEMINI_API_KEY": "k-gemini",
    "ANTHROPIC_API_KEY": "k-anthropic",
    "DEEPSEEK_API_KEY": "k-deepseek",
    "MINIMAX_API_KEY": "k-minimax", "MOONSHOT_API_KEY": "k-moonshot",
    "NVIDIA_API_KEY": "k-nvidia", "XAI_API_KEY": "k-xai",
    "MISTRAL_API_KEY": "k-mistral",
    "OPENROUTER_API_KEY": "k-openrouter",
    "CUSTOM_KEY_ENV": "k-custom",
}


def stub_post(response):
    calls = []

    def fake(url, headers, payload, timeout=240):
        calls.append({"url": url, "headers": headers,
                      "payload": payload})
        return response
    return fake, calls


class RegistryTests(unittest.TestCase):
    def test_all_major_providers_present_with_byok_env_and_family(self):
        for name in ("openai", "gemini", "anthropic", "deepseek",
                     "minimax", "moonshot", "nvidia", "xai",
                     "mistral", "openrouter"):
            preset = registry.PRESETS[name]
            self.assertTrue(preset["key_env"], name)
            self.assertTrue(preset["family"], name)
            self.assertTrue(preset["model"], name)
            self.assertIn(preset["kind"], registry.WIRE_KINDS, name)

    def test_owner_named_cheap_seats_point_at_the_real_endpoints(self):
        self.assertEqual(registry.PRESETS["deepseek"]["base_url"],
                         "https://api.deepseek.com")
        self.assertEqual(registry.PRESETS["minimax"]["base_url"],
                         "https://api.minimax.io/v1")
        self.assertEqual(registry.PRESETS["moonshot"]["base_url"],
                         "https://api.moonshot.ai/v1")
        self.assertEqual(registry.PRESETS["moonshot"]["key_env"],
                         "MOONSHOT_API_KEY")
        self.assertEqual(registry.PRESETS["minimax"]["key_env"],
                         "MINIMAX_API_KEY")


class PresetRequestShapeTests(unittest.TestCase):
    def _call(self, spec, response=OC_RESPONSE):
        fake, calls = stub_post(response)
        with mock.patch.dict(os.environ, KEYS), \
                mock.patch.object(providers, "_post_json", fake):
            name, fn, _label = providers.build_provider(spec)
            text = fn("review this")
        return name, text, calls[0]

    def test_openai_compatible_presets(self):
        for spec, host, model, key in (
                ("deepseek", "api.deepseek.com", "deepseek-chat",
                 "k-deepseek"),
                ("minimax", "api.minimax.io", "MiniMax-M2",
                 "k-minimax"),
                ("moonshot", "api.moonshot.ai", "kimi-k2-0711-preview",
                 "k-moonshot"),
                ("mistral", "api.mistral.ai", "mistral-large-latest",
                 "k-mistral"),
                ("openrouter", "openrouter.ai",
                 "anthropic/claude-sonnet-4.5", "k-openrouter"),
                ("xai", "api.x.ai", "grok-4-mini", "k-xai"),
                ("nvidia", "integrate.api.nvidia.com",
                 "nvidia/nemotron-3.5-lightning-30b-a3b", "k-nvidia")):
            name, text, call = self._call(spec)
            self.assertEqual(text, "oc-text", spec)
            self.assertIn(host, call["url"], spec)
            self.assertTrue(
                call["url"].endswith("/chat/completions"), spec)
            self.assertEqual(call["headers"]["Authorization"],
                             f"Bearer {key}", spec)
            self.assertEqual(call["payload"]["model"], model, spec)
            self.assertEqual(call["payload"]["temperature"], 0.1,
                             spec)

    def test_nvidia_extra_payload_preserved(self):
        _name, _text, call = self._call("nvidia")
        self.assertEqual(
            call["payload"]["chat_template_kwargs"],
            {"enable_thinking": False})

    def test_anthropic_native_shape(self):
        name, text, call = self._call("anthropic",
                                      ANTHROPIC_RESPONSE)
        self.assertEqual(name, "anthropic")
        # The non-text (thinking) block is not part of the answer.
        self.assertEqual(text, "anthropic-text")
        self.assertEqual(call["url"],
                         "https://api.anthropic.com/v1/messages")
        self.assertEqual(call["headers"]["x-api-key"],
                         "k-anthropic")
        self.assertEqual(call["headers"]["anthropic-version"],
                         "2023-06-01")
        self.assertNotIn("Authorization", call["headers"])
        self.assertEqual(call["payload"]["model"],
                         "claude-sonnet-4-5")
        self.assertIn("system", call["payload"])

    def test_gemini_native_shape_still_works(self):
        fake, calls = stub_post(GEMINI_RESPONSE)
        with mock.patch.dict(os.environ, KEYS), \
                mock.patch.object(providers, "_post_json", fake):
            _name, fn, _label = providers.build_provider("gemini")
            self.assertEqual(fn("hi"), "gemini-text")
        self.assertIn("generativelanguage.googleapis.com",
                      calls[0]["url"])
        self.assertEqual(calls[0]["headers"]["x-goog-api-key"],
                         "k-gemini")

    def test_model_override_and_temperature_quirk(self):
        # gpt-5-class models reject a caller-set temperature: the
        # field is omitted, for the override AND the default.
        _n, _t, call = self._call("openai:gpt-5.4")
        self.assertEqual(call["payload"]["model"], "gpt-5.4")
        self.assertNotIn("temperature", call["payload"])
        _n, _t, call = self._call("openai")
        self.assertNotIn("temperature", call["payload"])
        # A model outside the quirk table keeps the temperature.
        _n, _t, call = self._call("moonshot:kimi-k2-turbo-preview")
        self.assertEqual(call["payload"]["model"],
                         "kimi-k2-turbo-preview")
        self.assertEqual(call["payload"]["temperature"], 0.1)
        self.assertTrue(registry.omit_temperature("openai",
                                                  "gpt-5.4"))
        self.assertFalse(registry.omit_temperature("deepseek",
                                                   "deepseek-chat"))

    def test_token_cap_parameter_per_model_family(self):
        # The L3 smoke bug (2026-11-07): the openai preset's
        # default model, gpt-5-mini, rejects `max_tokens`
        # (HTTP 400) and requires `max_completion_tokens` —
        # every CLI request through the preset failed, while
        # the llm_chain path (different payload builder) was
        # unaffected. The cap's parameter NAME now follows
        # the registry quirk table, per model family.
        _n, _t, call = self._call("openai")
        self.assertEqual(call["payload"]["model"], "gpt-5-mini")
        self.assertEqual(
            call["payload"]["max_completion_tokens"], 8192)
        self.assertNotIn("max_tokens", call["payload"])
        _n, _t, call = self._call("openai:gpt-5.4")
        self.assertEqual(
            call["payload"]["max_completion_tokens"], 8192)
        self.assertNotIn("max_tokens", call["payload"])
        # The smoke's documented override keeps max_tokens.
        _n, _t, call = self._call("openai:gpt-4.1")
        self.assertEqual(call["payload"]["max_tokens"], 8192)
        self.assertNotIn("max_completion_tokens",
                         call["payload"])
        # Other presets are untouched by the quirk.
        _n, _t, call = self._call("deepseek")
        self.assertEqual(call["payload"]["max_tokens"], 8192)
        self.assertNotIn("max_completion_tokens",
                         call["payload"])
        self.assertTrue(registry.completion_tokens(
            "openai", "gpt-5-mini"))
        self.assertFalse(registry.completion_tokens(
            "openai", "gpt-4.1"))
        self.assertFalse(registry.completion_tokens(
            "deepseek", "deepseek-chat"))

    def test_openai_compatible_escape_hatch(self):
        fake, calls = stub_post(OC_RESPONSE)
        with mock.patch.dict(os.environ, KEYS), \
                mock.patch.object(providers, "_post_json", fake):
            seats = providers.build_providers(
                ["openai-compatible:https://llm.example.com/v1"
                 "|my-model|CUSTOM_KEY_ENV"])
            self.assertEqual(list(seats), ["openai-compatible"])
            self.assertEqual(seats["openai-compatible"]("hi"),
                             "oc-text")
        self.assertEqual(calls[0]["url"],
                         "https://llm.example.com/v1/chat/completions")
        self.assertEqual(calls[0]["headers"]["Authorization"],
                         "Bearer k-custom")
        self.assertEqual(calls[0]["payload"]["model"], "my-model")

    def test_custom_anthropic_pipe_spec(self):
        fake, calls = stub_post(ANTHROPIC_RESPONSE)
        with mock.patch.dict(os.environ, KEYS), \
                mock.patch.object(providers, "_post_json", fake):
            name, fn, _label = providers.build_provider(
                "claude|anthropic|-|claude-x|CUSTOM_KEY_ENV")
            self.assertEqual(fn("hi"), "anthropic-text")
        self.assertEqual(name, "claude")
        self.assertEqual(calls[0]["headers"]["x-api-key"],
                         "k-custom")

    def test_missing_key_is_a_loud_provider_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            _name, fn, _label = providers.build_provider("minimax")
            with self.assertRaises(providers.ProviderError):
                fn("hi")


class FamilyTagTests(unittest.TestCase):
    def test_registry_family_travels_with_the_seat(self):
        seats = providers.build_providers(["moonshot"])
        self.assertEqual(
            getattr(seats["moonshot"], "_codereview_family"),
            "moonshot")
        pools = providers.build_providers(["deepseek", "deepseek"])
        self.assertIsInstance(pools["deepseek"],
                              providers.AccountPool)
        self.assertEqual(
            getattr(pools["deepseek"], "_codereview_family"),
            "deepseek")

    def test_seat_meta_prefers_the_build_family_over_the_name(self):
        seats = providers.build_providers(["moonshot"])
        meta = cli._default_seat_meta({"kimi": seats["moonshot"]})
        self.assertEqual(meta["kimi"]["family"], "moonshot")
        desc = providers.describe_spec("tech|openai-compatible"
                                       "|https://x/v1|m|K")
        self.assertEqual(desc["family"], "unknown")


class RoleAssignmentTests(unittest.TestCase):
    def test_parse_roles(self):
        roles = registry.parse_role_assignments(
            ["tech-lead=deepseek:deepseek-reasoner",
             "correctness=moonshot"])
        self.assertEqual(roles["tech-lead"],
                         "deepseek:deepseek-reasoner")
        with self.assertRaises(ValueError):
            registry.parse_role_assignments(
                ["tech-lead=a", "tech-lead=b"])
        with self.assertRaises(ValueError):
            registry.parse_role_assignments(["boss=deepseek"])
        with self.assertRaises(ValueError):
            registry.parse_role_assignments(["tech-lead"])

    def test_parse_roles_rejects_duplicate_lens_role(self):
        # Finding 84fc41a76d3f: the duplicate coverage above
        # used a non-lens role. A duplicated LENS role is the
        # dangerous case — a silent last-wins would pin the
        # wrong seat to the lens — so both lens roles get the
        # same explicit rejection coverage.
        for lens_role in ("correctness", "operations"):
            with self.assertRaises(ValueError):
                registry.parse_role_assignments(
                    [f"{lens_role}=moonshot",
                     f"{lens_role}=deepseek"])

    def test_apply_roles_rejects_duplicate_lens_role(self):
        # The same rejection must hold through the CLI seam
        # that builds lens_seats: the failure happens at parse
        # time, before any seat is built or merged, so the
        # panel is left untouched and no pin is recorded.
        panel = {}
        with self.assertRaises(ValueError):
            cli._apply_role_assignments(
                panel,
                ["correctness=moonshot", "correctness=deepseek"])
        self.assertEqual(panel, {})

    def test_apply_roles_builds_seats_pins_lens_and_records(self):
        panel = {}
        lens_seats, seat_roles, role_models, tech_lead = \
            cli._apply_role_assignments(
                panel,
                ["correctness=moonshot",
                 "tech-lead=deepseek:deepseek-reasoner"])
        self.assertEqual(set(panel), {"moonshot", "deepseek"})
        self.assertEqual(lens_seats, {"correctness": "moonshot"})
        self.assertEqual(seat_roles["tech-lead"], "deepseek")
        self.assertEqual(tech_lead, "deepseek")
        self.assertEqual(role_models["tech-lead"]["model"],
                         "deepseek-reasoner")
        self.assertEqual(role_models["tech-lead"]["family"],
                         "deepseek")
        self.assertEqual(role_models["correctness"]["family"],
                         "moonshot")
        # The independence data the Tech Lead check consumes:
        # the two roles' families are distinct, from the registry.
        meta = cli._default_seat_meta(panel)
        self.assertNotEqual(meta["deepseek"]["family"],
                            meta["moonshot"]["family"])

    def test_no_roles_means_no_change(self):
        panel = {"gemini": lambda p: PASS_JSON}
        out = cli._apply_role_assignments(panel, [])
        self.assertEqual(out, ({}, {}, {}, None))
        self.assertEqual(set(panel), {"gemini"})

    def test_lens_pin_is_honoured_and_default_is_unchanged(self):
        def seat(_prompt):
            return PASS_JSON

        panel = {"a": seat, "b": seat, "c": seat}
        report = core.run_review(
            PATCH, panel, lens_seats={"operations": "c"})
        served = {(r["provider"], r["lens"])
                  for r in report["reviewer_reports"]
                  if r["status"] == "ok"}
        self.assertIn(("c", "operations"), served)
        self.assertEqual({lens for _n, lens in served},
                         {"correctness", "operations"})
        # No pin: the historical split (first seat correctness,
        # second operations) is byte-for-byte the old behaviour.
        report2 = core.run_review(PATCH, {"a": seat, "b": seat})
        served2 = {(r["provider"], r["lens"])
                   for r in report2["reviewer_reports"]
                   if r["status"] == "ok"}
        self.assertEqual(served2, {("a", "correctness"),
                                   ("b", "operations")})

    def test_solver_role_spec_builds_a_text_mode_seat(self):
        solvers = providers.build_solvers(["deepseek"])
        self.assertEqual(list(solvers), ["deepseek"])
        self.assertEqual(
            getattr(solvers["deepseek"], "_codereview_family"),
            "deepseek")


class LensPinEdgeTests(unittest.TestCase):
    """Survivors 26–30, edges only (the main pin path is
    pinned by test_lens_pin_is_honoured_and_default_is_unchanged
    above): stale or partial pins must never drop a lens."""

    @staticmethod
    def _served(items, pins):
        tasks = core._reviewer_tasks(items, lens_seats=pins)
        return {(name, lens) for name, _fn, lens in tasks}

    def setUp(self):
        def seat(_prompt):
            return PASS_JSON
        self.items = [("a", seat), ("b", seat), ("c", seat)]

    def test_pin_naming_a_nonexistent_seat_is_ignored(self):
        served = self._served(self.items,
                              {"operations": "ghost"})
        # Falls back to the cycle: every lens tasked, the
        # ghost seat serving nothing.
        self.assertEqual(
            served, {("a", "correctness"), ("b", "operations")})

    def test_pin_naming_an_unknown_lens_is_ignored(self):
        served = self._served(self.items, {"bogus": "a"})
        self.assertEqual(
            served, {("a", "correctness"), ("b", "operations")})

    def test_single_seat_pinned_serves_remaining_lens_too(self):
        seat = self.items[0][1]
        served = self._served([("a", seat)],
                              {"operations": "a"})
        # The `or list(provider_items)` fallback: with the only
        # seat pinned, it also fills the unpinned lens.
        self.assertEqual(
            served, {("a", "operations"), ("a", "correctness")})

    def test_two_simultaneous_pins_both_honoured(self):
        served = self._served(
            self.items,
            {"correctness": "c", "operations": "a"})
        self.assertEqual(
            served, {("c", "correctness"), ("a", "operations")})


if __name__ == "__main__":
    unittest.main()
