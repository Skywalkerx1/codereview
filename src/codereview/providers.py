#!/usr/bin/env python3
"""codereview providers — build reviewer callables from API keys.

A provider is a callable: prompt (str) -> raw model text (str).
Keys are read from environment variables only; nothing is stored,
logged, or written to disk by this module. Redirects are refused on
authenticated requests.

Presets: gemini, openai, xai, nvidia, deepseek.
Custom:  name|openai-compatible|https://base.url/v1|model|KEY_ENV
         name|gemini|-|model|KEY_ENV
Agent:   agent:<name>:<command> — a local agent CLI (Claude Code,
         Codex, Gemini CLI, a wrapper script, ...) seated as a
         reviewer or solver. The prompt is written to a temp file
         whose path is in $CODEREVIEW_PROMPT and also piped to the
         command's stdin; the agent's stdout is the response. The
         command line is split like a shell line (shlex) and run
         WITHOUT a shell — pipes and redirects belong in a wrapper
         script. The command is operator-supplied — the same trust
         level as the loop's --builder-cmd — and is never taken
         from a repo or a diff under review.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 240
AGENT_TIMEOUT = 900


class ProviderError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ProviderError("redirect refused on authenticated request")


def _post_json(url, headers, payload, timeout=DEFAULT_TIMEOUT):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ProviderError(f"HTTP {e.code} from {url.split('/')[2]}") from e
    except (TimeoutError, ConnectionError, urllib.error.URLError) as e:
        raise ProviderError(f"network error: {e}") from e


def _key(key_env):
    key = os.environ.get(key_env, "").strip()
    if not key:
        raise ProviderError(f"{key_env} is not set")
    return key


_SYSTEM = ("You are an independent, strict code reviewer in a multi-model "
           "review loop. Output only the JSON object the user prompt "
           "asks for.")

_SOLVER_SYSTEM = ("You are the solver in a software-maintenance "
                  "workflow. You turn an issue report into an "
                  "executable solution plan in Markdown. You never "
                  "write the fix yourself; a builder implements your "
                  "plan and an independent review gates the result.")


def openai_compatible(base_url, model, key_env, extra_payload=None,
                      system=_SYSTEM):
    """Callable for any OpenAI-compatible chat completions endpoint."""
    def call(prompt):
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 8192,
        }
        if extra_payload:
            payload.update(extra_payload)
        data = _post_json(
            base_url.rstrip("/") + "/chat/completions",
            {"Authorization": f"Bearer {_key(key_env)}"}, payload)
        try:
            text = (data["choices"][0]["message"].get("content")
                    or "").strip()
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise ProviderError(f"bad response shape: {e}") from e
        if not text:
            raise ProviderError("empty content from model")
        return text
    return call


def gemini(model, key_env="GEMINI_API_KEY", system=_SYSTEM,
           json_mode=True):
    """Callable for the Gemini generateContent API.

    json_mode (the reviewer default) asks the API for a JSON body;
    solver callables pass json_mode=False because their answer is a
    Markdown plan, not a JSON object."""
    def call(prompt):
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent")
        generation = {"temperature": 0.1, "maxOutputTokens": 8192}
        if json_mode:
            generation["responseMimeType"] = "application/json"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": generation,
        }
        data = _post_json(url, {"x-goog-api-key": _key(key_env)}, payload)
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise ProviderError(f"bad response shape: {e}") from e
        if not text:
            raise ProviderError("empty content from model")
        return text
    return call


def command_agent(command, timeout=AGENT_TIMEOUT):
    """Callable backed by a local agent command.

    The prompt goes to a temp file ($CODEREVIEW_PROMPT) and to the
    command's stdin; stdout is the response. The command line is
    split with shlex and executed WITHOUT a shell (shell=False):
    shell metacharacters in it are literal, and anything needing
    pipes or redirection belongs in a wrapper script. A bad command
    line, a non-zero exit, a timeout, or empty output is a
    ProviderError — the seat degrades honestly in the run report,
    like any other provider failure."""
    def call(prompt):
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise ProviderError(f"bad agent command {command!r}: {exc}")
        if not argv:
            raise ProviderError("empty agent command")
        fd, path = tempfile.mkstemp(prefix="codereview-prompt-",
                                    suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(prompt)
            env = dict(os.environ, CODEREVIEW_PROMPT=path)
            try:
                out = subprocess.run(
                    argv, shell=False, input=prompt,
                    capture_output=True, text=True, timeout=timeout,
                    env=env, check=False)
            except subprocess.TimeoutExpired:
                raise ProviderError(
                    f"agent command timed out after {timeout}s")
            except OSError as exc:
                raise ProviderError(
                    f"agent command failed to start: "
                    f"{exc.strerror or exc}")
            if out.returncode != 0:
                tail = (out.stderr or "").strip()[-300:]
                raise ProviderError(
                    f"agent command exited {out.returncode}"
                    + (f": {tail}" if tail else ""))
            text = (out.stdout or "").strip()
            if not text:
                raise ProviderError("agent command produced no output")
            return text
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    return call


PRESETS = {
    "gemini": ("gemini", None, "gemini-2.5-flash", "GEMINI_API_KEY", None),
    "openai": ("openai-compatible", "https://api.openai.com/v1",
               "gpt-5-mini", "OPENAI_API_KEY", None),
    "xai": ("openai-compatible", "https://api.x.ai/v1",
            "grok-4-mini", "XAI_API_KEY", None),
    "nvidia": ("openai-compatible", "https://integrate.api.nvidia.com/v1",
               "nvidia/nemotron-3.5-lightning-30b-a3b", "NVIDIA_API_KEY",
               {"chat_template_kwargs": {"enable_thinking": False}}),
    "deepseek": ("openai-compatible", "https://api.deepseek.com",
                 "deepseek-chat", "DEEPSEEK_API_KEY", None),
}


def build_provider(spec, occurrence=1, text_mode=False):
    """spec -> (name, callable, account_label).

    `occurrence` > 1 (the same seat requested again) selects the
    next account's key env for presets: GEMINI_API_KEY_2, _3, ...

    `text_mode` builds a solver callable instead of a reviewer: a
    solver-persona system prompt and, for Gemini, no JSON response
    mode — the answer is a Markdown plan."""
    system = _SOLVER_SYSTEM if text_mode else _SYSTEM
    if spec.startswith("agent:"):
        parts = spec.split(":", 2)
        if len(parts) != 3 or not parts[1].strip() \
                or not parts[2].strip():
            raise ProviderError(
                f"bad agent spec {spec!r}: want agent:<name>:<command>")
        agent_name, command = parts[1].strip(), parts[2].strip()
        # text_mode changes nothing here: the seat receives the
        # full prompt (reviewer JSON instructions or the solver's
        # plan request) as its input document.
        # Each occurrence is a DISTINCT agent (its own command), not
        # another account of one seat — suffix the seat name so two
        # same-named agent specs never collapse into one pool.
        seat_name = agent_name if occurrence <= 1 \
            else f"{agent_name}-{occurrence}"
        return seat_name, command_agent(command), f"agent:{seat_name}"
    if "|" in spec:
        parts = [p.strip() for p in spec.split("|")]
        if len(parts) != 5:
            raise ProviderError(
                f"bad provider spec {spec!r}: want "
                "name|type|base_url|model|key_env")
        name, kind, base, model, key_env = parts
        if kind == "gemini":
            return name, gemini(model, key_env, system=system,
                                json_mode=not text_mode), key_env
        if kind == "openai-compatible":
            return name, openai_compatible(base, model, key_env,
                                           system=system), key_env
        raise ProviderError(f"unknown provider type {kind!r}")
    name = spec.strip().lower()
    if name not in PRESETS:
        raise ProviderError(
            f"unknown provider {spec!r}; presets: "
            f"{', '.join(sorted(PRESETS))}, or use the custom "
            "name|type|base_url|model|key_env form")
    kind, base, model, key_env, extra = PRESETS[name]
    if occurrence > 1:
        key_env = f"{key_env}_{occurrence}"
    if kind == "gemini":
        return name, gemini(model, key_env, system=system,
                            json_mode=not text_mode), key_env
    return name, openai_compatible(base, model, key_env, extra,
                                   system=system), key_env


_RETRYABLE_MARKERS = ("429", "500", "502", "503", "504", "401", "403",
                      "quota", "rate limit", "network", "timed out",
                      "timeout")


def is_retryable(exc):
    """Quota / availability / dead-key errors are worth rotating to
    the next account for; a malformed request is not."""
    msg = str(exc).lower()
    return any(m in msg for m in _RETRYABLE_MARKERS)


class AccountPool:
    """One reviewer seat backed by several accounts, tried in order.

    On a retryable error (quota, rate limit, 5xx, dead key) the next
    account takes the seat. Every rotation is recorded on
    `rotations` and the serving account on `last_account`, so run
    reports show exactly which account reviewed and when a switch
    happened — never a silent substitution. Account labels are key
    env names, never key values."""

    def __init__(self, accounts):
        # accounts: [(label, callable)]
        self.accounts = list(accounts)
        self.rotations = []
        self.last_account = None
        import threading
        self._lock = threading.Lock()

    def __call__(self, prompt):
        last_exc = None
        for i, (label, fn) in enumerate(self.accounts):
            try:
                text = fn(prompt)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not is_retryable(exc):
                    raise
                if i + 1 < len(self.accounts):
                    with self._lock:
                        self.rotations.append({
                            "from": label,
                            "to": self.accounts[i + 1][0],
                            "error": str(exc)[:200]})
                continue
            with self._lock:
                self.last_account = label
            return text
        raise last_exc


def build_providers(specs, text_mode=False):
    """specs -> {seat name: callable}. Repeating a seat (the same
    preset twice, or custom specs sharing a name) builds an
    AccountPool for that seat with one account per occurrence.
    Agent seats are the exception: each occurrence runs a different
    command, so occurrences become distinct seats (name, name-2,
    ...) instead of accounts of one seat."""
    seats = {}
    counts = {}
    for spec in specs:
        if spec.startswith("agent:"):
            seat_key = spec.split(":", 2)[1].strip().lower()
        elif "|" in spec:
            seat_key = spec.split("|")[0].strip().lower()
        else:
            seat_key = spec.strip().lower()
        counts[seat_key] = counts.get(seat_key, 0) + 1
        name, fn, label = build_provider(spec, counts[seat_key],
                                         text_mode=text_mode)
        seats.setdefault(name, []).append((label, fn))
    providers = {}
    for name, accounts in seats.items():
        providers[name] = accounts[0][1] if len(accounts) == 1 \
            else AccountPool(accounts)
    return providers


def build_solvers(specs):
    """specs -> {seat name: solver callable} for intake mode: same
    seats and account pools as build_providers, but each callable
    answers in plain Markdown (see build_provider's text_mode)."""
    return build_providers(specs, text_mode=True)
